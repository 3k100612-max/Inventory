from flask import Flask, render_template, request, jsonify

app = Flask(__name__)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/scanned', methods=['POST'])
def scanned():
    data = request.json
    scanned_text = data.get("code")
    status = data.get("status")
    
    # Log the result to the console
    print(f"Update: Item {scanned_text} is now {status}")
    
    return jsonify({
        "status": "success", 
        "received_code": scanned_text,
        "received_status": status
    })

if __name__ == '__main__':
    # Running on port 8506 as requested
    app.run(host='0.0.0.0', port=8506, debug=True)
