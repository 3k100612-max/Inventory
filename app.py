import os
from flask import Flask, render_template, request, jsonify
import psycopg2
from dotenv import load_dotenv # Add this
from psycopg2.extras import RealDictCursor

# Load the .env file
load_dotenv() 

app = Flask(__name__)

def get_db_connection():
    # Use the DATABASE_URL variable which is standard for cloud Postgres
    url = os.environ.get("DATABASE_URL")
    if url:
        return psycopg2.connect(url)
    
    # Fallback for local testing
    return psycopg2.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        database=os.environ.get("DB_NAME"),
        user=os.environ.get("DB_USER"),
        password=os.environ.get("DB_PASS")
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
