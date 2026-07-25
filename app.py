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
from openpyxl import load_workbook
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'change-this-in-hostinger-settings')
DB_USER = os.environ.get('DB_USER'); DB_PASS = os.environ.get('DB_PASS')
DB_HOST = os.environ.get('DB_HOST'); DB_NAME = os.environ.get('DB_NAME')
app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:5432/{DB_NAME}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
UPLOAD_FOLDER = "uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024

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
    
def get_valid_substatus(status, substatus):
    valid_values = SUBSTATUS_RULES.get(status, [])

    if not valid_values:
        return None

    if substatus not in valid_values:
        return None

    return substatus


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
    imei = db.Column(db.String(100)); 
    mac_address = db.Column(db.String(100))
    device_type = db.Column(db.String(100), nullable=False)
    department = db.Column(db.String(100))
    status = db.Column(db.String(50), nullable=False)
    substatus = db.Column(db.String(50))
    is_flagged = db.Column(db.Boolean, default=False, nullable=False)
    person_name = db.Column(db.String(100)); employee_id = db.Column(db.String(50))
    email = db.Column(db.String(120))
    return_date = db.Column(db.Date); purchase_date = db.Column(db.Date); end_of_cycle = db.Column(db.Date)
    notes = db.Column(db.Text); image_data = db.Column(db.Text)
    reason = db.Column(db.Text)   # NEW — why a Retired unit was reactivated, etc.
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
   
@login_manager.user_loader
def load_user(uid): return User.query.get(int(uid))

