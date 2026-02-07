from flask import Flask, request, jsonify, render_template, Response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import os

app = Flask(__name__)

# ---------------- CONFIG ----------------

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

# ✅ IMPORTANT: correct replace (bug fixed)
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

# ---------------- MODELS ----------------

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # admin / staff

class Menu(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False)

class Cart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), default="ACTIVE")  
    # ACTIVE / HOLD / EXPIRED / PAID
    customer_name = db.Column(db.String(100))
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
    transaction_id = db.Column(db.String(100))
    staff_id = db.Column(db.Integer)
    business_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ---------------- UI ROUTES ----------------

@app.route("/")
def home():
    return "Thirupugazh POS API Running"

@app.route("/ui/login")
def ui_login():
    return render_template("login.html")

@app.route("/ui/billing")
def ui_billing():
    return render_template("billing.html")

@app.route("/ui/admin/reports")
def ui_admin_reports():
    return render_template("admin_reports.html")

# ---------------- AUTH ----------------

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    user = User.query.filter_by(username=data.get("username")).first()
    if user and check_password_hash(user.password, data.get("password")):
        return jsonify({
            "status": "ok",
            "user_id": user.id,
            "role": user.role
        })
    return jsonify({"status": "error"}), 401

# ---------------- MENU ----------------

@app.route("/menu")
def get_menu():
    items = Menu.query.all()
    return jsonify([
        {"id": i.id, "name": i.name, "price": i.price}
        for i in items
    ])

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
    total = 0
    rows = []

    for i in items:
        subtotal = i.menu.price * i.quantity
        total += subtotal
        rows.append({
            "menu_id": i.menu.id,
            "name": i.menu.name,
            "quantity": i.quantity,
            "subtotal": subtotal
        })

    return jsonify({"items": rows, "total": total})

# ---------------- HOLD / EXPIRE ----------------

@app.route("/cart/hold", methods=["POST"])
def hold_cart():
    data = request.json
    cart = Cart.query.get(data.get("cart_id"))
    if not cart:
        return jsonify({"error": "Cart not found"}), 404

    cart.status = "HOLD"
    cart.customer_name = data.get("customer_name")
    db.session.commit()

    new_cart = Cart(status="ACTIVE")
    db.session.add(new_cart)
    db.session.commit()

    return jsonify({"new_cart_id": new_cart.id})

@app.route("/cart/holds")
def list_holds():
    now = datetime.now()
    cutoff = now.replace(hour=15, minute=0, second=0, microsecond=0)

    carts = Cart.query.filter(Cart.status.in_(["HOLD", "EXPIRED"])).all()
    result = []

    for c in carts:
        if c.status == "HOLD" and now >= cutoff and c.created_at < cutoff:
            c.status = "EXPIRED"

        result.append({
            "id": c.id,
            "status": c.status,
            "customer_name": c.customer_name or "Unknown",
            "time": c.created_at.strftime("%H:%M")
        })

    db.session.commit()
    return jsonify(result)

# ---------------- ADMIN OVERRIDE HOLD ----------------

@app.route("/admin/override/hold/<int:cart_id>", methods=["POST"])
def admin_override_hold(cart_id):
    cart = Cart.query.get(cart_id)
    if not cart or cart.status != "EXPIRED":
        return jsonify({"error": "Invalid or non-expired cart"}), 400

    new_cart = Cart(status="ACTIVE")
    db.session.add(new_cart)
    db.session.commit()

    items = CartItem.query.filter_by(cart_id=cart.id).all()
    for i in items:
        db.session.add(CartItem(
            cart_id=new_cart.id,
            menu_id=i.menu_id,
            quantity=i.quantity
        ))

    cart.status = "PAID"
    db.session.commit()

    return jsonify({"new_cart_id": new_cart.id})

# ---------------- CHECKOUT ----------------

@app.route("/checkout", methods=["POST"])
def checkout():
    data = request.json
    items = CartItem.query.filter_by(cart_id=data.get("cart_id")).all()
    if not items:
        return jsonify({"error": "Cart empty"}), 400

    total = sum(i.menu.price * i.quantity for i in items)

    sale = Sale(
        total=total,
        payment_method=data.get("payment_method"),
        customer_name=data.get("customer_name"),
        customer_phone=data.get("customer_phone"),
        transaction_id=data.get("transaction_id"),
        staff_id=data.get("staff_id"),
        business_date=get_business_date()
    )

    db.session.add(sale)

    cart = Cart.query.get(data.get("cart_id"))
    cart.status = "PAID"

    db.session.commit()
    return jsonify({"status": "success", "total": total})

# ---------------- INIT DB ----------------

def init_db():
    with app.app_context():
        db.create_all()

        if not User.query.first():
            db.session.add(
                User(
                    username="admin",
                    password=generate_password_hash("admin123"),
                    role="admin"
                )
            )

        if not Menu.query.first():
            db.session.add(Menu(name="Full Set", price=580))
            db.session.add(Menu(name="Half Set", price=300))
            db.session.add(Menu(name="Three Tickets", price=150))

        db.session.commit()

init_db()

# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
