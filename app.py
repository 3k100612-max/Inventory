import os
import sys
import re
import html
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text

app = Flask(__name__)

# --- SECURITY CONFIGURATION ---
# Fetches secrets from Hostinger Environment Settings
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-key-change-me')

# PostgreSQL Connection
DB_USER = os.environ.get('DB_USER')
DB_PASS = os.environ.get('DB_PASS')
DB_HOST = os.environ.get('DB_HOST')
DB_NAME = os.environ.get('DB_NAME')

app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:5432/{DB_NAME}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- DATABASE MODELS ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

class InventoryScan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), nullable=False)
    imei = db.Column(db.String(100), nullable=True)
    mac_address = db.Column(db.String(100), nullable=True)
    device_type = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(50), nullable=False)
    person_name = db.Column(db.String(100), nullable=True)
    employee_id = db.Column(db.String(50), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    return_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    purchase_date = db.Column(db.Date, nullable=True)
    end_of_cycle = db.Column(db.Date, nullable=True)
    image_data = db.Column(db.Text, nullable=True) 
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- DB INITIALIZATION & MIGRATION ---
def init_db():
    with app.app_context():
        try:
            db.create_all()
            # Ensure is_admin column exists (Migration helper)
            try:
                db.session.execute(text("ALTER TABLE \"user\" ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE"))
                db.session.commit()
            except Exception: db.session.rollback()

            # Create default admin if not exists (admin / P12345)
            if not User.query.filter_by(username='admin').first():
                admin = User(username='admin', 
                             password=generate_password_hash('P12345'), 
                             is_admin=True)
                db.session.add(admin)
                db.session.commit()
        except Exception as e:
            print(f"Init Error: {e}", file=sys.stderr)

init_db()

# --- HELPERS ---
def sanitize(val, length=100):
    if not val: return None
    return html.escape(str(val).strip()[:length])

def is_valid_email(email):
    if not email: return True
    return re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email) is not None

# --- AUTH ROUTES ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = sanitize(request.form.get('username'))
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid credentials')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

# --- ADMIN ROUTES ---
@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
def manage_users():
    if not current_user.is_admin:
        return redirect(url_for('index'))
    if request.method == 'POST':
        u = sanitize(request.form.get('username'))
        p = request.form.get('password')
        a = True if request.form.get('is_admin') else False
        if User.query.filter_by(username=u).first():
            flash("User exists!")
        else:
            db.session.add(User(username=u, password=generate_password_hash(p), is_admin=a))
            db.session.commit()
            flash("User created!")
    return render_template('admin_users.html', users=User.query.all())

@app.route('/admin/users/delete/<int:user_id>')
@login_required
def delete_user(user_id):
    if not current_user.is_admin: return redirect(url_for('index'))
    u = User.query.get(user_id)
    if u and u.id != current_user.id:
        db.session.delete(u)
        db.session.commit()
    return redirect(url_for('manage_users'))

# --- APP ROUTES ---
@app.route('/')
@login_required
def index():
    scans = InventoryScan.query.order_by(InventoryScan.timestamp.desc()).limit(100).all()
    return render_template('index.html', scans=scans, user=current_user)

@app.route('/scanned', methods=['POST'])
@login_required
def scanned():
    data = request.get_json()
    email = sanitize(data.get("email"), 120)
    if email and not is_valid_email(email):
        return jsonify({"status": "error", "message": "Invalid email"}), 400

    def parse_dt(s):
        try: return datetime.strptime(s, '%Y-%m-%d').date() if s else None
        except: return None

    try:
        new_scan = InventoryScan(
            code=sanitize(data.get("code")),
            imei=sanitize(data.get("imei")),
            mac_address=sanitize(data.get("mac_address")),
            device_type=sanitize(data.get("device_type")),
            department=sanitize(data.get("dept")),
            status=sanitize(data.get("status")),
            person_name=sanitize(data.get("user")),
            employee_id=sanitize(data.get("empId"), 50),
            email=email,
            return_date=parse_dt(data.get("date")),
            notes=sanitize(data.get("notes"), 1000),
            purchase_date=parse_dt(data.get("purchase")),
            end_of_cycle=parse_dt(data.get("end")),
            image_data=data.get("image_data")
        )
        db.session.add(new_scan)
        db.session.commit()
        return jsonify({"status": "success", "id": new_scan.id, "time": new_scan.timestamp.strftime('%H:%M')})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/delete', methods=['POST'])
@login_required
def delete_scans():
    ids = request.json.get('ids', [])
    InventoryScan.query.filter(InventoryScan.id.in_(ids)).delete(synchronize_session=False)
    db.session.commit()
    return jsonify({"status": "success"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8506)
