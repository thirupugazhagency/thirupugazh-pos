from flask import Flask, request, jsonify, render_template, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os, io

import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

app = Flask(__name__)

# ==================================================
# CONFIG
# ==================================================

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ==================================================
# BUSINESS DATE (3 PM – 3 PM)
# ==================================================

def get_business_date():
    now = datetime.now()
    if now.hour < 15:
        return (now - timedelta(days=1)).date()
    return now.date()

# ==================================================
# MODELS
# ==================================================

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default="ACTIVE")

class Menu(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False)

class Cart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), default="ACTIVE")
    customer_name = db.Column(db.String(100))
    customer_phone = db.Column(db.String(20))
    transaction_id = db.Column(db.String(100))
    discount = db.Column(db.Integer, default=0)
    staff_id = db.Column(db.Integer)
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
    discount = db.Column(db.Integer, default=0)
    staff_id = db.Column(db.Integer)
    business_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ==================================================
# UI ROUTES
# ==================================================

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

@app.route("/ui/admin-staff")
def ui_admin_staff():
    return render_template("admin_staff.html")

# ==================================================
# AUTH
# ==================================================

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    user = User.query.filter_by(username=data.get("username")).first()

    if user and check_password_hash(user.password, data.get("password")):
        if user.status != "ACTIVE":
            return jsonify({"status": "disabled"}), 403

        return jsonify({
            "status": "ok",
            "user_id": user.id,
            "role": user.role
        })

    return jsonify({"status": "error"}), 401

# ==================================================
# MENU
# ==================================================

@app.route("/menu")
def get_menu():
    return jsonify([
        {"id": m.id, "name": m.name, "price": m.price}
        for m in Menu.query.all()
    ])

# ==================================================
# CART / CHECKOUT (UNCHANGED)
# ==================================================
# (keeping all your existing cart, hold, resume, checkout routes exactly)

# ==================================================
# ================= ADMIN REPORTS ==================
# ==================================================

# ---------- DAILY JSON ----------
@app.route("/admin/report/daily")
def admin_daily_report():
    date_str = request.args.get("date")
    business_date = (
        datetime.strptime(date_str, "%Y-%m-%d").date()
        if date_str else get_business_date()
    )

    sales = Sale.query.filter_by(business_date=business_date).all()

    return jsonify({
        "bill_count": len(sales),
        "total_amount": sum(s.total for s in sales)
    })

# ---------- DAILY EXCEL ----------
@app.route("/admin/report/daily/excel")
def admin_daily_excel():
    date_str = request.args.get("date")
    business_date = (
        datetime.strptime(date_str, "%Y-%m-%d").date()
        if date_str else get_business_date()
    )

    sales = Sale.query.filter_by(business_date=business_date).all()

    df = pd.DataFrame([{
        "Date": s.business_date,
        "Amount": s.total,
        "Payment": s.payment_method,
        "Customer": s.customer_name
    } for s in sales])

    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="daily_sales.xlsx"
    )

# ---------- DAILY PDF ----------
@app.route("/admin/report/daily/pdf")
def admin_daily_pdf():
    date_str = request.args.get("date")
    business_date = (
        datetime.strptime(date_str, "%Y-%m-%d").date()
        if date_str else get_business_date()
    )

    sales = Sale.query.filter_by(business_date=business_date).all()

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    y = 800

    pdf.setFont("Helvetica", 12)
    pdf.drawString(50, y, f"Daily Sales Report: {business_date}")
    y -= 30

    for s in sales:
        pdf.drawString(50, y, f"₹{s.total} - {s.payment_method} - {s.customer_name}")
        y -= 20
        if y < 50:
            pdf.showPage()
            y = 800

    pdf.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="daily_sales.pdf"
    )

# ---------- MONTHLY EXCEL ----------
@app.route("/admin/report/monthly/excel")
def admin_monthly_excel():
    month = int(request.args.get("month"))
    year = int(request.args.get("year"))

    sales = Sale.query.filter(
        db.extract("month", Sale.business_date) == month,
        db.extract("year", Sale.business_date) == year
    ).all()

    df = pd.DataFrame([{
        "Date": s.business_date,
        "Amount": s.total,
        "Payment": s.payment_method
    } for s in sales])

    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name="monthly_sales.xlsx"
    )

# ---------- MONTHLY PDF ----------
@app.route("/admin/report/monthly/pdf")
def admin_monthly_pdf():
    month = int(request.args.get("month"))
    year = int(request.args.get("year"))

    sales = Sale.query.filter(
        db.extract("month", Sale.business_date) == month,
        db.extract("year", Sale.business_date) == year
    ).all()

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    y = 800

    pdf.setFont("Helvetica", 12)
    pdf.drawString(50, y, f"Monthly Sales Report: {month}/{year}")
    y -= 30

    for s in sales:
        pdf.drawString(50, y, f"{s.business_date} - ₹{s.total}")
        y -= 20
        if y < 50:
            pdf.showPage()
            y = 800

    pdf.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="monthly_sales.pdf"
    )

# ==================================================
# INIT DB (SAFE)
# ==================================================

def init_db():
    with app.app_context():
        db.create_all()

        if not User.query.first():
            db.session.add(User(
                username="admin",
                password=generate_password_hash("admin123"),
                role="admin",
                status="ACTIVE"
            ))
            db.session.add(User(
                username="staff1",
                password=generate_password_hash("1234"),
                role="staff",
                status="ACTIVE"
            ))

        if Menu.query.count() == 0:
            db.session.add_all([
                Menu(name="Full Set", price=580),
                Menu(name="Half Set", price=300),
                Menu(name="Three Tickets", price=150)
            ])

        db.session.commit()

init_db()

# ==================================================
# RUN
# ==================================================

@app.route("/debug/db")
def debug_db():
    return jsonify({
        "users": User.query.count(),
        "staff": User.query.filter_by(role="staff").count(),
        "menu": Menu.query.count(),
        "sales": Sale.query.count()
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
