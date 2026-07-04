import os
from flask import Flask, render_template, request, jsonify
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)

# Database connection helper
def get_db_connection():
    # In production, use environment variables (e.g., DATABASE_URL)
    conn = psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        database=os.environ.get("DB_NAME", "your_db_name"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ.get("DB_PASS", "your_password")
    )
    return conn

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/log', methods=['POST'])
def log_asset():
    data = request.json
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO asset_logs (asset_id, status, item_type, accessory_detail) VALUES (%s, %s, %s, %s)",
            (data['asset_id'], data['status'], data['type'], data.get('accessory_detail'))
        )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"status": "success", "message": "Asset logged successfully"}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(debug=True)
