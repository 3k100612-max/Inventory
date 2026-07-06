from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from datetime import datetime, timezone
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
app.config['PROPAGATE_EXCEPTIONS'] = True

db = SQLAlchemy(app)

class InventoryScan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), nullable=False) 
    imei = db.Column(db.String(100), nullable=True)
    mac_address = db.Column(db.String(100), nullable=True)
    device_type = db.Column(db.String(50))
    department = db.Column(db.String(50))
    peripheral_detail = db.Column(db.String(100))
    status = db.Column(db.String(50), nullable=False)
    person_name = db.Column(db.String(100), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    return_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_flagged = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))

def run_global_maintenance():
    """Scans for overdue items safely."""
    try:
        today = datetime.now(timezone.utc).date()
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
    """Initializes the database with correct SQL types."""
    with app.app_context():
        try:
            db.create_all()
            # Map columns to their correct PostgreSQL types
            col_types = {
                "imei": "VARCHAR(100)",
                "mac_address": "VARCHAR(100)",
                "device_type": "VARCHAR(50)",
                "department": "VARCHAR(50)",
                "person_name": "VARCHAR(100)",
                "email": "VARCHAR(120)",
                "return_date": "DATE",
                "is_flagged": "BOOLEAN DEFAULT FALSE",
                "timestamp": "TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP"
            }
            
            for col, sql_type in col_types.items():
                try:
                    db.session.execute(text(f"ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS {col} {sql_type}"))
                    db.session.commit()
                except Exception as col_err:
                    db.session.rollback()
                    print(f"Notice: Column {col} check result: {col_err}", file=sys.stderr)
            print("Database initialization completed.")
        except Exception as e:
            print(f"Critical DB Init Error: {e}", file=sys.stderr)

@app.route('/')
def index():
    try:
        run_global_maintenance()
        recent_scans = InventoryScan.query.order_by(InventoryScan.timestamp.desc()).limit(100).all()
        return render_template('index.html', scans=recent_scans)
    except Exception as e:
        # Returns the actual error message to the browser for debugging
        return f"Database Error: {str(e)}", 500

@app.route('/scanned', methods=['POST'])
def scanned():
    data = request.json
    code = data.get("code")
    status = data.get("status")
    r_date_str = data.get("return_date")
    
    r_date = None
    if r_date_str and r_date_str.strip():
        try:
            r_date = datetime.strptime(r_date_str, '%Y-%m-%d').date()
        except: 
            r_date = None
    
    try:
        repair_count = InventoryScan.query.filter_by(code=code, status='Repair').count()
        flag_it = False
        today = datetime.now(timezone.utc).date()
        
        if status == 'Repair' and repair_count >= 2:
            flag_it = True
        elif status == 'Loaned' and r_date and r_date < today:
            flag_it = True

        new_scan = InventoryScan(
            code=code,
            imei=data.get("imei"),
            mac_address=data.get("mac_address"),
            device_type=data.get("device_type"),
            department=data.get("department"),
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

@app.route('/delete', methods=['POST'])
def delete_scans():
    data = request.json
    ids = data.get('ids', [])
    if not ids:
        return jsonify({"status": "error", "message": "No items selected"}), 400
    try:
        InventoryScan.query.filter(InventoryScan.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get("PORT", 8506))
    app.run(host='0.0.0.0', port=port)
