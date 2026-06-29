import threading
import time
from collections import deque
from flask import Flask, jsonify, request

# --- Shared state ---
state_lock = threading.Lock()
state = {
    "ambient_temperature": 25.0,
    "load_percent": 30.0,
    "fans_on": False,
    "fan_mode": "auto",        # "auto" or "manual"
    "fan_on_threshold": 85.0,  # °C — turn fans ON above this
    "fan_off_threshold": 50.0, # °C — turn fans OFF below this
    "current_temperature": 25.0,
    "control": True,
}
# Store last 60 seconds of readings (one per 5s = 12 points max)
history = deque(maxlen=20)

# --- Thread 1: Temperature simulation ---
def temperature_thread():
    with state_lock:
        state["current_temperature"] = state["ambient_temperature"] + 0.7 * state["load_percent"]

    while True:
        with state_lock:
            if not state["control"]:
                break
            ambient = state["ambient_temperature"]
            load = state["load_percent"]
            fan_mode = state["fan_mode"]
            fans_on = state["fans_on"]
            current = state["current_temperature"]
            on_thresh = state["fan_on_threshold"]
            off_thresh = state["fan_off_threshold"]

        if fan_mode == "auto":
            if current > on_thresh:
                fans_on = True
            elif current < off_thresh:
                fans_on = False

        k = 1 if fans_on else 0
        new_temp = ambient + load * (0.7 - 0.2 * k)
        current_temp = (new_temp - current) / 10 + current

        with state_lock:
            if fan_mode == "auto":
                state["fans_on"] = fans_on
            state["current_temperature"] = current_temp
            history.append({"t": round(time.time()), "v": round(current_temp, 2)})

        time.sleep(3)

# --- Thread 2: Flask API ---
app = Flask(__name__)

