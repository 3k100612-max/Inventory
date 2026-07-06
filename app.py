from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, cast, Date  # Added cast and Date here
from datetime import datetime
import os
import logging

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Database Configuration
DB_USER = os.environ.get('DB_USER', 'postgres')
DB_PASS = os.environ.get('DB_PASS', 'P12345')
DB_HOST = os.environ.get('DB_HOST', 'inventory-inventory-sqaoox')
DB_NAME = os.environ.get('DB_NAME', 'inventory')

# Connection string with SSL requirement
app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:5432/{DB_NAME}?sslmode=require'
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
    """Initializes the database and attempts to fix the column type."""
    with app.app_context():
        try:
            db.session.execute(text('SELECT 1'))
            db.create_all()
            
            # Attempt to convert return_date to DATE type
            # We use NULLIF to handle empty strings safely
            try:
                db.session.execute(text("""
                    ALTER TABLE inventory_scan 
                    ALTER COLUMN return_date TYPE DATE 
                    USING (NULLIF(return_date, '')::date)
                """))
                db.session.commit()
                logger.info("Database migration: return_date converted to DATE.")
            except Exception as e:
                db.session.rollback()
                logger.info(f"Migration skipped (likely already fixed or contains invalid data): {e}")

            logger.info("Database schema check complete.")
        except Exception as e:
            logger.error(f"DB Init Error: {e}")

@app.route('/health')
def health():
    return "OK", 200

@app.route('/')
def index():
    try:
        # Maintenance: Flag overdue items
        today = datetime.now().date()
        
        # FIXED: Using cast() to ensure PostgreSQL compares Date to Date
        # Also wrapped in a sub-try to prevent the whole page from crashing if one row is bad
        try:
            InventoryScan.query.filter(
                InventoryScan.status == 'Loaned',
                cast(InventoryScan.return_date, Date) < today,
                InventoryScan.is_flagged == False
            ).update({InventoryScan.is_flagged: True}, synchronize_session=False)
            db.session.commit()
        except Exception as maintenance_err:
            db.session.rollback()
            logger.warning(f"Overdue check skipped due to data type mismatch: {maintenance_err}")
        
        recent_scans = InventoryScan.query.order_by(InventoryScan.timestamp.desc()).limit(100).all()
        return render_template('index.html', scans=recent_scans)
    except Exception as e:
        logger.error(f"Index Error: {e}")
        return f"Database Error: {str(e)}", 500

@app.route('/scanned', methods=['POST'])
def scanned():
    data = request.json
    code = data.get("code")
    status = data.get("status")
    
    if not code:
        return jsonify({"status": "error", "message": "Serial number is required"}), 400
    
    r_date_str = data.get("return_date")
    r_date = None
    if r_date_str and r_date_str.strip():
        try:
            r_date = datetime.strptime(r_date_str, '%Y-%m-%d').date()
        except: pass
    
    try:
        # Flagging logic
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
    init_db()
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
