"""
Interactive debug script for the Adafruit Motor Shield V2.3 on Raspberry Pi.

It checks motor supply, pulses all four channels briefly, and reports encoder
activity plus any terminal voltage observations you enter.

Examples:
    PYTHONPATH=src python scripts/debug_motor_shield.py --duty 1.0 --seconds 1
    PYTHONPATH=src python scripts/debug_motor_shield.py --supply-voltage 5.1 --no-prompt-terminals
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from dataclasses import dataclass
from typing import Optional

from tocado_pi.config import EncoderConfig
from tocado_pi.hardware import EncoderReader, MotorDriver

LOG = logging.getLogger(__name__)


def _safe_input(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""


@dataclass
class ChannelResult:
    channel: int
    encoder_before: int
    encoder_after: int
    observation: Optional[str]
    error: Optional[str]

    @property
    def encoder_delta(self) -> int:
        return self.encoder_after - self.encoder_before

    @property
    def responded(self) -> bool:
        if self.error:
            return False
        if self.encoder_delta != 0:
            return True
        if self.observation:
            try:
                return float(self.observation) > 0.2
            except ValueError:
                return True
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Debug helper for Motor Shield V2.3 on Raspberry Pi")
    parser.add_argument("--pin-a", type=int, default=17, help="BCM pin for encoder A")
    parser.add_argument("--pin-b", type=int, default=27, help="BCM pin for encoder B")
    parser.add_argument("--no-pullup", action="store_true", help="Disable pull-ups on encoder pins")
    parser.add_argument("--i2c-address", type=lambda x: int(x, 0), default=0x60, help="I2C address of Motor Shield")
    parser.add_argument("--duty", type=float, default=1.0, help="Pulse duty cycle -1..1")
    parser.add_argument("--seconds", type=float, default=1.0, help="Pulse duration per channel")
    parser.add_argument("--rest-seconds", type=float, default=1.0, help="Rest between pulses")
    parser.add_argument("--min-supply", type=float, default=4.5, help="Minimum acceptable motor supply voltage")
    parser.add_argument("--supply-voltage", type=float, default=None, help="Measured motor supply at POWER +/- (skip prompt)")
    parser.add_argument("--skip-supply-check", action="store_true", help="Do not prompt for motor supply measurement")
    parser.add_argument("--no-prompt-terminals", action="store_true", help="Do not prompt for MxA/MxB observations")
    parser.add_argument("--force", action="store_true", help="Continue even if supply looks too low")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return parser


def verify_supply(args: argparse.Namespace) -> tuple[Optional[float], bool]:
    if args.skip_supply_check:
        LOG.warning("Skipping motor-supply check at user request")
        return None, True

    measured: Optional[float] = args.supply_voltage
    if measured is None:
        user = _safe_input(
            "Measure motor supply at shield POWER +/- with a meter. "
            "Enter voltage in V (blank to skip): "
        ).strip()
        if user:
            try:
                measured = float(user)
            except ValueError:
                LOG.warning("Could not parse '%s' as a voltage; continuing without a value", user)

    if measured is None:
        LOG.warning("Motor supply voltage not provided; results may be ambiguous")
        return None, True

    LOG.info("Motor supply reported: %.2f V", measured)
    ok = measured >= args.min_supply
    if not ok:
        LOG.error("Supply %.2f V is below minimum %.2f V", measured, args.min_supply)
    return measured, ok


def build_motor_drivers(address: int) -> dict[int, MotorDriver]:
    try:
        from adafruit_motorkit import MotorKit  # type: ignore
    except ImportError as exc:  # pragma: no cover - hardware import
        raise RuntimeError(
            "adafruit-circuitpython-motorkit not available; install requirements on the Pi."
        ) from exc

    kit = MotorKit(address=address)
    motors = {}
    for channel in range(1, 5):
        motor = getattr(kit, f"motor{channel}", None)
        if motor is None:
            raise RuntimeError(f"motor{channel} not available from MotorKit")
        motors[channel] = MotorDriver(motor, name=f"motor{channel}")
    return motors


def pulse_channel(
    channel: int,
    driver: MotorDriver,
    encoder: EncoderReader,
    *,
    duty: float,
    seconds: float,
    prompt_terminals: bool,
) -> ChannelResult:
    LOG.info("=== Channel M%dA/M%dB ===", channel, channel)
    encoder_before = encoder.read()
    observation: Optional[str] = None
    error: Optional[str] = None

    if prompt_terminals:
        _safe_input(
            f"Place meter probes on M{channel}A/M{channel}B. "
            f"Press Enter to fire a {seconds:.1f}s pulse at duty {duty:.2f}..."
        )

    try:
        driver.set_throttle(duty)
        time.sleep(seconds)
    except Exception as exc:  # pragma: no cover - hardware path
        error = str(exc)
        LOG.error("Channel %d error during pulse: %s", channel, exc)
    finally:
        try:
            driver.brake()
        except Exception as exc:  # pragma: no cover - hardware path
            LOG.error("Failed to brake channel %d: %s", channel, exc)
            if not error:
                error = f"brake failed: {exc}"

    if prompt_terminals:
        obs = _safe_input(
            f"Observed terminal voltage on M{channel} (e.g., 0 / 5.1 / toggling / none): "
        ).strip()
        observation = obs or None

    encoder_after = encoder.read()
    LOG.info(
        "Channel %d encoder delta: %+d (before=%d after=%d)",
        channel,
        encoder_after - encoder_before,
        encoder_before,
        encoder_after,
    )
    return ChannelResult(
        channel=channel,
        encoder_before=encoder_before,
        encoder_after=encoder_after,
        observation=observation,
        error=error,
    )


def summarize(results: list[ChannelResult], supply_v: Optional[float], min_supply: float) -> None:
    responded = [r for r in results if r.responded]
    silent = [r for r in results if not r.responded]

    print("\n=== Summary ===")
    if supply_v is None:
        print(f"- Motor supply: not provided (min expected {min_supply:.1f} V)")
    else:
        status = "ok" if supply_v >= min_supply else "LOW"
        print(f"- Motor supply: {supply_v:.2f} V ({status}, min {min_supply:.1f} V)")

    for r in results:
        status = "response" if r.responded else "no-response"
        detail = f"encoder Δ={r.encoder_delta}"
        if r.observation:
            detail += f", observed={r.observation}"
        if r.error:
            detail += f", error={r.error}"
        print(f"- M{r.channel}: {status} ({detail})")

    print("\nLikely next checks:")
    if supply_v is not None and supply_v < min_supply:
        print("* Motor supply below expectation: verify POWER +/- wiring and fuse; keep green LED lit.")
    if not responded:
        print("* No channels produced movement/voltage: confirm motor supply present, shield seated, and TB6612/power jumper intact.")
    elif silent:
        silent_str = ", ".join(f"M{r.channel}" for r in silent)
        print(f"* {silent_str} quiet while others responded: check those screw terminals, cables, and TB6612 outputs for damage.")
    if any(r.encoder_delta == 0 for r in results):
        print("* Encoder stayed at 0: verify encoder wiring, 3.3 V power, and pull-ups on the Pi pins.")
    print("* If terminal voltage stays at 0 V despite supply being good: suspect driver enable/PCA9685 or I2C control path.")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level))

    supply_v, supply_ok = verify_supply(args)
    if not supply_ok and not args.force:
        print("Supply below threshold; re-run with a healthy motor supply or add --force to proceed anyway.")
        return 2

    try:
        drivers = build_motor_drivers(args.i2c_address)
    except Exception as exc:  # pragma: no cover - hardware path
        LOG.error("Failed to initialize MotorKit: %s", exc)
        return 2

    encoder_cfg = EncoderConfig(pin_a=args.pin_a, pin_b=args.pin_b, pull_up=not args.no_pullup)
    encoder = EncoderReader(encoder_cfg, name="debug-encoder")
    encoder.start()

    results: list[ChannelResult] = []
    try:
        for channel in sorted(drivers):
            results.append(
                pulse_channel(
                    channel,
                    drivers[channel],
                    encoder,
                    duty=args.duty,
                    seconds=args.seconds,
                    prompt_terminals=not args.no_prompt_terminals,
                )
            )
            time.sleep(args.rest_seconds)
    finally:
        for driver in drivers.values():
            driver.brake()
        encoder.stop()

    summarize(results, supply_v, args.min_supply)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
