from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, time
import os

app = Flask(__name__)

# ---------------- CONFIG ----------------

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL not set")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

db = SQLAlchemy(app)

# ---------------- MODELS ----------------

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password = db.Column(db.String(200))
    role = db.Column(db.String(20))  # admin / staff

class Menu(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    price = db.Column(db.Integer)

class Cart(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class CartItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey("cart.id"))
    menu_id = db.Column(db.Integer, db.ForeignKey("menu.id"))
    quantity = db.Column(db.Integer, default=1)
    menu = db.relationship("Menu")

class AppliedDiscount(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer)
    reason = db.Column(db.String(200))
    amount = db.Column(db.Integer)

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    total = db.Column(db.Integer)
    payment_method = db.Column(db.String(20))
    txn_id = db.Column(db.String(100))
    cash_details = db.Column(db.String(200))
    customer_name = db.Column(db.String(100))
    customer_phone = db.Column(db.String(20))
    staff_id = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class HeldBill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    staff_id = db.Column(db.Integer)
    data = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class BusinessDay(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    start_time = db.Column(db.DateTime)
    end_time = db.Column(db.DateTime)
    closed = db.Column(db.Boolean, default=False)

# ---------------- HELPERS ----------------

def get_business_day():
    now = datetime.utcnow() + timedelta(hours=5, minutes=30)  # IST
    today_3pm = datetime.combine(now.date(), time(15,0))

    if now < today_3pm:
        start = today_3pm - timedelta(days=1)
        end = today_3pm
    else:
        start = today_3pm
        end = today_3pm + timedelta(days=1)

    day = BusinessDay.query.filter_by(start_time=start).first()
    if not day:
        day = BusinessDay(start_time=start, end_time=end, closed=False)
        db.session.add(day)
        db.session.commit()

    return day

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
    data = request.json
    u = User.query.filter_by(username=data.get("username")).first()
    if u and check_password_hash(u.password, data.get("password")):
        return jsonify({"status":"ok","role":u.role,"user_id":u.id})
    return jsonify({"status":"error"}),401

# ---------------- USERS ----------------

@app.route("/users", methods=["POST"])
def create_user():
    d = request.json
    u = User(username=d["username"], password=generate_password_hash(d["password"]), role=d["role"])
    db.session.add(u)
    db.session.commit()
    return jsonify({"status":"created"})

# ---------------- MENU ----------------

@app.route("/menu")
def menu():
    return jsonify([{"id":m.id,"name":m.name,"price":m.price} for m in Menu.query.all()])

# ---------------- CART ----------------

@app.route("/cart/create", methods=["POST"])
def cart_create():
    c = Cart()
    db.session.add(c)
    db.session.commit()
    return jsonify({"cart_id":c.id})

@app.route("/cart/add", methods=["POST"])
def cart_add():
    d = request.json
    item = CartItem.query.filter_by(cart_id=d["cart_id"], menu_id=d["menu_id"]).first()
    if item:
        item.quantity += d.get("quantity",1)
    else:
        item = CartItem(cart_id=d["cart_id"], menu_id=d["menu_id"], quantity=d.get("quantity",1))
        db.session.add(item)
    db.session.commit()
    return jsonify({"status":"added"})

@app.route("/cart/add-discount", methods=["POST"])
def add_discount():
    d = request.json
    disc = AppliedDiscount(cart_id=d["cart_id"], amount=d["amount"], reason=d.get("reason","Manual"))
    db.session.add(disc)
    db.session.commit()
    return jsonify({"status":"ok"})

@app.route("/cart/<int:cid>")
def view_cart(cid):
    items = CartItem.query.filter_by(cart_id=cid).all()
    discs = AppliedDiscount.query.filter_by(cart_id=cid).all()
    total = sum(i.menu.price * i.quantity for i in items)
    disc_total = sum(d.amount for d in discs)
    return jsonify({
        "items":[{"name":i.menu.name,"qty":i.quantity,"price":i.menu.price} for i in items],
        "total": total,
        "discount": disc_total,
        "final": total - disc_total
    })

# ---------------- HOLD BILL ----------------

@app.route("/hold", methods=["POST"])
def hold_bill():
    d = request.json
    hb = HeldBill(staff_id=d["staff_id"], data=str(d))
    db.session.add(hb)
    db.session.commit()
    return jsonify({"status":"held"})

@app.route("/holds/<int:staff_id>")
def list_holds(staff_id):
    return jsonify([{"id":h.id,"data":h.data} for h in HeldBill.query.filter_by(staff_id=staff_id).all()])

@app.route("/hold/<int:hid>", methods=["DELETE"])
def delete_hold(hid):
    h = HeldBill.query.get(hid)
    db.session.delete(h)
    db.session.commit()
    return jsonify({"status":"deleted"})

# ---------------- CHECKOUT ----------------

@app.route("/checkout", methods=["POST"])
def checkout():
    d = request.json
    if not d.get("staff_id"):
        return jsonify({"error":"staff_id required"}),400

    items = CartItem.query.filter_by(cart_id=d["cart_id"]).all()
    if not items:
        return jsonify({"error":"Cart empty"}),400

    total = sum(i.menu.price * i.quantity for i in items)
    discs = AppliedDiscount.query.filter_by(cart_id=d["cart_id"]).all()
    disc_total = sum(x.amount for x in discs)
    final = total - disc_total

    sale = Sale(
        total=final,
        payment_method=d["payment_method"],
        txn_id=d.get("txn_id",""),
        cash_details=d.get("cash_details",""),
        customer_name=d.get("customer_name",""),
        customer_phone=d.get("customer_phone",""),
        staff_id=d["staff_id"]
    )

    db.session.add(sale)

    for i in items: db.session.delete(i)
    for x in discs: db.session.delete(x)

    db.session.commit()

    return jsonify({"status":"success","total":final})

# ---------------- REPORTS ----------------

@app.route("/report/today")
def report_today():
    day = get_business_day()
    total = db.session.query(db.func.sum(Sale.total)).filter(
        Sale.created_at >= day.start_time,
        Sale.created_at < day.end_time
    ).scalar() or 0
    return jsonify({"total":total,"from":str(day.start_time),"to":str(day.end_time)})

# ---------------- INIT ----------------

def init_db():
    with app.app_context():
        db.create_all()
        if not User.query.first():
            db.session.add(User(username="admin",password=generate_password_hash("admin123"),role="admin"))
            db.session.add(User(username="staff1",password=generate_password_hash("1234"),role="staff"))
        if not Menu.query.first():
            db.session.add(Menu(name="Full Set",price=580))
            db.session.add(Menu(name="Half Set",price=300))
            db.session.add(Menu(name="Three Tickets",price=150))
        db.session.commit()

init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
