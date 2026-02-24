from flask import Flask, request, jsonify, render_template, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os, io
import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.platypus import Image
from reportlab.lib.utils import ImageReader

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
    status = db.Column(db.String(20), default="ACTIVE")
    staff_id = db.Column(db.Integer)
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
    return render_template("admin_reports.html")

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
            "username": user.username,
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
# DASHBOARD API
# ==================================================
@app.route("/admin/dashboard")
def admin_dashboard():
    today = get_business_date()

    # Today's sales
    today_sales = Sale.query.filter_by(business_date=today).all()
    today_total = sum(s.total for s in today_sales)

    # Hold carts
    hold_count = Cart.query.filter_by(status="HOLD").count()

    # Monthly sales
    now = datetime.now()
    monthly_sales = Sale.query.filter(
        db.extract("month", Sale.business_date) == now.month,
        db.extract("year", Sale.business_date) == now.year
    ).all()

    monthly_total = sum(s.total for s in monthly_sales)

    return jsonify({
        "today_total": today_total,
        "today_bills": len(today_sales),
        "hold_count": hold_count,
        "monthly_total": monthly_total,
        "monthly_bills": len(monthly_sales)
    })

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
    data = request.json or {}

    cart = Cart(
        status="ACTIVE",
        staff_id=data.get("staff_id")
    )

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
    data = request.json
    cart = Cart.query.get(data.get("cart_id"))

    if cart and cart.status == "ACTIVE":
        cart.status = "HOLD"
        cart.customer_name = data.get("customer_name")
        cart.customer_phone = data.get("customer_phone")
        db.session.commit()

    return jsonify({"status": "ok"})

@app.route("/cart/held")
def held_carts():
    role = request.args.get("role")
    user_id = request.args.get("user_id")

    query = Cart.query.filter_by(status="HOLD")

    if role != "admin" and user_id:
        query = query.filter_by(staff_id=int(user_id))

    carts = query.order_by(Cart.created_at.desc()).all()

    result = []

    for c in carts:
        items = CartItem.query.filter_by(cart_id=c.id).all()
        staff = User.query.get(c.staff_id)

        item_list = []
        for i in items:
            item_list.append(f"{i.menu.name} x{i.quantity}")

        result.append({
    "cart_id": c.id,
    "bill_no": f"HOLD-{c.id}",
    "customer_name": c.customer_name or "",
    "customer_phone": c.customer_phone or "",
    "staff_name": staff.username if staff else "",
    "items": ", ".join(item_list),
    "created_at": c.created_at.strftime("%d-%m-%Y %I:%M %p")
})

@app.route("/cart/resume/<int:cart_id>")
def resume_cart(cart_id):
    cart = Cart.query.get(cart_id)

    if cart and cart.status == "HOLD":
        cart.status = "ACTIVE"
        db.session.commit()

        return jsonify({
            "cart_id": cart.id,
            "customer_name": cart.customer_name,
            "customer_phone": cart.customer_phone
        })

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
    "bill_no": bill_no,
    "sale_id": sale.id
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
# STAFF DAILY SALES (ONLY THEIR OWN)
# ==================================================
@app.route("/staff/report/daily")
def staff_daily_report():
    staff_id = request.args.get("staff_id")

    if not staff_id:
        return jsonify({
            "bill_count": 0,
            "total_amount": 0
        })

    sales = Sale.query.filter_by(
        staff_id=staff_id,
        business_date=get_business_date()
    ).all()

    return jsonify({
        "bill_count": len(sales),
        "total_amount": sum(s.total for s in sales)
    })
