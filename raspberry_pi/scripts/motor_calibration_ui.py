"""
Web UI to calibrate a single motor travel using the encoder.

Features:
- Set Home (zero) at current position.
- Set Max at current position.
- Move to a fraction of travel (0..1) or an absolute count.
- Shows encoder count/delta/rate and raw A/B levels.
- Jog buttons for small manual moves.

Run example (Motor 1, encoder A/B on BCM 17/27):
    PYTHONPATH=src python scripts/motor_calibration_ui.py --motor-channel 1 --pin-a 17 --pin-b 27
Then open http://<pi-ip>:8000
"""

from __future__ import annotations

import argparse
import atexit
import logging
import threading
import time
from typing import Any, Dict, Optional

from flask import Flask, jsonify, render_template_string, request

from tocado_pi.config import EncoderConfig, MotorConfig, MotorShieldConfig, MotionLimits
from tocado_pi.hardware import EncoderReader, MotorDriver, build_motorkit_driver
from tocado_pi.motor_control import MotorController

LOG = logging.getLogger(__name__)

HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Motor Calibration UI</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 720px; margin: 20px auto; padding: 0 12px; }
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
    <h2>Motor Calibration (M{{ channel }})</h2>
    <p>I²C 0x{{ address_hex }} | Encoder A/B: {{ pin_a }}/{{ pin_b }}</p>

    <div class="row">
      <button onclick="setHome()">Set Home (0)</button>
      <button onclick="setMax()">Set Max (current)</button>
      <span>Max: <span id="maxCount">--</span></span>
    </div>

    <div class="row">
      <label for="frac">Fraction (0..1):</label>
      <input type="number" id="frac" min="0" max="1" step="0.01" value="0.5">
      <button onclick="moveFraction()">Move to Fraction</button>
      <label for="abs">Abs count:</label>
      <input type="number" id="abs" step="1" value="0">
      <button onclick="moveAbs()">Move to Count</button>
    </div>

    <div class="row">
      <label for="duty">Duty (0..1):</label>
      <input type="number" id="duty" min="0" max="1" step="0.01" value="0.4">
      <button onclick="jog('f')">Jog Fwd</button>
      <button onclick="jog('b')">Jog Back</button>
      <button onclick="sendCommand('brake')">Brake</button>
      <button onclick="sendCommand('release')">Release</button>
    </div>

    <div>
      <div>Zähler: <span id="count">--</span></div>
      <div>Δ seit letztem Poll: <span id="delta">--</span></div>
      <div>Rate (counts/s): <span id="rate">--</span></div>
      <div>Throttle: <span id="throttle">--</span></div>
      <div>Letzte Aktion: <span id="last">--</span></div>
      <div>In Bewegung: <span id="moving">--</span></div>
      <div>Max Count: <span id="max">--</span></div>
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

    async function sendCommand(action, payload={}) {
      const body = Object.assign({ action: action }, payload);
      await fetch("/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body)
      });
      refreshStatus();
    }

    function jog(dir) {
      const duty = parseFloat(document.getElementById("duty").value || "0") || 0;
      const seconds = 0.25;
      sendCommand("jog", { dir: dir, duty: duty, seconds: seconds });
    }

    function setHome() { sendCommand("set_home"); }
    function setMax() { sendCommand("set_max"); }
    function moveFraction() {
      const frac = parseFloat(document.getElementById("frac").value || "0") || 0;
      sendCommand("move_fraction", { fraction: frac });
    }
    function moveAbs() {
      const target = parseInt(document.getElementById("abs").value || "0");
      sendCommand("move_abs", { target: target });
    }

    async function refreshStatus() {
      const res = await fetch("/status");
      const m = await res.json();
      document.getElementById("count").innerText = m.count;
      document.getElementById("delta").innerText = m.delta;
      document.getElementById("rate").innerText = m.rate_cps.toFixed(2);
      document.getElementById("throttle").innerText = m.throttle.toFixed(2);
      document.getElementById("last").innerText = m.last_action;
      document.getElementById("moving").innerText = m.in_motion;
      document.getElementById("max").innerText = m.max_count;
      document.getElementById("maxCount").innerText = m.max_count;
      addLogSample(m);
      updateRaw(m);
    }

    setInterval(refreshStatus, 400);
    refreshStatus();
  </script>
