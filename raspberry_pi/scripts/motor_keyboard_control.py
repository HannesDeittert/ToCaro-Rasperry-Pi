"""
Keyboard-controlled motor jog with fast encoder count print (minimal, Uno-like).

Controls (terminal):
- Right arrow: forward
- Left arrow: reverse
- Space: brake
- R: release (coast)
- Q or Esc: quit

Prints count/delta/rate at ~20 Hz; encoder updates instantly via interrupts.

Example (Motor 1, encoder A/B on BCM 17/27):
    PYTHONPATH=src python scripts/motor_keyboard_control.py --motor-channel 1 --pin-a 17 --pin-b 27
"""

from __future__ import annotations

import argparse
import atexit
import curses
import logging
import time

from tocado_pi.config import EncoderConfig, MotorShieldConfig
from tocado_pi.hardware import EncoderReader, build_motorkit_driver

LOG = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Keyboard jog + fast encoder print")
    p.add_argument("--motor-channel", type=int, default=1, help="Motor channel on shield (1-4)")
    p.add_argument("--i2c-address", type=lambda x: int(x, 0), default=0x60, help="I2C address of Motor Shield")
    p.add_argument("--pin-a", type=int, default=17, help="BCM pin for encoder A")
    p.add_argument("--pin-b", type=int, default=27, help="BCM pin for encoder B")
    p.add_argument("--no-pullup", action="store_true", help="Disable pull-ups on encoder pins")
    p.add_argument("--duty", type=float, default=0.4, help="Duty magnitude for forward/reverse jogs")
    p.add_argument("--poll-interval", type=float, default=0.001, help="Poll interval seconds for display/rate")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p


def run_ui(stdscr, encoder: EncoderReader, motor, duty: float, poll_interval: float):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(50)  # ~20 Hz keyboard/read loop

    last_count = encoder.read()
    last_ts = time.monotonic()
    throttle = 0.0
    last_action = "idle"

    def brake():
        nonlocal throttle, last_action
        motor.brake()
        throttle = 0.0
        last_action = "brake"

    brake()

    while True:
        ch = stdscr.getch()
        if ch in (ord("q"), 27):
            last_action = "quit"
            break
        elif ch == ord(" "):
            brake()
        elif ch in (ord("r"), ord("R")):
            motor.release()
            throttle = 0.0
            last_action = "release"
        elif ch == curses.KEY_RIGHT:
            motor.set_throttle(abs(duty))
            throttle = abs(duty)
            last_action = "forward"
        elif ch == curses.KEY_LEFT:
            motor.set_throttle(-abs(duty))
            throttle = -abs(duty)
            last_action = "reverse"

        now = time.monotonic()
        count = encoder.read()
        dt = now - last_ts
        delta = count - last_count
        rate = (delta / dt) if dt > 0 else 0.0
        last_count = count
        last_ts = now

        stdscr.erase()
        stdscr.addstr(0, 0, "Keyboard Motor Control (q/esc quit, arrows fwd/rev, space brake, R release)")
        stdscr.addstr(2, 0, f"Count: {count:>10d}   Δ: {delta:>6d}   Rate: {rate:>8.2f} cnt/s")
        stdscr.addstr(3, 0, f"Throttle: {throttle:+.3f}   Last: {last_action}")
        stdscr.refresh()
        time.sleep(poll_interval)

    brake()


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level))

    encoder_cfg = EncoderConfig(pin_a=args.pin_a, pin_b=args.pin_b, pull_up=not args.no_pullup)
    encoder = EncoderReader(encoder_cfg, name="kbd-encoder")
    encoder.start()

    shield_cfg = MotorShieldConfig(motor_channel=args.motor_channel, i2c_address=args.i2c_address)
    motor = build_motorkit_driver(shield_cfg)

    atexit.register(lambda: (motor.brake(), encoder.stop()))
    try:
        curses.wrapper(run_ui, encoder, motor, abs(args.duty), args.poll_interval)
    finally:
        try:
            motor.brake()
        except Exception:
            pass
        encoder.stop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
