from flask import Flask, request, jsonify
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
    role = db.Column(db.String(20), nullable=False)

class Menu(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False)

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    total = db.Column(db.Integer, nullable=False)
    payment_method = db.Column(db.String(20), nullable=False)
    txn_id = db.Column(db.String(100))
    cash_details = db.Column(db.String(200))
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
    return "Thirupugazh POS API is running with database"

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

@app.route("/menu", methods=["POST"])
def add_menu():
    data = request.json
    item = Menu(name=data["name"], price=data["price"])
    db.session.add(item)
    db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/menu/<int:item_id>", methods=["DELETE"])
def delete_menu(item_id):
    item = Menu.query.get(item_id)
    if not item:
        return jsonify({"error": "Not found"}), 404
    db.session.delete(item)
    db.session.commit()
    return jsonify({"status": "deleted"})

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
    cart_id = data.get("cart_id")
    menu_id = data.get("menu_id")
    qty = data.get("quantity", 1)

    cart = Cart.query.get(cart_id)
    if not cart:
        return jsonify({"error": "Cart not found"}), 404

    item = CartItem.query.filter_by(cart_id=cart_id, menu_id=menu_id).first()

    if item:
        item.quantity += qty
    else:
        item = CartItem(cart_id=cart_id, menu_id=menu_id, quantity=qty)
        db.session.add(item)

    db.session.commit()
    return jsonify({"status": "added"})

@app.route("/cart/<int:cart_id>", methods=["GET"])
def view_cart(cart_id):
    items = CartItem.query.filter_by(cart_id=cart_id).all()

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

    return jsonify({
        "cart_id": cart_id,
        "items": result,
        "total": total
    })

# ---------------- CHECKOUT ----------------

@app.route("/checkout", methods=["POST"])
def checkout():
    data = request.json
    cart_id = data.get("cart_id")
    payment_method = data.get("payment_method")
    txn_id = data.get("txn_id", "")
    cash_details = data.get("cash_details", "")

    items = CartItem.query.filter_by(cart_id=cart_id).all()
    if not items:
        return jsonify({"error": "Cart empty"}), 400

    total = sum(i.menu.price * i.quantity for i in items)

    sale = Sale(
        total=total,
        payment_method=payment_method,
        txn_id=txn_id,
        cash_details=cash_details
    )

    db.session.add(sale)

    # Clear cart
    for i in items:
        db.session.delete(i)

    db.session.commit()

    return jsonify({
        "status": "success",
        "total": total
    })

# ---------------- REPORTS ----------------

@app.route("/report/today")
def report_today():
    today = datetime.utcnow().date()
    total = db.session.query(db.func.sum(Sale.total)).filter(
        db.func.date(Sale.created_at) == today
    ).scalar() or 0
    return jsonify({"total": total})

@app.route("/report/month")
def report_month():
    now = datetime.utcnow()
    total = db.session.query(db.func.sum(Sale.total)).filter(
        db.extract("month", Sale.created_at) == now.month,
        db.extract("year", Sale.created_at) == now.year
    ).scalar() or 0
    return jsonify({"total": total})

# ---------------- SALES HISTORY ----------------

@app.route("/sales", methods=["GET"])
def all_sales():
    sales = Sale.query.order_by(Sale.created_at.desc()).all()

    result = []
    for s in sales:
        result.append({
            "id": s.id,
            "total": s.total,
            "payment_method": s.payment_method,
            "txn_id": s.txn_id,
            "cash_details": s.cash_details,
            "created_at": s.created_at.strftime("%Y-%m-%d %H:%M:%S")
        })

    return jsonify(result)


@app.route("/sales/today", methods=["GET"])
def sales_today():
    today = datetime.utcnow().date()

    sales = Sale.query.filter(
        db.func.date(Sale.created_at) == today
    ).all()

    total = sum(s.total for s in sales)

    return jsonify({
        "count": len(sales),
        "total": total
    })

# ---------------- INIT DB ----------------

def init_db():
    with app.app_context():
        db.create_all()

        # Create admin user if not exists
        if not User.query.first():
            admin = User(
                username="admin",
                password=generate_password_hash("admin123"),
                role="admin"
            )
            db.session.add(admin)
            db.session.commit()

        # Create menu items if not exists
        if not Menu.query.first():
            db.session.add(Menu(name="Full Set", price=580))
            db.session.add(Menu(name="Half Set", price=300))
            db.session.add(Menu(name="Three Tickets", price=150))
            db.session.commit()

init_db()

# ---------------- LOCAL RUN ----------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