# ---------------- SCANNING RULES (the "brain") ----------------
# This dict is now the ONE place that defines scanning behavior.
DEVICE_TYPES = ["Laptop", "Mobile", "Monitor", "Printer", "Other"]
DEPARTMENTS  = ["IT", "FINANCE", "PROCUREMENT", "Other"]
STATUSES     = ["In Stock", "Loaned", "In Use", "Repair", "Retired"]
SUBSTATUS_RULES = {
    "In Stock": ["New", "Active"],
    "Loaned": ["Service Unit"],
    "Repair": ["Ongoing"],
    "Retired": ["Lost", "End of Life"]
}


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
               db.session.execute(text('ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS reason TEXT'))
               db.session.execute(text('ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS is_flagged BOOLEAN DEFAULT FALSE'))
               db.session.execute(text('ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS substatus VARCHAR(50)'))
               db.session.commit()
            except Exception: db.session.rollback()
            if not User.query.filter_by(username='admin').first():
                db.session.add(User(username='admin', password=generate_password_hash('P12345'),
                                     is_admin=True))
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

    user = sanitize(d.get('user'))
    emp = sanitize(d.get('empId'))

    if not user or not emp:
        return jsonify({
            "ok": False,
            "error": "Employee Name and ID are mandatory."
        }), 400

    device = sanitize(d.get('device'))

    if device == 'Other':
        device = sanitize(d.get('otherDevice')) or 'Other'

    dept = sanitize(d.get('dept'))

    if dept == 'Other':
        dept = sanitize(d.get('otherDept')) or 'Other'

    status = sanitize(d.get('status'))

    if status not in STATUSES:
        return jsonify({
            "ok": False,
            "error": "Invalid status."
        }), 400

    # Validate substatus based on the selected main status
    substatus = sanitize(d.get('substatus'))
    # Determine and validate substatus based on the selected status
    valid_substatuses = SUBSTATUS_RULES.get(status, [])

    if status == "Loaned":
    # Loaned always gets this substatus automatically
        substatus = "Service Unit"

    elif status == "Repair":
    # Repair always gets this substatus automatically
        substatus = "Ongoing"

    elif valid_substatuses:
    # In Stock and Retired require the user to select a substatus
        substatus = sanitize(d.get('substatus'))

    if substatus not in valid_substatuses:
        return jsonify({
            "ok": False,
            "error": (
                f"Substatus is required for {status}. "
                f"Choose one of: {', '.join(valid_substatuses)}."
            )
        }), 400

    else:
    # In Use does not use a substatus
        substatus = None


    base = device if device in DEVICE_IDENTIFIER_RULES else 'Other'

    # Store the authoritative session configuration server-side
    flask_session['scan_cfg'] = {
        "user": user,
        "empId": emp,
        "device": device,
        "dept": dept,
        "status": status,
        "substatus": substatus,
        "scanMode": sanitize(d.get('scanMode')) or "Single",
        "email": sanitize(d.get('email'), 120),
        "date": sanitize(d.get('date')),
        "purchase": sanitize(d.get('purchase')),
        "end": sanitize(d.get('end')),
        "notes": sanitize(d.get('notes'), 1000),
        "image_data": d.get('image_data'),
        "identifiers": DEVICE_IDENTIFIER_RULES.get(base, [])
    }

    return jsonify({
        "ok": True,
        "config": {
            "user": user,
            "empId": emp,
            "device": device,
            "dept": dept,
            "status": status,
            "substatus": substatus,
            "scanMode": flask_session['scan_cfg']['scanMode'],
            "requiredFields": STATUS_FIELD_RULES.get(status, []),
            "identifiers": flask_session['scan_cfg']['identifiers']
        }
    })


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
    last = InventoryScan.query.filter_by(code=code).order_by(
        InventoryScan.timestamp.desc()
    ).first()

    result = {
        "ok": True,
        "accept": True,
        "code": code,
        "nextIdentifiers": cfg.get("identifiers", []),
        "confirmMessage": None,
        "requireReason": False,
        "flag": None
    }

    if last:
        current = last.status

        if current == "In Stock":
            result["confirmMessage"] = (
                f"Serial '{code}' was already scanned (In Stock). Save this record again?"
            )

        elif current == "Loaned" and new_status == "In Use":
            result["confirmMessage"] = (
                f"Serial '{code}' is currently Loaned and has not been returned. "
                f"It will be updated to In Use. Continue?"
            )

        elif current == "In Use" and new_status == "In Use":
            result["confirmMessage"] = (
                f"Serial '{code}' is already In Use. Save this record again?"
            )

        elif current == "Repair":
            repair_count = InventoryScan.query.filter_by(
                code=code,
                status="Repair"
            ).count()

            if repair_count >= 2:
                result["flag"] = "red"
                result["confirmMessage"] = (
                    f"⚠️ Serial '{code}' will now be tagged as FLAGGED because "
                    f"this is Repair #{repair_count + 1}. Save anyway?"
                )

        elif current == "Retired" and new_status == "In Use":
            result["requireReason"] = True
            result["confirmMessage"] = (
                f"Serial '{code}' is Retired. Provide a reason to reactivate it to In Use."
            )

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

    last = InventoryScan.query.filter_by(code=code).order_by(
        InventoryScan.timestamp.desc()
    ).first()

    if last and last.status == "Retired" and cfg["status"] == "In Use" and not reason:
        return jsonify({
            "status": "error",
            "message": "A reason is required to reactivate a Retired unit."
        }), 400

    # -------------------------------
    # Automatically determine if this
    # serial should be flagged
    # -------------------------------
    is_flagged = False

    if cfg["status"] == "Repair":
        repair_count = InventoryScan.query.filter_by(
            code=code,
            status="Repair"
        ).count()

        # This save becomes the 3rd repair
        if repair_count + 1 >= 3:
            is_flagged = True

    try:
        s = InventoryScan(
            code=code,
            imei=sanitize(d.get("imei")),
            mac_address=sanitize(d.get("mac_address")),
            device_type=cfg["device"],
            department=cfg["dept"],
            status=cfg["status"],
            substatus=cfg["substatus"],
            person_name=cfg["user"],
            employee_id=cfg["empId"],
            email=cfg["email"],
            return_date=parse_dt(cfg["date"]),
            purchase_date=parse_dt(cfg["purchase"]),
            end_of_cycle=parse_dt(cfg["end"]),
            notes=cfg["notes"],
            image_data=cfg["image_data"],
            reason=reason,

            # NEW
            is_flagged=is_flagged
        )

        db.session.add(s)
        db.session.commit()

        return jsonify({
            "status": "success",
            "id": s.id,
            "is_flagged": is_flagged
        })

    except Exception as e:
        db.session.rollback()
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

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
    scans = InventoryScan.query.order_by(
        InventoryScan.timestamp.desc()
    ).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Inventory"

    headers = [
        "Timestamp",
        "Serial/Code",
        "Device Type",
        "IMEI",
        "MAC Address",
        "Department",
        "Status",
        "Substatus",
        "Employee Name",
        "Employee ID",
        "Email",
        "Purchase Date",
        "Return Date",
        "End of Cycle",
        "Reason",
        "Notes"
    ]

    ws.append(headers)

    header_fill = PatternFill(
        start_color="0D6EFD",
        end_color="0D6EFD",
        fill_type="solid"
    )

    header_font = Font(color="FFFFFF", bold=True)

    for col_num, _ in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_num)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center")

    for s in scans:
        ws.append([
            s.timestamp.strftime('%Y-%m-%d %H:%M:%S')
            if s.timestamp else "",

            s.code,
            s.device_type,
            s.imei or "",
            s.mac_address or "",
            s.department or "",
            s.status,
            s.substatus or "",
            s.person_name or "",
            s.employee_id or "",
            s.email or "",

            s.purchase_date.strftime('%Y-%m-%d')
            if s.purchase_date else "",

            s.return_date.strftime('%Y-%m-%d')
            if s.return_date else "",

            s.end_of_cycle.strftime('%Y-%m-%d')
            if s.end_of_cycle else "",

            s.reason or "",
            s.notes or ""
        ])

    for col_cells in ws.columns:
        length = max(
            len(str(cell.value))
            if cell.value is not None else 0
            for cell in col_cells
        )

        col_letter = col_cells[0].column_letter
        ws.column_dimensions[col_letter].width = min(
            max(length + 2, 10),
            40
        )

    ws.freeze_panes = "A2"

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = (
        f"inventory_export_"
        f"{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    )

    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype=(
            "application/vnd.openxmlformats-officedocument."
            "spreadsheetml.sheet"
        )
    )

  
