import os, sys, html
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session as flask_session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-this-in-hostinger-settings')
DB_USER = os.environ.get('DB_USER'); DB_PASS = os.environ.get('DB_PASS')
DB_HOST = os.environ.get('DB_HOST'); DB_NAME = os.environ.get('DB_NAME')
app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:5432/{DB_NAME}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ---------------- MODELS ----------------
class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)

class InventoryScan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), nullable=False)
    imei = db.Column(db.String(100)); mac_address = db.Column(db.String(100))
    device_type = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100))
    status = db.Column(db.String(50), nullable=False)
    person_name = db.Column(db.String(100)); employee_id = db.Column(db.String(50))
    email = db.Column(db.String(120))
    return_date = db.Column(db.Date); purchase_date = db.Column(db.Date); end_of_cycle = db.Column(db.Date)
    notes = db.Column(db.Text); image_data = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

@login_manager.user_loader
def load_user(uid): return User.query.get(int(uid))

# ---------------- SCANNING RULES (the "brain") ----------------
# This dict is now the ONE place that defines scanning behavior.
DEVICE_TYPES = ["Laptop", "Mobile", "Monitor", "Printer", "Other"]
DEPARTMENTS  = ["IT", "FINANCE", "PROCUREMENT", "Other"]
STATUSES     = ["In Stock", "Loaned", "In Use", "Repair", "Retired"]

# Which extra fields each status needs. Client just renders what Python says.
STATUS_FIELD_RULES = {
    "In Stock": ["purchase", "end"],
    "Loaned":   ["email", "date"],
    "In Use":   [],
    "Repair":   [],
    "Retired":  [],
}

# Which identifiers Python will ask the client to scan, per device type.
# This replaces the hardcoded "Scan IMEI / Scan MAC" buttons logic.
DEVICE_IDENTIFIER_RULES = {
    "Laptop":  ["mac"],
    "Mobile":  ["imei", "mac"],
    "Monitor": [],
    "Printer": ["mac"],
    "Other":   [],
}

# ---------------- INIT ----------------
def init_db():
    with app.app_context():
        try:
            db.create_all()
            try:
                db.session.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_admin BOOLEAN DEFAULT FALSE'))
                db.session.commit()
            except Exception: db.session.rollback()
            if not User.query.filter_by(username='admin').first():
                db.session.add(User(username='admin', password=generate_password_hash('P12345'), is_admin=True))
                db.session.commit()
        except Exception as e:
            print(f"DB Init Error: {e}", file=sys.stderr)
init_db()

def sanitize(val, length=100):
    if not val: return None
    return html.escape(str(val).strip()[:length])

def parse_dt(s):
    try: return datetime.strptime(s, '%Y-%m-%d').date() if s else None
    except: return None

# ---------------- AUTH / PAGES ----------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = sanitize(request.form.get('username')); p = request.form.get('password')
        user = User.query.filter_by(username=u).first()
        if user and check_password_hash(user.password, p):
            login_user(user); return redirect(url_for('index'))
        flash('Invalid username or password')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user(); return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    scans = InventoryScan.query.order_by(InventoryScan.timestamp.desc()).limit(50).all()
    # Ship the rules to the template so the client renders, not decides.
    return render_template('index.html', scans=scans, user=current_user,
                           device_types=DEVICE_TYPES, departments=DEPARTMENTS, statuses=STATUSES)

# ---------------- SESSION: Python validates + owns config ----------------
@app.route('/session/start', methods=['POST'])
@login_required
def session_start():
    d = request.get_json() or {}
    user = sanitize(d.get('user')); emp = sanitize(d.get('empId'))
    if not user or not emp:
        return jsonify({"ok": False, "error": "Employee Name and ID are mandatory."}), 400

    device = sanitize(d.get('device'))
    if device == 'Other': device = sanitize(d.get('otherDevice')) or 'Other'
    dept = sanitize(d.get('dept'))
    if dept == 'Other': dept = sanitize(d.get('otherDept')) or 'Other'

    status = sanitize(d.get('status'))
    if status not in STATUSES:
        return jsonify({"ok": False, "error": "Invalid status."}), 400

    base = device if device in DEVICE_IDENTIFIER_RULES else 'Other'

    # Store the authoritative session server-side.
    flask_session['scan_cfg'] = {
        "user": user, "empId": emp, "device": device, "dept": dept, "status": status,
        "scanMode": sanitize(d.get('scanMode')) or "Single",
        "email": sanitize(d.get('email'), 120), "date": sanitize(d.get('date')),
        "purchase": sanitize(d.get('purchase')), "end": sanitize(d.get('end')),
        "notes": sanitize(d.get('notes'), 1000), "image_data": d.get('image_data'),
        "identifiers": DEVICE_IDENTIFIER_RULES.get(base, []),
    }
    return jsonify({"ok": True, "config": {
        "user": user, "empId": emp, "device": device, "dept": dept,
        "status": status, "scanMode": flask_session['scan_cfg']['scanMode'],
        "requiredFields": STATUS_FIELD_RULES.get(status, []),
        "identifiers": flask_session['scan_cfg']['identifiers'],
    }})

