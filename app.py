from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
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
    role = db.Column(db.String(20), nullable=False)

class Menu(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False)

class Cart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("cart.id"))
    menu_id = db.Column(db.Integer, db.ForeignKey("menu.id"))
    quantity = db.Column(db.Integer, default=1)
    menu = db.relationship("Menu")

class HeldCart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class HeldCartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    held_cart_id = db.Column(db.Integer, db.ForeignKey("held_cart.id"))
    menu_id = db.Column(db.Integer, db.ForeignKey("menu.id"))
    quantity = db.Column(db.Integer)
    menu = db.relationship("Menu")

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    total = db.Column(db.Integer)
    payment_method = db.Column(db.String(20))
    customer_name = db.Column(db.String(100))
    customer_phone = db.Column(db.String(20))
    staff_id = db.Column(db.Integer)
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

# ---------------- MENU ----------------

@app.route("/menu")
def menu():
    items = Menu.query.all()
    return jsonify([{"id":i.id,"name":i.name,"price":i.price} for i in items])

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
    cart_id = data["cart_id"]
    menu_id = data["menu_id"]

    item = CartItem.query.filter_by(cart_id=cart_id, menu_id=menu_id).first()
    if item:
        item.quantity += 1
    else:
        item = CartItem(cart_id=cart_id, menu_id=menu_id, quantity=1)
        db.session.add(item)

    db.session.commit()
    return jsonify({"status":"added"})

@app.route("/cart/<int:cart_id>")
def view_cart(cart_id):
    items = CartItem.query.filter_by(cart_id=cart_id).all()
    result = []
    total
    for i in items:
        subtotal = i.menu.price * i.quantity
        total += subtotal
        result.append({
            "name": i.menu.name,
            "quantity": i.quantity,
            "subtotal": subtotal
        })
    return jsonify({"items": result, "total": total})

@app.route("/cart/remove", methods=["POST"])
def remove_from_cart():
    data = request.json
    cart_id = data.get("cart_id")
    menu_id = data.get("menu_id")

    item = CartItem.query.filter_by(cart_id=cart_id, menu_id=menu_id).first()

    if not item:
        return jsonify({"error": "Item not found"}), 404

    if item.quantity > 1:
        item.quantity -= 1
    else:
        db.session.delete(item)

    db.session.commit()
    return jsonify({"status": "removed"})


# ---------------- HOLD SYSTEM ----------------

@app.route("/cart/hold", methods=["POST"])
def hold_cart():
    data = request.json
    cart_id = data["cart_id"]
    name = data.get("name", "HOLD")

    held = HeldCart(name=name)
    db.session.add(held)
    db.session.commit()

    items = CartItem.query.filter_by(cart_id=cart_id).all()
    for i in items:
        db.session.add(HeldCartItem(
            held_cart_id=held.id,
            menu_id=i.menu_id,
            quantity=i.quantity
        ))
        db.session.delete(i)

    db.session.commit()
    return jsonify({"status":"held","held_id":held.id})

@app.route("/cart/list-held")
def list_held():
    held = HeldCart.query.all()
    return jsonify([{"id":h.id,"name":h.name} for h in held])

@app.route("/cart/resume/<int:held_id>", methods=["POST"])
def resume_held(held_id):
    cart = Cart()
    db.session.add(cart)
    db.session.commit()

    items = HeldCartItem.query.filter_by(held_cart_id=held_id).all()
    for i in items:
        db.session.add(CartItem(cart_id=cart.id, menu_id=i.menu_id, quantity=i.quantity))
        db.session.delete(i)

    HeldCart.query.filter_by(id=held_id).delete()
    db.session.commit()
    return jsonify({"cart_id": cart.id})

# ---------------- INIT DB ----------------

def init_db():
    with app.app_context():
        db.create_all()

        if not Menu.query.first():
            db.session.add(Menu(name="Full Set", price=580))
            db.session.add(Menu(name="Half Set", price=300))
            db.session.add(Menu(name="Three Tickets", price=150))

        if not User.query.first():
            db.session.add(User(username="admin", password=generate_password_hash("admin123"), role="admin"))

        db.session.commit()

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
