from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os
import re

app = Flask(__name__, static_folder="static")

# ---------------- CONFIG ----------------
DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# ---------------- BUSINESS DAY (3 PM – 3 PM) ----------------
def get_business_date(dt=None):
    if not dt:
        dt = datetime.now()
    if dt.hour < 15:
        return (dt - timedelta(days=1)).date()
    return dt.date()

# ---------------- MODELS ----------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)

class Menu(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    price = db.Column(db.Integer)

class Cart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), default="ACTIVE")  # ACTIVE / HOLD / PAID / EXPIRED
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("cart.id"))
    menu_id = db.Column(db.Integer, db.ForeignKey("menu.id"))
    quantity = db.Column(db.Integer, default=1)
    menu = db.relationship("Menu")

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    total = db.Column(db.Integer)
    discount = db.Column(db.Integer, default=0)
    payment_method = db.Column(db.String(20))
    customer_name = db.Column(db.String(100))
    customer_phone = db.Column(db.String(20))
    transaction_id = db.Column(db.String(100))
    staff_id = db.Column(db.Integer)
    business_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

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
        return jsonify({"status": "ok", "user_id": user.id, "role": user.role})
    return jsonify({"status": "error"}), 401

# ---------------- MENU ----------------
@app.route("/menu")
def get_menu():
    return jsonify([{"id": m.id, "name": m.name, "price": m.price} for m in Menu.query.all()])

# ---------------- CART ----------------
@app.route("/cart/create", methods=["POST"])
def create_cart():
    cart = Cart()
    db.session.add(cart)
    db.session.commit()
    return jsonify({"cart_id": cart.id})

@app.route("/cart/add", methods=["POST"])
def add_to_cart():
    d = request.json
    item = CartItem.query.filter_by(cart_id=d["cart_id"], menu_id=d["menu_id"]).first()
    if item:
        item.quantity += 1
    else:
        db.session.add(CartItem(cart_id=d["cart_id"], menu_id=d["menu_id"], quantity=1))
    db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/cart/remove", methods=["POST"])
def remove_from_cart():
    d = request.json
    item = CartItem.query.filter_by(cart_id=d["cart_id"], menu_id=d["menu_id"]).first()
    if item:
        if item.quantity > 1:
            item.quantity -= 1
        else:
            db.session.delete(item)
    db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/cart/<int:cart_id>")
def view_cart(cart_id):
    items = CartItem.query.filter_by(cart_id=cart_id).all()
    total = sum(i.menu.price * i.quantity for i in items)
    return jsonify({
        "items": [{
            "menu_id": i.menu.id,
            "name": i.menu.name,
            "quantity": i.quantity,
            "subtotal": i.menu.price * i.quantity
        } for i in items],
        "total": total
    })

# ---------------- HOLD (WITH AUTO-EXPIRE) ----------------
@app.route("/cart/hold", methods=["POST"])
def hold_cart():
    cart = Cart.query.get(request.json["cart_id"])
    cart.status = "HOLD"
    db.session.commit()

    new_cart = Cart()
    db.session.add(new_cart)
    db.session.commit()

    return jsonify({"new_cart_id": new_cart.id})

@app.route("/cart/holds")
def list_holds():
    today_bd = get_business_date()
    valid_holds = []

    for c in Cart.query.filter_by(status="HOLD").all():
        cart_bd = get_business_date(c.created_at)
        if cart_bd == today_bd:
            valid_holds.append({"id": c.id})
        else:
            c.status = "EXPIRED"

    db.session.commit()
    return jsonify(valid_holds)

@app.route("/cart/resume/<int:cart_id>", methods=["POST"])
def resume(cart_id):
    cart = Cart.query.get(cart_id)
    if not cart or cart.status != "HOLD":
        return jsonify({"error": "Invalid hold bill"}), 400

    cart_bd = get_business_date(cart.created_at)
    today_bd = get_business_date()

    if cart_bd != today_bd:
        cart.status = "EXPIRED"
        db.session.commit()
        return jsonify({"error": "Hold bill expired at 3 PM"}), 400

    cart.status = "ACTIVE"
    db.session.commit()
    return jsonify({"status": "resumed"})

# ---------------- CHECKOUT ----------------
@app.route("/checkout", methods=["POST"])
def checkout():
    d = request.json

    if not d.get("customer_name"):
        return jsonify({"error": "Customer name required"}), 400

    if not re.fullmatch(r"\d{10}", d.get("customer_phone", "")):
        return jsonify({"error": "Valid mobile required"}), 400

    if d["payment_method"] in ["UPI", "ONLINE", "MIXED"] and not d.get("transaction_id"):
        return jsonify({"error": "Transaction ID required"}), 400

    items = CartItem.query.filter_by(cart_id=d["cart_id"]).all()
    total = sum(i.menu.price * i.quantity for i in items)
    discount = min(int(d.get("discount", 0)), total)
    final = total - discount

    sale = Sale(
        total=final,
        discount=discount,
        payment_method=d["payment_method"],
        customer_name=d["customer_name"],
        customer_phone=d["customer_phone"],
        transaction_id=d.get("transaction_id"),
        staff_id=d["staff_id"],
        business_date=get_business_date()
    )

    db.session.add(sale)
    Cart.query.get(d["cart_id"]).status = "PAID"
    db.session.commit()

    return jsonify({"status": "success", "total": final})

# ---------------- INIT DB ----------------
def init_db():
    with app.app_context():
        db.create_all()

        if not User.query.filter_by(username="admin").first():
            db.session.add(User(username="admin",
                                password=generate_password_hash("admin123"),
                                role="admin"))

        if not User.query.filter_by(username="agent1").first():
            db.session.add(User(username="agent1",
                                password=generate_password_hash("agent123"),
                                role="staff"))

        if not Menu.query.first():
            db.session.add(Menu(name="Full Set", price=580))
            db.session.add(Menu(name="Half Set", price=300))
            db.session.add(Menu(name="Three Tickets", price=150))

        db.session.commit()

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
