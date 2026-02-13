import os
from datetime import datetime
from flask import (
    Flask, render_template, request,
    redirect, url_for, session,
    flash, send_file
)
from flask_sqlalchemy import SQLAlchemy
from werkzeug.utils import secure_filename
from sqlalchemy import func
import shutil

# =========================================================
# FLASK CONFIG
# =========================================================

app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "super_secret_key")

# =========================================================
# DATABASE CONFIG (POSTGRESQL FOR RENDER)
# =========================================================

DATABASE_URL = os.getenv("DATABASE_URL")

if DATABASE_URL:
    if DATABASE_URL.startswith("postgres://"):
        DATABASE_URL = DATABASE_URL.replace(
            "postgres://", "postgresql://", 1
        )
    app.config["SQLALCHEMY_DATABASE_URI"] = DATABASE_URL
else:
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///local.db"

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)

# =========================================================
# UPLOAD CONFIG
# =========================================================

UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER

# =========================================================
# ADMIN LOGIN
# =========================================================

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"

def admin_required():
    return session.get("admin")

# =========================================================
# MODELS
# =========================================================

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    phone = db.Column(db.String(20))
    email = db.Column(db.String(100))
    place = db.Column(db.String(100))

class Activity(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer)
    description = db.Column(db.String(300))
    date = db.Column(db.String(50))

class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer)
    filename = db.Column(db.String(200))

class Bill(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.Integer)
    customer_id = db.Column(db.Integer)
    items = db.Column(db.Text)
    subtotal = db.Column(db.Integer)
    discount = db.Column(db.Integer)
    total = db.Column(db.Integer)
    date = db.Column(db.String(50))

# =========================================================
# AUTO CREATE TABLES
# =========================================================

with app.app_context():
    db.create_all()

# =========================================================
# AUTH
# =========================================================

@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        if request.form["username"] == ADMIN_USERNAME and request.form["password"] == ADMIN_PASSWORD:
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
    return render_template("dashboard.html", customers=customers)

# =========================================================
# CUSTOMER CRUD
# =========================================================

@app.route("/add_customer", methods=["GET","POST"])
def add_customer():
    if not admin_required():
        return redirect("/")
    if request.method == "POST":
        customer = Customer(
            name=request.form["name"],
            phone=request.form["phone"],
            email=request.form["email"],
            place=request.form["place"]
        )
        db.session.add(customer)
        db.session.commit()
        flash("Customer added")
        return redirect("/dashboard")
    return render_template("add_customer.html")

@app.route("/edit_customer/<int:id>", methods=["GET","POST"])
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
        flash("Customer updated")
        return redirect("/dashboard")
    return render_template("edit_customer.html", customer=customer)

@app.route("/delete_customer/<int:id>")
def delete_customer(id):
    if not admin_required():
        return redirect("/")
    Bill.query.filter_by(customer_id=id).delete()
    Activity.query.filter_by(customer_id=id).delete()
    Document.query.filter_by(customer_id=id).delete()
    customer = Customer.query.get_or_404(id)
    db.session.delete(customer)
    db.session.commit()
    flash("Customer deleted")
    return redirect("/dashboard")

# =========================================================
# CUSTOMER PROFILE
# =========================================================

@app.route("/customer/<int:id>")
def customer_profile(id):
    if not admin_required():
        return redirect("/")
    customer = Customer.query.get_or_404(id)
    history = Activity.query.filter_by(customer_id=id).all()
    documents = Document.query.filter_by(customer_id=id).all()
    bills = Bill.query.filter_by(customer_id=id).all()
    return render_template("customer_profile.html",
                           customer=customer,
                           history=history,
                           documents=documents,
                           bills=bills)

# =========================================================
# CUSTOMER HISTORY
# =========================================================

@app.route("/add_history/<int:id>", methods=["POST"])
def add_history(id):
    activity = Activity(
        customer_id=id,
        description=request.form["description"],
        date=datetime.now().strftime("%d-%m-%Y %I:%M %p")
    )
    db.session.add(activity)
    db.session.commit()
    return redirect(url_for("customer_profile", id=id))

# =========================================================
# DOCUMENT UPLOAD
# =========================================================

@app.route("/upload/<int:id>", methods=["POST"])
def upload(id):
    file = request.files["file"]
    filename = secure_filename(file.filename)
    file.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
    doc = Document(customer_id=id, filename=filename)
    db.session.add(doc)
    db.session.commit()
    return redirect(url_for("customer_profile", id=id))

# =========================================================
# BILLING
# =========================================================

@app.route("/billing/<int:id>", methods=["GET","POST"])
def billing(id):
    if not admin_required():
        return redirect("/")
    customer = Customer.query.get_or_404(id)

    if request.method == "POST":
        subtotal = int(request.form["subtotal"])
        discount = int(request.form["discount"])
        total = subtotal - discount

        last_invoice = db.session.query(func.max(Bill.invoice_number)).scalar()
        next_invoice = 1 if not last_invoice else last_invoice + 1

        bill = Bill(
            invoice_number=next_invoice,
            customer_id=id,
            items=request.form["items"],
            subtotal=subtotal,
            discount=discount,
            total=total,
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
# RUN
# =========================================================

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
