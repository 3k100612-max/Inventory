from flask import Flask, render_template, request, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text
from datetime import datetime
import os
import io
import csv

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
    imei = db.Column(db.String(100), nullable=True)
    mac_address = db.Column(db.String(100), nullable=True)
    
    # New Fields
    device_type = db.Column(db.String(50), nullable=False)
    device_type_other = db.Column(db.String(100), nullable=True)
    department = db.Column(db.String(50), nullable=False)
    department_other = db.Column(db.String(100), nullable=True)
    status = db.Column(db.String(50), nullable=False)
    
    # Loan Tracking
    borrower_name = db.Column(db.String(100), nullable=True)
    borrower_email = db.Column(db.String(120), nullable=True)
    loan_start_date = db.Column(db.Date, nullable=True)
    expected_return_date = db.Column(db.Date, nullable=True)
    
    notes = db.Column(db.Text, nullable=True)
    is_flagged = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

def init_db():
    with app.app_context():
        db.create_all()
        # Ensure all columns exist for migration
        cols = ["borrower_name", "borrower_email", "loan_start_date", "expected_return_date", "device_type_other", "department_other"]
        for col in cols:
            try:
                db.session.execute(text(f"ALTER TABLE inventory_scan ADD COLUMN IF NOT EXISTS {col} VARCHAR"))
                db.session.commit()
            except: db.session.rollback()

init_db()

@app.route('/')
def index():
    # Maintenance: Auto-flag overdue items
    today = datetime.now().date()
    InventoryScan.query.filter(
        InventoryScan.status == 'Loan',
        InventoryScan.expected_return_date < today,
        InventoryScan.is_flagged == False
    ).update({InventoryScan.is_flagged: True})
    db.session.commit()

    scans = InventoryScan.query.order_by(InventoryScan.timestamp.desc()).all()
    return render_template('index.html', scans=scans)

@app.route('/scanned', methods=['POST'])
def scanned():
    data = request.json
    try:
        # Date parsing
        start_dt = datetime.strptime(data['loan_start'], '%Y-%m-%d').date() if data.get('loan_start') else None
        end_dt = datetime.strptime(data['loan_end'], '%Y-%m-%d').date() if data.get('loan_end') else None
        
        # Auto-flag if saving an already overdue loan
        is_overdue = False
        if end_dt and end_dt < datetime.now().date() and data['status'] == 'Loan':
            is_overdue = True

        new_scan = InventoryScan(
            code=data['code'],
            imei=data.get('imei'),
            mac_address=data.get('mac_address'),
            device_type=data['device_type'],
            device_type_other=data.get('device_type_other'),
            department=data['department'],
            department_other=data.get('department_other'),
            status=data['status'],
            borrower_name=data.get('borrower_name'),
            borrower_email=data.get('borrower_email'),
            loan_start_date=start_dt,
            expected_return_date=end_dt,
            notes=data.get('notes'),
            is_flagged=is_overdue
        )
        db.session.add(new_scan)
        db.session.commit()
        return jsonify({"status": "success", "id": new_scan.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/export')
def export_data():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID', 'Serial', 'IMEI', 'MAC', 'Type', 'Dept', 'Status', 'Borrower', 'Due Date', 'Flagged'])
    
    records = InventoryScan.query.all()
    for r in records:
        writer.writerow([r.id, r.code, r.imei, r.mac_address, r.device_type, r.department, r.status, r.borrower_name, r.expected_return_date, r.is_flagged])
    
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/csv', as_attachment=True, download_name='inventory_report.csv')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8506)
