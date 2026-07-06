from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from datetime import datetime
import os

app = Flask(__name__)

# Database Configuration
DB_USER = os.environ.get('DB_USER', 'postgres')
DB_PASS = os.environ.get('DB_PASS', 'P12345')
DB_HOST = os.environ.get('DB_HOST', 'inventory-inventory-sqaoox')
DB_NAME = os.environ.get('DB_NAME', 'inventory')

app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:5432/{DB_NAME}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class InventoryScan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), nullable=False) # Serial (Mandatory)
    status = db.Column(db.String(50), nullable=False)
    device_type = db.Column(db.String(50))
    department = db.Column(db.String(100), nullable=False) # Mandatory
    notes = db.Column(db.Text)
    photo = db.Column(db.Text) # Optional
    is_flagged = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    scanner_name = db.Column(db.String(100), nullable=False) # Mandatory
    user_email = db.Column(db.String(120))
    return_date = db.Column(db.Date)
    imei = db.Column(db.String(50)) # Optional
    mac_address = db.Column(db.String(50)) # Optional

with app.app_context():
    db.create_all()
    try:
        # Migration for all possible fields
        db.session.execute(text("ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS imei VARCHAR(50)"))
        db.session.execute(text("ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS mac_address VARCHAR(50)"))
        db.session.execute(text("ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS photo TEXT"))
        db.session.execute(text("ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS department VARCHAR(100)"))
        db.session.commit()
    except Exception:
        db.session.rollback()

@app.route('/')
def index():
    recent_scans = InventoryScan.query.order_by(InventoryScan.timestamp.desc()).limit(30).all()
    return render_template('index.html', scans=recent_scans)

@app.route('/scanned', methods=['POST'])
def scanned():
    data = request.json
    code = data.get("code")
    scanner = data.get("scanner_name")
    dept = data.get("department")

    if not code or not scanner or not dept:
        return jsonify({"status": "error", "message": "Serial, Operator, and Dept are mandatory"}), 400
    
    try:
        # Repair Flagging Logic
        repair_count = InventoryScan.query.filter_by(code=code, status='Repair').count()
        flag_it = (data.get("status") == 'Repair' and repair_count >= 2)
        warning_msg = f"IT ALERT: Item {code} flagged! {repair_count+1}th repair scan." if flag_it else None

        ret_date = None
        if data.get("return_date"):
            ret_date = datetime.strptime(data.get("return_date"), '%Y-%m-%d').date()

        new_scan = InventoryScan(
            code=code, status=data.get("status"), notes=data.get("notes"),
            device_type=data.get("device_type"), department=dept,
            scanner_name=scanner, user_email=data.get("user_email"),
            return_date=ret_date, is_flagged=flag_it,
            imei=data.get("imei"), mac_address=data.get("mac_address"),
            photo=data.get("photo")
        )
        db.session.add(new_scan)
        db.session.commit()
        
        return jsonify({"status": "success", "is_flagged": flag_it, "warning": warning_msg, "id": new_scan.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/delete-scans', methods=['POST'])
def delete_scans():
    ids = request.json.get('ids', [])
    try:
        InventoryScan.query.filter(InventoryScan.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8506)