@app.route("/", methods=["GET"])
def dashboard():
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Transformer Monitor</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: Arial, sans-serif; background: #f0f2f5;
               display: flex; justify-content: center; align-items: flex-start;
               min-height: 100vh; padding: 40px 20px; }
        .layout { display: flex; gap: 24px; width: 100%; max-width: 980px; align-items: flex-start; }
        .left-col { display: flex; flex-direction: column; gap: 20px; width: 380px; flex-shrink: 0; }
        .card { background: white; border-radius: 12px; padding: 28px 32px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.1); }
        .card-output { padding: 32px 36px; }
        h2 { font-size: 18px; color: #222; margin-bottom: 20px; text-align: center; }
        .current { background: #f8f9fa; border-radius: 8px; padding: 14px 16px;
                   margin-bottom: 20px; border: 1px solid #e0e0e0; }
        .current-title { font-size: 11px; font-weight: bold; color: #999;
                         text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 10px; }
        .current-row { display: flex; justify-content: space-between;
                       font-size: 14px; color: #333; margin-bottom: 5px; }
        .current-row:last-child { margin-bottom: 0; }
        .current-row span:last-child { font-weight: bold; color: #222; }
        .field { margin-bottom: 18px; }
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
        #fan_mode_manual:checked + label { background: #f39c12; color: white; border-color: #f39c12; }
        .threshold-row { display: flex; gap: 12px; }
        .threshold-row .field { flex: 1; }
        button { width: 100%; padding: 12px; margin-top: 4px; font-size: 16px;
                 background: #4a90e2; color: white; border: none;
                 border-radius: 8px; cursor: pointer; font-weight: bold; }
        button:hover { background: #357abd; }
        .btn-reset { background: #e74c3c; margin-top: 10px; }
        .btn-reset:hover { background: #c0392b; }
        .msg { text-align: center; margin-top: 12px; font-size: 14px;
               color: #2ecc71; display: none; }
        .hidden { display: none; }
        .fan-wrap { display: flex; justify-content: center; align-items: center;
                    padding: 16px 0 8px; }
        .fan-svg { transition: opacity 0.4s; }
        @keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }
        .fan-spinning { animation: spin 0.6s linear infinite; transform-origin: 50px 50px; }
        .fan-off { opacity: 0.25; }
        .temp-now { text-align: center; font-size: 52px; font-weight: bold;
                    color: #2ecc71; margin-bottom: 20px; transition: color 0.5s; }
        .temp-now span { font-size: 22px; color: #999; font-weight: normal; }
    </style>
</head>
<body>
<div class="layout">
    <div class="left-col">
        <!-- Card 1: Input -->
        <div class="card">
            <h2>Input</h2>
            <div class="current">
                <div class="current-title">Current Values</div>
                <div class="current-row"><span>Ambient Temperature</span><span id="cv-ambient">—</span></div>
                <div class="current-row"><span>Datacenter Load</span><span id="cv-load">—</span></div>
            </div>
            <form id="frm-input">
                <div class="field">
                    <label>Ambient Temperature (°C)</label>
                    <input type="number" id="ambient" step="0.1">
                </div>
                <div class="field">
                    <label>Datacenter Load (%)</label>
                    <input type="number" id="load" step="1" min="0" max="120">
                </div>
                <button type="submit">Apply</button>
                <div class="msg" id="msg-input">Settings applied!</div>
            </form>
        </div>

        <!-- Card 2: Transformer Settings -->
        <div class="card">
            <h2>Transformer Settings</h2>
            <div class="current">
                <div class="current-title">Current Values</div>
                <div class="current-row"><span>Fan Mode</span><span id="cv-fan-mode">—</span></div>
                <div class="current-row"><span>Fans</span><span id="cv-fans">—</span></div>
                <div class="current-row"><span>Fan ON above</span><span id="cv-fan-on-thresh">—</span></div>
                <div class="current-row"><span>Fan OFF below</span><span id="cv-fan-off-thresh">—</span></div>
            </div>
            <div class="fan-wrap">
                <svg id="fan-svg" class="fan-svg fan-off" width="100" height="100" viewBox="0 0 100 100">
                    <g id="fan-blades">
                        <!-- Blade 1 -->
                        <path d="M50,50 C50,50 45,30 50,15 C55,5 65,8 63,20 C61,30 50,50 50,50Z" fill="#4a90e2" opacity="0.9"/>
                        <!-- Blade 2 -->
                        <path d="M50,50 C50,50 70,45 85,50 C95,55 92,65 80,63 C70,61 50,50 50,50Z" fill="#4a90e2" opacity="0.9"/>
                        <!-- Blade 3 -->
                        <path d="M50,50 C50,50 55,70 50,85 C45,95 35,92 37,80 C39,70 50,50 50,50Z" fill="#4a90e2" opacity="0.9"/>
                        <!-- Blade 4 -->
                        <path d="M50,50 C50,50 30,55 15,50 C5,45 8,35 20,37 C30,39 50,50 50,50Z" fill="#4a90e2" opacity="0.9"/>
                    </g>
                    <circle cx="50" cy="50" r="7" fill="#2c3e50"/>
                    <circle cx="50" cy="50" r="3" fill="#ecf0f1"/>
                </svg>
            </div>
            <form id="frm-fans">
                <div class="field">
                    <label>Fan Mode</label>
                    <div class="toggle">
                        <input type="radio" name="fan_mode" id="fan_mode_auto" value="auto" checked>
                        <label for="fan_mode_auto">AUTO</label>
                        <input type="radio" name="fan_mode" id="fan_mode_manual" value="manual">
                        <label for="fan_mode_manual">MANUAL</label>
                    </div>
                </div>
                <div id="auto-settings">
                    <div class="threshold-row">
                        <div class="field">
                            <label>Fan ON above (°C)</label>
                            <input type="number" id="fan_on_threshold" step="0.5">
                        </div>
                        <div class="field">
                            <label>Fan OFF below (°C)</label>
                            <input type="number" id="fan_off_threshold" step="0.5">
                        </div>
                    </div>
                </div>
                <div id="manual-settings" class="hidden">
                    <div class="field">
                        <label>Fans</label>
                        <div class="toggle">
                            <input type="radio" name="fans" id="fans_on" value="true">
                            <label for="fans_on">ON</label>
                            <input type="radio" name="fans" id="fans_off" value="false" checked="checked">
                            <label for="fans_off">OFF</label>
                        </div>
                    </div>
                </div>
                <button type="submit">Apply</button>
                <div class="msg" id="msg-fans">Settings applied!</div>
            </form>
        </div>

    </div><!-- end left-col -->

    <div style="display:flex; flex-direction:column; gap:20px; flex:1;">
        <div class="card card-output">
            <h2>Transformer Oil Temperature</h2>
            <div class="temp-now" id="now">— <span>°C</span></div>
            <canvas id="chart" height="220"></canvas>
        </div>
        <div class="card">
            <button class="btn-reset" id="btn-reset">Reset</button>
            <div class="msg" id="msg-reset">Reset done!</div>
        </div>
    </div>
</div>
<script>
    // --- Chart ---
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

    function updateChart() {
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
                var temp = data[data.length-1].v;
                var color = temp <= 50 ? '#2ecc71' : temp <= 80 ? '#f39c12' : '#e74c3c';
                var el = document.getElementById('now');
                el.innerHTML = temp + ' <span>°C</span>';
                el.style.color = color;
            }
        });
    }

    // --- State ---
    var fanUserEdited = false;
    var modeUserEdited = false;

    document.querySelectorAll('input[name=fans]').forEach(function(r) {
        r.addEventListener('change', function() { fanUserEdited = true; });
    });
    document.querySelectorAll('input[name=fan_mode]').forEach(function(r) {
        r.addEventListener('change', function() {
            modeUserEdited = true;
            updateModeUI();
        });
    });

    function updateModeUI() {
        var isAuto = document.getElementById('fan_mode_auto').checked;
        document.getElementById('auto-settings').classList.toggle('hidden', !isAuto);
        document.getElementById('manual-settings').classList.toggle('hidden', isAuto);
    }

    function loadCurrent() {
        fetch('/temperature').then(function(r) { return r.json(); }).then(function(d) {
            document.getElementById('cv-ambient').innerText = d.ambient_temperature + ' °C';
            document.getElementById('cv-load').innerText = d.load_percent + ' %';
            document.getElementById('cv-fan-mode').innerText = d.fan_mode.toUpperCase();
            document.getElementById('cv-fans').innerText = d.fans_on ? 'ON' : 'OFF';
            document.getElementById('cv-fan-on-thresh').innerText = d.fan_on_threshold + ' °C';
            document.getElementById('cv-fan-off-thresh').innerText = d.fan_off_threshold + ' °C';
            var blades = document.getElementById('fan-blades');
            var fanSvg = document.getElementById('fan-svg');
            if (d.fans_on) {
                blades.classList.add('fan-spinning');
                fanSvg.classList.remove('fan-off');
            } else {
                blades.classList.remove('fan-spinning');
                fanSvg.classList.add('fan-off');
            }
            if (!modeUserEdited) {
                document.getElementById(d.fan_mode === 'auto' ? 'fan_mode_auto' : 'fan_mode_manual').checked = true;
                updateModeUI();
            }
            if (!fanUserEdited) {
                document.getElementById(d.fans_on ? 'fans_on' : 'fans_off').checked = true;
            }
        });
    }

    function showMsg(id) {
        var msg = document.getElementById(id);
        msg.style.display = 'block';
        setTimeout(function() { msg.style.display = 'none'; }, 2000);
    }

    function postSettings(data, msgId, resetFn) {
        fetch('/settings', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data)
        }).then(function() {
            if (resetFn) resetFn();
            showMsg(msgId);
            loadCurrent();
        });
    }

    loadCurrent();
    updateChart();
    setInterval(function() { loadCurrent(); updateChart(); }, 3000);

    // Input form — ambient & load
    document.getElementById('frm-input').addEventListener('submit', function(e) {
        e.preventDefault();
        var data = {};
        var a = document.getElementById('ambient').value;
        var l = document.getElementById('load').value;
        if (a) data.ambient_temperature = parseFloat(a);
        if (l) data.load_percent = parseFloat(l);
        postSettings(data, 'msg-input', function() {
            document.getElementById('ambient').value = '';
            document.getElementById('load').value = '';
        });
    });

    // Reset button
    document.getElementById('btn-reset').addEventListener('click', function() {
        fetch('/reset', { method: 'POST' }).then(function() {
            fanUserEdited = false;
            modeUserEdited = false;
            showMsg('msg-reset');
            loadCurrent();
        });
    });

    // Transformer settings form — fans
    document.getElementById('frm-fans').addEventListener('submit', function(e) {
        e.preventDefault();
        var data = {};
        var mode = document.querySelector('input[name=fan_mode]:checked').value;
        data.fan_mode = mode;
        if (mode === 'auto') {
            var on_t = document.getElementById('fan_on_threshold').value;
            var off_t = document.getElementById('fan_off_threshold').value;
            if (on_t) data.fan_on_threshold = parseFloat(on_t);
            if (off_t) data.fan_off_threshold = parseFloat(off_t);
        } else {
            data.fans_on = document.querySelector('input[name=fans]:checked').value === 'true';
        }
        postSettings(data, 'msg-fans', function() {
            fanUserEdited = false;
            modeUserEdited = false;
            document.getElementById('fan_on_threshold').value = '';
            document.getElementById('fan_off_threshold').value = '';
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
    from flask import redirect
    return redirect("/")

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
            "fan_mode": state["fan_mode"],
            "fan_on_threshold": state["fan_on_threshold"],
            "fan_off_threshold": state["fan_off_threshold"],
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
        if "fan_mode" in data:
            state["fan_mode"] = data["fan_mode"]
        if "fan_on_threshold" in data:
            state["fan_on_threshold"] = float(data["fan_on_threshold"])
        if "fan_off_threshold" in data:
            state["fan_off_threshold"] = float(data["fan_off_threshold"])
        if state["fan_mode"] == "auto":
            temp = state["current_temperature"]
            if temp > state["fan_on_threshold"]:
                state["fans_on"] = True
            elif temp < state["fan_off_threshold"]:
                state["fans_on"] = False
    return jsonify({"status": "ok"})

DEFAULTS = {
    "ambient_temperature": 25.0,
    "load_percent": 30.0,
    "fans_on": False,
    "fan_mode": "auto",
    "fan_on_threshold": 85.0,
    "fan_off_threshold": 50.0,
}

@app.route("/reset", methods=["POST"])
def reset():
    with state_lock:
        state.update(DEFAULTS)
        state["current_temperature"] = DEFAULTS["ambient_temperature"] + 0.7 * DEFAULTS["load_percent"]
    return jsonify({"status": "ok"})

t = threading.Thread(target=temperature_thread, daemon=True)
t.start()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
