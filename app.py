from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/scanned', methods=['POST'])
def scanned():
    data = request.json
    scanned_text = data.get("code")
    
    # Here you can process the code (e.g., look up a database, log it, etc.)
    print(f"Server received scanned code: {scanned_text}")
    
    return jsonify({"status": "success", "received": scanned_text})

if __name__ == '__main__':
    # '0.0.0.0' allows access from other devices on your network (like your phone)
    app.run(host='0.0.0.0', port=5000, debug=True)