</body>
</html>
"""


class CalSession:
    def __init__(self, controller: MotorController, encoder: EncoderReader) -> None:
        self.controller = controller
        self.encoder = encoder
        self._lock = threading.Lock()
        self._throttle = 0.0
        self._last_action = "idle"
        self._last_count = 0
        self._last_ts = time.monotonic()
        self._max_count = 0
        self._move_thread: Optional[threading.Thread] = None
        self._in_motion = False
        self._stop_flag = False

    def _run_move(self, target: int, duty: float) -> None:
        try:
            self._in_motion = True
            result = self.controller.move_to_count(target, duty=duty)
            LOG.info("Move done: reached=%s final=%s target=%s", result.reached, result.final_count, result.target)
            self._last_action = f"move_to {target} reached={result.reached}"
        finally:
            self._in_motion = False
            try:
                self.controller.motor.brake()
            except Exception:
                pass

    def command(self, action: str, payload: Dict[str, Any]) -> None:
        with self._lock:
            if action == "set_home":
                self.encoder.reset(0)
                self.controller.cfg.limits.min_count = 0
                self._last_action = "home set"
            elif action == "set_max":
                current = self.encoder.read()
                if current > 0:
                    self._max_count = current
                    self.controller.cfg.limits.max_count = current
                    self._last_action = f"max set {current}"
                else:
                    self._last_action = "max not set (<=0)"
            elif action == "move_fraction":
                frac = float(payload.get("fraction", 0.0) or 0.0)
                frac = max(0.0, min(1.0, frac))
                target = int(round(self._max_count * frac))
                self._start_move(target, payload)
            elif action == "move_abs":
                target = int(payload.get("target", 0))
                self._start_move(target, payload)
            elif action == "brake":
                self.controller.motor.brake()
                self._throttle = 0.0
                self._last_action = "brake"
            elif action == "release":
                self.controller.motor.release()
                self._throttle = 0.0
                self._last_action = "release"
            elif action == "jog":
                duty = float(payload.get("duty", 0.3) or 0.3)
                seconds = float(payload.get("seconds", 0.25) or 0.25)
                direction = payload.get("dir", "f")
                duty = abs(duty) if direction == "f" else -abs(duty)
                self.controller.motor.set_throttle(duty)
                self._throttle = duty
                self._last_action = f"jog {direction}"
                threading.Thread(target=self._finish_jog, args=(seconds,), daemon=True).start()
            else:
                raise ValueError(f"unknown action {action}")

    def _start_move(self, target: int, payload: Dict[str, Any]) -> None:
        if self._in_motion:
            self._last_action = "busy"
            return
        duty = float(payload.get("duty", self.controller.cfg.shield.default_duty) or self.controller.cfg.shield.default_duty)
        self._move_thread = threading.Thread(target=self._run_move, args=(target, duty), daemon=True)
        self._move_thread.start()
        self._last_action = f"moving to {target}"

    def _finish_jog(self, seconds: float) -> None:
        try:
            time.sleep(seconds)
            self.controller.motor.brake()
        finally:
            self._throttle = 0.0

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
            except Exception as exc:  # pragma: no cover
                LOG.debug("Raw read failed: %s", exc)
            return {
                "count": count,
                "delta": delta,
                "rate_cps": rate,
                "throttle": float(self._throttle),
                "last_action": self._last_action,
                "in_motion": self._in_motion,
                "max_count": self._max_count,
                "raw_a": raw_a,
                "raw_b": raw_b,
            }

    def shutdown(self) -> None:
        try:
            self.controller.motor.brake()
        except Exception:
            pass
        try:
            self.encoder.stop()
        except Exception:
            pass


def build_controller(args, encoder: EncoderReader) -> MotorController:
    limits = MotionLimits(
        min_count=0,
        max_count=args.temp_max_counts,
        max_runtime_s=args.max_runtime,
        poll_interval_s=args.poll_interval,
        stop_tolerance=args.tolerance,
    )
    cfg = MotorConfig(
        shield=MotorShieldConfig(
            motor_channel=args.motor_channel,
            i2c_address=args.i2c_address,
            i2c_busnum=args.i2c_bus,
            default_duty=args.default_duty,
        ),
        encoder=EncoderConfig(pin_a=args.pin_a, pin_b=args.pin_b, pull_up=not args.no_pullup),
        limits=limits,
        name="motor",
    )
    motor = build_motorkit_driver(cfg.shield)
    return MotorController(motor, encoder, cfg)


def create_app(session: CalSession, *, channel: int, pin_a: int, pin_b: int, address_hex: str) -> Flask:
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
        try:
            session.command(action, payload)
        except Exception as exc:  # pragma: no cover
            LOG.error("Command %s failed: %s", action, exc)
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True})

    return app


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Motor calibration UI (home/max + moves)")
    parser.add_argument("--motor-channel", type=int, default=1, help="Motor channel on shield (1-4)")
    parser.add_argument("--i2c-address", type=lambda x: int(x, 0), default=0x60, help="I2C address of Motor Shield")
    parser.add_argument("--i2c-bus", type=int, default=1, help="I2C bus number")
    parser.add_argument("--pin-a", type=int, default=17, help="BCM pin for encoder A")
    parser.add_argument("--pin-b", type=int, default=27, help="BCM pin for encoder B")
    parser.add_argument("--no-pullup", action="store_true", help="Disable pull-ups on encoder pins")
    parser.add_argument("--default-duty", type=float, default=0.5, help="Default duty for moves")
    parser.add_argument("--max-runtime", type=float, default=15.0, help="Max runtime seconds for a move")
    parser.add_argument("--temp-max-counts", type=int, default=200000, help="Temporary max count before calibration")
    parser.add_argument("--poll-interval", type=float, default=0.01, help="Polling interval seconds")
    parser.add_argument("--tolerance", type=int, default=2, help="Stop tolerance in counts")
    parser.add_argument("--host", default="0.0.0.0", help="Host/IP to bind")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level))

    encoder_cfg = EncoderConfig(pin_a=args.pin_a, pin_b=args.pin_b, pull_up=not args.no_pullup)
    encoder = EncoderReader(encoder_cfg, name="cal-encoder")
    encoder.start()

    controller = build_controller(args, encoder)
    session = CalSession(controller, encoder)
    atexit.register(session.shutdown)

    app = create_app(session, channel=args.motor_channel, pin_a=args.pin_a, pin_b=args.pin_b, address_hex=f"{args.i2c_address:02x}")

    try:
        app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    finally:
        session.shutdown()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
