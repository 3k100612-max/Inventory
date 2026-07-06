from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, func
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

def run_maintenance():
    """
    Scans the entire database to ensure flags are accurate.
    This is much more efficient than looping in Python.
    """
    with app.app_context():
        try:
            today = datetime.now().date()
            # 1. Bulk Flag all Overdue Loans across the whole table
            InventoryScan.query.filter(
                InventoryScan.status == 'Loaned',
                InventoryScan.return_date < today,
                InventoryScan.is_flagged == False
            ).update({InventoryScan.is_flagged: True}, synchronize_session=False)
            
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            print(f"Maintenance Error: {e}", file=sys.stderr)

def init_db():
    with app.app_context():
        db.create_all()
        # Ensure all columns exist (Migrations)
        cols = ["device_type", "person_name", "email", "return_date", "is_flagged", "timestamp"]
        for col in cols:
            try:
                # Basic check/add logic
                db.session.execute(text(f"ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS {col} VARCHAR"))
                db.session.commit()
            except: db.session.rollback()

@app.route('/')
def index():
    # Run a global scan for overdue items every time the dashboard is loaded
    run_maintenance()
    
    # Fetch the data for the UI
    recent_scans = InventoryScan.query.order_by(InventoryScan.timestamp.desc()).limit(50).all()
    return render_template('index.html', scans=recent_scans)

@app.route('/scanned', methods=['POST'])
def scanned():
    data = request.json
    code = data.get("code")
    status = data.get("status")
    r_date_str = data.get("return_date")
    
    # Date parsing with safety
    r_date = None
    if r_date_str and r_date_str.strip():
        try:
            r_date = datetime.strptime(r_date_str, '%Y-%m-%d').date()
        except: r_date = None
    
    try:
        # Check repeat repairs: Scan DB for existing repair records for this specific item
        repair_count = InventoryScan.query.filter_by(code=code, status='Repair').count()
        
        # Determine flag status
        flag_it = False
        if status == 'Repair' and repair_count >= 2:
            flag_it = True
        elif status == 'Loaned' and r_date and r_date < datetime.now().date():
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
    init_db()
    app.run(host='0.0.0.0', port=8506)
