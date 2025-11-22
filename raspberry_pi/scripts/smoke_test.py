"""
Quick smoke test to spin a motor for a short duration.

Usage:
    PYTHONPATH=src python scripts/smoke_test.py --duty 0.5 --seconds 2
"""

from __future__ import annotations

import argparse
import logging

from tocado_pi.cli import _build_config_from_args, _add_shared_args
from tocado_pi.hardware import EncoderReader, build_motorkit_driver
from tocado_pi.motor_control import MotorController


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Simple motor spin smoke test")
    _add_shared_args(parser)
    parser.add_argument("--duty", type=float, default=0.5, help="Duty cycle -1..1")
    parser.add_argument("--seconds", type=float, default=2.0, help="Duration to spin")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level))

    cfg = _build_config_from_args(args)
    encoder = EncoderReader(cfg.encoder, name=f"{cfg.name}-encoder")
    motor = build_motorkit_driver(cfg.shield)
    ctrl = MotorController(motor, encoder, cfg)
    encoder.start()
    try:
        result = ctrl.spin_for(args.duty, args.seconds)
    finally:
        ctrl.motor.brake()
        encoder.stop()

    status = "ok" if result.reached else "stopped"
    print(f"{cfg.name} smoke test {status}: final={result.final_count}, elapsed={result.elapsed_s:.2f}s")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
