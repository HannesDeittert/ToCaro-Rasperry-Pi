"""
Simple web UI to view encoder counts and manually drive a motor channel.

Run:
    PYTHONPATH=src python scripts/motor_web_ui.py --motor-channel 1 --pin-a 17 --pin-b 27
Then open http://<pi-ip>:8000 in a browser on the same network.
"""

from __future__ import annotations

import argparse
import atexit
import logging
import threading
from typing import Any, Dict

from flask import Flask, jsonify, render_template_string, request

from tocado_pi.config import EncoderConfig, MotorShieldConfig
from tocado_pi.hardware import EncoderReader, MotorDriver, build_motorkit_driver

LOG = logging.getLogger(__name__)

HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Motor Shield UI</title>
  <style>
    body { font-family: Arial, sans-serif; max-width: 640px; margin: 20px auto; padding: 0 12px; }
    header { margin-bottom: 12px; }
    .panel { border: 1px solid #ddd; padding: 12px; border-radius: 8px; margin-bottom: 12px; }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
    button { padding: 8px 12px; }
    .status { font-size: 1.1em; }
    input[type=number] { width: 80px; }
  </style>
</head>
<body>
  <header>
    <h2>Motor Shield UI</h2>
    <p>Channel {{ channel }} | I²C 0x{{ address_hex }} | Encoder pins A={{ pin_a }} B={{ pin_b }}</p>
  </header>

  <div class="panel">
    <div class="row">
      <label for="duty">Duty (0..1):</label>
      <input type="number" id="duty" min="0" max="1" step="0.01" value="0.5">
      <button onclick="sendCommand('forward')">Forward</button>
      <button onclick="sendCommand('reverse')">Reverse</button>
      <button onclick="sendCommand('brake')">Brake</button>
      <button onclick="sendCommand('release')">Release</button>
      <button onclick="sendCommand('reset')">Reset encoder</button>
    </div>
  </div>

  <div class="panel status">
    <div>Encoder count: <span id="count">--</span></div>
    <div>Throttle: <span id="throttle">--</span></div>
    <div>Last action: <span id="last">--</span></div>
  </div>

  <script>
    async function sendCommand(action) {
      const dutyField = document.getElementById("duty");
      const duty = parseFloat(dutyField.value || "0") || 0;
      await fetch("/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: action, duty: duty })
      });
      refreshStatus();
    }

    async function refreshStatus() {
      const res = await fetch("/status");
      const data = await res.json();
      document.getElementById("count").innerText = data.count;
      document.getElementById("throttle").innerText = data.throttle.toFixed(2);
      document.getElementById("last").innerText = data.last_action;
    }

    setInterval(refreshStatus, 1000);
    refreshStatus();
  </script>
</body>
</html>
"""


class MotorSession:
    """Serializes motor commands and tracks current state."""

    def __init__(self, driver: MotorDriver, encoder: EncoderReader) -> None:
        self.driver = driver
        self.encoder = encoder
        self._lock = threading.Lock()
        self._throttle = 0.0
        self._last_action = "idle"

    def set_throttle(self, value: float, action: str) -> None:
        with self._lock:
            self.driver.set_throttle(value)
            self._throttle = value
            self._last_action = action
            LOG.info("Throttle -> %.2f (%s)", value, action)

    def brake(self) -> None:
        with self._lock:
            self.driver.brake()
            self._throttle = 0.0
            self._last_action = "brake"
            LOG.info("Brake engaged")

    def release(self) -> None:
        with self._lock:
            self.driver.release()
            self._throttle = 0.0
            self._last_action = "release"
            LOG.info("Release (coast)")

    def reset_encoder(self) -> None:
        with self._lock:
            self.encoder.reset(0)
            self._last_action = "reset-encoder"
            LOG.info("Encoder reset to 0")

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "count": self.encoder.read(),
                "throttle": float(self._throttle),
                "last_action": self._last_action,
            }

    def shutdown(self) -> None:
        try:
            self.brake()
        except Exception as exc:  # pragma: no cover - hardware path
            LOG.error("Failed to brake on shutdown: %s", exc)
        try:
            self.encoder.stop()
        except Exception as exc:  # pragma: no cover - hardware path
            LOG.error("Failed to stop encoder: %s", exc)


def create_app(session: MotorSession, *, channel: int, cfg: EncoderConfig, address_hex: str) -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def index():
        return render_template_string(
            HTML,
            channel=channel,
            pin_a=cfg.pin_a,
            pin_b=cfg.pin_b,
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
            if action == "forward":
                session.set_throttle(abs(duty), "forward")
            elif action == "reverse":
                session.set_throttle(-abs(duty), "reverse")
            elif action == "brake":
                session.brake()
            elif action == "release":
                session.release()
            elif action == "reset":
                session.reset_encoder()
            else:
                return jsonify({"ok": False, "error": "unknown action"}), 400
        except Exception as exc:  # pragma: no cover - hardware path
            LOG.error("Command %s failed: %s", action, exc)
            return jsonify({"ok": False, "error": str(exc)}), 500
        return jsonify({"ok": True})

    return app


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Web UI for Motor Shield control")
    parser.add_argument("--motor-channel", type=int, default=1, help="Motor channel on shield (1-4)")
    parser.add_argument("--i2c-address", type=lambda x: int(x, 0), default=0x60, help="I2C address of Motor Shield")
    parser.add_argument("--pin-a", type=int, default=17, help="BCM pin for encoder A")
    parser.add_argument("--pin-b", type=int, default=27, help="BCM pin for encoder B")
    parser.add_argument("--no-pullup", action="store_true", help="Disable pull-ups on encoder pins")
    parser.add_argument("--host", default="0.0.0.0", help="Host/IP to bind (default: all interfaces)")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port to serve on")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level))

    LOG.info(
        "Starting web UI on %s:%s (motor channel %d, I2C 0x%x, encoder pins %s/%s)",
        args.host,
        args.port,
        args.motor_channel,
        args.i2c_address,
        args.pin_a,
        args.pin_b,
    )

    encoder_cfg = EncoderConfig(pin_a=args.pin_a, pin_b=args.pin_b, pull_up=not args.no_pullup)
    encoder = EncoderReader(encoder_cfg, name="web-ui-encoder")
    encoder.start()

    shield_cfg = MotorShieldConfig(motor_channel=args.motor_channel, i2c_address=args.i2c_address)
    driver = build_motorkit_driver(shield_cfg)
    session = MotorSession(driver, encoder)
    atexit.register(session.shutdown)

    app = create_app(session, channel=args.motor_channel, cfg=encoder_cfg, address_hex=f"{args.i2c_address:02x}")

    try:
        app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    finally:
        session.shutdown()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
