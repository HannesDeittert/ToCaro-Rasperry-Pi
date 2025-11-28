"""
Minimal encoder monitor to debug wiring on the Raspberry Pi.

Mirrors the Arduino setup:
- A/B as inputs with pull-ups
- Interrupt on channel A, counts up/down based on B state
- Optional edge logging and raw level printing each poll

Run (motor 1 example, Arduino pins 2/3 mapped to BCM 17/27):
    PYTHONPATH=src python scripts/encoder_monitor.py --pin-a 17 --pin-b 27
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from tocado_pi.hardware import EncoderReader
from tocado_pi.config import EncoderConfig

LOG = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Simple encoder monitor for wiring debug")
    p.add_argument("--pin-a", type=int, required=True, help="BCM pin for encoder A (attach interrupt)")
    p.add_argument("--pin-b", type=int, required=True, help="BCM pin for encoder B")
    p.add_argument("--no-pullup", action="store_true", help="Disable pull-ups (default: enabled)")
    p.add_argument("--debounce-ms", type=int, default=0, help="GPIO bouncetime in ms (0 to disable)")
    p.add_argument("--log-edges", action="store_true", help="Print every edge (A/B states)")
    p.add_argument("--show-levels", action="store_true", help="Print raw A/B levels every interval")
    p.add_argument("--interval", type=float, default=0.2, help="Print interval seconds")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level))

    cfg = EncoderConfig(pin_a=args.pin_a, pin_b=args.pin_b, pull_up=not args.no_pullup, debounce_ms=args.debounce_ms)
    enc = EncoderReader(cfg, name="monitor")

    # Wrap edge handler to optionally log transitions
    if args.log_edges:
        orig_handle = enc._handle_edge  # type: ignore[attr-defined]

        def _wrapped(ch):
            orig_handle(ch)
            try:
                GPIO = enc._ensure_gpio()  # type: ignore[attr-defined]
                a_state = GPIO.input(cfg.pin_a)
                b_state = GPIO.input(cfg.pin_b)
                LOG.info("edge on %s: A=%d B=%d count=%d", ch, a_state, b_state, enc.read())
            except Exception:
                LOG.exception("edge logging failed")

        enc._handle_edge = _wrapped  # type: ignore[assignment]

    enc.start()
    LOG.info("Monitoring encoder on A=%s B=%s (pull-ups %s)", cfg.pin_a, cfg.pin_b, "off" if args.no_pullup else "on")

    stop = False

    def handle_sig(sig, frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, handle_sig)

    last = enc.read()
    while not stop:
        time.sleep(args.interval)
        now = enc.read()
        delta = now - last
        last = now
        if args.show_levels:
            try:
                GPIO = enc._ensure_gpio()  # type: ignore[attr-defined]
                a_state = GPIO.input(cfg.pin_a)
                b_state = GPIO.input(cfg.pin_b)
                print(f"count={now} delta={delta} A={a_state} B={b_state}")
            except Exception:
                LOG.exception("failed to read raw levels")
                print(f"count={now} delta={delta} A=? B=?")
        else:
            print(f"count={now} delta={delta}")

    enc.stop()
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
