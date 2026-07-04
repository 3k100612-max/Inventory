import os
from flask import Flask, render_template, request, jsonify
import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import RealDictCursor

load_dotenv() 

app = Flask(__name__)

def get_db_connection():
    url = os.environ.get("DATABASE_URL")
    if url:
        return psycopg2.connect(url)
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        database=os.environ.get("DB_NAME"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASS"),
        port=os.environ.get("DB_PORT", 5432)
    )

def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    create_table_query = """
    CREATE TABLE IF NOT EXISTS asset_logs (
        id SERIAL PRIMARY KEY,
        asset_id VARCHAR(255) NOT NULL,
        status VARCHAR(100),
        item_type VARCHAR(100),
        accessory_detail TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """
    cur.execute(create_table_query)
    conn.commit()
    cur.close()
    conn.close()

@app.route('/')
def index():
    return render_template('index.html')

# This endpoint handles both manual entry and camera scans
@app.route('/api/log', methods=['POST'])
def log_asset():
    data = request.json
    # Validation: Ensure asset_id is present
    if not data or 'asset_id' not in data:
        return jsonify({"status": "error", "message": "Missing asset ID"}), 400

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO asset_logs (asset_id, status, item_type, accessory_detail) VALUES (%s, %s, %s, %s)",
            (
                data.get('asset_id'), 
                data.get('status', 'Scanned'), # Default status if not provided
                data.get('type', 'Unknown'), 
                data.get('accessory_detail', 'Logged via Scanner')
            )
        )
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"status": "success", "message": f"Asset {data['asset_id']} logged"}), 201
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get("PORT", 8506)))
