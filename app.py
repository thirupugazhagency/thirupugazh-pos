from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os

app = Flask(__name__)

# ---------------- CONFIG ----------------

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set")

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
    role = db.Column(db.String(20), nullable=False)

class Menu(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False)

class Coupon(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    active = db.Column(db.Boolean, default=True)

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)

    total_before_coupon = db.Column(db.Integer, nullable=False)
    coupon_amount = db.Column(db.Integer, default=0)
    final_total = db.Column(db.Integer, nullable=False)

    payment_method = db.Column(db.String(20), nullable=False)
    txn_id = db.Column(db.String(100))
    cash_details = db.Column(db.String(200))

    customer_name = db.Column(db.String(100))
    customer_phone = db.Column(db.String(20))

    staff_id = db.Column(db.Integer, db.ForeignKey("user.id"))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Cart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("cart.id"))
    menu_id = db.Column(db.Integer, db.ForeignKey("menu.id"))
    quantity = db.Column(db.Integer, default=1)

    menu = db.relationship("Menu")

# ---------------- ROUTES ----------------

@app.route("/")
def home():
    return "Thirupugazh POS API Running"

# ---------------- AUTH ----------------

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    user = User.query.filter_by(username=data.get("username")).first()
    if user and check_password_hash(user.password, data.get("password")):
        return jsonify({"status": "ok", "role": user.role})
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
    return jsonify({"status": "user created"})

# ---------------- MENU ----------------

@app.route("/menu", methods=["GET"])
def get_menu():
    items = Menu.query.all()
    return jsonify([{"id": i.id, "name": i.name, "price": i.price} for i in items])

# ---------------- COUPON ----------------

@app.route("/coupon", methods=["POST"])
def add_coupon():
    data = request.json
    c = Coupon(name=data["name"], amount=data["amount"])
    db.session.add(c)
    db.session.commit()
    return jsonify({"status": "coupon added"})

@app.route("/coupon", methods=["GET"])
def list_coupons():
    coupons = Coupon.query.filter_by(active=True).all()
    return jsonify([{"id": c.id, "name": c.name, "amount": c.amount} for c in coupons])

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

    item = CartItem.query.filter_by(
        cart_id=data["cart_id"],
        menu_id=data["menu_id"]
    ).first()

    if item:
        item.quantity += data.get("quantity", 1)
    else:
        item = CartItem(
            cart_id=data["cart_id"],
            menu_id=data["menu_id"],
            quantity=data.get("quantity", 1)
        )
        db.session.add(item)

    db.session.commit()
    return jsonify({"status": "added"})

@app.route("/cart/<int:cart_id>")
def view_cart(cart_id):
    items = CartItem.query.filter_by(cart_id=cart_id).all()

    total = 0
    result = []

    for i in items:
        subtotal = i.menu.price * i.quantity
        total += subtotal
        result.append({
            "name": i.menu.name,
            "price": i.menu.price,
            "qty": i.quantity,
            "subtotal": subtotal
        })

    return jsonify({
        "cart_id": cart_id,
        "items": result,
        "total": total
    })

# ---------------- CHECKOUT ----------------

@app.route("/checkout", methods=["POST"])
def checkout():
    data = request.json

    cart_id = data["cart_id"]
    payment_method = data["payment_method"]
    staff_id = data["staff_id"]

    customer_name = data.get("customer_name", "")
    customer_phone = data.get("customer_phone", "")

    coupon_id = data.get("coupon_id")

    items = CartItem.query.filter_by(cart_id=cart_id).all()
    if not items:
        return jsonify({"error": "Cart empty"}), 400

    total = sum(i.menu.price * i.quantity for i in items)

    coupon_amount = 0
    if coupon_id:
        coupon = Coupon.query.get(coupon_id)
        if coupon and coupon.active:
            coupon_amount = coupon.amount

    final_total = max(0, total - coupon_amount)

    sale = Sale(
        total_before_coupon=total,
        coupon_amount=coupon_amount,
        final_total=final_total,
        payment_method=payment_method,
        txn_id=data.get("txn_id", ""),
        cash_details=data.get("cash_details", ""),
        customer_name=customer_name,
        customer_phone=customer_phone,
        staff_id=staff_id
    )

    db.session.add(sale)

    for i in items:
        db.session.delete(i)

    db.session.commit()

    return jsonify({
        "status": "success",
        "total_before_coupon": total,
        "coupon_amount": coupon_amount,
        "final_total": final_total
    })

# ---------------- INIT DB ----------------

def init_db():
    with app.app_context():
        db.create_all()

        if not User.query.first():
            admin = User(
                username="admin",
                password=generate_password_hash("admin123"),
                role="admin"
            )
            staff = User(
                username="staff",
                password=generate_password_hash("staff123"),
                role="staff"
            )
            db.session.add(admin)
            db.session.add(staff)

            db.session.add(Menu(name="Full Set", price=580))
            db.session.add(Menu(name="Half Set", price=300))
            db.session.add(Menu(name="Three Tickets", price=150))

            db.session.add(Coupon(name="TEST100", amount=100))

            db.session.commit()

init_db()

# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
