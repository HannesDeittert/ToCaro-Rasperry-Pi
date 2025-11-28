"""
Interactive position calibrator for one motor using the encoder.

Flow:
- Jog to the inner (min) stop, press OK to set zero.
- Jog to the outer (max) stop, press OK to record travel counts.
- Then command relative positions (fraction 0..1) or absolute counts.

Example (Motor 1, encoder A/B on BCM 17/27):
    PYTHONPATH=src python scripts/position_calibrator.py --motor-channel 1 --pin-a 17 --pin-b 27
"""

from __future__ import annotations

import argparse
import logging
import sys
import time

from tocado_pi.config import EncoderConfig, MotorConfig, MotorShieldConfig, MotionLimits
from tocado_pi.hardware import EncoderReader, build_motorkit_driver
from tocado_pi.motor_control import MotorController

LOG = logging.getLogger(__name__)


def jog(motor, duty: float, seconds: float) -> None:
    motor.set_throttle(duty)
    time.sleep(seconds)
    motor.brake()


def prompt_jog(name: str, motor, encoder: EncoderReader, duty: float, jog_s: float) -> int:
    print(f"\nJog to {name} stop. Commands: f=forward, b=back, s=stop, ok=accept, q=quit")
    while True:
        cmd = input("> ").strip().lower()
        if cmd == "f":
            jog(motor, abs(duty), jog_s)
        elif cmd == "b":
            jog(motor, -abs(duty), jog_s)
        elif cmd == "s":
            motor.brake()
        elif cmd == "ok":
            pos = encoder.read()
            print(f"{name} recorded at count={pos}")
            return pos
        elif cmd == "q":
            raise SystemExit(0)
        else:
            pos = encoder.read()
            print(f"Unknown '{cmd}'. Use f/b/s/ok/q. Current count={pos}")


def build_controller(args, encoder: EncoderReader):
    limits = MotionLimits(
        min_count=0,
        max_count=args.max_runtime_counts,
        max_runtime_s=args.max_runtime,
        poll_interval_s=args.poll_interval,
        stop_tolerance=args.tolerance,
    )
    cfg = MotorConfig(
        shield=MotorShieldConfig(
            motor_channel=args.motor_channel,
            i2c_address=args.i2c_address,
            i2c_busnum=args.i2c_bus,
            default_duty=args.move_duty,
        ),
        encoder=EncoderConfig(pin_a=args.pin_a, pin_b=args.pin_b, pull_up=not args.no_pullup),
        limits=limits,
        name="motor",
    )
    motor = build_motorkit_driver(cfg.shield)
    return MotorController(motor, encoder, cfg)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Interactive encoder calibration and positioning")
    parser.add_argument("--motor-channel", type=int, default=1, help="Motor channel on shield (1-4)")
    parser.add_argument("--i2c-address", type=lambda x: int(x, 0), default=0x60, help="I2C address of Motor Shield")
    parser.add_argument("--i2c-bus", type=int, default=1, help="I2C bus number")
    parser.add_argument("--pin-a", type=int, default=17, help="BCM pin for encoder A")
    parser.add_argument("--pin-b", type=int, default=27, help="BCM pin for encoder B")
    parser.add_argument("--no-pullup", action="store_true", help="Disable pull-ups on encoder pins")
    parser.add_argument("--debounce-ms", type=int, default=0, help="GPIO bouncetime in ms (0 to disable)")
    parser.add_argument("--jog-duty", type=float, default=0.3, help="Duty for jog steps")
    parser.add_argument("--jog-seconds", type=float, default=0.2, help="Duration per jog step")
    parser.add_argument("--move-duty", type=float, default=0.5, help="Duty for automatic moves")
    parser.add_argument("--max-runtime", type=float, default=15.0, help="Max runtime seconds for a move")
    parser.add_argument("--max-runtime-counts", type=int, default=200000, help="Temporary max count until calibrated")
    parser.add_argument("--poll-interval", type=float, default=0.001, help="Polling interval seconds")
    parser.add_argument("--tolerance", type=int, default=2, help="Stop tolerance in counts")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = parser.parse_args(argv)

    logging.basicConfig(level=getattr(logging, args.log_level))

    encoder_cfg = EncoderConfig(pin_a=args.pin_a, pin_b=args.pin_b, pull_up=not args.no_pullup, debounce_ms=args.debounce_ms)
    encoder = EncoderReader(encoder_cfg, name="cal-encoder")
    encoder.start()

    controller = build_controller(args, encoder)
    motor = controller.motor

    try:
        # Set min to zero
        encoder.reset(0)
        prompt_jog("MIN", motor, encoder, duty=args.jog_duty, jog_s=args.jog_seconds)
        encoder.reset(0)
        print("Min set to 0.")

        max_pos = prompt_jog("MAX", motor, encoder, duty=args.jog_duty, jog_s=args.jog_seconds)
        if max_pos <= 0:
            print("Max position not greater than 0; calibration aborted.")
            return 1

        # Update limits to calibrated travel
        controller.cfg.limits.min_count = 0
        controller.cfg.limits.max_count = max_pos
        print(f"Calibrated travel: 0 .. {max_pos} counts.")

        while True:
            cmd = input("\nEnter target (fraction 0..1), absolute count (cN), home, or q: ").strip().lower()
            if cmd in ("q", "quit", "exit"):
                break
            elif cmd == "home":
                target = 0
            elif cmd.startswith("c"):
                try:
                    target = int(cmd[1:])
                except ValueError:
                    print("Use c<number> for absolute count, e.g., c5000")
                    continue
            else:
                try:
                    frac = float(cmd)
                except ValueError:
                    print("Enter a fraction 0..1, 'home', 'c<number>', or 'q'.")
                    continue
                if not 0.0 <= frac <= 1.0:
                    print("Fraction must be between 0 and 1.")
                    continue
                target = int(round(max_pos * frac))

            print(f"Moving to target count {target}...")
            result = controller.move_to_count(target, duty=args.move_duty)
            print(f"Done: reached={result.reached} final={result.final_count} target={result.target} elapsed={result.elapsed_s:.2f}s")
    finally:
        try:
            motor.brake()
        except Exception:
            pass
        encoder.stop()

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