# ---------------- IMPORT TO EXCEL ----------------
@app.route('/import/excel', methods=['POST'])
@login_required
def import_excel():

    if 'file' not in request.files:
        return jsonify({
            "status": "error",
            "message": "No file selected."
        }), 400

    file = request.files['file']

    if file.filename == '':
        return jsonify({
            "status": "error",
            "message": "Empty filename."
        }), 400

    filename = secure_filename(file.filename)

    if not filename.lower().endswith('.xlsx'):
        return jsonify({
            "status": "error",
            "message": "Only .xlsx files are allowed."
        }), 400

    filepath = os.path.join(
        app.config['UPLOAD_FOLDER'],
        filename
    )

    file.save(filepath)

    try:
        wb = load_workbook(filepath)
        ws = wb.active

        imported = 0
        skipped = 0
        errors = []

        for row_number, row in enumerate(
            ws.iter_rows(min_row=2, values_only=True),
            start=2
        ):

            try:
                timestamp = row[0]
                serial = str(row[1]).strip() if row[1] else ""

                if serial == "":
                    skipped += 1
                    errors.append(
                        f"Row {row_number}: Serial Number is empty."
                    )
                    continue

                status_value = str(row[6]).strip() \
                    if row[6] else "In Stock"

                substatus_value = str(row[7]).strip() \
                    if row[7] else None

                if status_value not in STATUSES:
                    skipped += 1
                    errors.append(
                        f"Row {row_number}: Invalid status "
                        f"'{status_value}'."
                    )
                    continue

                valid_substatuses = SUBSTATUS_RULES.get(
                    status_value,
                    []
                )

                if valid_substatuses:
                    if substatus_value not in valid_substatuses:
                        skipped += 1
                        errors.append(
                            f"Row {row_number}: Invalid or missing "
                            f"substatus '{substatus_value}' for "
                            f"status '{status_value}'."
                        )
                        continue
                else:
                    substatus_value = None

                scan = InventoryScan(
                    code=serial,
                    device_type=row[2] or "Other",
                    imei=row[3],
                    mac_address=row[4],
                    department=row[5],
                    status=status_value,
                    substatus=substatus_value,
                    person_name=row[8],
                    employee_id=row[9],
                    email=row[10],
                    purchase_date=row[11],
                    return_date=row[12],
                    end_of_cycle=row[13],
                    reason=row[14],
                    notes=row[15],
                    timestamp=(
                        timestamp
                        if isinstance(timestamp, datetime)
                        else datetime.utcnow()
                    )
                )

                db.session.add(scan)
                imported += 1

            except Exception as e:
                skipped += 1
                errors.append(
                    f"Row {row_number}: {str(e)}"
                )

        db.session.commit()

        return jsonify({
            "status": "success",
            "imported": imported,
            "skipped": skipped,
            "errors": errors
        })

    except Exception as e:
        db.session.rollback()

        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

    finally:
        if os.path.exists(filepath):
            os.remove(filepath)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8506)
