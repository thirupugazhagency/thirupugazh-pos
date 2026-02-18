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
# DATABASE CONFIG (SAFE FOR WINDOWS + RENDER)
# ==================================================
DATABASE_URL = os.environ.get("DATABASE_URL")

if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///thirupugazh_pos.db"
    print("⚠️ DATABASE_URL not set. Using local SQLite DB")

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
    status = db.Column(db.String(20), default="ACTIVE")  # ACTIVE / HOLD / PAID
    customer_name = db.Column(db.String(100))
    customer_phone = db.Column(db.String(20))
    transaction_id = db.Column(db.String(100))
    discount = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("cart.id"))
    menu_id = db.Column(db.Integer, db.ForeignKey("menu.id"))
    quantity = db.Column(db.Integer, default=1)
    menu = db.relationship("Menu")

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bill_no = db.Column(db.String(30), unique=True)  # ✅ BILL NUMBER
    total = db.Column(db.Integer, nullable=False)
    payment_method = db.Column(db.String(20))
    customer_name = db.Column(db.String(100))
    customer_phone = db.Column(db.String(20))
    staff_id = db.Column(db.Integer)
    business_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ==================================================
# BILL NUMBER GENERATOR
# ==================================================
def generate_bill_no():
    year = datetime.now().year
    prefix = f"TLA-{year}"

    last_sale = (
        Sale.query
        .filter(Sale.bill_no.like(f"{prefix}-%"))
        .order_by(Sale.id.desc())
        .first()
    )

    if last_sale and last_sale.bill_no:
        last_number = int(last_sale.bill_no.split("-")[-1])
        next_number = last_number + 1
    else:
        next_number = 1

    return f"{prefix}-{str(next_number).zfill(4)}"

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
    return render_template("admin_report.html")

@app.route("/ui/change-password")
def ui_change_password():
    return render_template("change_password.html")

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
# CHANGE PASSWORD
# ==================================================
@app.route("/change-password", methods=["POST"])
def change_password():
    data = request.json
    user = User.query.get(data.get("user_id"))

    if not user or not check_password_hash(user.password, data.get("old_password")):
        return jsonify({"status": "error"}), 400

    user.password = generate_password_hash(data.get("new_password"))
    db.session.commit()
    return jsonify({"status": "ok"})

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
# CART
# ==================================================
@app.route("/cart/create", methods=["POST"])
def create_cart():
    cart = Cart(status="ACTIVE")
    db.session.add(cart)
    db.session.commit()
    return jsonify({"cart_id": cart.id})

@app.route("/cart/add", methods=["POST"])
def add_to_cart():
    d = request.json
    item = CartItem.query.filter_by(cart_id=d["cart_id"], menu_id=d["menu_id"]).first()
    if item:
        item.quantity += 1
    else:
        db.session.add(CartItem(cart_id=d["cart_id"], menu_id=d["menu_id"], quantity=1))
    db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/cart/remove", methods=["POST"])
def remove_from_cart():
    d = request.json
    item = CartItem.query.filter_by(cart_id=d["cart_id"], menu_id=d["menu_id"]).first()
    if item:
        if item.quantity > 1:
            item.quantity -= 1
        else:
            db.session.delete(item)
    db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/cart/<int:cart_id>")
def view_cart(cart_id):
    items = CartItem.query.filter_by(cart_id=cart_id).all()
    total = 0
    result = []
    for i in items:
        subtotal = i.menu.price * i.quantity
        total += subtotal
        result.append({
            "menu_id": i.menu.id,
            "name": i.menu.name,
            "quantity": i.quantity,
            "subtotal": subtotal
        })
    return jsonify({"items": result, "total": total})

# ==================================================
# HOLD / RESUME
# ==================================================
@app.route("/cart/hold", methods=["POST"])
def hold_cart():
    cart = Cart.query.get(request.json.get("cart_id"))
    if cart and cart.status == "ACTIVE":
        cart.status = "HOLD"
        db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/cart/held")
def held_carts():
    carts = Cart.query.filter_by(status="HOLD").order_by(Cart.created_at.desc()).all()
    return jsonify([
        {"cart_id": c.id, "created_at": c.created_at.strftime("%d-%m-%Y %I:%M %p")}
        for c in carts
    ])

@app.route("/cart/resume/<int:cart_id>")
def resume_cart(cart_id):
    cart = Cart.query.get(cart_id)
    if cart and cart.status == "HOLD":
        cart.status = "ACTIVE"
        db.session.commit()
    return jsonify({"cart_id": cart_id})

