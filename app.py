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

# ---------------- BUSINESS DAY (3 PM – 3 PM) ----------------
def get_business_date():
    now = datetime.now()
    if now.hour < 15:
        return (now - timedelta(days=1)).date()
    return now.date()

# ---------------- PAYMENT MODES ----------------
PAYMENT_MODES = ["CASH", "UPI", "ONLINE", "MIXED"]

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

class Cart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), default="ACTIVE")
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
    discount = db.Column(db.Integer, default=0)
    payment_method = db.Column(db.String(20))
    customer_name = db.Column(db.String(100))
    customer_phone = db.Column(db.String(20))
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
        return jsonify({"status": "ok", "role": user.role, "user_id": user.id})
    return jsonify({"status": "error"}), 401

# ---------------- MENU ----------------
@app.route("/menu")
def get_menu():
    items = Menu.query.all()
    return jsonify([{"id": i.id, "name": i.name, "price": i.price} for i in items])

# ---------------- CART ----------------
@app.route("/cart/create", methods=["POST"])
def create_cart():
    cart = Cart(status="ACTIVE")
    db.session.add(cart)
    db.session.commit()
    return jsonify({"cart_id": cart.id})

@app.route("/cart/add", methods=["POST"])
def add_to_cart():
    data = request.json
    item = CartItem.query.filter_by(
        cart_id=data.get("cart_id"),
        menu_id=data.get("menu_id")
    ).first()

    if item:
        item.quantity += 1
    else:
        db.session.add(CartItem(
            cart_id=data.get("cart_id"),
            menu_id=data.get("menu_id"),
            quantity=1
        ))

    db.session.commit()
    return jsonify({"status": "added"})

@app.route("/cart/remove", methods=["POST"])
def remove_from_cart():
    data = request.json
    item = CartItem.query.filter_by(
        cart_id=data.get("cart_id"),
        menu_id=data.get("menu_id")
    ).first()

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
            "price": i.menu.price,
            "quantity": i.quantity,
            "subtotal": i.menu.price * i.quantity
        } for i in items],
        "total": total,
        "final_total": total
    })

# ---------------- HOLD ----------------
@app.route("/cart/hold", methods=["POST"])
def hold_cart():
    cart = Cart.query.get(request.json.get("cart_id"))
    cart.status = "HOLD"
    db.session.commit()

    new_cart = Cart(status="ACTIVE")
    db.session.add(new_cart)
    db.session.commi
