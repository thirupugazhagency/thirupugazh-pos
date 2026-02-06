from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os

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

# ---------------- MODELS ----------------
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(200))
    role = db.Column(db.String(20))

class Menu(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    price = db.Column(db.Integer)

class Cart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), default="ACTIVE")  # ACTIVE / HOLD
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("cart.id"))
    menu_id = db.Column(db.Integer, db.ForeignKey("menu.id"))
    quantity = db.Column(db.Integer)
    menu = db.relationship("Menu")

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
def get_menu():
    return jsonify([
        {"id": m.id, "name": m.name, "price": m.price}
        for m in Menu.query.all()
    ])

# ---------------- CART ----------------
@app.route("/cart/create", methods=["POST"])
def create_cart():
    c = Cart(status="ACTIVE")
    db.session.add(c)
    db.session.commit()
    return jsonify({"cart_id": c.id})

@app.route("/cart/add", methods=["POST"])
def add_cart():
    d = request.json
    item = CartItem.query.filter_by(
        cart_id=d["cart_id"],
        menu_id=d["menu_id"]
    ).first()

    if item:
        item.quantity += 1
    else:
        db.session.add(CartItem(
            cart_id=d["cart_id"],
            menu_id=d["menu_id"],
            quantity=1
        ))

    db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/cart/remove", methods=["POST"])
def remove_cart():
    d = request.json
    item = CartItem.query.filter_by(
        cart_id=d["cart_id"],
        menu_id=d["menu_id"]
    ).first()

    if item:
        if item.quantity > 1:
            item.quantity -= 1
        else:
            db.session.delete(item)

    db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/cart/<int:cid>")
def view_cart(cid):
    items = CartItem.query.filter_by(cart_id=cid).all()
    total = 0
    result = []

    for i in items:
        sub = i.menu.price * i.quantity
        total += sub
        result.append({
            "menu_id": i.menu.id,
            "name": i.menu.name,
            "quantity": i.quantity,
            "subtotal": sub
        })

    return jsonify({"items": result, "total": total})

# ---------------- HOLD / RESUME ----------------
@app.route("/cart/hold", methods=["POST"])
def hold_cart():
    d = request.json
    cart = Cart.query.get(d["cart_id"])
    if not cart:
        return jsonify({"error": "Cart not found"}), 404

    cart.status = "HOLD"
    db.session.commit()

    new_cart = Cart(status="ACTIVE")
    db.session.add(new_cart)
    db.session.commit()

    return jsonify({"new_cart_id": new_cart.id})

@app.route("/cart/holds")
def list_holds():
    holds = Cart.query.filter_by(status="HOLD").all()
    return jsonify([
        {"cart_id": h.id, "time": h.created_at.strftime("%H:%M")}
        for h in holds
    ])

@app.route("/cart/resume/<int:cid>", methods=["POST"])
def resume_cart(cid):
    cart = Cart.query.get(cid)
    if not cart or cart.status != "HOLD":
        return jsonify({"error": "Invalid hold"}), 400

    cart.status = "ACTIVE"
    db.session.commit()
    return jsonify({"cart_id": cart.id})

# ---------------- INIT ----------------
def init_db():
    with app.app_context():
        db.create_all()

        if Menu.query.count() == 0:
            db.session.add(Menu(name="Full Set", price=580))
            db.session.add(Menu(name="Half Set", price=300))
            db.session.add(Menu(name="Three Tickets", price=150))

        db.session.commit()

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