# ==================================================
# CHECKOUT (WITH BILL NUMBER)
# ==================================================
@app.route("/checkout", methods=["POST"])
def checkout():
    d = request.json
    items = CartItem.query.filter_by(cart_id=d["cart_id"]).all()
    total = sum(i.menu.price * i.quantity for i in items)

    bill_no = generate_bill_no()

    sale = Sale(
        bill_no=bill_no,
        total=total,
        payment_method=d.get("payment_method"),
        customer_name=d.get("customer_name"),
        customer_phone=d.get("customer_phone"),
        staff_id=d.get("staff_id"),
        business_date=get_business_date()
    )

    db.session.add(sale)
    Cart.query.get(d["cart_id"]).status = "PAID"
    db.session.commit()

    return jsonify({
        "total": total,
        "bill_no": bill_no
    })

# ==================================================
# ADMIN STAFF MANAGEMENT
# ==================================================
@app.route("/admin/staff/list")
def admin_staff_list():
    staff = User.query.filter(User.role != "admin").all()
    return jsonify([
        {"id": s.id, "username": s.username, "status": s.status}
        for s in staff
    ])

@app.route("/admin/staff/toggle", methods=["POST"])
def admin_staff_toggle():
    staff = User.query.get(request.json.get("staff_id"))
    if not staff or staff.role == "admin":
        return jsonify({"status": "error"}), 400

    staff.status = "DISABLED" if staff.status == "ACTIVE" else "ACTIVE"
    db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/admin/staff/reset-password", methods=["POST"])
def admin_staff_reset_password():
    staff = User.query.get(request.json.get("staff_id"))
    if not staff or staff.role == "admin":
        return jsonify({"status": "error"}), 400

    staff.password = generate_password_hash(request.json.get("new_password"))
    db.session.commit()
    return jsonify({"status": "ok"})

# ==================================================
# ADMIN DAILY REPORT
# ==================================================
@app.route("/admin/report/daily")
def admin_daily_report():
    date_str = request.args.get("date")
    business_date = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else get_business_date()
    sales = Sale.query.filter_by(business_date=business_date).all()
    return jsonify({
        "bill_count": len(sales),
        "total_amount": sum(s.total for s in sales)
    })

# ==================================================
# ADMIN DAILY EXCEL (WITH BILL NO)
# ==================================================
@app.route("/admin/report/daily/excel")
def admin_daily_excel():
    date_str = request.args.get("date")
    business_date = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else get_business_date()

    sales = Sale.query.filter_by(business_date=business_date).order_by(Sale.id.asc()).all()

    data = []
    for s in sales:
        data.append({
            "Bill No": s.bill_no,
            "Customer Name": s.customer_name or "",
            "Mobile": s.customer_phone or "",
            "Payment Mode": s.payment_method,
            "Amount": s.total,
            "Date Time": s.created_at.strftime("%d-%m-%Y %I:%M %p")
        })

    df = pd.DataFrame(data)

    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=f"daily_sales_{business_date}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

# ==================================================
# ADMIN DAILY PDF (WITH BILL NO)
# ==================================================
@app.route("/admin/report/daily/pdf")
def admin_daily_pdf():
    date_str = request.args.get("date")
    business_date = datetime.strptime(date_str, "%Y-%m-%d").date() if date_str else get_business_date()

    sales = Sale.query.filter_by(business_date=business_date).order_by(Sale.id.asc()).all()

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    y = 800

    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(50, y, f"Daily Sales Report - {business_date}")
    y -= 30

    pdf.setFont("Helvetica", 10)

    if not sales:
        pdf.drawString(50, y, "No sales found")
    else:
        for s in sales:
            line = f"{s.bill_no} | {s.payment_method} | ₹{s.total}"
            pdf.drawString(50, y, line)
            y -= 18

            if y < 50:
                pdf.showPage()
                y = 800
                pdf.setFont("Helvetica", 10)

    pdf.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"daily_sales_{business_date}.pdf",
        mimetype="application/pdf"
    )

# ==================================================
# INIT DB
# ==================================================
def init_db():
    with app.app_context():
        db.create_all()

        if not User.query.first():
            db.session.add(User(username="admin", password=generate_password_hash("admin123"), role="admin"))
            db.session.add(User(username="staff1", password=generate_password_hash("1234"), role="staff"))

        if not Menu.query.first():
            db.session.add_all([
                Menu(name="Full Set", price=580),
                Menu(name="Half Set", price=300),
                Menu(name="Three Tickets", price=150)
            ])

        db.session.commit()

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
