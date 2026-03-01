from flask import Flask, request, jsonify, render_template, send_file
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os, io
import pandas as pd

# ==================================================
# IST CONVERSION HELPER
# ==================================================
def to_ist(dt):
    if not dt:
        return None
    return dt + timedelta(hours=5, minutes=30)

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

    app.config["SQLALCHEMY_ENGINE_OPTIONS"] = {
    "pool_pre_ping": True,
    "pool_recycle": 180,
    "pool_size": 3,
    "max_overflow": 2,
    "pool_timeout": 30
}

else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///thirupugazh_pos.db"

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

    custom_price = db.Column(db.Integer)  # NEW
    custom_name = db.Column(db.String(100))   # NEW

    menu = db.relationship("Menu")

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    bill_no = db.Column(db.String(30), unique=True)

    subtotal = db.Column(db.Integer, nullable=False)   # NEW
    discount = db.Column(db.Integer, default=0)       # NEW
    total = db.Column(db.Integer, nullable=False)     # FINAL AFTER DISCOUNT
    items_json = db.Column(db.JSON)
    payment_method = db.Column(db.String(20))
    customer_name = db.Column(db.String(100))
    customer_phone = db.Column(db.String(20))
    staff_id = db.Column(db.Integer)
    business_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default="COMPLETED")

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

@app.route("/ui/admin-breakdown")
def ui_admin_breakdown():
    return render_template("admin_breakdown.html")

# ==================================================
# STAFF CASH CLOSING DATA
# ==================================================
@app.route("/staff/report/cash-summary")
def staff_cash_summary():
    staff_id = request.args.get("staff_id")

    if not staff_id:
        return jsonify({"expected_cash": 0})

    business_date = get_business_date()

    sales = Sale.query.filter_by(
        staff_id=staff_id,
        business_date=business_date
    ).all()

    expected_cash = 0

    for s in sales:
        if s.payment_method == "CASH":
            expected_cash += s.total

    return jsonify({
        "expected_cash": expected_cash
    })

# ==================================================
# ADMIN VOID BILL
# ==================================================
@app.route("/admin/sale/void", methods=["POST"])
def admin_void_sale():
    data = request.json
    sale_id = data.get("sale_id")

    sale = Sale.query.get(sale_id)

    if not sale:
        return jsonify({"status": "not_found"}), 404

    if sale.status == "VOID":
        return jsonify({"status": "already_void"})

    sale.status = "VOID"
    db.session.commit()

    return jsonify({"status": "ok"})

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
# ADMIN DAILY REPORT WITH BILL NUMBER
# ==================================================
@app.route("/admin/report/daily/data")
def admin_daily_data():

    business_date = get_business_date()

    query = Sale.query.filter(
        Sale.business_date == business_date,
        Sale.status == "COMPLETED"
    )

    sales = query.all()

    return jsonify({
        "bill_count": len(sales),
        "total_amount": sum(s.total or 0 for s in sales)
    })