# ==================================================
# ADMIN DAILY REPORT (WITH STAFF FILTER)
# ==================================================
@app.route("/admin/report/daily")
def admin_daily_report():
    date_str = request.args.get("date")
    staff_id = request.args.get("staff_id")

    business_date = (
        datetime.strptime(date_str, "%Y-%m-%d").date()
        if date_str else get_business_date()
    )

    query = Sale.query.filter(Sale.business_date == business_date)

    if staff_id:
        query = query.filter(Sale.staff_id == int(staff_id))

    sales = query.order_by(Sale.id.asc()).all()

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
    staff_id = request.args.get("staff_id")

    business_date = (
        datetime.strptime(date_str, "%Y-%m-%d").date()
        if date_str else get_business_date()
    )

    query = Sale.query.filter(Sale.business_date == business_date)

    if staff_id:
        query = query.filter(Sale.staff_id == int(staff_id))

    sales = query.order_by(Sale.id.asc()).all()

    data = []

    for s in sales:
        staff = User.query.get(s.staff_id)
        data.append({
            "Bill Number": s.bill_no,
            "Staff ID": s.staff_id,
            "Staff Name": staff.username if staff else "",
            "Customer Name": s.customer_name or "",
            "Mobile": s.customer_phone or "",
            "Payment Mode": s.payment_method,
            "Amount (₹)": s.total,
            "Date & Time": s.created_at.strftime("%d-%m-%Y %I:%M %p")
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
    staff_id = request.args.get("staff_id")

    business_date = (
        datetime.strptime(date_str, "%Y-%m-%d").date()
        if date_str else get_business_date()
    )

    query = Sale.query.filter(Sale.business_date == business_date)

    if staff_id:
        query = query.filter(Sale.staff_id == int(staff_id))

    sales = query.order_by(Sale.id.asc()).all()

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    y = 800

    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(50, y, f"Daily Sales Report - {business_date}")
    y -= 30

    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(50, y, "Bill No")
    pdf.drawString(130, y, "Staff")
    pdf.drawString(220, y, "Payment")
    pdf.drawString(320, y, "Amount")
    y -= 20

    pdf.setFont("Helvetica", 10)

    total_amount = 0

    for s in sales:
        staff = User.query.get(s.staff_id)

        pdf.drawString(50, y, s.bill_no)
        pdf.drawString(130, y, staff.username if staff else "")
        pdf.drawString(220, y, s.payment_method or "")
        pdf.drawString(320, y, f"₹{s.total}")

        total_amount += s.total
        y -= 18

        if y < 50:
            pdf.showPage()
            y = 800
            pdf.setFont("Helvetica", 10)

    y -= 10
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(50, y, f"Total: ₹{total_amount}")

    pdf.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"daily_sales_{business_date}.pdf",
        mimetype="application/pdf"
    )

# ==================================================
# ADMIN MONTHLY REPORT (WITH BILL NUMBERS)
# ==================================================
@app.route("/admin/report/monthly")
def admin_monthly_report():
    month = int(request.args.get("month"))
    year = int(request.args.get("year"))

    sales = Sale.query.filter(
        db.extract("month", Sale.business_date) == month,
        db.extract("year", Sale.business_date) == year
    ).order_by(Sale.id.asc()).all()

    return jsonify({
        "bill_count": len(sales),
        "total_amount": sum(s.total for s in sales),
        "bills": [
            {
                "bill_no": s.bill_no,
                "amount": s.total
            }
            for s in sales
        ]
    })

# ==================================================
# Bill PDF for Each Transaction
# ==================================================
@app.route("/bill/<int:sale_id>/pdf")
def generate_bill_pdf(sale_id):
    sale = Sale.query.get_or_404(sale_id)

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)

    width, height = A4

    # ================= COLORED HEADER STRIP =================
    pdf.setFillColorRGB(0.12, 0.23, 0.54)  # Dark blue
    pdf.rect(0, height - 100, width, 100, fill=1)

    # Reset text color to white
    pdf.setFillColorRGB(1, 1, 1)

    # ================= LOGO =================
    logo_path = os.path.join(app.root_path, "static", "logo.png")
    if os.path.exists(logo_path):
        pdf.drawImage(logo_path, 50, height - 85, width=70, height=50, preserveAspectRatio=True, mask='auto')

    # ================= SHOP NAME =================
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(140, height - 60, "Thirupugazh Lottery Agency")

    pdf.setFont("Helvetica", 11)
    pdf.drawString(140, height - 80, "M.Pudur, Govindhapuram, Palakad (Dt) , Kerala - 678507")
    pdf.drawString(140, height - 95, "Phone: 04923 - 276225")
    
    # Reset text color to black
    pdf.setFillColorRGB(0, 0, 0)

    y = height - 140

    # ================= BILL DETAILS =================
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(50, y, "Bill Details")
    y -= 20

    pdf.setFont("Helvetica", 11)
    pdf.drawString(50, y, f"Bill No: {sale.bill_no}")
    y -= 18
    pdf.drawString(50, y, f"Date: {sale.created_at.strftime('%d-%m-%Y %I:%M %p')}")
    y -= 18
    pdf.drawString(50, y, f"Customer Name: {sale.customer_name}")
    y -= 18
    pdf.drawString(50, y, f"Mobile: {sale.customer_phone}")
    y -= 18
    pdf.drawString(50, y, f"Payment Mode: {sale.payment_method}")

    y -= 40

    # ================= TOTAL SECTION =================
    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(50, y, f"Total Amount: ₹{sale.total}")

    y -= 40

    pdf.setFont("Helvetica-Oblique", 10)
    pdf.drawString(50, y, "Thank you for choosing Thirupugazh Lottery Agency!")
    pdf.drawString(50, y - 15, "We appreciate your business.")

    pdf.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"{sale.bill_no}.pdf",
        mimetype="application/pdf"
    )

