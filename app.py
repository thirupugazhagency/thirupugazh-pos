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

# ---------------- MENU ----------------
@app.route("/menu")
def menu():
    return jsonify([{"id":m.id,"name":m.name,"price":m.price} for m in Menu.query.all()])

# ---------------- CHECKOUT ----------------
@app.route("/checkout", methods=["POST"])
def checkout():
    d = request.json

    if not d.get("customer_name"):
        return jsonify({"error":"Customer name required"}),400
    if not re.fullmatch(r"\d{10}", d.get("customer_phone","")):
        return jsonify({"error":"Valid mobile required"}),400

    items = CartItem.query.filter_by(cart_id=d["cart_id"]).all()
    total = sum(i.menu.price * i.quantity for i in items)
    discount = min(int(d.get("discount",0)), total)
    final = total - discount

    sale = Sale(
        total=final,
        discount=discount,
        payment_method=d["payment_method"],
        customer_name=d["customer_name"],
        customer_phone=d["customer_phone"],
        transaction_id=d.get("transaction_id"),
        staff_id=d["staff_id"],
        business_date=get_business_date()
    )

    db.session.add(sale)
    Cart.query.get(d["cart_id"]).status = "PAID"
    db.session.commit()

    return jsonify({"status":"success","total":final})

# ================== MONTHLY SUMMARY ==================

@app.route("/admin/report/monthly/excel")
def monthly_excel():
    month = request.args.get("month")
    if not month:
        return "Month required (YYYY-MM)", 400

    year, mon = month.split("-")

    count, total, discount = db.session.query(
        func.count(Sale.id),
        func.sum(Sale.total),
        func.sum(Sale.discount)
    ).filter(
        extract("year", Sale.business_date) == int(year),
        extract("month", Sale.business_date) == int(mon)
    ).first()

    total = total or 0
    discount = discount or 0
    net = total - discount

    wb = Workbook()
    ws = wb.active
    ws.title = "Monthly Summary"

    ws.append(["Month","Bills","Total Sales","Total Discount","Net Amount"])
    ws.append([month, count or 0, total, discount, net])

    file = BytesIO()
    wb.save(file)
    file.seek(0)

    return send_file(
        file,
        as_attachment=True,
        download_name=f"monthly_summary_{month}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route("/admin/report/monthly/pdf")
def monthly_pdf():
    month = request.args.get("month")
    if not month:
        return "Month required (YYYY-MM)", 400

    year, mon = month.split("-")

    count, total, discount = db.session.query(
        func.count(Sale.id),
        func.sum(Sale.total),
        func.sum(Sale.discount)
    ).filter(
        extract("year", Sale.business_date) == int(year),
        extract("month", Sale.business_date) == int(mon)
    ).first()

    total = total or 0
    discount = discount or 0
    net = total - discount

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)

    pdf.setFont("Helvetica-Bold",16)
    pdf.drawString(40,800,"Thirupugazh POS – Monthly Summary")

    pdf.setFont("Helvetica",12)
    pdf.drawString(40,760,f"Month: {month}")
    pdf.drawString(40,730,f"Total Bills: {count or 0}")
    pdf.drawString(40,700,f"Total Sales: ₹{total}")
    pdf.drawString(40,670,f"Total Discount: ₹{discount}")
    pdf.drawString(40,640,f"Net Amount: ₹{net}")

    pdf.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"monthly_summary_{month}.pdf",
        mimetype="application/pdf"
    )

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

        if not Menu.query.first():
            db.session.add(Menu(name="Full Set", price=580))
            db.session.add(Menu(name="Half Set", price=300))
            db.session.add(Menu(name="Three Tickets", price=150))

        db.session.commit()

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