# ==================================================
# ADMIN SALES VIEW
# ==================================================
@app.route("/admin/sales-breakdown")
def admin_sales_breakdown():

    business_date = get_business_date()

    sales = Sale.query.filter(
        Sale.business_date == business_date,
        Sale.status == "COMPLETED"
    ).all()

    total_sales = sum((s.total or 0) for s in sales)
    total_bills = len(sales)

    payment_totals = {
        "CASH": 0,
        "UPI": 0,
        "GPAY": 0,
        "ONLINE": 0,
        "MIXED": 0
    }

    for s in sales:
        if s.payment_method in payment_totals:
            payment_totals[s.payment_method] += (s.total or 0)

    return jsonify({
        "total_sales": total_sales,
        "total_bills": total_bills,
        "payment_breakdown": payment_totals
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

@app.route("/owner/dashboard")
def owner_dashboard():
    business_date = get_business_date()

    sales_today = Sale.query.filter_by(
        business_date=business_date
    ).all()

    total_today = 0
    bill_count = len(sales_today)

    cash_total = 0
    upi_total = 0
    gpay_total = 0
    online_total = 0

    staff_data = {}

    for s in sales_today:
        total_today += s.total or 0

        if s.payment_method == "CASH":
            cash_total += s.total or 0
        elif s.payment_method == "UPI":
            upi_total += s.total or 0
        elif s.payment_method == "GPAY":
            gpay_total += s.total or 0
        elif s.payment_method == "ONLINE":
            online_total += s.total or 0

        if s.staff_id:
            staff = User.query.get(s.staff_id)
            if staff:
                staff_data.setdefault(staff.username, 0)
                staff_data[staff.username] += s.total or 0

    hold_count = Cart.query.filter_by(status="HOLD").count()

    now = datetime.now()
    monthly_sales = Sale.query.filter(
        db.extract("month", Sale.business_date) == now.month,
        db.extract("year", Sale.business_date) == now.year
    ).all()

    monthly_total = sum(s.total or 0 for s in monthly_sales)

    return jsonify({
        "total_today": total_today,
        "bill_count": bill_count,
        "cash_total": cash_total,
        "upi_total": upi_total,
        "gpay_total": gpay_total,
        "online_total": online_total,
        "hold_count": hold_count,
        "staff_performance": [
            {"staff": name, "total": amount}
            for name, amount in staff_data.items()
        ],
        "monthly_total": monthly_total
    })

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

    db.session.add(CartItem(
        cart_id=d["cart_id"],
        menu_id=d.get("menu_id"),
        quantity=1,
        custom_price=d.get("custom_price"),
        custom_name=d.get("custom_name")
    ))

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
        price = i.custom_price if i.custom_price is not None else (i.menu.price if i.menu else 0)
        subtotal = price * i.quantity
        total += subtotal

        result.append({
            "menu_id": i.menu.id if i.menu else 0,
            "name": i.custom_name if i.custom_name else (i.menu.name if i.menu else "Custom Item"),
            "quantity": i.quantity,
            "subtotal": subtotal
        })

    return jsonify({
        "items": result,
        "total": total
    })

# ==================================================
# ADMIN DELETE HOLD BILL (SAFE VERSION)
# ==================================================
@app.route("/admin/hold/delete/<int:cart_id>", methods=["DELETE"])
def admin_delete_hold(cart_id):

    cart = Cart.query.get(cart_id)

    if not cart:
        return jsonify({"error": "Not found"}), 404

    if cart.status != "HOLD":
        return jsonify({"error": "Not a hold bill"}), 400

    # Delete cart items first
    items = CartItem.query.filter_by(cart_id=cart_id).all()
    for item in items:
        db.session.delete(item)

    # Then delete cart
    db.session.delete(cart)

    db.session.commit()

    return jsonify({"status": "deleted"})

# ==================================================
# SERVER TIME CHECK (TEMPORARY DEBUG)
# ==================================================
@app.route("/time-check")
def time_check():
    from datetime import datetime, timedelta

def get_business_date():
    # Convert UTC to IST (UTC + 5:30)
    now = datetime.utcnow() + timedelta(hours=5, minutes=30)

    # 3PM IST business cycle
    if now.hour < 15:
        return (now - timedelta(days=1)).date()

    return now.date()
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

    now = datetime.now()

    # After 3PM staff cannot see holds
    if now.hour >= 15 and role != "admin":
        return jsonify([])

    query = Cart.query.filter_by(status="HOLD")

    if role != "admin" and user_id:
        query = query.filter_by(staff_id=int(user_id))

    carts = query.order_by(Cart.created_at.desc()).all()

    result = []

    for c in carts:
        result.append({
            "cart_id": c.id,
            "customer_name": c.customer_name or "",
            "customer_phone": c.customer_phone or "",
            "created_at": c.created_at.strftime("%d-%m-%Y %I:%M %p")
        })

    return jsonify(result)

@app.route("/cart/resume/<int:cart_id>")
def resume_cart(cart_id):

    role = request.args.get("role")
    now = datetime.now()

    # After 3PM only admin can resume
    if now.hour >= 15 and role != "admin":
        return jsonify({"error": "Hold expired"}), 403

    cart = Cart.query.get(cart_id)

    if cart and cart.status == "HOLD":
        cart.status = "ACTIVE"
        db.session.commit()

        return jsonify({
            "cart_id": cart.id,
            "customer_name": cart.customer_name,
            "customer_phone": cart.customer_phone
        })

    return jsonify({"error": "Not found"}), 404
# ==================================================
# # ==================================================
# CHECKOUT (WITH BILL NUMBER + ITEM STORAGE)
# ==================================================
@app.route("/checkout", methods=["POST"])
def checkout():

    d = request.json or {}
    cart_id = d.get("cart_id")
    discount = int(d.get("discount") or 0)

    if not cart_id:
        return jsonify({"error": "Cart ID missing"}), 400

    items = CartItem.query.filter_by(cart_id=cart_id).all()

    if not items:
        return jsonify({"error": "Cart empty"}), 400

    subtotal = 0
    items_data = []

    for i in items:
        price = i.custom_price if i.custom_price is not None else (i.menu.price if i.menu else 0)
        name = i.custom_name if i.custom_name else (i.menu.name if i.menu else "Custom Item")

        item_subtotal = price * i.quantity
        subtotal += item_subtotal

        items_data.append({
            "name": name,
            "quantity": i.quantity,
            "price": price,
            "subtotal": item_subtotal
        })

    final_total = max(subtotal - discount, 0)

    bill_no = generate_bill_no()

    sale = Sale(
        bill_no=bill_no,
        subtotal=subtotal,
        discount=discount,
        total=final_total,
        items_json=items_data,  # 
        payment_method=d.get("payment_method"),
        customer_name=d.get("customer_name"),
        customer_phone=d.get("customer_phone"),
        staff_id=d.get("staff_id"),
        business_date=get_business_date()  # 
    )

    db.session.add(sale)

    cart = Cart.query.get(cart_id)
    if cart:
        cart.status = "PAID"

    db.session.commit()

    return jsonify({
        "subtotal": subtotal,
        "discount": discount,
        "total": final_total,
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
    business_date=get_business_date(),
    status="COMPLETED"
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

    query = Sale.query.filter(
    Sale.business_date == business_date,
    Sale.status == "COMPLETED"
)

    if staff_id:
        query = query.filter(Sale.staff_id == int(staff_id))

    sales = query.order_by(Sale.id.asc()).all()

    return jsonify({
    "bill_count": len(sales),
    "total_amount": sum((s.total or 0) for s in sales),
    "total_discount": sum((s.discount or 0) for s in sales)
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

    query = Sale.query.filter(
        Sale.business_date == business_date,
        Sale.status == "COMPLETED"
    )

    if staff_id:
        query = query.filter(Sale.staff_id == int(staff_id))

    sales = query.order_by(Sale.id.asc()).all()

    data = []

    for s in sales:
        staff = User.query.get(s.staff_id)

        data.append({
    "Bill Number": s.bill_no or "",
    "Staff Name": staff.username if staff else "",
    "Customer Name": s.customer_name or "",
    "Mobile": s.customer_phone or "",
    "Payment Mode": s.payment_method or "",
    "Subtotal (₹)": s.subtotal or 0,
    "Discount (₹)": s.discount or 0,
    "Final Amount (₹)": s.total or 0,
    "Date & Time": to_ist(s.created_at).strftime("%d-%m-%Y %I:%M %p") if s.created_at else ""
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
# STAFF TODAY DISCOUNT SUMMARY
# ==================================================
@app.route("/staff/report/discount")
def staff_discount_report():
    staff_id = request.args.get("staff_id")

    if not staff_id:
        return jsonify({"total_discount": 0})

    sales = Sale.query.filter_by(
        staff_id=staff_id,
        business_date=get_business_date(),
        status="COMPLETED"
    ).all()

    total_discount = sum(s.discount or 0 for s in sales)

    return jsonify({
        "total_discount": total_discount,
        "bill_count": len(sales)
    })

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

    query = Sale.query.filter(
    Sale.business_date == business_date,
    Sale.status == "COMPLETED"
)

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

        total_amount += (s.total or 0)
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
# ADMIN TOTAL DISCOUNT (ALL STAFF - TODAY)
# ==================================================
@app.route("/admin/report/discount")
def admin_discount_report():

    try:
        business_date = get_business_date()

        sales = Sale.query.filter(
            Sale.business_date == business_date,
            Sale.status == "COMPLETED"
        ).all()

        total_discount = 0
        staff_summary = {}

        for s in sales:
            discount_value = s.discount if s.discount else 0
            total_discount += discount_value

            if s.staff_id:
                staff = User.query.get(s.staff_id)
                if staff:
                    staff_summary.setdefault(staff.username, 0)
                    staff_summary[staff.username] += discount_value

        return jsonify({
            "total_discount": total_discount,
            "staff_breakdown": staff_summary
        })

    except Exception as e:
        print("Discount route error:", e)
        return jsonify({
            "total_discount": 0,
            "staff_breakdown": {}
        })

# ==================================================
# ADMIN MONTHLY REPORT (WITH BILL NUMBERS)
# ==================================================
@app.route("/admin/report/monthly")
def admin_monthly_report():
    month = int(request.args.get("month"))
    year = int(request.args.get("year"))

    sales = Sale.query.filter(
    db.extract("month", Sale.business_date) == month,
    db.extract("year", Sale.business_date) == year,
    Sale.status == "COMPLETED"
).order_by(Sale.id.asc()).all()

    return jsonify({
    "bill_count": len(sales),
    "total_amount": sum((s.total or 0) for s in sales),
    "total_discount": sum(s.discount for s in sales)  # NEW
})

# ==================================================
# Bill PDF for Each Transaction (IST TIME VERSION)
# ==================================================
@app.route("/bill/<int:sale_id>/pdf")
def generate_bill_pdf(sale_id):

    sale = Sale.query.get_or_404(sale_id)

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)

    width, height = A4

    # ================= COLORED HEADER STRIP =================
    pdf.setFillColorRGB(0.12, 0.23, 0.54)
    pdf.rect(0, height - 100, width, 100, fill=1)

    pdf.setFillColorRGB(1, 1, 1)

    # ================= LOGO =================
    logo_path = os.path.join(app.root_path, "static", "logo.png")
    if os.path.exists(logo_path):
        pdf.drawImage(
            logo_path,
            50,
            height - 85,
            width=70,
            height=50,
            preserveAspectRatio=True,
            mask='auto'
        )

    # ================= SHOP NAME =================
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(140, height - 60, "Thirupugazh Lottery Agency")

    pdf.setFont("Helvetica", 11)
    pdf.drawString(140, height - 80, "M.Pudur, Govindhapuram, Palakad (Dt) , Kerala - 678507")
    pdf.drawString(140, height - 95, "Phone: 04923 - 276225")

    pdf.setFillColorRGB(0, 0, 0)

    y = height - 140

    # ================= BILL DETAILS =================
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(50, y, "Bill Details")
    y -= 20

    pdf.setFont("Helvetica", 11)

    # 🔥 CONVERT TO IST HERE
    ist_time = to_ist(sale.created_at)

    pdf.drawString(50, y, f"Bill No: {sale.bill_no}")
    y -= 18

    pdf.drawString(
        50,
        y,
        f"Date: {ist_time.strftime('%d-%m-%Y %I:%M %p')} IST"
    )
    y -= 18

    pdf.drawString(50, y, f"Customer Name: {sale.customer_name}")
    y -= 18

    pdf.drawString(50, y, f"Mobile: {sale.customer_phone}")
    y -= 18

    pdf.drawString(50, y, f"Payment Mode: {sale.payment_method}")
    y -= 40

    # ================= TOTAL SECTION =================
    pdf.setFont("Helvetica-Bold", 14)

    pdf.drawString(50, y, f"Subtotal: ₹{sale.subtotal}")
    y -= 20

    pdf.drawString(50, y, f"Discount: ₹{sale.discount}")
    y -= 20

    pdf.drawString(50, y, f"Final Total: ₹{sale.total}")
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

    # ================= SHOP NAME =================
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(140, height - 60, "Thirupugazh Lottery Agency")

    pdf.setFont("Helvetica", 11)
    pdf.drawString(140, height - 80, "M.Pudur, Govindhapuram, Palakad (Dt) , Kerala - 678507")
    pdf.drawString(140, height - 95, "Phone: 04923 - 276225")

    pdf.setFillColorRGB(0, 0, 0)

    y = height - 140

    # ================= BILL DETAILS =================
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(50, y, "Bill Details")
    y -= 20

    pdf.setFont("Helvetica", 11)
    pdf.drawString(50, y, f"Bill No: {sale.bill_no}")
    y -= 18
    pdf.drawString(50, y, f"Date: to_ist(sale.created_at).strftime('%d-%m-%Y %I:%M %p')
    y -= 18
    pdf.drawString(50, y, f"Customer Name: {sale.customer_name}")
    y -= 18
    pdf.drawString(50, y, f"Mobile: {sale.customer_phone}")
    y -= 18
    pdf.drawString(50, y, f"Payment Mode: {sale.payment_method}")

    y -= 30

# ================= ITEM TABLE HEADER =================
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(50, y, "Item")
    pdf.drawString(250, y, "Qty")
    pdf.drawString(300, y, "Price")
    pdf.drawString(380, y, "Total")
    y -= 15

    pdf.line(50, y, 500, y)
    y -= 15

    pdf.setFont("Helvetica", 10)

# ================= ITEM LIST =================
    if sale.items_json:
        for item in sale.items_json:
            pdf.drawString(50, y, str(item.get("name", ""))[:25])
            pdf.drawString(250, y, str(item.get("quantity", "")))
            pdf.drawString(300, y, f"₹{item.get('price', 0)}")
            pdf.drawString(380, y, f"₹{item.get('subtotal', 0)}")

            y -= 18

            if y < 100:
                pdf.showPage()
                y = 800
                pdf.setFont("Helvetica", 10)

    y -= 10
    pdf.line(50, y, 500, y)
    y -= 25

        # ================= TOTAL SECTION =================
    pdf.setFont("Helvetica-Bold", 12)

    pdf.drawString(50, y, f"Subtotal: ₹{sale.subtotal}")
    y -= 20

    pdf.drawString(50, y, f"Discount: ₹{sale.discount}")
    y -= 20

    pdf.drawString(50, y, f"Final Total: ₹{sale.total}")
    y -= 30

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
    Sale.business_date < end_date.date(),
    Sale.status == "COMPLETED"
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
    "Subtotal (₹)": s.subtotal,
    "Discount (₹)": s.discount,
    "Final Amount (₹)": s.total,
    "Date & Time": to_ist(s.created_at).strftime("%d-%m-%Y %I:%M %p")
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
    Sale.business_date < end_date.date(),
    Sale.status == "COMPLETED"
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
# BUSINESS DATE DEBUG CHECK
# ==================================================
@app.route("/business-date-check")
def business_date_check():
    from datetime import datetime, timedelta

    # Convert UTC to IST
    ist_now = datetime.utcnow() + timedelta(hours=5, minutes=30)

    return jsonify({
        "utc_time": datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S"),
        "ist_time": ist_now.strftime("%Y-%m-%d %H:%M:%S"),
        "business_date": str(get_business_date())
    })

# ==================================================
# ADMIN UPDATE STAFF USERNAME
# ==================================================
@app.route("/admin/staff/update-username", methods=["POST"])
def admin_update_staff_username():
    data = request.json
    staff = User.query.get(data.get("staff_id"))

    if not staff or staff.role == "admin":
        return jsonify({"status": "error"}), 400

    new_username = data.get("new_username").strip()

    # Prevent duplicate usernames
    if User.query.filter_by(username=new_username).first():
        return jsonify({"status": "exists"}), 400

    staff.username = new_username
    db.session.commit()

    return jsonify({"status": "ok"})

# ==================================================
# STAFF DAILY CLOSING PDF (WITH PAYMENT BREAKDOWN)
# ==================================================
@app.route("/staff/report/daily/pdf")
def staff_daily_pdf():
    staff_id = request.args.get("staff_id")

    if not staff_id:
        return "Staff ID required", 400

    business_date = get_business_date()
    day_name = business_date.strftime("%A")

    sales = Sale.query.filter(
    Sale.staff_id == staff_id,
    Sale.business_date == business_date,
    Sale.status == "COMPLETED"
).order_by(Sale.id.asc()).all()

    hold_count = Cart.query.filter_by(
        staff_id=staff_id,
        status="HOLD"
    ).count()

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)

    y = 800

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(50, y, "Thirupugazh Lottery Agency")
    y -= 30

    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(50, y, "Daily Closing Report")
    y -= 30

    pdf.setFont("Helvetica", 11)
    pdf.drawString(50, y, f"Business Date: {business_date} ({day_name})")
    y -= 20

    staff = User.query.get(staff_id)
    pdf.drawString(50, y, f"Staff: {staff.username if staff else ''}")
    y -= 30

    total_amount = 0

    # Payment breakdown dictionary
    payment_totals = {
        "CASH": 0,
        "UPI": 0,
        "GPAY": 0,
        "ONLINE": 0,
        "MIXED": 0
    }

    # Table Header
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(50, y, "Bill No")
    pdf.drawString(130, y, "Customer")
    pdf.drawString(250, y, "Payment")
    pdf.drawString(350, y, "Amount")
    y -= 20

    pdf.setFont("Helvetica", 9)

    for s in sales:
        pdf.drawString(50, y, s.bill_no or "")
        pdf.drawString(130, y, (s.customer_name or "")[:15])
        pdf.drawString(250, y, s.payment_method or "")
        pdf.drawString(350, y, f"₹{s.total}")

        total_amount += (s.total or 0)

        # Add to payment breakdown
        if s.payment_method in payment_totals:
            payment_totals[s.payment_method] += (s.total or 0)

        y -= 18

        if y < 100:
            pdf.showPage()
            y = 800
            pdf.setFont("Helvetica", 9)

    y -= 20

    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(50, y, f"Total Bills: {len(sales)}")
    y -= 20
    pdf.drawString(50, y, f"Active Holds: {hold_count}")
    y -= 30

    # PAYMENT BREAKDOWN SECTION
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(50, y, "Payment Breakdown")
    y -= 20

    pdf.setFont("Helvetica", 11)

    for mode, amount in payment_totals.items():
        if amount > 0:
            pdf.drawString(60, y, f"{mode}: ₹{amount}")
            y -= 18

    y -= 10
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(50, y, f"Grand Total: ₹{total_amount}")

    pdf.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"closing_report_{business_date}.pdf",
        mimetype="application/pdf"
    )

@app.route("/health")
def health():
    return "OK", 200

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
                Menu(name="Three Tickets", price=150),
                Menu(name="Custom Amount", price=0)  # NEW

            ])

        db.session.commit()

init_db()

@app.errorhandler(Exception)
def handle_exception(e):
    print("Unhandled error:", e)
    return jsonify({"error": "Internal server error"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
