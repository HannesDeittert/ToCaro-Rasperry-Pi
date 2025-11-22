"""
Small CLI for manual Raspberry Pi motor checks.

Examples:
- Spin for 2 seconds at 50% duty: `python -m tocado_pi.cli spin --duty 0.5 --seconds 2`
- Move to encoder count 500 at 60% duty: `python -m tocado_pi.cli move --target 500 --duty 0.6`
"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import EncoderConfig, MotorConfig, MotionLimits, MotorShieldConfig
from .hardware import EncoderReader, build_motorkit_driver
from .motor_control import MotorController


def _build_config_from_args(args: argparse.Namespace) -> MotorConfig:
    return MotorConfig(
        shield=MotorShieldConfig(
            motor_channel=args.motor_channel,
            i2c_address=args.i2c_address,
            i2c_busnum=args.i2c_bus,
            default_duty=args.default_duty,
        ),
        encoder=EncoderConfig(pin_a=args.pin_a, pin_b=args.pin_b, pull_up=not args.no_pullup),
        limits=MotionLimits(
            min_count=args.min_count,
            max_count=args.max_count,
            max_runtime_s=args.max_runtime,
            poll_interval_s=args.poll_interval,
            stop_tolerance=args.tolerance,
        ),
        name=args.name,
    )


def _add_shared_args(parser: argparse.ArgumentParser) -> None:
    # Defaults are conservative; override for your wiring. Pins are BCM numbers.
    parser.add_argument("--pin-a", type=int, default=17, help="BCM pin for encoder A")
    parser.add_argument("--pin-b", type=int, default=27, help="BCM pin for encoder B")
    parser.add_argument("--no-pullup", action="store_true", help="Disable pull-ups on encoder pins")
    parser.add_argument("--motor-channel", type=int, default=1, help="Motor channel on shield (1-4)")
    parser.add_argument("--i2c-address", type=lambda x: int(x, 0), default=0x60, help="I2C address of Motor Shield")
    parser.add_argument("--i2c-bus", type=int, default=1, help="I2C bus number to use")
    parser.add_argument("--default-duty", type=float, default=0.5, help="Default duty (0..1)")
    parser.add_argument("--min-count", type=int, default=0, help="Lower encoder bound")
    parser.add_argument("--max-count", type=int, default=10_000, help="Upper encoder bound")
    parser.add_argument("--tolerance", type=int, default=0, help="Stop tolerance in counts")
    parser.add_argument("--max-runtime", type=float, default=15.0, help="Max runtime seconds before timeout")
    parser.add_argument("--poll-interval", type=float, default=0.01, help="Polling interval seconds")
    parser.add_argument("--name", type=str, default="motor1", help="Logical motor name for logs")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Adafruit Motor Shield test CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    _add_shared_args(common)

    spin = sub.add_parser("spin", parents=[common], help="Spin at duty for a duration")
    spin.add_argument("--duty", type=float, required=True, help="Duty cycle -1..1 (sign sets direction)")
    spin.add_argument("--seconds", type=float, default=2.0, help="Duration to spin")

    move = sub.add_parser("move", parents=[common], help="Move to a target encoder count")
    move.add_argument("--target", type=int, required=True, help="Target encoder count")
    move.add_argument("--duty", type=float, default=None, help="Duty 0..1 (direction inferred)")
    move.add_argument("--timeout", type=float, default=None, help="Optional timeout override")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level))

    cfg = _build_config_from_args(args)

    encoder = EncoderReader(cfg.encoder, name=f"{cfg.name}-encoder")
    encoder.start()
    motor = build_motorkit_driver(cfg.shield)
    controller = MotorController(motor, encoder, cfg)

    try:
        if args.command == "spin":
            result = controller.spin_for(args.duty, args.seconds)
        elif args.command == "move":
            result = controller.move_to_count(args.target, duty=args.duty, timeout_s=args.timeout)
        else:  # pragma: no cover - argparse enforces commands
            parser.error("unknown command")
            return 2
    finally:
        encoder.stop()
        motor.brake()

    status = "ok" if result.reached else "not-reached"
    print(f"{cfg.name} finished: {status}, final={result.final_count}, target={result.target}, elapsed={result.elapsed_s:.2f}s")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
