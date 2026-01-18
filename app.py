from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os

app = Flask(__name__)

# ---------------- CONFIG (updated) ----------------

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

# ---------------- SALES ----------------

@app.route("/sale", methods=["POST"])
def create_sale():
    data = request.json
    sale = Sale(
        total=data["total"],
        payment_method=data["payment_method"],
        txn_id=data.get("txn_id", ""),
        cash_details=data.get("cash_details", "")
    )
    db.session.add(sale)
    db.session.commit()
    return jsonify({"status": "ok"})

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

# ---------------- INIT DB ----------------

def init_db():
    with app.app_context():
        db.create_all()

        if not User.query.first():
            admin = User(
                username="admin",
                password=generate_password_hash("admin123"),
                role="admin"
            )
            db.session.add(admin)

            db.session.add(Menu(name="Full Ticket", price=580))
            db.session.add(Menu(name="Half Ticket", price=300))
            db.session.add(Menu(name="Three Ticket", price=150))

            db.session.commit()

init_db()

# ---------------- LOCAL RUN ----------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
