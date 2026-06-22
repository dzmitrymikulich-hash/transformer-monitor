import threading
import time
from collections import deque
from flask import Flask, jsonify, request

# --- Shared state ---
state_lock = threading.Lock()
state = {
    "ambient_temperature": 25.0,
    "load_percent": 50.0,
    "fans_on": True,
    "current_temperature": 25.0,
    "control": True,
}
# Store last 60 seconds of readings (one per 5s = 12 points max)
history = deque(maxlen=12)

# --- Thread 1: Temperature simulation ---
def temperature_thread():
    with state_lock:
        state["current_temperature"] = state["ambient_temperature"]

    while True:
        with state_lock:
            if not state["control"]:
                break
            ambient = state["ambient_temperature"]
            load = state["load_percent"]
            k = 1 if state["fans_on"] else 0
            current = state["current_temperature"]

        new_temp = ambient + load * (0.5 - 0.2 * k)
        current_temp = (new_temp - current) / 10 + current

        with state_lock:
            state["current_temperature"] = current_temp
            history.append({"t": round(time.time()), "v": round(current_temp, 2)})

        time.sleep(5)

# --- Thread 2: Flask API ---
app = Flask(__name__)

@app.route("/", methods=["GET"])
def dashboard():
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Input UI</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: Arial, sans-serif; background: #f0f2f5;
               display: flex; justify-content: center; align-items: center; min-height: 100vh; }
        .card { background: white; border-radius: 12px; padding: 36px 40px;
                width: 380px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); }
        h2 { font-size: 20px; color: #222; margin-bottom: 24px; text-align: center; }
        .current { background: #f8f9fa; border-radius: 8px; padding: 14px 16px;
                   margin-bottom: 24px; border: 1px solid #e0e0e0; }
        .current-title { font-size: 11px; font-weight: bold; color: #999;
                         text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 10px; }
        .current-row { display: flex; justify-content: space-between;
                       font-size: 14px; color: #333; margin-bottom: 5px; }
        .current-row:last-child { margin-bottom: 0; }
        .current-row span:last-child { font-weight: bold; color: #222; }
        .field { margin-bottom: 20px; }
        label { display: block; font-size: 13px; font-weight: bold;
                color: #555; margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; }
        input[type=number] { width: 100%; padding: 10px 12px; border: 1px solid #ddd;
                             border-radius: 8px; font-size: 16px; outline: none; }
        input[type=number]:focus { border-color: #4a90e2; }
        .toggle { display: flex; gap: 10px; }
        .toggle input { display: none; }
        .toggle label { flex: 1; text-align: center; padding: 10px; border: 1px solid #ddd;
                        border-radius: 8px; cursor: pointer; font-size: 15px;
                        font-weight: bold; color: #888; text-transform: none; letter-spacing: 0; }
        .toggle input:checked + label { background: #2ecc71; color: white; border-color: #2ecc71; }
        #fans_off:checked + label { background: #e74c3c; color: white; border-color: #e74c3c; }
        button { width: 100%; padding: 12px; margin-top: 8px; font-size: 16px;
                 background: #4a90e2; color: white; border: none;
                 border-radius: 8px; cursor: pointer; font-weight: bold; }
        button:hover { background: #357abd; }
        .msg { text-align: center; margin-top: 14px; font-size: 14px;
               color: #2ecc71; display: none; }
    </style>
</head>
<body>
<div class="card">
    <h2>Input UI</h2>
    <div class="current">
        <div class="current-title">Current Values</div>
        <div class="current-row"><span>Ambient Temperature</span><span id="cv-ambient">—</span></div>
        <div class="current-row"><span>Load</span><span id="cv-load">—</span></div>
        <div class="current-row"><span>Fans</span><span id="cv-fans">—</span></div>
    </div>
    <form id="frm">
        <div class="field">
            <label>Ambient Temperature (°C)</label>
            <input type="number" id="ambient" step="0.1" placeholder="e.g. 25">
        </div>
        <div class="field">
            <label>Load (%)</label>
            <input type="number" id="load" step="1" min="0" max="100" placeholder="e.g. 50">
        </div>
        <div class="field">
            <label>Fans</label>
            <div class="toggle">
                <input type="radio" name="fans" id="fans_on" value="true" checked>
                <label for="fans_on">ON</label>
                <input type="radio" name="fans" id="fans_off" value="false">
                <label for="fans_off">OFF</label>
            </div>
        </div>
        <button type="submit">Apply</button>
        <div class="msg" id="msg">Settings applied!</div>
    </form>
</div>
<script>
    function loadCurrent() {
        fetch('/temperature').then(function(r) { return r.json(); }).then(function(d) {
            document.getElementById('cv-ambient').innerText = d.ambient_temperature + ' °C';
            document.getElementById('cv-load').innerText = d.load_percent + ' %';
            document.getElementById('cv-fans').innerText = d.fans_on ? 'ON' : 'OFF';
        });
    }
    loadCurrent();
    setInterval(loadCurrent, 5000);

    document.getElementById('frm').addEventListener('submit', function(e) {
        e.preventDefault();
        var data = {};
        var a = document.getElementById('ambient').value;
        var l = document.getElementById('load').value;
        var f = document.querySelector('input[name=fans]:checked').value;
        if (a) data.ambient_temperature = parseFloat(a);
        if (l) data.load_percent = parseFloat(l);
        data.fans_on = f === 'true';
        fetch('/settings', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data)
        }).then(function() {
            var msg = document.getElementById('msg');
            msg.style.display = 'block';
            setTimeout(function() { msg.style.display = 'none'; }, 2000);
            loadCurrent();
        });
    });
</script>
</body>
</html>
"""

@app.route("/history", methods=["GET"])
def get_history():
    with state_lock:
        return jsonify(list(history))

@app.route("/output", methods=["GET"])
def output():
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Output UI</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: Arial, sans-serif; background: #f0f2f5;
               display: flex; justify-content: center; align-items: center; min-height: 100vh; }
        .card { background: white; border-radius: 12px; padding: 36px 40px;
                width: 560px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); }
        h2 { font-size: 20px; color: #222; margin-bottom: 8px; text-align: center; }
        .temp-now { text-align: center; font-size: 48px; font-weight: bold;
                    color: #e74c3c; margin-bottom: 24px; }
        .temp-now span { font-size: 20px; color: #999; font-weight: normal; }
        a { display: block; text-align: center; margin-top: 20px;
            color: #4a90e2; text-decoration: none; font-size: 14px; }
        a:hover { text-decoration: underline; }
    </style>
</head>
<body>
<div class="card">
    <h2>Transformer Temperature</h2>
    <div class="temp-now" id="now">— <span>°C</span></div>
    <canvas id="chart" height="180"></canvas>
    <a href="/">Go to Input UI</a>
</div>
<script>
    var ctx = document.getElementById('chart').getContext('2d');
    var chart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: [],
            datasets: [{
                label: 'Temperature (°C)',
                data: [],
                borderColor: '#e74c3c',
                backgroundColor: 'rgba(231,76,60,0.1)',
                borderWidth: 2,
                pointRadius: 4,
                fill: true,
                tension: 0.3
            }]
        },
        options: {
            animation: false,
            scales: {
                x: { title: { display: true, text: 'Time' } },
                y: { title: { display: true, text: '°C' } }
            },
            plugins: { legend: { display: false } }
        }
    });

    function update() {
        fetch('/history').then(function(r) { return r.json(); }).then(function(data) {
            chart.data.labels = data.map(function(d) {
                var dt = new Date(d.t * 1000);
                return dt.getHours().toString().padStart(2,'0') + ':' +
                       dt.getMinutes().toString().padStart(2,'0') + ':' +
                       dt.getSeconds().toString().padStart(2,'0');
            });
            chart.data.datasets[0].data = data.map(function(d) { return d.v; });
            chart.update();
            if (data.length > 0) {
                document.getElementById('now').innerHTML =
                    data[data.length-1].v + ' <span>°C</span>';
            }
        });
    }
    update();
    setInterval(update, 5000);
</script>
</body>
</html>
"""

@app.route("/settings_form", methods=["POST"])
def update_settings_form():
    with state_lock:
        if request.form.get("ambient_temperature"):
            state["ambient_temperature"] = float(request.form["ambient_temperature"])
        if request.form.get("load_percent"):
            state["load_percent"] = float(request.form["load_percent"])
        if request.form.get("fans_on"):
            state["fans_on"] = request.form["fans_on"] == "true"
    return '<meta http-equiv="refresh" content="0;url=/">'

@app.route("/temperature", methods=["GET"])
def get_temperature():
    with state_lock:
        return jsonify({
            "current_temperature": round(state["current_temperature"], 2),
            "ambient_temperature": state["ambient_temperature"],
            "load_percent": state["load_percent"],
            "fans_on": state["fans_on"],
        })

@app.route("/settings", methods=["POST"])
def update_settings():
    data = request.get_json(force=True)
    with state_lock:
        if "ambient_temperature" in data:
            state["ambient_temperature"] = float(data["ambient_temperature"])
        if "load_percent" in data:
            state["load_percent"] = float(data["load_percent"])
        if "fans_on" in data:
            state["fans_on"] = bool(data["fans_on"])
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    t = threading.Thread(target=temperature_thread, daemon=True)
    t.start()
    app.run(host="0.0.0.0", port=5000)
