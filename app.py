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
app.config['PROPAGATE_EXCEPTIONS'] = True

db = SQLAlchemy(app)

class InventoryScan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), nullable=False)
    imei = db.Column(db.String(100), nullable=True)
    mac_address = db.Column(db.String(100), nullable=True)
    device_type = db.Column(db.String(50))
    department = db.Column(db.String(50))
    status = db.Column(db.String(50), nullable=False)
    person_name = db.Column(db.String(100), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    return_date = db.Column(db.Date, nullable=True)
    notes = db.Column(db.Text, nullable=True)
    is_flagged = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

def init_db():
    """Initializes the database. Called during app startup."""
    with app.app_context():
        try:
            db.create_all()
            # Ensure columns exist (useful for incremental updates)
            cols = ["imei", "mac_address", "device_type", "department", "person_name", "email", "return_date", "is_flagged", "timestamp"]
            for col in cols:
                try:
                    # PostgreSQL specific 'ADD COLUMN IF NOT EXISTS'
                    db.session.execute(text(f"ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS {col} VARCHAR"))
                    db.session.commit()
                except Exception:
                    db.session.rollback()
            print("Database initialized successfully.")
        except Exception as e:
            print(f"DB Connection Error: {e}", file=sys.stderr)

# RUN INIT IMMEDIATELY
init_db()

@app.route('/')
def index():
    try:
        # Wrap maintenance in a try-block so it doesn't crash the whole UI
        run_global_maintenance()
        recent_scans = InventoryScan.query.order_by(InventoryScan.timestamp.desc()).limit(100).all()
        return render_template('index.html', scans=recent_scans)
    except Exception as e:
        return f"Database Error: {str(e)}", 500

def run_global_maintenance():
    try:
        today = datetime.now().date()
        InventoryScan.query.filter(
            InventoryScan.status == 'Loaned',
            InventoryScan.return_date < today,
            InventoryScan.is_flagged == False
        ).update({InventoryScan.is_flagged: True}, synchronize_session=False)
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Maintenance failed: {e}")

@app.route('/scanned', methods=['POST'])
def scanned():
    data = request.json
    if not data or not data.get("code"):
        return jsonify({"status": "error", "message": "Missing Serial Number"}), 400

    r_date_str = data.get("return_date")
    r_date = None
    if r_date_str and r_date_str.strip():
        try:
            r_date = datetime.strptime(r_date_str, '%Y-%m-%d').date()
        except: pass
    
    try:
        code = data.get("code")
        status = data.get("status")
        
        # Check for flag conditions
        repair_count = InventoryScan.query.filter_by(code=code, status='Repair').count()
        flag_it = False
        if status == 'Repair' and repair_count >= 2:
            flag_it = True
        elif status == 'Loaned' and r_date and r_date < datetime.now().date():
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
    try:
        InventoryScan.query.filter(InventoryScan.id.in_(ids)).delete(synchronize_session=False)
        db.session.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8506))
    app.run(host='0.0.0.0', port=port)
