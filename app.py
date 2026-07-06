from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = 'super-secret-inventory-key'

# Database Configuration
DB_USER = os.environ.get('DB_USER', 'postgres')
DB_PASS = os.environ.get('DB_PASS', 'P12345')
DB_HOST = os.environ.get('DB_HOST', 'inventory-inventory-sqaoox')
DB_NAME = os.environ.get('DB_NAME', 'inventory')

app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:5432/{DB_NAME}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- MODELS ---

class Admin(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='admin') # 'super_admin' or 'admin'

class InventoryScan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(50), nullable=False)
    device_type = db.Column(db.String(50))
    department = db.Column(db.String(100), nullable=False)
    assigned_user = db.Column(db.String(100), nullable=False) # Renamed from Operator
    notes = db.Column(db.Text)
    photo = db.Column(db.Text)
    is_flagged = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    user_email = db.Column(db.String(120))
    return_date = db.Column(db.Date)
    imei = db.Column(db.String(50))
    mac_address = db.Column(db.String(50))

@login_manager.user_loader
def load_user(user_id):
    return Admin.query.get(int(user_id))

with app.app_context():
    db.create_all()
    # Create default Super Admin if none exists
    if not Admin.query.filter_by(username='admin').first():
        hashed_pw = generate_password_hash('admin123')
        default_admin = Admin(username='admin', password_hash=hashed_pw, role='super_admin')
        db.add(default_admin)
        db.commit()

# --- ROUTES ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = Admin.query.filter_by(username=request.form['username']).first()
        if user and check_password_hash(user.password_hash, request.form['password']):
            login_user(user)
            return redirect(url_for('index'))
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    today = datetime.utcnow().date()
    # Auto-flag overdue loans
    overdue = InventoryScan.query.filter(InventoryScan.status == 'Loan', InventoryScan.return_date < today).all()
    for item in overdue:
        item.is_flagged = True
    db.session.commit()

    recent_scans = InventoryScan.query.order_by(InventoryScan.timestamp.desc()).limit(30).all()
    return render_template('index.html', scans=recent_scans, role=current_user.role)

@app.route('/scanned', methods=['POST'])
@login_required
def scanned():
    data = request.json
    try:
        repair_count = InventoryScan.query.filter_by(code=data.get("code"), status='Repair').count()
        flag_it = (data.get("status") == 'Repair' and repair_count >= 2)
        
        ret_date = None
        if data.get("return_date"):
            ret_date = datetime.strptime(data.get("return_date"), '%Y-%m-%d').date()

        new_scan = InventoryScan(
            code=data.get("code"), status=data.get("status"), notes=data.get("notes"),
            device_type=data.get("device_type"), department=data.get("department"),
            assigned_user=data.get("assigned_user"), user_email=data.get("user_email"),
            return_date=ret_date, is_flagged=flag_it,
            imei=data.get("imei"), mac_address=data.get("mac_address"), photo=data.get("photo")
        )
        db.add(new_scan)
        db.commit()
        return jsonify({"status": "success", "is_flagged": flag_it, "id": new_scan.id})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/delete-scans', methods=['POST'])
@login_required
def delete_scans():
    if current_user.role != 'super_admin':
        return jsonify({"status": "error", "message": "Unauthorized"}), 403
    
    ids = request.json.get('ids', [])
    InventoryScan.query.filter(InventoryScan.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    return jsonify({"status": "success"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8506)
