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

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # admin / staff

class Menu(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    price = db.Column(db.Integer)

class Cart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer)
    menu_id = db.Column(db.Integer)
    quantity = db.Column(db.Integer, default=1)

class AppliedDiscount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer)
    amount = db.Column(db.Integer)
    reason = db.Column(db.String(200))

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    total = db.Column(db.Integer)
    payment_method = db.Column(db.String(20))
    txn_id = db.Column(db.String(100))
    cash_details = db.Column(db.String(200))
    customer_name = db.Column(db.String(100))
    customer_phone = db.Column(db.String(20))
    staff_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ---------------- UI ----------------

@app.route("/")
def home():
    return "Thirupugazh POS Running"

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

# ---------------- USERS ----------------

@app.route("/users", methods=["POST"])
def create_user():
    data = request.json
    user = User(
        username=data["username"],
        password=generate_password_hash(data["password"]),
        role=data["role"]
    )
    db.session.add(user)
    db.session.commit()
    return jsonify({"status": "created"})

# ---------------- MENU ----------------

@app.route("/menu")
def menu():
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
    item = CartItem(
        cart_id=data["cart_id"],
        menu_id=data["menu_id"],
        quantity=data.get("quantity", 1)
    )
    db.session.add(item)
    db.session.commit()
    return jsonify({"status": "added"})

@app.route("/cart/add-discount", methods=["POST"])
def add_discount():
    data = request.json
    d = AppliedDiscount(
        cart_id=data["cart_id"],
        amount=data["amount"],
        reason=data.get("reason", "Manual Discount")
    )
    db.session.add(d)
    db.session.commit()
    return jsonify({"status": "discount added"})

@app.route("/cart/<int:cart_id>")
def view_cart(cart_id):
    items = CartItem.query.filter_by(cart_id=cart_id).all()
    discounts = AppliedDiscount.query.filter_by(cart_id=cart_id).all()

    total = 0
    rows = []

    for i in items:
        m = Menu.query.get(i.menu_id)
        sub = m.price * i.quantity
        total += sub
        rows.append({
            "name": m.name,
            "price": m.price,
            "qty": i.quantity,
            "subtotal": sub
        })

    discount_total = sum(d.amount for d in discounts)

    return jsonify({
        "items": rows,
        "total": total,
        "discount": discount_total,
        "final": total - discount_total
    })

# ---------------- CHECKOUT ----------------

@app.route("/checkout", methods=["POST"])
def checkout():
    data = request.json

    cart_id = data["cart_id"]
    staff_id = data["staff_id"]

    items = CartItem.query.filter_by(cart_id=cart_id).all()
    if not items:
        return jsonify({"error": "Cart empty"}), 400

    total = 0
    for i in items:
        m = Menu.query.get(i.menu_id)
        total += m.price * i.quantity

    discounts = AppliedDiscount.query.filter_by(cart_id=cart_id).all()
    discount_total = sum(d.amount for d in discounts)

    final = total - discount_total

    sale = Sale(
        total=final,
        payment_method=data["payment_method"],
        txn_id=data.get("txn_id", ""),
        cash_details=data.get("cash_details", ""),
        customer_name=data.get("customer_name", ""),
        customer_phone=data.get("customer_phone", ""),
        staff_id=staff_id
    )

    db.session.add(sale)

    # Clear cart
    for i in items:
        db.session.delete(i)
    for d in discounts:
        db.session.delete(d)

    db.session.commit()

    return jsonify({"status": "success", "total": final})

# ---------------- REPORTS ----------------

@app.route("/report/staff/<int:staff_id>")
def staff_report(staff_id):
    sales = Sale.query.filter_by(staff_id=staff_id).all()
    total = sum(s.total for s in sales)
    return jsonify({
        "staff_id": staff_id,
        "total": total,
        "count": len(sales)
    })

@app.route("/report/summary")
def summary():
    sales = Sale.query.all()
    return jsonify({
        "total_sales": len(sales),
        "amount": sum(s.total for s in sales)
    })

# ---------------- INIT ----------------

def init_db():
    with app.app_context():
        db.create_all()

        if not User.query.first():
            db.session.add(User(username="admin", password=generate_password_hash("admin123"), role="admin"))
            db.session.add(User(username="staff1", password=generate_password_hash("staff123"), role="staff"))

        if not Menu.query.first():
            db.session.add(Menu(name="Full Set", price=580))
            db.session.add(Menu(name="Half Set", price=300))
            db.session.add(Menu(name="Three Tickets", price=150))

        db.session.commit()

init_db()

# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
