from flask import Flask, render_template, request, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import text, desc
from datetime import datetime, timedelta
import os
import csv
import io
import json

app = Flask(__name__)

# Database Configuration
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///enterprise_assets.db' # Or PostgreSQL
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# ==========================================
# DATABASE MODELS
# ==========================================

class Asset(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset_tag = db.Column(db.String(50), unique=True)
    serial_number = db.Column(db.String(100), nullable=False)
    imei = db.Column(db.String(100))
    mac_address = db.Column(db.String(100))
    
    device_type = db.Column(db.String(50)) # Laptop, Desktop, etc.
    device_type_other = db.Column(db.String(100))
    department = db.Column(db.String(50))
    department_other = db.Column(db.String(100))
    
    status = db.Column(db.String(50), default='In Stock')
    
    # Warranty & EOL
    vendor = db.Column(db.String(100))
    purchase_date = db.Column(db.Date)
    warranty_expiry = db.Column(db.Date)
    
    # Loan Tracking (Current)
    borrower_name = db.Column(db.String(100))
    borrower_email = db.Column(db.String(100))
    borrower_emp_id = db.Column(db.String(50))
    expected_return_date = db.Column(db.Date)
    
    # Flags
    repair_count = db.Column(db.Integer, default=0)
    is_overdue = db.Column(db.Boolean, default=False)
    
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer)
    action = db.Column(db.String(50)) # CREATE, EDIT, LOAN, REPAIR
    user = db.Column(db.String(100))
    before_state = db.Column(db.Text)
    after_state = db.Column(db.Text)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class RepairHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('asset.id'))
    reason = db.Column(db.String(255))
    vendor = db.Column(db.String(100))
    notes = db.Column(db.Text)
    cost = db.Column(db.Float)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# ==========================================
# CORE LOGIC & ROUTES
# ==========================================

@app.before_first_request
def init_system():
    db.create_all()

def log_audit(asset_id, action, user, before, after):
    log = AuditLog(
        asset_id=asset_id,
        action=action,
        user=user,
        before_state=json.dumps(before),
        after_state=json.dumps(after)
    )
    db.session.add(log)

@app.route('/')
def dashboard():
    # Auto-Maintenance: Check Overdue
    today = datetime.now().date()
    Asset.query.filter(Asset.status == 'Loan', Asset.expected_return_date < today).update({Asset.is_overdue: True})
    db.session.commit()
    
    assets = Asset.query.order_by(desc(Asset.timestamp)).all()
    
    # Stats for Dashboard
    stats = {
        "total": Asset.query.count(),
        "loaned": Asset.query.filter_by(status='Loan').count(),
        "repair": Asset.query.filter_by(status='Repair').count(),
        "overdue": Asset.query.filter_by(is_overdue=True).count(),
        "high_maintenance": Asset.query.filter(Asset.repair_count >= 3).count()
    }
    
    return render_template('index.html', assets=assets, stats=stats)

@app.route('/api/scan', methods=['POST'])
def handle_scan():
    data = request.json
    user = data.get('operator', 'System Admin')
    
    # Try to find existing asset by serial or tag
    asset = Asset.query.filter((Asset.serial_number == data['serial']) | (Asset.asset_tag == data.get('tag'))).first()
    
    action = "EDIT" if asset else "CREATE"
    before = {}
    if asset:
        before = {c.name: str(getattr(asset, c.name)) for c in asset.__table__.columns}
    else:
        asset = Asset(serial_number=data['serial'], asset_tag=data.get('tag'))

    # Map incoming data
    asset.status = data.get('status', asset.status)
    asset.device_type = data.get('device_type')
    asset.device_type_other = data.get('device_type_other')
    asset.department = data.get('department')
    asset.imei = data.get('imei', asset.imei)
    asset.mac_address = data.get('mac', asset.mac_address)
    
    # Loan Logic
    if asset.status == 'Loan':
        asset.borrower_name = data.get('borrower_name')
        asset.borrower_email = data.get('borrower_email')
        asset.borrower_emp_id = data.get('borrower_id')
        if data.get('return_date'):
            asset.expected_return_date = datetime.strptime(data['return_date'], '%Y-%m-%d').date()

    # Repair Logic
    if asset.status == 'Repair':
        asset.repair_count += 1
        repair = RepairHistory(asset_id=asset.id, reason=data.get('repair_reason'), vendor=data.get('repair_vendor'))
        db.session.add(repair)

    db.session.add(asset)
    db.session.commit()
    
    after = {c.name: str(getattr(asset, c.name)) for c in asset.__table__.columns}
    log_audit(asset.id, action, user, before, after)
    
    return jsonify({"status": "success", "repair_count": asset.repair_count, "asset_id": asset.id})

@app.route('/export')
def export_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['Asset Tag', 'Serial', 'Type', 'Dept', 'Status', 'Borrower', 'Repair Count', 'Health'])
    
    assets = Asset.query.all()
    for a in assets:
        health = "RED" if a.repair_count >= 3 else "YELLOW" if a.repair_count == 2 else "GREEN"
        writer.writerow([a.asset_tag, a.serial_number, a.device_type, a.department, a.status, a.borrower_name, a.repair_count, health])
    
    output.seek(0)
    return send_file(io.BytesIO(output.getvalue().encode()), mimetype='text/csv', as_attachment=True, download_name='asset_report.csv')

if __name__ == '__main__':
    app.run(debug=True, port=8506)
