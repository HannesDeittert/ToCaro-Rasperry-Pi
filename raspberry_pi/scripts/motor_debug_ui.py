"""
Single-motor debug UI with raw encoder levels.

- Control motor: forward/reverse/brake/release.
- View encoder count, delta, rate.
- See raw A/B levels and a short history to confirm wiring.

Example (Motor 1, encoder A/B on BCM 17/27):
    PYTHONPATH=src python scripts/motor_debug_ui.py --motor-channel 1 --pin-a 17 --pin-b 27
Then open http://<pi-ip>:8000 in a browser.
"""

from __future__ import annotations

import argparse
import atexit
import logging
import threading
import time
from typing import Any, Dict, Optional

from flask import Flask, jsonify, render_template_string, request

from tocado_pi.config import EncoderConfig, MotorShieldConfig
from tocado_pi.hardware import EncoderReader, MotorDriver, build_motorkit_driver

LOG = logging.getLogger(__name__)

HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Motor Debug UI</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 640px; margin: 20px auto; padding: 0 12px; }
    .panel { border: 1px solid #ddd; padding: 12px; border-radius: 8px; }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
    button { padding: 6px 10px; }
    input[type=number] { width: 80px; }
    .monitor pre { background: #fafafa; border: 1px solid #eee; padding: 8px; height: 140px; overflow-y: auto; font-family: monospace; font-size: 12px; }
    .levels { margin-top: 6px; font-size: 0.95em; }
    .level-dot { display: inline-block; width: 10px; height: 10px; border-radius: 50%; background: #ccc; margin-left: 4px; vertical-align: middle; }
    .level-high { background: #27ae60; }
    .level-low { background: #bdc3c7; }
  </style>
</head>
<body>
  <div class="panel">
    <h2>Motor Debug (M{{ channel }})</h2>
    <p>I²C 0x{{ address_hex }} | Encoder A/B: {{ pin_a }}/{{ pin_b }}</p>
    <div class="row">
      <label for="duty">Duty (0..1):</label>
      <input type="number" id="duty" min="0" max="1" step="0.01" value="0.5">
      <button onclick="sendCommand('forward')">Forward</button>
      <button onclick="sendCommand('reverse')">Reverse</button>
      <button onclick="sendCommand('brake')">Brake</button>
      <button onclick="sendCommand('release')">Release</button>
      <button onclick="sendCommand('reset')">Reset encoder</button>
    </div>
    <div>
      <div>Zähler: <span id="count">--</span></div>
      <div>Δ seit letztem Poll: <span id="delta">--</span></div>
      <div>Rate (counts/s): <span id="rate">--</span></div>
      <div>Throttle: <span id="throttle">--</span></div>
      <div>Letzte Aktion: <span id="last">--</span></div>
    </div>
    <div class="levels">
      Raw A: <span id="rawA">?</span><span id="dotA" class="level-dot"></span>
      Raw B: <span id="rawB">?</span><span id="dotB" class="level-dot"></span><br>
      History: <span id="rawHist">--</span>
    </div>
    <div class="monitor">
      <div>Encoder Monitor (letzte Samples):</div>
      <pre id="log"></pre>
    </div>
  </div>

  <script>
    const history = [];
    const levelHistory = [];
    const MAX_LOG = 120;
    const MAX_LEVEL_HISTORY = 60;

    function visualizeRate(rate) {
      const mag = Math.min(20, Math.round(Math.abs(rate)));
      if (mag === 0) return ".";
      const bar = "|".repeat(mag);
      return rate >= 0 ? ">" + bar : "<" + bar;
    }

    function addLogSample(m) {
      const ts = new Date().toLocaleTimeString();
      history.push(`${ts} c=${m.count} Δ=${m.delta} r=${m.rate_cps.toFixed(2)} ${visualizeRate(m.rate_cps)}`);
      if (history.length > MAX_LOG) history.shift();
      const el = document.getElementById("log");
      if (el) {
        el.innerText = history.join("\\n");
        el.scrollTop = el.scrollHeight;
      }
    }

    function updateRaw(m) {
      const aVal = (m.raw_a === null || m.raw_a === undefined) ? "?" : m.raw_a;
      const bVal = (m.raw_b === null || m.raw_b === undefined) ? "?" : m.raw_b;
      document.getElementById("rawA").innerText = aVal;
      document.getElementById("rawB").innerText = bVal;
      const dotA = document.getElementById("dotA");
      const dotB = document.getElementById("dotB");
      if (dotA) {
        dotA.classList.remove("level-high", "level-low");
        if (aVal == 1) dotA.classList.add("level-high"); else if (aVal == 0) dotA.classList.add("level-low");
      }
      if (dotB) {
        dotB.classList.remove("level-high", "level-low");
        if (bVal == 1) dotB.classList.add("level-high"); else if (bVal == 0) dotB.classList.add("level-low");
      }
      if (aVal !== "?" && bVal !== "?") {
        levelHistory.push(`${aVal}${bVal}`);
        if (levelHistory.length > MAX_LEVEL_HISTORY) levelHistory.shift();
        const histEl = document.getElementById("rawHist");
        if (histEl) histEl.innerText = levelHistory.join(" ");
      }
    }

    async function sendCommand(action) {
      const duty = parseFloat(document.getElementById("duty").value || "0") || 0;
      await fetch("/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: action, duty: duty })
      });
      refreshStatus();
    }

    async function refreshStatus() {
      const res = await fetch("/status");
      const m = await res.json();
      document.getElementById("count").innerText = m.count;
      document.getElementById("delta").innerText = m.delta;
      document.getElementById("rate").innerText = m.rate_cps.toFixed(2);
      document.getElementById("throttle").innerText = m.throttle.toFixed(2);
      document.getElementById("last").innerText = m.last_action;
      addLogSample(m);
      updateRaw(m);
    }

    setInterval(refreshStatus, 400);
    refreshStatus();
  </script>
</body>
</html>
"""


class SingleMotorSession:
    def __init__(self, driver: MotorDriver, encoder: EncoderReader) -> None:
        self.driver = driver
        self.encoder = encoder
        self._lock = threading.Lock()
        self._throttle = 0.0
        self._last_action = "idle"
        self._last_count = 0
        self._last_ts = time.monotonic()

    def command(self, action: str, duty: float) -> None:
        duty = float(duty)
        with self._lock:
            if action == "forward":
                self.driver.set_throttle(abs(duty))
                self._throttle = abs(duty)
                self._last_action = "forward"
            elif action == "reverse":
                self.driver.set_throttle(-abs(duty))
                self._throttle = -abs(duty)
                self._last_action = "reverse"
            elif action == "brake":
                self.driver.brake()
                self._throttle = 0.0
                self._last_action = "brake"
            elif action == "release":
                self.driver.release()
                self._throttle = 0.0
                self._last_action = "release"
            elif action == "reset":
                self.encoder.reset(0)
                self._last_action = "reset-encoder"
            else:
                raise ValueError(f"unknown action {action}")
            LOG.info("Command %s duty=%.2f", self._last_action, self._throttle)

    def status(self) -> Dict[str, Any]:
        with self._lock:
            now = time.monotonic()
            count = self.encoder.read()
            dt = now - self._last_ts if self._last_ts else 0.0
            delta = count - self._last_count
            rate = (delta / dt) if dt > 0 else 0.0
            self._last_count = count
            self._last_ts = now
            raw_a = raw_b = None
            try:
                GPIO = self.encoder._ensure_gpio()  # type: ignore[attr-defined]
                raw_a = GPIO.input(self.encoder.cfg.pin_a)  # type: ignore[attr-defined]
                raw_b = GPIO.input(self.encoder.cfg.pin_b)  # type: ignore[attr-defined]
            except Exception as exc:  # pragma: no cover - hardware path
                LOG.debug("Failed to read raw levels: %s", exc)
            return {
                "count": count,
                "delta": delta,
                "rate_cps": rate,
                "throttle": float(self._throttle),
                "last_action": self._last_action,
                "raw_a": raw_a,
                "raw_b": raw_b,
            }

    def shutdown(self) -> None:
        try:
            self.driver.brake()
        except Exception as exc:  # pragma: no cover
            LOG.error("Brake failed: %s", exc)
        try:
            self.encoder.stop()
        except Exception as exc:  # pragma: no cover
            LOG.error("Stop encoder failed: %s", exc)


def create_app(session: SingleMotorSession, *, channel: int, pin_a: int, pin_b: int, address_hex: str) -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def index():
        return render_template_string(
            HTML,
            channel=channel,
            pin_a=pin_a,
            pin_b=pin_b,
            address_hex=address_hex,
        )

    @app.route("/status")
    def status():
        return jsonify(session.status())

    @app.route("/command", methods=["POST"])
    def command():
        payload = request.get_json(silent=True) or {}
        action = payload.get("action", "")
        duty = float(payload.get("duty", 0.0) or 0.0)
        try:
            session.command(action, duty)
        except Exception as exc:  # pragma: no cover - hardware path
            LOG.error("Command %s failed: %s", action, exc)
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True})

    return app


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Single motor debug UI")
    parser.add_argument("--motor-channel", type=int, default=1, help="Motor channel on shield (1-4)")
    parser.add_argument("--i2c-address", type=lambda x: int(x, 0), default=0x60, help="I2C address of Motor Shield")
    parser.add_argument("--pin-a", type=int, default=17, help="BCM pin for encoder A")
    parser.add_argument("--pin-b", type=int, default=27, help="BCM pin for encoder B")
    parser.add_argument("--no-pullup", action="store_true", help="Disable pull-ups on encoder pins")
    parser.add_argument("--debounce-ms", type=int, default=0, help="GPIO bouncetime in ms (0 to disable)")
    parser.add_argument("--host", default="0.0.0.0", help="Host/IP to bind")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level))

    encoder_cfg = EncoderConfig(pin_a=args.pin_a, pin_b=args.pin_b, pull_up=not args.no_pullup, debounce_ms=args.debounce_ms)
    encoder = EncoderReader(encoder_cfg, name="debug-encoder")
    encoder.start()

    shield_cfg = MotorShieldConfig(motor_channel=args.motor_channel, i2c_address=args.i2c_address)
    driver = build_motorkit_driver(shield_cfg)
    session = SingleMotorSession(driver, encoder)
    atexit.register(session.shutdown)

    app = create_app(session, channel=args.motor_channel, pin_a=args.pin_a, pin_b=args.pin_b, address_hex=f"{args.i2c_address:02x}")

    try:
        app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    finally:
        session.shutdown()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
