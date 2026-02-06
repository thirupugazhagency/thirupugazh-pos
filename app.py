from flask import Flask, request, jsonify, render_template
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
import os, re

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

# ---------------- UI ----------------
@app.route("/")
def home():
    return "Thirupugazh POS API Running"

@app.route("/ui/login")
def ui_login():
    return render_template("login.html")

@app.route("/ui/admin-menu")
def ui_admin_menu():
    return render_template("admin_menu.html")

# ---------------- AUTH ----------------
@app.route("/login", methods=["POST"])
def login():
    d = request.json
    u = User.query.filter_by(username=d.get("username")).first()
    if u and check_password_hash(u.password, d.get("password")):
        return jsonify({"status":"ok","user_id":u.id,"role":u.role})
    return jsonify({"status":"error"}),401

# ---------------- MENU (PUBLIC – FOR BILLING) ----------------
@app.route("/menu")
def menu():
    return jsonify([{"id":m.id,"name":m.name,"price":m.price} for m in Menu.query.all()])

# ================== ADMIN MENU MANAGEMENT ==================

@app.route("/admin/menu")
def admin_menu_list():
    return jsonify([{"id":m.id,"name":m.name,"price":m.price} for m in Menu.query.all()])

@app.route("/admin/menu/add", methods=["POST"])
def admin_menu_add():
    d = request.json
    if not d.get("name") or not str(d.get("price")).isdigit():
        return jsonify({"error":"Invalid data"}),400

    m = Menu(name=d["name"], price=int(d["price"]))
    db.session.add(m)
    db.session.commit()
    return jsonify({"status":"added"})

@app.route("/admin/menu/update", methods=["POST"])
def admin_menu_update():
    d = request.json
    m = Menu.query.get(d.get("id"))
    if not m or not str(d.get("price")).isdigit():
        return jsonify({"error":"Invalid"}),400

    m.price = int(d["price"])
    db.session.commit()
    return jsonify({"status":"updated"})

@app.route("/admin/menu/delete", methods=["POST"])
def admin_menu_delete():
    m = Menu.query.get(request.json.get("id"))
    if not m:
        return jsonify({"error":"Not found"}),404
    db.session.delete(m)
    db.session.commit()
    return jsonify({"status":"deleted"})

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
