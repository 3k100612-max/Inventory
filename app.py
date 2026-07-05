from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text # Added for migration
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
    status = db.Column(db.String(50), nullable=False)
    person_name = db.Column(db.String(100), nullable=True)
    person_id = db.Column(db.String(100), nullable=True)
    department = db.Column(db.String(50), nullable=True)
    return_date = db.Column(db.String(50), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# --- SELF-HEALING MIGRATION BLOCK ---
with app.app_context():
    db.create_all()
    try:
        # Check if department column exists, if not, add it
        db.session.execute(text("ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS department VARCHAR(50)"))
        db.session.commit()
        print("Database migration successful: 'department' column verified.", file=sys.stderr)
    except Exception as e:
        db.session.rollback()
        print(f"Migration Notice: {e}", file=sys.stderr)
# ------------------------------------

@app.route('/')
def index():
    recent_scans = InventoryScan.query.order_by(InventoryScan.timestamp.desc()).limit(15).all()
    return render_template('index.html', scans=recent_scans)

@app.route('/scanned', methods=['POST'])
def scanned():
    data = request.json
    try:
        new_scan = InventoryScan(
            code=data.get("code"),
            status=data.get("status"),
            person_name=data.get("person_name"),
            person_id=data.get("person_id"),
            department=data.get("department"),
            return_date=data.get("return_date")
        )
        db.session.add(new_scan)
        db.session.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        db.session.rollback()
        # This will print the exact error to your server logs
        print(f"DATABASE ERROR: {str(e)}", file=sys.stderr)
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8506)
