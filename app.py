from flask import Flask, request, jsonify, render_template, Response
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os

app = Flask(__name__)

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

def get_business_date():
    now = datetime.now()
    if now.hour < 15:
        return (now - timedelta(days=1)).date()
    return now.date()

# ---------------- MODELS ----------------

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # admin / staff

class Menu(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False)

class Cart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), default="ACTIVE")  # ACTIVE / HOLD / PAID / EXPIRED
    customer_name = db.Column(db.String(100))
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

@app.route("/ui/admin/reports")
def admin_reports_ui():
    return render_template("admin_reports.html")

# ---------------- AUTH ----------------

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    user = User.query.filter_by(username=data.get("username")).first()
    if user and check_password_hash(user.password, data.get("password")):
        return jsonify({
            "status": "ok",
            "user_id": user.id,
            "role": user.role
        })
    return jsonify({"status": "error"}), 401

# ---------------- ADMIN CHANGE PASSWORD ----------------

@app.route("/admin/change-password", methods=["POST"])
def admin_change_password():
    data = request.json

    admin = User.query.get(data.get("admin_id"))
    if not admin or admin.role != "admin":
        return jsonify({"error": "Unauthorized"}), 403

    user = User.query.get(data.get("user_id"))
    if not user:
        return jsonify({"error": "User not found"}), 404

    user.password = generate_password_hash(data.get("new_password"))
    db.session.commit()
    return jsonify({"status": "password_updated"})

# ---------------- MENU ----------------

@app.route("/menu")
def get_menu():
    items = Menu.query.all()
    return jsonify([
        {"id": i.id, "name": i.name, "price": i.price}
        for i in items
    ])

# ---------------- CART ----------------

@app.route("/cart/create", methods=["POST"])
def create_cart():
    cart = Cart(status="ACTIVE")
    db.session.add(cart)
    db.session.commit()
    return jsonify({"cart_id": cart.id})

@app.route("/cart/add", methods=["POST"])
def add_to_cart():
    data = request.json
    item = CartItem.query.filter_by(
        cart_id=data.get("cart_id"),
        menu_id=data.get("menu_id")
    ).first()

    if item:
        item.quantity += 1
    else:
        db.session.add(CartItem(
            cart_id=data.get("cart_id"),
            menu_id=data.get("menu_id"),
            quantity=1
        ))

    db.session.commit()
    return jsonify({"status": "added"})

@app.route("/cart/remove", methods=["POST"])
def remove_from_cart():
    data = request.json
    item = CartItem.query.filter_by(
        cart_id=data.get("cart_id"),
        menu_id=data.get("menu_id")
    ).first()

    if not item:
        return jsonify({"status": "ok"})

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
            "price": i.menu.price,
            "quantity": i.quantity,
            "subtotal": subtotal
        })

    return jsonify({"items": result, "total": total})

# ---------------- HOLD / RESUME ----------------

@app.route("/cart/hold", methods=["POST"])
def hold_cart():
    data = request.json
    cart = Cart.query.get(data.get("cart_id"))
    if not cart:
        return jsonify({"error": "Cart not found"}), 404

    cart.status = "HOLD"
    cart.customer_name = data.get("customer_name")
    db.session.commit()

    new_cart = Cart(status="ACTIVE")
    db.session.add(new_cart)
    db.session.commit()

    return jsonify({"new_cart_id": new_cart.id})

@app.route("/cart/holds")
def list_holds():
    now = datetime.now()
    cutoff = now.replace(hour=15, minute=0, second=0, microsecond=0)

    carts = Cart.query.filter_by(status="HOLD").all()
    valid = []

    for c in carts:
        if now >= cutoff and c.created_at < cutoff:
            c.status = "EXPIRED"
        else:
            valid.append({
                "id": c.id,
                "customer_name": c.customer_name or "Unknown",
                "created_at": c.created_at.strftime("%H:%M")
            })

    db.session.commit()
    return jsonify(valid)

@app.route("/cart/resume/<int:cart_id>", methods=["POST"])
def resume_cart(cart_id):
    cart = Cart.query.get(cart_id)
    if not cart or cart.status != "HOLD":
        return jsonify({"error": "Invalid cart"}), 400

    cart.status = "ACTIVE"
    db.session.commit()
    return jsonify({"status": "resumed"})

# ---------------- CHECKOUT ----------------

@app.route("/checkout", methods=["POST"])
def checkout():
    data = request.json
    items = CartItem.query.filter_by(cart_id=data.get("cart_id")).all()
    if not items:
        return jsonify({"error": "Cart empty"}), 400

    total = sum(i.menu.price * i.quantity for i in items)

    sale = Sale(
        total=total,
        payment_method=data.get("payment_method"),
        customer_name=data.get("customer_name"),
        customer_phone=data.get("customer_phone"),
        transaction_id=data.get("transaction_id"),
        staff_id=data.get("staff_id"),
        business_date=get_business_date()
    )

    db.session.add(sale)

    cart = Cart.query.get(data.get("cart_id"))
    cart.status = "PAID"

    db.session.commit()
    return jsonify({"status": "success", "total": total})

# ---------------- ADMIN REPORT APIs ----------------

@app.route("/admin/report/daily")
def admin_daily_report():
    date_str = request.args.get("date")
    if not date_str:
        return jsonify({"error": "Date required"}), 400

    date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
    sales = Sale.query.filter_by(business_date=date_obj).all()
    total = sum(s.total for s in sales)

    return jsonify({
        "date": date_str,
        "total_sales": total,
        "count": len(sales)
    })

@app.route("/admin/report/daily/excel")
def admin_daily_report_excel():
    date_str = request.args.get("date")
    if not date_str:
        return "Date required", 400

    date_obj = datetime.strptime(date_str, "%Y-%m-%d").date()
    sales = Sale.query.filter_by(business_date=date_obj).all()

    def generate():
        yield "Bill ID,Amount,Payment Mode,Customer Name,Mobile,Transaction ID,Staff ID,Time\n"
        for s in sales:
            yield f"{s.id},{s.total},{s.payment_method},{s.customer_name},{s.customer_phone},{s.transaction_id},{s.staff_id},{s.created_at.strftime('%H:%M')}\n"

    filename = f"daily_sales_{date_str}.csv"

    return Response(
        generate(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.route("/admin/report/monthly")
def admin_monthly_report():
    year = int(request.args.get("year"))
    month = int(request.args.get("month"))

    start = datetime(year, month, 1)
    end = (start + timedelta(days=32)).replace(day=1)

    sales = Sale.query.filter(
        Sale.created_at >= start,
        Sale.created_at < end
    ).all()

    total = sum(s.total for s in sales)

    return jsonify({
        "year": year,
        "month": month,
        "total_sales": total,
        "count": len(sales)
    })

# ---------------- INIT DB ----------------

def init_db():
    with app.app_context():
        db.create_all()

        if not User.query.first():
            db.session.add(User(
                username="admin",
                password=generate_password_hash("admin123"),
                role="admin"
            ))
            db.session.add(User(
                username="staff1",
                password=generate_password_hash("1234"),
                role="staff"
            ))

        if not Menu.query.first():
            db.session.add(Menu(name="Full Set", price=580))
            db.session.add(Menu(name="Half Set", price=300))
            db.session.add(Menu(name="Three Tickets", price=150))

        db.session.commit()

init_db()

# ---------------- RUN ----------------

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
