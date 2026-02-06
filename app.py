from flask import Flask, request, jsonify, render_template, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os, re
from io import BytesIO

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

# ---------------- BUSINESS DAY ----------------
def get_business_date(dt=None):
    if not dt:
        dt = datetime.now()
    if dt.hour < 15:
        return (dt - timedelta(days=1)).date()
    return dt.date()

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
    discount = db.Column(db.Integer)
    payment_method = db.Column(db.String(20))
    customer_name = db.Column(db.String(100))
    customer_phone = db.Column(db.String(20))
    transaction_id = db.Column(db.String(100))
    staff_id = db.Column(db.Integer)
    business_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ---------------- AUTH ----------------
@app.route("/login", methods=["POST"])
def login():
    d = request.json
    u = User.query.filter_by(username=d["username"]).first()
    if u and check_password_hash(u.password, d["password"]):
        return jsonify({"status":"ok","user_id":u.id,"role":u.role})
    return jsonify({"status":"error"}),401

# ---------------- REPORT HELPERS ----------------
def admin_only():
    return request.headers.get("X-ROLE") == "admin"

# ---------------- EXCEL REPORT ----------------
@app.route("/admin/report/excel")
def admin_excel_report():
    if not admin_only():
        return "Access denied", 403

    date_str = request.args.get("date")
    if date_str:
        sales = Sale.query.filter_by(business_date=date_str).all()
    else:
        sales = Sale.query.all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Sales"

    ws.append([
        "Date","Customer","Mobile","Payment",
        "Transaction ID","Discount","Total"
    ])

    for s in sales:
        ws.append([
            str(s.business_date),
            s.customer_name,
            s.customer_phone,
            s.payment_method,
            s.transaction_id,
            s.discount,
            s.total
        ])

    file = BytesIO()
    wb.save(file)
    file.seek(0)

    return send_file(
        file,
        as_attachment=True,
        download_name="sales_report.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ---------------- PDF REPORT ----------------
@app.route("/admin/report/pdf")
def admin_pdf_report():
    if not admin_only():
        return "Access denied", 403

    date_str = request.args.get("date")
    if date_str:
        sales = Sale.query.filter_by(business_date=date_str).all()
    else:
        sales = Sale.query.all()

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 40
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, "Thirupugazh POS – Sales Report")
    y -= 30

    pdf.setFont("Helvetica", 10)

    for s in sales:
        line = f"{s.business_date} | {s.customer_name} | ₹{s.total} | {s.payment_method}"
        pdf.drawString(40, y, line)
        y -= 15
        if y < 40:
            pdf.showPage()
            y = height - 40

    pdf.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name="sales_report.pdf",
        mimetype="application/pdf"
    )
