from flask import Flask, render_template, request, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, desc
import os
import json
import io
import csv
from datetime import datetime

app = Flask(__name__)

# --- DATABASE CONFIG ---
# This setup uses SQLite by default if no Postgres URL is provided, 
# preventing "Bad Gateway" crashes caused by database connection timeouts.
DB_URL = os.environ.get('postgresql://postgres:P12345@inventory-inventory-sqaoox:5432/inventory')
if DB_URL and DB_URL.startswith("postgres://"):
    DB_URL = DB_URL.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = DB_URL or 'sqlite:///enterprise_assets.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['PROPAGATE_EXCEPTIONS'] = True

db = SQLAlchemy(app)

# --- MODELS ---
class Asset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset_tag = db.Column(db.String(50), unique=True)
    serial_number = db.Column(db.String(100), nullable=False)
    imei = db.Column(db.String(100))
    mac_address = db.Column(db.String(100))
    device_type = db.Column(db.String(50))
    department = db.Column(db.String(50))
    status = db.Column(db.String(50), default='In Stock')
    borrower_name = db.Column(db.String(100))
    borrower_email = db.Column(db.String(100))
    expected_return_date = db.Column(db.Date)
    repair_count = db.Column(db.Integer, default=0)
    is_overdue = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# --- INITIALIZATION ---
def init_db():
    with app.app_context():
        try:
            db.create_all()
            print("Database initialized successfully.")
        except Exception as e:
            print(f"Database error: {e}")

init_db()

# --- ROUTES ---
@app.route('/')
def index():
    try:
        # Maintenance: Check for overdue items
        today = datetime.now().date()
        Asset.query.filter(Asset.status == 'Loan', Asset.expected_return_date < today).update({Asset.is_overdue: True})
        db.session.commit()
        
        assets = Asset.query.order_id(desc(Asset.timestamp)).all()
        stats = {
            "total": Asset.query.count(),
            "loaned": Asset.query.filter_by(status='Loan').count(),
            "overdue": Asset.query.filter_by(is_overdue=True).count()
        }
        return render_template('index.html', assets=assets, stats=stats)
    except Exception as e:
        return f"App Error: {str(e)}", 500

@app.route('/api/scan', methods=['POST'])
def handle_scan():
    data = request.json
    try:
        asset = Asset.query.filter_by(serial_number=data['serial']).first()
        if not asset:
            asset = Asset(serial_number=data['serial'])
        
        asset.status = data.get('status', 'In Stock')
        asset.device_type = data.get('device_type')
        asset.department = data.get('department')
        asset.imei = data.get('imei')
        asset.mac_address = data.get('mac')
        
        if asset.status == 'Loan':
            asset.borrower_name = data.get('borrower_name')
            asset.borrower_email = data.get('borrower_email')
            if data.get('return_date'):
                asset.expected_return_date = datetime.strptime(data['return_date'], '%Y-%m-%d').date()

        db.session.add(asset)
        db.session.commit()
        return jsonify({"status": "success"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    # Use the PORT environment variable if available (e.g., on Heroku/Render)
    port = int(os.environ.get("PORT", 8506))
    app.run(host='0.0.0.0', port=port)
