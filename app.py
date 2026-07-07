from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from datetime import datetime
import os
import sys
import re
import html  # For XSS protection

app = Flask(__name__)

# Database Configuration
DB_USER = os.environ.get('DB_USER', 'postgres')
DB_PASS = os.environ.get('DB_PASS', 'P12345')
DB_HOST = os.environ.get('DB_HOST', 'inventory-inventory-sqaoox')
DB_NAME = os.environ.get('DB_NAME', 'inventory')

app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:5432/{DB_NAME}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PROPAGATE_EXCEPTIONS'] = True

db = SQLAlchemy(app)

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

def init_db():
    with app.app_context():
        try:
            db.create_all()
            # Migration logic for existing databases
            cols = {
                "purchase_date": "DATE", "end_of_cycle": "DATE", 
                "image_data": "TEXT", "device_type": "VARCHAR(100)",
                "employee_id": "VARCHAR(50)", "notes": "TEXT",
                "person_name": "VARCHAR(100)", "email": "VARCHAR(120)",
                "department": "VARCHAR(100)"
            }
            for col, col_type in cols.items():
                try:
                    db.session.execute(text(f"ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS {col} {col_type}"))
                    db.session.commit()
                except Exception: db.session.rollback()
        except Exception as e:
            print(f"Init Error: {e}", file=sys.stderr)

init_db()

# SECURITY HELPERS
def sanitize(val, length=100):
    """Prevents XSS by escaping HTML and prevents DoS by truncating length."""
    if not val: return None
    return html.escape(str(val).strip()[:length])

def is_valid_email(email):
    """Regex validation for email format."""
    if not email: return True
    regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(regex, email) is not None

@app.route('/')
def index():
    recent_scans = InventoryScan.query.order_by(InventoryScan.timestamp.desc()).limit(100).all()
    return render_template('index.html', scans=recent_scans)

@app.route('/scanned', methods=['POST'])
def scanned():
    if not request.is_json:
        return jsonify({"status": "error", "message": "Invalid Request"}), 400
    
    data = request.get_json()
    email = sanitize(data.get("email"), 120)
    
    # Validation
    if email and not is_valid_email(email):
        return jsonify({"status": "error", "message": "Invalid email format"}), 400

    def parse_dt(s):
        if not s or not s.strip(): return None
        try: return datetime.strptime(s, '%Y-%m-%d').date()
        except: return None

    try:
        # Parameterized ORM call prevents SQL Injection
        new_scan = InventoryScan(
            code=sanitize(data.get("code")),
            imei=sanitize(data.get("imei")),
            mac_address=sanitize(data.get("mac_address")),
            device_type=sanitize(data.get("device_type")),
            department=sanitize(data.get("department")),
            status=sanitize(data.get("status")),
            person_name=sanitize(data.get("person_name")),
            employee_id=sanitize(data.get("employee_id"), 50),
            email=email,
            return_date=parse_dt(data.get("return_date")),
            notes=sanitize(data.get("notes"), 1000),
            purchase_date=parse_dt(data.get("purchase_date")),
            end_of_cycle=parse_dt(data.get("end_of_cycle")),
            image_data=data.get("image_data") # Base64 string
        )
        db.session.add(new_scan)
        db.session.commit()
        return jsonify({"status": "success", "id": new_scan.id, "time": new_scan.timestamp.strftime('%H:%M')})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": "Database error"}), 500

@app.route('/delete', methods=['POST'])
def delete_scans():
    data = request.json
    ids = data.get('ids', [])
    if not all(isinstance(i, int) for i in ids):
        return jsonify({"status": "error", "message": "Invalid IDs"}), 400
    try:
        InventoryScan.query.filter(InventoryScan.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": "Delete failed"}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8506)
