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

# ---------------- HELPERS ----------------
def get_business_date():
    now = datetime.now()
    if now.hour < 15:
        return (now - timedelta(days=1)).date()
    return now.date()

# ---------------- MODELS ----------------
class Menu(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    price = db.Column(db.Integer)

class Cart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), default="ACTIVE")  # ACTIVE / HOLD / PAID
    customer_name = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("cart.id"))
    menu_id = db.Column(db.Integer, db.ForeignKey("menu.id"))
    quantity = db.Column(db.Integer)
    menu = db.relationship("Menu")

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    total = db.Column(db.Integer)
    discount = db.Column(db.Integer)
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
    item = CartItem.query.filter_by(cart_id=d["cart_id"], menu_id=d["menu_id"]).first()
    if item:
        item.quantity += 1
    else:
        db.session.add(CartItem(cart_id=d["cart_id"], menu_id=d["menu_id"], quantity=1))
    db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/cart/remove", methods=["POST"])
def remove_cart():
    d = request.json
    item = CartItem.query.filter_by(cart_id=d["cart_id"], menu_id=d["menu_id"]).first()
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

# ---------------- HOLD ----------------
@app.route("/cart/hold", methods=["POST"])
def hold_cart():
    d = request.json
    cart = Cart.query.get(d["cart_id"])
    cart.status = "HOLD"
    cart.customer_name = d["customer_name"]
    db.session.commit()

    new_cart = Cart(status="ACTIVE")
    db.session.add(new_cart)
    db.session.commit()

    return jsonify({"new_cart_id": new_cart.id})

@app.route("/cart/holds")
def list_holds():
    holds = Cart.query.filter_by(status="HOLD").all()
    return jsonify([
        {"cart_id": h.id, "customer": h.customer_name}
        for h in holds
    ])

@app.route("/cart/resume/<int:cid>", methods=["POST"])
def resume_cart(cid):
    cart = Cart.query.get(cid)
    cart.status = "ACTIVE"
    db.session.commit()
    return jsonify({"cart_id": cid})

# ---------------- PAY (FINAL STEP) ----------------
@app.route("/checkout", methods=["POST"])
def checkout():
    d = request.json

    items = CartItem.query.filter_by(cart_id=d["cart_id"]).all()
    if not items:
        return jsonify({"error": "Cart empty"}), 400

    total = sum(i.menu.price * i.quantity for i in items)
    discount = int(d.get("discount", 0))
    final_total = total - discount

    sale = Sale(
        total=final_total,
        discount=discount,
        payment_method=d["payment_method"],
        customer_name=d["customer_name"],
        customer_phone=d["customer_phone"],
        transaction_id=d["transaction_id"],
        staff_id=d.get("staff_id"),
        business_date=get_business_date()
    )

    db.session.add(sale)

    cart = Cart.query.get(d["cart_id"])
    cart.status = "PAID"

    db.session.commit()
    return jsonify({"status": "success", "total": final_total})

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
