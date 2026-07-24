import os, sys, html
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, session as flask_session, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from sqlalchemy import text
from sqlalchemy import func
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from functools import wraps

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-this-in-hostinger-settings')
DB_USER = os.environ.get('DB_USER'); DB_PASS = os.environ.get('DB_PASS')
DB_HOST = os.environ.get('DB_HOST'); DB_NAME = os.environ.get('DB_NAME')
app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:5432/{DB_NAME}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- SECURITY HEADERS (Content Security Policy) ---
@app.after_request
def add_csp(resp):
    resp.headers['Content-Security-Policy'] = (
        "default-src 'self' 'unsafe-inline' 'unsafe-eval' data: blob: "
        "https://esm.sh https://cdn.jsdelivr.net https://fastly.jsdelivr.net; "
        "worker-src 'self' blob:; "
        "connect-src 'self' https://esm.sh https://cdn.jsdelivr.net https://fastly.jsdelivr.net;"
    )
    return resp


# ---------------- MODELS ----------------



class User(UserMixin, db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(100), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    is_admin = db.Column(db.Boolean, default=False)
    is_superadmin = db.Column(db.Boolean, default=False)
    
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
    reason = db.Column(db.Text)   # NEW — why a Retired unit was reactivated, etc.
    edited_by = db.Column(db.String(100))
    edited_at = db.Column(db.DateTime)  
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    edited_by = db.Column(db.String(100))
    edited_at = db.Column(db.DateTime)  
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
               db.session.execute(text('ALTER TABLE "user" ADD COLUMN IF NOT EXISTS is_superadmin BOOLEAN DEFAULT FALSE'))
               db.session.execute(text('ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS reason TEXT'))
               db.session.execute(text('ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS edited_by VARCHAR(100)'))  # NEW
               db.session.execute(text('ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS edited_at TIMESTAMP'))     # NEW
               db.session.commit()
            except Exception: db.session.rollback()
            if not User.query.filter_by(username='admin').first():
                db.session.add(User(username='admin', password=generate_password_hash('P12345'),
                                     is_admin=True, is_superadmin=True))
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
    repair_counts = dict(
        db.session.query(InventoryScan.code, func.count(InventoryScan.id))
        .filter(InventoryScan.status == 'Repair').group_by(InventoryScan.code).all()
    )
    flagged_codes = {c for c, n in repair_counts.items() if n >= 3}
    return render_template('index.html', scans=scans, user=current_user,
                           device_types=DEVICE_TYPES, departments=DEPARTMENTS, statuses=STATUSES,
                           flagged_codes=flagged_codes)

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

    new_status = cfg.get("status")
    last = InventoryScan.query.filter_by(code=code).order_by(InventoryScan.timestamp.desc()).first()

    result = {
        "ok": True, "accept": True, "code": code,
        "nextIdentifiers": cfg.get("identifiers", []),
        "confirmMessage": None,
        "requireReason": False,
        "flag": None
    }

    if last:
        current = last.status

        if current == "In Stock":
            result["confirmMessage"] = f"Serial '{code}' was already scanned (In Stock). Save this record again?"

        elif current == "Loaned" and new_status == "In Use":
            result["confirmMessage"] = (f"Serial '{code}' is currently Loaned and has not been returned. "
                                         f"It will be updated to In Use. Continue?")

        elif current == "In Use" and new_status == "In Use":
            result["confirmMessage"] = f"Serial '{code}' is already In Use. Save this record again?"

        elif current == "Repair":
            repair_count = InventoryScan.query.filter_by(code=code, status="Repair").count()
            if repair_count >= 3:
                result["flag"] = "red"
                result["confirmMessage"] = (f"⚠️ Serial '{code}' has already been tagged for Repair "
                                             f"{repair_count} times. Save anyway?")

        elif current == "Retired" and new_status == "In Use":
            result["requireReason"] = True
            result["confirmMessage"] = f"Serial '{code}' is Retired. Provide a reason to reactivate it to In Use."

    return jsonify(result)

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

    reason = sanitize(d.get('reason'), 500)
    last = InventoryScan.query.filter_by(code=code).order_by(InventoryScan.timestamp.desc()).first()

    if last and last.status == "Retired" and cfg["status"] == "In Use" and not reason:
        return jsonify({"status": "error", "message": "A reason is required to reactivate a Retired unit."}), 400

    try:
        s = InventoryScan(
            code=code, imei=sanitize(d.get("imei")), mac_address=sanitize(d.get("mac_address")),
            device_type=cfg["device"], department=cfg["dept"], status=cfg["status"],
            person_name=cfg["user"], employee_id=cfg["empId"],
            email=cfg["email"], return_date=parse_dt(cfg["date"]),
            purchase_date=parse_dt(cfg["purchase"]), end_of_cycle=parse_dt(cfg["end"]),
            notes=cfg["notes"], image_data=cfg["image_data"], reason=reason)
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

# ---------------- EXPORT TO EXCEL ----------------
@app.route('/export/excel')
@login_required
def export_excel():
    scans = InventoryScan.query.order_by(InventoryScan.timestamp.desc()).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Inventory"

    headers = [
        "Timestamp", "Serial/Code", "Device Type", "IMEI", "MAC Address",
        "Department", "Status", "Employee Name", "Employee ID", "Email",
        "Purchase Date", "Return Date", "End of Cycle", "Reason", "Notes"
    ]
    ws.append(headers)

    header_fill = PatternFill(start_color="0D6EFD", end_color="0D6EFD", fill_type="solid")
    header_font = Font(color="FFFFFF", bold=True)
    for col_num, _ in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for s in scans:
        ws.append([
            s.timestamp.strftime('%Y-%m-%d %H:%M:%S') if s.timestamp else "",
            s.code,
            s.device_type,
            s.imei or "",
            s.mac_address or "",
            s.department or "",
            s.status,
            s.person_name or "",
            s.employee_id or "",
            s.email or "",
            s.purchase_date.strftime('%Y-%m-%d') if s.purchase_date else "",
            s.return_date.strftime('%Y-%m-%d') if s.return_date else "",
            s.end_of_cycle.strftime('%Y-%m-%d') if s.end_of_cycle else "",
            s.reason or "",
            s.notes or "",
        ])

    # Auto-width columns (rough heuristic based on content length)
    for col_cells in ws.columns:
        length = max((len(str(c.value)) if c.value is not None else 0) for c in col_cells)
        col_letter = col_cells[0].column_letter
        ws.column_dimensions[col_letter].width = min(max(length + 2, 10), 40)

    ws.freeze_panes = "A2"

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"inventory_export_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
 # ---------------- Import TO EXCEL ----------------   
ALLOWED_IMPORT_EXT = {'.xlsx', '.xls'}

@app.route('/admin/scans/import', methods=['GET'])
@login_required
@superadmin_required
def import_scans_form():
    return render_template('import_scans.html')

@app.route('/admin/scans/import', methods=['POST'])
@login_required
@superadmin_required
def import_scans():
    file = request.files.get('file')
    if not file or file.filename == '':
        return jsonify({"status": "error", "message": "No file uploaded."}), 400

    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ALLOWED_IMPORT_EXT:
        return jsonify({"status": "error", "message": "Only .xlsx/.xls files are supported."}), 400

    try:
        wb = load_workbook(file, data_only=True)
        ws = wb.active
    except Exception as e:
        return jsonify({"status": "error", "message": f"Could not read file: {e}"}), 400

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return jsonify({"status": "error", "message": "File is empty."}), 400

    header_row = [str(h).strip().lower() if h else '' for h in rows[0]]

    def col(*names):
        for n in names:
            if n in header_row:
                return header_row.index(n)
        return None

    idx_code    = col('serial/code', 'serial', 'code')
    idx_name    = col('employee name', 'person name', 'name')
    idx_empid   = col('employee id', 'emp id', 'empid')
    idx_device  = col('device type', 'device')
    idx_dept    = col('department')
    idx_status  = col('status')
    idx_imei    = col('imei')
    idx_mac     = col('mac address', 'mac')
    idx_email   = col('email')
    idx_purchase = col('purchase date', 'purchase')
    idx_return   = col('return date', 'return')
    idx_end      = col('end of cycle', 'end')
    idx_notes    = col('notes')
    idx_reason   = col('reason')

    # These three MUST exist as columns at all
    missing_required = [n for n, i in
                         [('Serial/Code', idx_code), ('Employee Name', idx_name), ('Employee ID', idx_empid)]
                         if i is None]
    if missing_required:
        return jsonify({"status": "error",
                         "message": f"Missing required column(s): {', '.join(missing_required)}"}), 400

    def cell(r, i):
        if i is None or i >= len(r): return None
        return r[i]

    def parse_cell_date(v):
        if v is None: return None
        if isinstance(v, datetime): return v.date()
        if hasattr(v, 'year') and hasattr(v, 'month'): return v  # already a date object
        return parse_dt(str(v))

    imported, skipped = 0, []
    for line_num, r in enumerate(rows[1:], start=2):
        if r is None or all(v is None for v in r):
            continue

        code  = sanitize(cell(r, idx_code))
        name  = sanitize(cell(r, idx_name))
        empid = sanitize(cell(r, idx_empid))

        # Mandatory per-row check
        if not code or not name or not empid:
            skipped.append({"row": line_num, "reason": "Missing Serial/Code, Employee Name, or Employee ID"})
            continue

        status = sanitize(cell(r, idx_status)) or 'In Stock'
        if status not in STATUSES:
            status = 'In Stock'

        try:
            s = InventoryScan(
                code=code, imei=sanitize(cell(r, idx_imei)), mac_address=sanitize(cell(r, idx_mac)),
                device_type=sanitize(cell(r, idx_device)) or 'Other',
                department=sanitize(cell(r, idx_dept)), status=status,
                person_name=name, employee_id=empid, email=sanitize(cell(r, idx_email), 120),
                purchase_date=parse_cell_date(cell(r, idx_purchase)),
                return_date=parse_cell_date(cell(r, idx_return)),
                end_of_cycle=parse_cell_date(cell(r, idx_end)),
                notes=sanitize(cell(r, idx_notes), 1000),
                reason=sanitize(cell(r, idx_reason), 500),
                edited_by=current_user.username, edited_at=datetime.utcnow(),
            )
            db.session.add(s)
            imported += 1
        except Exception as e:
            skipped.append({"row": line_num, "reason": str(e)})

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": f"Database error: {e}"}), 500

    return jsonify({"status": "success", "imported": imported, "skipped": skipped})


@app.route('/admin/scans/edit/<int:scan_id>', methods=['GET'])
@login_required
@superadmin_required
def edit_scan_form(scan_id):
    s = InventoryScan.query.get_or_404(scan_id)
    return render_template('edit_scan.html', s=s,
                           device_types=DEVICE_TYPES, departments=DEPARTMENTS, statuses=STATUSES)

@app.route('/admin/scans/edit/<int:scan_id>', methods=['POST'])
@login_required
@superadmin_required
def edit_scan(scan_id):
    s = InventoryScan.query.get_or_404(scan_id)
    d = request.get_json() or {}

    status = sanitize(d.get('status'))
    if status not in STATUSES:
        return jsonify({"status": "error", "message": "Invalid status."}), 400

    s.code = sanitize(d.get('code')) or s.code
    s.imei = sanitize(d.get('imei'))
    s.mac_address = sanitize(d.get('mac_address'))
    s.device_type = sanitize(d.get('device_type')) or s.device_type
    s.department = sanitize(d.get('department'))
    s.status = status
    s.person_name = sanitize(d.get('person_name'))
    s.employee_id = sanitize(d.get('employee_id'))
    s.email = sanitize(d.get('email'), 120)
    s.purchase_date = parse_dt(d.get('purchase_date'))
    s.return_date = parse_dt(d.get('return_date'))
    s.end_of_cycle = parse_dt(d.get('end_of_cycle'))
    s.notes = sanitize(d.get('notes'), 1000)
    s.reason = sanitize(d.get('reason'), 500)
    s.edited_by = current_user.username
    s.edited_at = datetime.utcnow()

    try:
        db.session.commit()
        return jsonify({"status": "success", "id": s.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/admin/users', methods=['GET', 'POST'])
@login_required
def manage_users():
    if not current_user.is_admin: return redirect(url_for('index'))
    if request.method == 'POST':
        u = sanitize(request.form.get('username')); p = request.form.get('password')
        a = bool(request.form.get('is_admin'))
        sa = bool(request.form.get('is_superadmin')) and current_user.is_superadmin  # NEW — only a superadmin can grant it
        if User.query.filter_by(username=u).first(): flash("User exists!")
        else:
            db.session.add(User(username=u, password=generate_password_hash(p), is_admin=a, is_superadmin=sa))
            db.session.commit(); flash("User created.")
    return render_template('admin_users.html', users=User.query.all())
    
def superadmin_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_superadmin:
            return jsonify({"status": "error", "message": "Super admin only"}), 403
        return f(*args, **kwargs)
    return wrapper
     

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8506)
