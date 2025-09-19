from flask import Flask, render_template, jsonify
import json
import os
from datetime import datetime

app = Flask(__name__)
CACHE_FILE = "standings_cache.json"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/full")
def api_full():
    if not os.path.exists(CACHE_FILE):
        return jsonify({"error": "Data not available yet, please try again in a few minutes."}), 503

    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        # Opcional: añadir la marca de tiempo de la última actualización
        data["last_updated"] = datetime.fromtimestamp(os.path.getmtime(CACHE_FILE)).strftime("%Y-%m-%d %H:%M:%S")
        
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": f"Failed to read cached data: {e}"}), 500

if __name__ == "__main__":
    app.run(debug=True)