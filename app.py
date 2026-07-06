from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from datetime import datetime
import os
import sys

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
    code = db.Column(db.String(100), nullable=False)
    device_type = db.Column(db.String(50))
    peripheral_detail = db.Column(db.String(100))
    status = db.Column(db.String(50), nullable=False)
    person_name = db.Column(db.String(100), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    return_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_flagged = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

with app.app_context():
    db.create_all()
    try:
        # Migration: Ensure all monitoring and loan columns exist
        db.session.execute(text("ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS device_type VARCHAR(50)"))
        db.session.execute(text("ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS peripheral_detail VARCHAR(100)"))
        db.session.execute(text("ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS person_name VARCHAR(100)"))
        db.session.execute(text("ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS email VARCHAR(120)"))
        db.session.execute(text("ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS return_date DATE"))
        db.session.execute(text("ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS notes TEXT"))
        db.session.execute(text("ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS is_flagged BOOLEAN DEFAULT FALSE"))
        db.session.execute(text("ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP"))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Migration Notice: {e}", file=sys.stderr)

@app.route('/')
def index():
    # Fetch recent history, newest first
    recent_scans = InventoryScan.query.order_by(InventoryScan.timestamp.desc()).limit(20).all()
    
    # Logic to flag overdue items on page load
    today = datetime.now().date()
    for scan in recent_scans:
        if scan.status == 'Loaned' and scan.return_date and scan.return_date < today:
            if not scan.is_flagged:
                scan.is_flagged = True
                db.session.commit()
    
    return render_template('index.html', scans=recent_scans)

@app.route('/scanned', methods=['POST'])
def scanned():
    data = request.json
    code = data.get("code")
    status = data.get("status")
    r_date_str = data.get("return_date")
    
    # Date conversion
    r_date = datetime.strptime(r_date_str, '%Y-%m-%d').date() if r_date_str else None
    
    try:
        # Flagging Logic 1: Frequent Repairs (3rd time+)
        repair_count = InventoryScan.query.filter_by(code=code, status='Repair').count()
        flag_it = (status == 'Repair' and repair_count >= 2)
        
        # Flagging Logic 2: Immediate overdue detection
        if status == 'Loaned' and r_date and r_date < datetime.now().date():
            flag_it = True

        new_scan = InventoryScan(
            code=code,
            device_type=data.get("device_type"),
            peripheral_detail=data.get("peripheral_detail"),
            status=status,
            person_name=data.get("person_name"),
            email=data.get("email"),
            return_date=r_date,
            notes=data.get("notes"),
            is_flagged=flag_it
        )
        db.session.add(new_scan)
        db.session.commit()
        
        return jsonify({"status": "success", "is_flagged": flag_it})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8506)
