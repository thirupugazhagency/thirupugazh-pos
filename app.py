from flask import Flask, request, jsonify, render_template, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from io import BytesIO
import os, re

from sqlalchemy import func, extract
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
    if dt is None:
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
    status = db.Column(db.String(20), default="ACTIVE")
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

@app.route("/ui/admin-reports")
def ui_admin_reports():
    return render_template("admin_reports.html")

# ---------------- AUTH ----------------
@app.route("/login", methods=["POST"])
def login():
    d = request.json
    u = User.query.filter_by(username=d.get("username")).first()
    if u and check_password_hash(u.password, d.get("password")):
        return jsonify({"status":"ok","user_id":u.id,"role":u.role})
    return jsonify({"status":"error"}),401

# ---------------- ADMIN: AGENTS LIST ----------------
@app.route("/admin/agents")
def list_agents():
    agents = User.query.filter(User.role != "admin").all()
    return jsonify([
        {"id": a.id, "username": a.username}
        for a in agents
    ])

# ---------------- ADMIN: CHANGE PASSWORD ----------------
@app.route("/admin/change-password", methods=["POST"])
def change_agent_password():
    data = request.json
    user_id = data.get("user_id")
    new_password = data.get("new_password")

    if not new_password or len(new_password) < 4:
        return jsonify({"error":"Password too short"}),400

    user = User.query.get(user_id)
    if not user or user.role == "admin":
        return jsonify({"error":"Invalid agent"}),400

    user.password = generate_password_hash(new_password)
    db.session.commit()

    return jsonify({"status":"password updated"})

# ---------------- INIT ----------------
def init_db():
    with app.app_context():
        db.create_all()

        if not User.query.filter_by(username="admin").first():
            db.session.add(User(
                username="admin",
                password=generate_password_hash("admin123"),
                role="admin"
            ))

        if not User.query.filter_by(username="agent1").first():
            db.session.add(User(
                username="agent1",
                password=generate_password_hash("agent123"),
                role="staff"
            ))

        db.session.commit()

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
