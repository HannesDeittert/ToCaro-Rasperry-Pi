"""
Simple web UI to view encoder counts and manually drive up to 3 motors.

Run (example with three motors and their encoder pins):
    PYTHONPATH=src python scripts/motor_web_ui.py \\
        --motor 1:17:27 --motor 2:22:23 --motor 3:24:25
Then open http://<pi-ip>:8000 in a browser on the same network.
"""

from __future__ import annotations

import argparse
import atexit
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from flask import Flask, jsonify, render_template_string, request

from tocado_pi.config import EncoderConfig
from tocado_pi.hardware import EncoderReader, MotorDriver

LOG = logging.getLogger(__name__)

HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Motor Shield UI</title>
    <style>
    body { font-family: Arial, sans-serif; max-width: 900px; margin: 20px auto; padding: 0 12px; }
    header { margin-bottom: 12px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 12px; }
    .panel { border: 1px solid #ddd; padding: 12px; border-radius: 8px; }
    .row { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
    button { padding: 6px 10px; }
    .status { font-size: 1.0em; }
    input[type=number] { width: 80px; }
    h3 { margin: 6px 0 8px 0; }
  </style>
</head>
<body>
  <header>
    <h2>Motor Shield UI</h2>
    <p>I²C 0x{{ address_hex }} | {{ motors|length }} Motor(en)</p>
  </header>

  <div class="grid">
    {% for m in motors %}
    <div class="panel" id="panel-{{ m.channel }}">
      <h3>Motor M{{ m.channel }}</h3>
      <div class="row">
        <label for="duty-{{ m.channel }}">Duty (0..1):</label>
        <input type="number" id="duty-{{ m.channel }}" min="0" max="1" step="0.01" value="0.5">
      </div>
      <div class="row">
        <button onclick="sendCommand({{ m.channel }}, 'forward')">Forward</button>
        <button onclick="sendCommand({{ m.channel }}, 'reverse')">Reverse</button>
        <button onclick="sendCommand({{ m.channel }}, 'brake')">Brake</button>
        <button onclick="sendCommand({{ m.channel }}, 'release')">Release</button>
        <button onclick="sendCommand({{ m.channel }}, 'reset')">Reset encoder</button>
      </div>
      <div class="status">
        <div>Encoder (A/B): {{ m.pin_a if m.pin_a is not none else '-' }}/{{ m.pin_b if m.pin_b is not none else '-' }}</div>
        <div>Zähler: <span id="count-{{ m.channel }}">--</span></div>
        <div>Δ seit letztem Poll: <span id="delta-{{ m.channel }}">--</span></div>
        <div>Rate (counts/s): <span id="rate-{{ m.channel }}">--</span></div>
        <div>Throttle: <span id="throttle-{{ m.channel }}">--</span></div>
        <div>Letzte Aktion: <span id="last-{{ m.channel }}">--</span></div>
      </div>
    </div>
    {% endfor %}
  </div>

  <script>
    async function sendCommand(channel, action) {
      const dutyField = document.getElementById(`duty-${channel}`);
      const duty = parseFloat(dutyField.value || "0") || 0;
      await fetch("/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel: channel, action: action, duty: duty })
      });
      refreshStatus();
    }

    async function refreshStatus() {
      const res = await fetch("/status");
      const data = await res.json();
      data.motors.forEach((m) => {
        const countEl = document.getElementById(`count-${m.channel}`);
        const deltaEl = document.getElementById(`delta-${m.channel}`);
        const rateEl = document.getElementById(`rate-${m.channel}`);
        const thrEl = document.getElementById(`throttle-${m.channel}`);
        const lastEl = document.getElementById(`last-${m.channel}`);
        if (countEl) { countEl.innerText = m.count; }
        if (deltaEl) { deltaEl.innerText = m.delta; }
        if (rateEl) { rateEl.innerText = m.rate_cps.toFixed(2); }
        if (thrEl) { thrEl.innerText = m.throttle.toFixed(2); }
        if (lastEl) { lastEl.innerText = m.last_action; }
      });
    }

    setInterval(refreshStatus, 500);
    refreshStatus();
  </script>
</body>
</html>
"""


@dataclass
class MotorSpec:
    channel: int
    pin_a: Optional[int]
    pin_b: Optional[int]


@dataclass
class MotorState:
    driver: MotorDriver
    encoder: Optional[EncoderReader]
    throttle: float = 0.0
    last_action: str = "idle"
    last_count: int = 0
    last_ts: float = 0.0


class MultiMotorSession:
    """Serializes commands across multiple motors and tracks their state."""

    def __init__(self, states: Dict[int, MotorState]) -> None:
        self._states = states
        self._lock = threading.Lock()

    def command(self, channel: int, action: str, duty: float) -> None:
        if channel not in self._states:
            raise ValueError(f"unknown motor channel {channel}")
        state = self._states[channel]
        duty = float(duty)

        with self._lock:
            if action == "forward":
                state.driver.set_throttle(abs(duty))
                state.throttle = abs(duty)
                state.last_action = "forward"
            elif action == "reverse":
                state.driver.set_throttle(-abs(duty))
                state.throttle = -abs(duty)
                state.last_action = "reverse"
            elif action == "brake":
                state.driver.brake()
                state.throttle = 0.0
                state.last_action = "brake"
            elif action == "release":
                state.driver.release()
                state.throttle = 0.0
                state.last_action = "release"
            elif action == "reset":
                if state.encoder:
                    state.encoder.reset(0)
                state.last_action = "reset-encoder"
            else:
                raise ValueError(f"unknown action {action}")
            LOG.info("M%d %s (duty=%.2f)", channel, state.last_action, state.throttle)

    def status_all(self) -> List[Dict[str, Any]]:
        with self._lock:
            now = time.monotonic()
            out = []
            for ch, state in sorted(self._states.items()):
                count = state.encoder.read() if state.encoder else 0
                dt = now - state.last_ts if state.last_ts else 0.0
                delta = count - state.last_count
                rate = (delta / dt) if dt > 0 else 0.0
                state.last_count = count
                state.last_ts = now
                out.append(
                    {
                        "channel": ch,
                        "count": count,
                        "throttle": float(state.throttle),
                        "last_action": state.last_action,
                        "delta": delta,
                        "rate_cps": rate,
                    }
                )
            return out

    def shutdown(self) -> None:
        for state in self._states.values():
            try:
                state.driver.brake()
            except Exception as exc:  # pragma: no cover - hardware path
                LOG.error("Failed to brake channel %s: %s", state.driver.name, exc)
            if state.encoder:
                try:
                    state.encoder.stop()
                except Exception as exc:  # pragma: no cover - hardware path
                    LOG.error("Failed to stop encoder for %s: %s", state.driver.name, exc)


def parse_motor_arg(raw: str) -> MotorSpec:
    parts = raw.split(":")
    if len(parts) not in (1, 3):
        raise ValueError("use CH or CH:PIN_A:PIN_B, e.g., 1:17:27")
    channel = int(parts[0])
    pin_a: Optional[int] = None
    pin_b: Optional[int] = None
    if len(parts) == 3:
        pin_a = int(parts[1])
        pin_b = int(parts[2])
    return MotorSpec(channel=channel, pin_a=pin_a, pin_b=pin_b)


def build_motor_drivers(address: int, channels: List[int]) -> Dict[int, MotorDriver]:
    try:
        from adafruit_motorkit import MotorKit  # type: ignore
    except ImportError as exc:  # pragma: no cover - hardware import
        raise RuntimeError(
            "adafruit-circuitpython-motorkit not available; install requirements on the Pi."
        ) from exc

    kit = MotorKit(address=address)
    drivers: Dict[int, MotorDriver] = {}
    for ch in channels:
        motor = getattr(kit, f"motor{ch}", None)
        if motor is None:
            raise RuntimeError(f"motor{ch} not available from MotorKit")
        drivers[ch] = MotorDriver(motor, name=f"motor{ch}")
    return drivers


def create_app(session: MultiMotorSession, *, specs: List[MotorSpec], address_hex: str) -> Flask:
    app = Flask(__name__)

    @app.route("/")
    def index():
        return render_template_string(
            HTML,
            motors=specs,
            address_hex=address_hex,
        )

    @app.route("/status")
    def status():
        return jsonify({"motors": session.status_all()})

    @app.route("/command", methods=["POST"])
    def command():
        payload = request.get_json(silent=True) or {}
        action = payload.get("action", "")
        duty = float(payload.get("duty", 0.0) or 0.0)
        channel = int(payload.get("channel", 0))
        try:
            session.command(channel, action, duty)
        except Exception as exc:  # pragma: no cover - hardware path
            LOG.error("Command %s on ch %s failed: %s", action, channel, exc)
            return jsonify({"ok": False, "error": str(exc)}), 400
        return jsonify({"ok": True})

    return app


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Web UI for Motor Shield control (multi-motor)")
    parser.add_argument(
        "--motor",
        action="append",
        metavar="CH:PIN_A:PIN_B",
        help="Motor channel and encoder pins, e.g., 1:17:27 (repeat for multiple motors)",
    )
    parser.add_argument("--motor-channel", type=int, default=1, help="Fallback motor channel if --motor not used")
    parser.add_argument("--i2c-address", type=lambda x: int(x, 0), default=0x60, help="I2C address of Motor Shield")
    parser.add_argument("--pin-a", type=int, default=17, help="Fallback BCM pin for encoder A (single motor mode)")
    parser.add_argument("--pin-b", type=int, default=27, help="Fallback BCM pin for encoder B (single motor mode)")
    parser.add_argument("--no-pullup", action="store_true", help="Disable pull-ups on encoder pins")
    parser.add_argument("--host", default="0.0.0.0", help="Host/IP to bind (default: all interfaces)")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port to serve on")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level))

    specs: List[MotorSpec] = []
    if args.motor:
        specs = [parse_motor_arg(raw) for raw in args.motor]
    else:
        specs = [MotorSpec(channel=args.motor_channel, pin_a=args.pin_a, pin_b=args.pin_b)]

    channels = [m.channel for m in specs]
    LOG.info(
        "Starting web UI on %s:%s (motors %s, I2C 0x%x)",
        args.host,
        args.port,
        ",".join(str(c) for c in channels),
        args.i2c_address,
    )

    drivers = build_motor_drivers(args.i2c_address, channels)

    states: Dict[int, MotorState] = {}
    for spec in specs:
        encoder = None
        if spec.pin_a is not None and spec.pin_b is not None:
            cfg = EncoderConfig(pin_a=spec.pin_a, pin_b=spec.pin_b, pull_up=not args.no_pullup)
            encoder = EncoderReader(cfg, name=f"encoder{spec.channel}")
            encoder.start()
        else:
            LOG.warning("Motor %d has no encoder pins configured; counts will stay at 0", spec.channel)
        states[spec.channel] = MotorState(
            driver=drivers[spec.channel],
            encoder=encoder,
            last_ts=time.monotonic(),
            last_count=encoder.read() if encoder else 0,
        )

    session = MultiMotorSession(states)
    atexit.register(session.shutdown)

    app = create_app(session, specs=specs, address_hex=f"{args.i2c_address:02x}")

    try:
        app.run(host=args.host, port=args.port, debug=False, use_reloader=False)
    finally:
        session.shutdown()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
