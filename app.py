from flask import Flask, render_template, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

app = Flask(__name__)

# Database Configuration
# Format: postgresql://username:password@host:port/database_name
DB_USER = os.environ.get('DB_USER', 'postgres')
DB_PASS = os.environ.get('DB_PASS', 'P12345')
DB_HOST = os.environ.get('DB_HOST', 'inventory-inventory-sqaoox')
DB_NAME = os.environ.get('DB_NAME', 'inventory')

app.config['SQLALCHEMY_DATABASE_URI'] = f'postgresql://{DB_USER}:{DB_PASS}@{DB_HOST}:5432/{DB_NAME}'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Database Model
class InventoryScan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(50), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# Create tables
with app.app_context():
    db.create_all()

@app.route('/')
def index():
    # Fetch the last 10 scans to display on the page
    recent_scans = InventoryScan.query.order_by(InventoryScan.timestamp.desc()).limit(10).all()
    return render_template('index.html', scans=recent_scans)

@app.route('/scanned', methods=['POST'])
def scanned():
    data = request.json
    code = data.get("code")
    status = data.get("status")
    
    # Save to PostgreSQL
    new_scan = InventoryScan(code=code, status=status)
    db.session.add(new_scan)
    db.session.commit()
    
    return jsonify({"status": "success", "message": f"Saved {code} as {status}"})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8506, debug=True)
