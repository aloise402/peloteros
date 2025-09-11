from flask import Flask, render_template, jsonify
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo

app = Flask(__name__)
CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "standings_cache.json")
SCL = ZoneInfo("America/Santiago")

@app.route("/")
def index():
    # Si no usas plantilla, puedes devolver un JSON o una página simple
    if os.path.exists(os.path.join(os.path.dirname(__file__), "templates", "index.html")):
        return render_template("index.html")
    return jsonify({"ok": True, "msg": "Servicio activo"}), 200

@app.get("/health")
def health():
    return {"ok": True}, 200

@app.route("/api/full")
def api_full():
    if not os.path.exists(CACHE_FILE):
        return jsonify({"error": "Data not available yet, please try again in a few minutes."}), 503

    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Añade marca de tiempo de última modificación (hora Chile)
        try:
            mtime = os.path.getmtime(CACHE_FILE)
            data["last_updated"] = datetime.fromtimestamp(mtime, tz=SCL).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            data.setdefault("last_updated", None)

        return jsonify(data)
    except Exception as e:
        return jsonify({"error": f"Failed to read cached data: {e}"}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")), debug=True)


