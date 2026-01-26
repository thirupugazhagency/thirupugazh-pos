from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os

app = Flask(__name__)

# ---------------- CONFIG ----------------

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ---------------- MODELS ----------------

class BusinessDay(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime)
    is_closed = db.Column(db.Boolean, default=False)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)

class Menu(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False)

class Cart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    is_hold = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("cart.id"))
    menu_id = db.Column(db.Integer, db.ForeignKey("menu.id"))
    quantity = db.Column(db.Integer, default=1)
    menu = db.relationship("Menu")

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    total = db.Column(db.Integer, nullable=False)
    payment_method = db.Column(db.String(20))
    customer_name = db.Column(db.String(100))
    customer_phone = db.Column(db.String(20))
    staff_id = db.Column(db.Integer)
    business_day_id = db.Column(db.Integer, db.ForeignKey("business_day.id"))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ---------------- HELPERS ----------------

def get_current_business_day():
    day = BusinessDay.query.filter_by(is_closed=False).first()
    if not day:
        day = BusinessDay(start_time=datetime.utcnow(), is_closed=False)
        db.session.add(day)
        db.session.commit()
    return day

# ---------------- UI ----------------

@app.route("/")
def home():
    return "Thirupugazh POS API Running"

@app.route("/ui/login")
def ui_login():
    return render_template("login.html")

@app.route("/ui/billing")
def ui_billing():
    return render_template("billing.html")

# ---------------- AUTH ----------------

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    user = User.query.filter_by(username=data.get("username")).first()
    if user and check_password_hash(user.password, data.get("password")):
        return jsonify({"status": "ok", "role": user.role, "user_id": user.id})
    return jsonify({"status": "error"}), 401

# ---------------- MENU ----------------

@app.route("/menu", methods=["GET"])
def get_menu():
    items = Menu.query.all()
    return jsonify([{"id": i.id, "name": i.name, "price": i.price} for i in items])

# ---------------- CART ----------------

@app.route("/cart/create", methods=["POST"])
def create_cart():
    cart = Cart()
    db.session.add(cart)
    db.session.commit()
    return jsonify({"cart_id": cart.id})

@app.route("/cart/add", methods=["POST"])
def add_to_cart():
    data = request.json
    cart_id = data.get("cart_id")
    menu_id = data.get("menu_id")

    item = CartItem.query.filter_by(cart_id=cart_id, menu_id=menu_id).first()

    if item:
        item.quantity += 1
    else:
        item = CartItem(cart_id=cart_id, menu_id=menu_id, quantity=1)
        db.session.add(item)

    db.session.commit()
    return jsonify({"status": "added"})

@app.route("/cart/remove", methods=["POST"])
def remove_from_cart():
    data = request.json
    cart_id = data.get("cart_id")
    menu_id = data.get("menu_id")

    item = CartItem.query.filter_by(cart_id=cart_id, menu_id=menu_id).first()
    if not item:
        return jsonify({"status": "ok"})

    if item.quantity > 1:
        item.quantity -= 1
    else:
        db.session.delete(item)

    db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/cart/<int:cart_id>")
def view_cart(cart_id):
    items = CartItem.query.filter_by(cart_id=cart_id).all()
    result = []
    total = 0

    for i in items:
        subtotal = i.menu.price * i.quantity
        total += subtotal
        result.append({
            "menu_id": i.menu.id,
            "name": i.menu.name,
            "price": i.menu.price,
            "quantity": i.quantity,
            "subtotal": subtotal
        })

    return jsonify({
        "items": result,
        "total": total,
        "final_total": total
    })

# ---------------- HOLD BILL ----------------

@app.route("/cart/hold", methods=["POST"])
def hold_cart():
    data = request.json
    cart_id = data.get("cart_id")
    cart = Cart.query.get(cart_id)
    cart.is_hold = True
    db.session.commit()
    return jsonify({"status": "held"})

@app.route("/cart/holds")
def list_holds():
    carts = Cart.query.filter_by(is_hold=True).all()
    return jsonify([{"id": c.id} for c in carts])

@app.route("/cart/resume/<int:cart_id>")
def resume_cart(cart_id):
    cart = Cart.query.get(cart_id)
    cart.is_hold = False
    db.session.commit()
    return jsonify({"status": "resumed", "cart_id": cart.id})

# ---------------- CHECKOUT ----------------

@app.route("/checkout", methods=["POST"])
def checkout():
    data = request.json

    cart_id = data.get("cart_id")
    payment_method = data.get("payment_method")
    customer_name = data.get("customer_name")
    customer_phone = data.get("customer_phone")
    staff_id = data.get("staff_id")

    items = CartItem.query.filter_by(cart_id=cart_id).all()
    if not items:
        return jsonify({"error": "Cart empty"}), 400

    total = sum(i.menu.price * i.quantity for i in items)

    day = get_current_business_day()

    sale = Sale(
        total=total,
        payment_method=payment_method,
        customer_name=customer_name,
        customer_phone=customer_phone,
        staff_id=staff_id,
        business_day_id=day.id
    )

    db.session.add(sale)

    for i in items:
        db.session.delete(i)

    db.session.commit()

    return jsonify({"status": "success", "total": total})

# ---------------- DAY CLOSE ----------------

@app.route("/day/close", methods=["POST"])
def close_day():
    day = get_current_business_day()
    day.is_closed = True
    day.end_time = datetime.utcnow()

    new_day = BusinessDay(start_time=datetime.utcnow(), is_closed=False)

    db.session.add(new_day)
    db.session.commit()

    return jsonify({"status": "day closed", "new_day_id": new_day.id})

# ---------------- INIT ----------------

def init_db():
    with app.app_context():
        db.create_all()

        if not User.query.first():
            admin = User(username="admin", password=generate_password_hash("admin123"), role="admin")
            staff = User(username="staff1", password=generate_password_hash("1234"), role="staff")
            db.session.add(admin)
            db.session.add(staff)

        if not Menu.query.first():
            db.session.add(Menu(name="Full Set", price=580))
            db.session.add(Menu(name="Half Set", price=300))
            db.session.add(Menu(name="Three Tickets", price=150))

        db.session.commit()

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