# ---------------- SCAN CHECK: Python decides accept/reject/next ----------------
@app.route('/scan/check', methods=['POST'])
@login_required
def scan_check():
    cfg = flask_session.get('scan_cfg')
    if not cfg:
        return jsonify({"ok": False, "error": "No active session. Start a session first."}), 400
    code = sanitize((request.get_json() or {}).get('code'))
    if not code:
        return jsonify({"ok": False, "accept": False, "reason": "Empty code"}), 200

    # Rule: reject duplicates already in DB.
    dup = InventoryScan.query.filter_by(code=code).first()
    if dup:
        return jsonify({"ok": True, "accept": False,
                        "reason": f"Serial '{code}' already exists (id {dup.id})."})

    # Python decides what the client should scan next.
    return jsonify({"ok": True, "accept": True, "code": code,
                    "nextIdentifiers": cfg.get("identifiers", [])})

# ---------------- SAVE: uses server-side session, not client claims ----------------
@app.route('/scanned', methods=['POST'])
@login_required
def scanned():
    cfg = flask_session.get('scan_cfg')
    if not cfg:
        return jsonify({"status": "error", "message": "No active session."}), 400
    d = request.get_json() or {}
    code = sanitize(d.get('code'))
    if not code:
        return jsonify({"status": "error", "message": "Serial is required."}), 400
    if InventoryScan.query.filter_by(code=code).first():
        return jsonify({"status": "error", "message": "Duplicate serial."}), 409
    try:
        s = InventoryScan(
            code=code, imei=sanitize(d.get("imei")), mac_address=sanitize(d.get("mac_address")),
            device_type=cfg["device"], department=cfg["dept"], status=cfg["status"],
            person_name=cfg["user"], employee_id=cfg["empId"],
            email=cfg["email"], return_date=parse_dt(cfg["date"]),
            purchase_date=parse_dt(cfg["purchase"]), end_of_cycle=parse_dt(cfg["end"]),
            notes=cfg["notes"], image_data=cfg["image_data"])
        db.session.add(s); db.session.commit()
        return jsonify({"status": "success", "id": s.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

# ---------------- ADMIN (unchanged) ----------------
@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
def manage_users():
    if not current_user.is_admin: return redirect(url_for('index'))
    if request.method == 'POST':
        u = sanitize(request.form.get('username')); p = request.form.get('password')
        a = bool(request.form.get('is_admin'))
        if User.query.filter_by(username=u).first(): flash("User exists!")
        else:
            db.session.add(User(username=u, password=generate_password_hash(p), is_admin=a))
            db.session.commit(); flash("User created.")
    return render_template('admin_users.html', users=User.query.all())

@app.route('/admin/users/delete/<int:user_id>')
@login_required
def delete_user(user_id):
    if not current_user.is_admin: return redirect(url_for('index'))
    u = User.query.get(user_id)
    if u and u.id != current_user.id:
        db.session.delete(u); db.session.commit()
    return redirect(url_for('manage_users'))

@app.route('/delete', methods=['POST'])
@login_required
def delete_scans():
    if not current_user.is_admin:
        return jsonify({"status": "error", "message": "Admin only"}), 403
    ids = request.json.get('ids', [])
    InventoryScan.query.filter(InventoryScan.id.in_(ids)).delete(synchronize_session=False)
    db.session.commit()
    return jsonify({"status": "success"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8506)
