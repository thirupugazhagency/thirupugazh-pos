from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os

app = Flask(__name__)

# ---------------- CONFIG ----------------

DATABASE_URL = os.environ.get("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set in environment variables")

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
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False)

class Cart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default="ACTIVE")  # ACTIVE / HOLD

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("cart.id"))
    menu_id = db.Column(db.Integer, db.ForeignKey("menu.id"))
    quantity = db.Column(db.Integer, default=1)
    menu = db.relationship("Menu")

class AppliedDiscount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("cart.id"))
    reason = db.Column(db.String(200))
    amount = db.Column(db.Integer, nullable=False)

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    total = db.Column(db.Integer, nullable=False)
    payment_method = db.Column(db.String(20), nullable=False)
    txn_id = db.Column(db.String(100))
    cash_details = db.Column(db.String(200))
    customer_name = db.Column(db.String(100))
    customer_phone = db.Column(db.String(20))
    staff_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ---------------- ROUTES ----------------

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

# ---------------- USERS ----------------

@app.route("/users", methods=["POST"])
def create_user():
    data = request.json

    if not data.get("username") or not data.get("password") or not data.get("role"):
        return jsonify({"error": "Missing fields"}), 400

    if User.query.filter_by(username=data["username"]).first():
        return jsonify({"error": "User already exists"}), 400

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
    cart_id = data.get("cart_id")
    menu_id = data.get("menu_id")
    qty = data.get("quantity", 1)

    cart = Cart.query.get(cart_id)
    if not cart or cart.status != "ACTIVE":
        return jsonify({"error": "Cart not found or not active"}), 404

    item = CartItem.query.filter_by(cart_id=cart_id, menu_id=menu_id).first()

    if item:
        item.quantity += qty
    else:
        item = CartItem(cart_id=cart_id, menu_id=menu_id, quantity=qty)
        db.session.add(item)

    db.session.commit()
    return jsonify({"status": "added"})

# ---------------- DISCOUNT ----------------

@app.route("/cart/add-discount", methods=["POST"])
def add_discount():
    data = request.json
    cart_id = data.get("cart_id")
    amount = data.get("amount")
    reason = data.get("reason", "Manual Discount")

    if not cart_id or not amount:
        return jsonify({"error": "cart_id and amount required"}), 400

    cart = Cart.query.get(cart_id)
    if not cart:
        return jsonify({"error": "Cart not found"}), 404

    discount = AppliedDiscount(
        cart_id=cart_id,
        amount=amount,
        reason=reason
    )

    db.session.add(discount)
    db.session.commit()

    return jsonify({"status": "discount added", "amount": amount})

# ---------------- VIEW CART ----------------

@app.route("/cart/<int:cart_id>", methods=["GET"])
def view_cart(cart_id):
    items = CartItem.query.filter_by(cart_id=cart_id).all()
    discounts = AppliedDiscount.query.filter_by(cart_id=cart_id).all()

    result = []
    total = 0

    for i in items:
        subtotal = i.menu.price * i.quantity
        total += subtotal
        result.append({
            "id": i.id,
            "menu_id": i.menu.id,
            "name": i.menu.name,
            "price": i.menu.price,
            "quantity": i.quantity,
            "subtotal": subtotal
        })

    discount_total = sum(d.amount for d in discounts)

    return jsonify({
        "cart_id": cart_id,
        "items": result,
        "discount_total": discount_total,
        "final_total": total - discount_total
    })

# ---------------- HOLD BILL ----------------

@app.route("/cart/hold/<int:cart_id>", methods=["POST"])
def hold_cart(cart_id):
    cart = Cart.query.get(cart_id)
    if not cart:
        return jsonify({"error": "Cart not found"}), 404

    cart.status = "HOLD"
    db.session.commit()

    return jsonify({"status": "held"})


@app.route("/cart/hold-list", methods=["GET"])
def hold_list():
    carts = Cart.query.filter_by(status="HOLD").all()
    return jsonify([{"cart_id": c.id} for c in carts])


@app.route("/cart/resume/<int:cart_id>", methods=["POST"])
def resume_cart(cart_id):
    cart = Cart.query.get(cart_id)
    if not cart:
        return jsonify({"error": "Cart not found"}), 404

    cart.status = "ACTIVE"
    db.session.commit()

    return jsonify({"status": "resumed"})

# ---------------- CHECKOUT ----------------

@app.route("/checkout", methods=["POST"])
def checkout():
    data = request.json

    cart_id = data.get("cart_id")
    payment_method = data.get("payment_method")
    txn_id = data.get("txn_id", "")
    cash_details = data.get("cash_details", "")
    customer_name = data.get("customer_name", "")
    customer_phone = data.get("customer_phone", "")
    staff_id = data.get("staff_id")

    if not staff_id:
        return jsonify({"error": "staff_id is required"}), 400

    items = CartItem.query.filter_by(cart_id=cart_id).all()
    if not items:
        return jsonify({"error": "Cart empty"}), 400

    cart_total = sum(i.menu.price * i.quantity for i in items)
    discounts = AppliedDiscount.query.filter_by(cart_id=cart_id).all()
    discount_total = sum(d.amount for d in discounts)
    final_total = cart_total - discount_total

    sale = Sale(
        total=final_total,
        payment_method=payment_method,
        txn_id=txn_id,
        cash_details=cash_details,
        customer_name=customer_name,
        customer_phone=customer_phone,
        staff_id=staff_id
    )

    db.session.add(sale)

    cart = Cart.query.get(cart_id)
    cart.status = "PAID"

    for i in items:
        db.session.delete(i)
    for d in discounts:
        db.session.delete(d)

    db.session.commit()

    return jsonify({"status": "success", "total": final_total})

# ---------------- REPORT ----------------

@app.route("/report/today")
def report_today():
    today = datetime.utcnow().date()
    total = db.session.query(db.func.sum(Sale.total)).filter(
        db.func.date(Sale.created_at) == today
    ).scalar() or 0
    return jsonify({"total": total})

# ---------------- INIT DB ----------------

def init_db():
    with app.app_context():
        db.create_all()

        if not User.query.first():
            admin = User(username="admin", password=generate_password_hash("admin123"), role="admin")
            staff = User(username="staff1", password=generate_password_hash("staff123"), role="staff")
            db.session.add(admin)
            db.session.add(staff)

        if not Menu.query.first():
            db.session.add(Menu(name="Full Set", price=580))
            db.session.add(Menu(name="Half Set", price=300))
            db.session.add(Menu(name="Three Tickets", price=150))

        db.session.commit()

init_db()

# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
