import os
import shutil
from datetime import datetime
from flask import (
    Flask, render_template, request,
    redirect, url_for, session,
    flash, send_file
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from openpyxl import Workbook

# =========================================================
# SAFE APP DATA LOCATION (PERMANENT DATABASE)
# =========================================================

def get_app_data_dir():
    base = os.getenv("LOCALAPPDATA")
    app_dir = os.path.join(base, "DotNetCafe")
    os.makedirs(app_dir, exist_ok=True)
    return app_dir

DATA_DIR = get_app_data_dir()

DB_PATH = os.path.join(DATA_DIR, "database.db")
EXCEL_FILE = os.path.join(DATA_DIR, "customers.xlsx")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
SCAN_DIR = os.path.join(DATA_DIR, "scan_inbox")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(SCAN_DIR, exist_ok=True)

# =========================================================
# FLASK CONFIG
# =========================================================

app = Flask(__name__)
app.secret_key = "net_cafe_secret_key"

app.config["SQLALCHEMY_DATABASE_URI"] = f"sqlite:///{DB_PATH}"
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
app.config["UPLOAD_FOLDER"] = UPLOAD_DIR

db = SQLAlchemy(app)

# =========================================================
# ADMIN LOGIN
# =========================================================

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

def admin_required():
    return session.get("admin")

# =========================================================
# DATABASE MODELS
# =========================================================

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    place = db.Column(db.String(100))

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer)
    filename = db.Column(db.String(200))

class Bill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, nullable=True)
    items = db.Column(db.Text)
    subtotal = db.Column(db.Integer)
    discount = db.Column(db.Integer)
    total = db.Column(db.Integer)
    date = db.Column(db.String(50))

class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer)
    description = db.Column(db.String(300))
    date = db.Column(db.String(50))

# =========================================================
# EXCEL REBUILD (AUTO SYNC)
# =========================================================

def rebuild_excel():
    wb = Workbook()
    ws = wb.active
    ws.append(["ID", "Name", "Phone", "Email", "Place"])

    customers = Customer.query.all()

    for c in customers:
        ws.append([c.id, c.name, c.phone, c.email, c.place])

    wb.save(EXCEL_FILE)

# =========================================================
# AUTH ROUTES
# =========================================================

@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        if (
            request.form["username"] == ADMIN_USERNAME and
            request.form["password"] == ADMIN_PASSWORD
        ):
            session["admin"] = True
            return redirect("/dashboard")

        flash("Invalid credentials")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("admin", None)
    return redirect("/")

# =========================================================
# DASHBOARD
# =========================================================

@app.route("/dashboard")
def dashboard():
    if not admin_required():
        return redirect("/")
    customers = Customer.query.all()
    return render_template("dashboard.html",
                           customers=customers,
                           search_query="")

@app.route("/search_customer")
def search_customer():
    if not admin_required():
        return redirect("/")
    q = request.args.get("q", "")
    customers = Customer.query.filter(
        (Customer.name.ilike(f"%{q}%")) |
        (Customer.phone.ilike(f"%{q}%"))
    ).all()
    return render_template("dashboard.html",
                           customers=customers,
                           search_query=q)

# =========================================================
# ADD CUSTOMER
# =========================================================

@app.route("/add_customer", methods=["GET", "POST"])
def add_customer():
    if not admin_required():
        return redirect("/")

    if request.method == "POST":
        c = Customer(
            name=request.form["name"],
            phone=request.form["phone"],
            email=request.form["email"],
            place=request.form["place"]
        )
        db.session.add(c)
        db.session.commit()

        rebuild_excel()

        flash("Customer added successfully!")
        return redirect("/dashboard")

    return render_template("add_customer.html")

# =========================================================
# EDIT CUSTOMER
# =========================================================

@app.route("/edit_customer/<int:id>", methods=["GET", "POST"])
def edit_customer(id):
    if not admin_required():
        return redirect("/")

    customer = Customer.query.get_or_404(id)

    if request.method == "POST":
        customer.name = request.form["name"]
        customer.phone = request.form["phone"]
        customer.email = request.form["email"]
        customer.place = request.form["place"]

        db.session.commit()
        rebuild_excel()

        flash("Customer updated successfully!")
        return redirect("/dashboard")

    return render_template("edit_customer.html", customer=customer)

# =========================================================
# DELETE CUSTOMER
# =========================================================

@app.route("/delete_customer/<int:id>")
def delete_customer(id):
    if not admin_required():
        return redirect("/")

    customer = Customer.query.get_or_404(id)

    folder = f"{customer.name}_{customer.phone}".replace(" ", "_")
    folder_path = os.path.join(UPLOAD_DIR, folder)
    if os.path.exists(folder_path):
        shutil.rmtree(folder_path)

    Bill.query.filter_by(customer_id=id).delete()
    Document.query.filter_by(customer_id=id).delete()
    Activity.query.filter_by(customer_id=id).delete()

    db.session.delete(customer)
    db.session.commit()

    rebuild_excel()

    flash("Customer deleted successfully!")
    return redirect("/dashboard")

# =========================================================
# CUSTOMER PROFILE
# =========================================================

@app.route("/customer/<int:id>/<name>")
def customer_profile(id, name):
    if not admin_required():
        return redirect("/")

    customer = Customer.query.get_or_404(id)
    docs = Document.query.filter_by(customer_id=id).all()
    history = Activity.query.filter_by(
        customer_id=id
    ).order_by(Activity.id.desc()).all()

    return render_template("customer_profile.html",
                           customer=customer,
                           docs=docs,
                           history=history)

# =========================================================
# BILLING
# =========================================================

@app.route("/billing/<int:id>", methods=["GET", "POST"])
def billing(id):
    customer = Customer.query.get_or_404(id)

    if request.method == "POST":
        items = []
        subtotal = 0

        def add_item(name, qty, price):
            nonlocal subtotal
            if name and qty > 0:
                total = qty * price
                subtotal += total
                items.append(f"{name}: {qty} x {price} = {total}")

        add_item("B/W Print", int(request.form.get("bw_qty", 0)), int(request.form.get("bw_price", 0)))
        add_item("Color Print", int(request.form.get("color_qty", 0)), int(request.form.get("color_price", 0)))
        add_item("Scan", int(request.form.get("scan_qty", 0)), int(request.form.get("scan_price", 0)))
        add_item("Digital Signature", int(request.form.get("ds_qty", 0)), int(request.form.get("ds_price", 0)))
        add_item(request.form.get("custom_name"),
                 int(request.form.get("custom_qty", 0)),
                 int(request.form.get("custom_price", 0)))

        discount = int(request.form.get("discount", 0))

        bill = Bill(
            customer_id=id,
            items="\n".join(items),
            subtotal=subtotal,
            discount=discount,
            total=subtotal - discount,
            date=datetime.now().strftime("%d-%m-%Y %I:%M %p")
        )

        db.session.add(bill)
        db.session.commit()

        return redirect(url_for("bill_print", id=bill.id))

    return render_template("billing.html", customer=customer)

# =========================================================
# BILL PRINT
# =========================================================

@app.route("/bill/<int:id>")
def bill_print(id):
    bill = Bill.query.get_or_404(id)
    customer = Customer.query.get(bill.customer_id)
    return render_template("bill_print.html",
                           bill=bill,
                           customer=customer)

# =========================================================
# OPEN EXCEL
# =========================================================

@app.route("/open_customers_excel")
def open_customers_excel():
    if not admin_required():
        return redirect("/")
    return send_file(EXCEL_FILE, as_attachment=False)

# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    app.run(host="0.0.0.0", port=5000)

