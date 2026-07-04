import os
from flask import Flask, render_template, request, jsonify
import psycopg2
from dotenv import load_dotenv
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
        password=os.environ.get("DB_PASS"),
        port=os.environ.get("DB_PORT", 5432)
    )

def init_db():
    """Creates the table if it does not exist."""
    conn = get_db_connection()
    cur = conn.cursor()
    # SQL to create the table
    # Added a 'created_at' column which is very useful for BI/Reports
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
    print("Database initialized (Table checked/created).")

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
    # Initialize the database table before starting the app
    init_db()
    # In production (Gunicorn), init_db might need to be called differently, 
    # but for local and standard cloud deployments, this works well.
    app.run(debug=True, host='0.0.0.0', port=int(os.environ.get("PORT", 8506)))
