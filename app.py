from flask import Flask, request, jsonify, render_template, Response, send_file
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

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ---------------- BUSINESS DAY ----------------
def get_business_date():
    now = datetime.now()
    if now.hour < 15:
        return (now - timedelta(days=1)).date()
    return now.date()

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
    status = db.Column(db.String(20))
    customer_name = db.Column(db.String(100))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("cart.id"))
    menu_id = db.Column(db.Integer, db.ForeignKey("menu.id"))
    quantity = db.Column(db.Integer)
    menu = db.relationship("Menu")

# ---------------- UI ----------------
@app.route("/ui/login")
def ui_login():
    return render_template("login.html")

@app.route("/")
def home():
    return "Thirupugazh POS API Running"

@app.route("/ui/billing")
def ui_billing():
    return render_template("billing.html")

# ============================
# RESTORE CORE POS ROUTES
# ============================

@app.route("/menu")
def get_menu():
    items = Menu.query.all()
    return jsonify([
        {"id": i.id, "name": i.name, "price": i.price}
        for i in items
    ])

@app.route("/cart/create", methods=["POST"])
def create_cart():
    cart = Cart(status="ACTIVE")
    db.session.add(cart)
    db.session.commit()
    return jsonify({"cart_id": cart.id})

@app.route("/cart/add", methods=["POST"])
def add_to_cart():
    data = request.json
    cart_id = data.get("cart_id")
    menu_id = data.get("menu_id")

    item = CartItem.query.filter_by(cart_id=cart_id, menu_id=menu_id).first()
    if item:
        item.quantity += 1
    else:
        db.session.add(
            CartItem(cart_id=cart_id, menu_id=menu_id, quantity=1)
        )

    db.session.commit()
    return jsonify({"status": "added"})

@app.route("/cart/remove", methods=["POST"])
def remove_from_cart():
    data = request.json
    cart_id = data.get("cart_id")
    menu_id = data.get("menu_id")

    item = CartItem.query.filter_by(cart_id=cart_id, menu_id=menu_id).first()
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

    result = []
    total = 0
    for i in items:
        subtotal = i.menu.price * i.quantity
        total += subtotal
        result.append({
            "menu_id": i.menu.id,
            "name": i.menu.name,
            "price": i.menu.price,
            "quantity": i.quantity,
            "subtotal": subtotal
        })

    return jsonify({
        "items": result,
        "total": total,
        "final_total": total
    })

# ---------------- ADMIN OVERRIDE + AUTO PDF ----------------
@app.route("/admin/override/hold/<int:cart_id>", methods=["POST"])
def admin_override_hold(cart_id):
    cart = Cart.query.get(cart_id)
    if not cart or cart.status != "EXPIRED":
        return jsonify({"error": "Invalid cart"}), 400

    # Create new cart
    new_cart = Cart(status="ACTIVE", customer_name=cart.customer_name)
    db.session.add(new_cart)
    db.session.commit()

    items = CartItem.query.filter_by(cart_id=cart.id).all()
    total = 0

    for i in items:
        db.session.add(CartItem(
            cart_id=new_cart.id,
            menu_id=i.menu_id,
            quantity=i.quantity
        ))
        total += i.menu.price * i.quantity

    cart.status = "PAID"
    db.session.commit()

    # -------- PDF RECEIPT --------
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 50
    p.setFont("Helvetica-Bold", 16)
    p.drawCentredString(width / 2, y, "Thirupugazh Lottery Agency")
    y -= 25

    p.setFont("Helvetica", 12)
    p.drawCentredString(width / 2, y, "Override Receipt")
    y -= 30

    p.setFont("Helvetica", 10)
    p.drawString(40, y, f"Customer: {cart.customer_name or 'N/A'}")
    y -= 20
    p.drawString(40, y, f"Date: {datetime.now().strftime('%d-%m-%Y %H:%M')}")
    y -= 30

    p.drawString(40, y, "Items:")
    y -= 20

    for i in items:
        line = f"{i.menu.name} x {i.quantity} = ₹{i.menu.price * i.quantity}"
        p.drawString(60, y, line)
        y -= 18

    y -= 10
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, f"TOTAL: ₹{total}")

    p.showPage()
    p.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"override_receipt_cart_{cart_id}.pdf",
        mimetype="application/pdf"
    )

# ---------------- INIT ----------------
def init_db():
    with app.app_context():
        db.create_all()

        if not Menu.query.first():
            db.session.add(Menu(name="Full Set", price=580))
            db.session.add(Menu(name="Half Set", price=300))
            db.session.add(Menu(name="Three Tickets", price=150))

        db.session.commit()

init_db()
@app.route("/__create_admin_once")
def create_admin_once():
    from werkzeug.security import generate_password_hash

    existing = User.query.filter_by(username="admin").first()
    if existing:
        return "Admin already exists"

    admin = User(
        username="admin",
        password=generate_password_hash("admin123"),
        role="admin"
    )
    db.session.add(admin)
    db.session.commit()

    return "Admin created successfully"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
