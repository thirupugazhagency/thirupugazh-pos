from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
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
class Menu(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    price = db.Column(db.Integer)

class Cart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), default="ACTIVE")
    customer_name = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("cart.id"))
    menu_id = db.Column(db.Integer, db.ForeignKey("menu.id"))
    quantity = db.Column(db.Integer, default=1)
    menu = db.relationship("Menu")

# ---------------- UI ----------------
@app.route("/")
def home():
    return "Thirupugazh POS API Running"

@app.route("/ui/billing")
def ui_billing():
    return render_template("billing.html")

# ---------------- MENU (CONFIRMED WORKING) ----------------
@app.route("/menu")
def get_menu():
    menus = Menu.query.order_by(Menu.id).all()
    return jsonify([
        {"id": m.id, "name": m.name, "price": m.price}
        for m in menus
    ])

# ---------------- CART (SAFE JSON ROUTES) ----------------
@app.route("/cart/create", methods=["POST"])
def create_cart():
    try:
        c = Cart(status="ACTIVE")
        db.session.add(c)
        db.session.commit()
        return jsonify({"cart_id": c.id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

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
    data = []

    for i in items:
        sub = i.menu.price * i.quantity
        total += sub
        data.append({
            "menu_id": i.menu.id,
            "name": i.menu.name,
            "quantity": i.quantity,
            "subtotal": sub
        })

    return jsonify({"items": data, "total": total})

# ---------------- INIT DB ----------------
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