# ==================================================
# ADMIN MONTHLY EXCEL (WITH BILL NUMBER COLUMN)
# ==================================================
@app.route("/admin/report/monthly/excel")
def admin_monthly_excel():
    month = request.args.get("month")
    year = request.args.get("year")
    staff_id = request.args.get("staff_id")

    if not month or not year:
        return "Month and Year required", 400

    month = int(month)
    year = int(year)

    start_date = datetime(year, month, 1)
    end_date = datetime(year + (month // 12), (month % 12) + 1, 1)

    query = Sale.query.filter(
        Sale.business_date >= start_date.date(),
        Sale.business_date < end_date.date()
    )

    if staff_id:
        query = query.filter(Sale.staff_id == int(staff_id))

    sales = query.order_by(Sale.id.asc()).all()

    data = []

    for s in sales:
        staff = User.query.get(s.staff_id)
        data.append({
            "Bill Number": s.bill_no,
            "Staff ID": s.staff_id,
            "Staff Name": staff.username if staff else "",
            "Customer Name": s.customer_name or "",
            "Mobile": s.customer_phone or "",
            "Payment Mode": s.payment_method,
            "Amount (₹)": s.total,
            "Date & Time": s.created_at.strftime("%d-%m-%Y %I:%M %p")
        })

    df = pd.DataFrame(data)

    output = io.BytesIO()
    df.to_excel(output, index=False)
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=f"monthly_sales_{month}_{year}.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
# ==================================================
# ADMIN MONTHLY PDF (WITH BILL NUMBER COLUMN FORMAT)
# ==================================================
@app.route("/admin/report/monthly/pdf")
def admin_monthly_pdf():
    month = request.args.get("month")
    year = request.args.get("year")
    staff_id = request.args.get("staff_id")

    if not month or not year:
        return "Month and Year required", 400

    month = int(month)
    year = int(year)

    start_date = datetime(year, month, 1)
    end_date = datetime(year + (month // 12), (month % 12) + 1, 1)

    query = Sale.query.filter(
        Sale.business_date >= start_date.date(),
        Sale.business_date < end_date.date()
    )

    if staff_id:
        query = query.filter(Sale.staff_id == int(staff_id))

    sales = query.order_by(Sale.id.asc()).all()

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    y = 800

    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(50, y, f"Monthly Sales Report - {month}/{year}")
    y -= 30

    pdf.setFont("Helvetica", 10)

    total = 0

    for s in sales:
        staff = User.query.get(s.staff_id)
        pdf.drawString(50, y, s.bill_no)
        pdf.drawString(150, y, staff.username if staff else "")
        pdf.drawString(250, y, s.payment_method or "")
        pdf.drawString(350, y, f"₹{s.total}")

        total += s.total
        y -= 18

        if y < 50:
            pdf.showPage()
            y = 800
            pdf.setFont("Helvetica", 10)

    y -= 10
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(50, y, f"Total: ₹{total}")

    pdf.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"monthly_sales_{month}_{year}.pdf",
        mimetype="application/pdf"
    )
# ==================================================
# INIT DB
# ==================================================
def init_db():
    with app.app_context():
        db.create_all()

        # Create admin if not exists
        if not User.query.filter_by(username="admin").first():
            db.session.add(User(
                username="admin",
                password=generate_password_hash("admin123"),
                role="admin"
            ))

        # Create staff1 to staff10
        for i in range(1, 11):
            username = f"staff{i}"
            if not User.query.filter_by(username=username).first():
                db.session.add(User(
                    username=username,
                    password=generate_password_hash("1234"),
                    role="staff"
                ))

        # Default menu
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
