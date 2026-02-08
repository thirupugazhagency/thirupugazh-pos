from flask import Flask, request, jsonify, render_template
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
    role = db.Column(db.String(20), nullable=False)

class Menu(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False)

class Cart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    status = db.Column(db.String(20), default="ACTIVE")
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

# ---------------- UI ROUTES ----------------

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

# ---------------- MENU ----------------

@app.route("/menu")
def get_menu():
    return jsonify([
        {"id": m.id, "name": m.name, "price": m.price}
        for m in Menu.query.all()
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
    d = request.json
    item = CartItem.query.filter_by(
        cart_id=d["cart_id"], menu_id=d["menu_id"]
    ).first()

    if item:
        item.quantity += 1
    else:
        db.session.add(CartItem(
            cart_id=d["cart_id"], menu_id=d["menu_id"], quantity=1
        ))

    db.session.commit()
    return jsonify({"status": "ok"})

@app.route("/cart/remove", methods=["POST"])
def remove_from_cart():
    d = request.json
    item = CartItem.query.filter_by(
        cart_id=d["cart_id"], menu_id=d["menu_id"]
    ).first()

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
            "price": i.menu.price,
            "quantity": i.quantity,
            "subtotal": subtotal
        })

    return jsonify({"items": result, "total": total})

# ---------------- HOLD / RESUME ----------------

@app.route("/cart/hold", methods=["POST"])
def hold_cart():
    d = request.json
    cart = Cart.query.get(d["cart_id"])
    cart.status = "HOLD"
    cart.customer_name = d.get("customer_name")
    db.session.commit()

    new_cart = Cart(status="ACTIVE")
    db.session.add(new_cart)
    db.session.commit()

    return jsonify({"new_cart_id": new_cart.id})

@app.route("/cart/holds")
def list_holds():
    holds = Cart.query.filter_by(status="HOLD").all()
    return jsonify([
        {"id": h.id, "customer_name": h.customer_name}
        for h in holds
    ])

@app.route("/cart/resume/<int:cart_id>", methods=["POST"])
def resume_cart(cart_id):
    cart = Cart.query.get(cart_id)
    cart.status = "ACTIVE"
    db.session.commit()
    return jsonify({"status": "ok"})

# ---------------- CHECKOUT ----------------

@app.route("/checkout", methods=["POST"])
def checkout():
    d = request.json
    items = CartItem.query.filter_by(cart_id=d["cart_id"]).all()
    total = sum(i.menu.price * i.quantity for i in items)

    sale = Sale(
        total=total,
        payment_method=d["payment_method"],
        customer_name=d.get("customer_name"),
        customer_phone=d.get("customer_phone"),
        transaction_id=d.get("transaction_id"),
        staff_id=d.get("staff_id"),
        business_date=get_business_date()
    )

    db.session.add(sale)
    Cart.query.get(d["cart_id"]).status = "PAID"
    db.session.commit()

    return jsonify({"total": total})

# ---------------- STAFF DAILY REPORT ----------------

@app.route("/staff/report/daily")
def staff_daily_report():
    staff_id = request.args.get("staff_id")
    if not staff_id:
        return jsonify({"error": "staff_id required"}), 400

    bd = get_business_date()
    sales = Sale.query.filter_by(
        staff_id=int(staff_id),
        business_date=bd
    ).all()

    return jsonify({
        "business_date": str(bd),
        "bill_count": len(sales),
        "total_amount": sum(s.total for s in sales)
    })

# ---------------- INIT ----------------

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

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
