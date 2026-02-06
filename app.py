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

# ---------------- AUTH ----------------
@app.route("/login", methods=["POST"])
def login():
    d = request.json
    u = User.query.filter_by(username=d.get("username")).first()
    if u and check_password_hash(u.password, d.get("password")):
        return jsonify({"status":"ok","user_id":u.id,"role":u.role})
    return jsonify({"status":"error"}), 401

# ---------------- MENU ----------------
@app.route("/menu")
def menu():
    return jsonify([{"id":m.id,"name":m.name,"price":m.price} for m in Menu.query.all()])

# ---------------- CART ----------------
@app.route("/cart/create", methods=["POST"])
def create_cart():
    c = Cart()
    db.session.add(c)
    db.session.commit()
    return jsonify({"cart_id":c.id})

@app.route("/cart/add", methods=["POST"])
def add_to_cart():
    d = request.json
    i = CartItem.query.filter_by(cart_id=d["cart_id"], menu_id=d["menu_id"]).first()
    if i:
        i.quantity += 1
    else:
        db.session.add(CartItem(cart_id=d["cart_id"], menu_id=d["menu_id"], quantity=1))
    db.session.commit()
    return jsonify({"status":"ok"})

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
    return jsonify({"status":"ok"})

@app.route("/cart/<int:cart_id>")
def view_cart(cart_id):
    items = CartItem.query.filter_by(cart_id=cart_id).all()
    total = sum(i.menu.price * i.quantity for i in items)
    return jsonify({
        "items":[{
            "menu_id":i.menu.id,
            "name":i.menu.name,
            "quantity":i.quantity,
            "subtotal":i.menu.price * i.quantity
        } for i in items],
        "total":total
    })

# ---------------- HOLD (AUTO-EXPIRE AT 3 PM) ----------------
@app.route("/cart/hold", methods=["POST"])
def hold_cart():
    c = Cart.query.get(request.json["cart_id"])
    c.status = "HOLD"
    db.session.commit()

    new = Cart()
    db.session.add(new)
    db.session.commit()
    return jsonify({"new_cart_id":new.id})

@app.route("/cart/holds")
def list_holds():
    today = get_business_date()
    valid = []
    for c in Cart.query.filter_by(status="HOLD").all():
        if get_business_date(c.created_at) == today:
            valid.append({"id":c.id})
        else:
            c.status = "EXPIRED"
    db.session.commit()
    return jsonify(valid)

@app.route("/cart/resume/<int:cart_id>", methods=["POST"])
def resume(cart_id):
    c = Cart.query.get(cart_id)
    if not c or c.status != "HOLD":
        return jsonify({"error":"Invalid hold"}),400
    if get_business_date(c.created_at) != get_business_date():
        c.status = "EXPIRED"
        db.session.commit()
        return jsonify({"error":"Hold expired at 3 PM"}),400
    c.status = "ACTIVE"
    db.session.commit()
    return jsonify({"status":"resumed"})

# ---------------- ADMIN OVERRIDE ----------------
@app.route("/admin/expired-holds")
def admin_expired():
    return jsonify([{"id":c.id,"created_at":c.created_at.strftime("%Y-%m-%d %H:%M")}
        for c in Cart.query.filter_by(status="EXPIRED").all()])

@app.route("/admin/resume-expired/<int:cart_id>", methods=["POST"])
def admin_resume(cart_id):
    c = Cart.query.get(cart_id)
    if not c or c.status != "EXPIRED":
        return jsonify({"error":"Invalid"}),400
    c.status = "ACTIVE"
    db.session.commit()
    return jsonify({"status":"admin resumed"})

# ---------------- CHECKOUT ----------------
@app.route("/checkout", methods=["POST"])
def checkout():
    d = request.json

    if not d.get("customer_name"):
        return jsonify({"error":"Customer name required"}),400
    if not re.fullmatch(r"\d{10}", d.get("customer_phone","")):
        return jsonify({"error":"Valid mobile required"}),400
    if d["payment_method"] in ["UPI","ONLINE","MIXED"] and not d.get("transaction_id"):
        return jsonify({"error":"Transaction ID required"}),400

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

# ---------------- EXCEL REPORT ----------------
@app.route("/admin/report/excel")
def excel_report():
    wb = Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["Date","Customer","Mobile","Payment","Txn ID","Discount","Total"])

    for s in Sale.query.order_by(Sale.created_at).all():
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
def pdf_report():
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    y = height - 40
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(40, y, "Thirupugazh POS – Sales Report")
    y -= 30
    pdf.setFont("Helvetica", 10)

    for s in Sale.query.order_by(Sale.created_at).all():
        pdf.drawString(40, y,
            f"{s.business_date} | {s.customer_name} | ₹{s.total} | {s.payment_method}")
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

        if not Menu.query.first():
            db.session.add(Menu(name="Full Set", price=580))
            db.session.add(Menu(name="Half Set", price=300))
            db.session.add(Menu(name="Three Tickets", price=150))

        db.session.commit()

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
