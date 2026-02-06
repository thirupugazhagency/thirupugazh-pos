from flask import Flask, request, jsonify, render_template, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from io import BytesIO
import os, re

from openpyxl import Workbook
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

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
    quantity = db.Column(db.Integer)
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

@app.route("/ui/admin-reports")
def ui_admin_reports():
    return render_template("admin_reports.html")

# ---------------- AUTH ----------------
@app.route("/login", methods=["POST"])
def login():
    d = request.json
    u = User.query.filter_by(username=d.get("username")).first()
    if u and check_password_hash(u.password, d.get("password")):
        return jsonify({"status": "ok", "user_id": u.id, "role": u.role})
    return jsonify({"status": "error"}), 401

# ---------------- MENU ----------------
@app.route("/menu")
def menu():
    return jsonify([
        {"id": m.id, "name": m.name, "price": m.price}
        for m in Menu.query.all()
    ])

# ---------------- CART ----------------
@app.route("/cart/create", methods=["POST"])
def create_cart():
    c = Cart()
    db.session.add(c)
    db.session.commit()
    return jsonify({"cart_id": c.id})

@app.route("/cart/add", methods=["POST"])
def add_to_cart():
    d = request.json
    i = CartItem.query.filter_by(cart_id=d["cart_id"], menu_id=d["menu_id"]).first()
    if i:
        i.quantity += 1
    else:
        db.session.add(CartItem(cart_id=d["cart_id"], menu_id=d["menu_id"], quantity=1))
    db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/cart/remove", methods=["POST"])
def remove_from_cart():
    d = request.json
    i = CartItem.query.filter_by(cart_id=d["cart_id"], menu_id=d["menu_id"]).first()
    if i:
        if i.quantity > 1:
            i.quantity -= 1
        else:
            db.session.delete(i)
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

# ---------------- HOLD + AUTO EXPIRE ----------------
@app.route("/cart/hold", methods=["POST"])
def hold_cart():
    c = Cart.query.get(request.json["cart_id"])
    c.status = "HOLD"
    db.session.commit()

    new = Cart()
    db.session.add(new)
    db.session.commit()
    return jsonify({"new_cart_id": new.id})

@app.route("/cart/holds")
def list_holds():
    today = get_business_date()
    valid = []
    for c in Cart.query.filter_by(status="HOLD").all():
        if get_business_date(c.created_at) == today:
            valid.append({"id": c.id})
        else:
            c.status = "EXPIRED"
    db.session.commit()
    return jsonify(valid)

@app.route("/cart/resume/<int:cart_id>", methods=["POST"])
def resume(cart_id):
    c = Cart.query.get(cart_id)
    if not c or c.status != "HOLD":
        return jsonify({"error": "Invalid hold"}), 400
    if get_business_date(c.created_at) != get_business_date():
        c.status = "EXPIRED"
        db.session.commit()
        return jsonify({"error": "Hold expired at 3 PM"}), 400
    c.status = "ACTIVE"
    db.session.commit()
    return jsonify({"status": "resumed"})

# ---------------- ADMIN OVERRIDE ----------------
@app.route("/admin/expired-holds")
def admin_expired_holds():
    return jsonify([
        {"id": c.id, "created_at": c.created_at.strftime("%Y-%m-%d %H:%M")}
        for c in Cart.query.filter_by(status="EXPIRED").all()
    ])

@app.route("/admin/resume-expired/<int:cart_id>", methods=["POST"])
def admin_resume_expired(cart_id):
    c = Cart.query.get(cart_id)
    if not c or c.status != "EXPIRED":
        return jsonify({"error": "Invalid cart"}), 400
    c.status = "ACTIVE"
    db.session.commit()
    return jsonify({"status": "admin resumed"})

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
        cus
