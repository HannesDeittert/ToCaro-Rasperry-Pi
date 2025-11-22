"""
High-level motor control primitives built on top of MotorDriver + EncoderReader.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Optional

from .config import MotorConfig
from .hardware import MotorDriver, EncoderReader

LOG = logging.getLogger(__name__)


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass
class MoveResult:
    target: int
    final_count: int
    elapsed_s: float
    reached: bool


class MotorController:
    """
    Minimal position and motion helpers for a single DC motor.

    Design notes:
    - Uses simple open-loop duty + encoder feedback for stop conditions.
    - Enforces bounds (min/max count) and a runtime timeout.
    - Can be exercised with fakes by injecting motor, encoder, now/sleep.
    """

    def __init__(
        self,
        motor: MotorDriver,
        encoder: EncoderReader,
        cfg: MotorConfig,
        *,
        now: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.motor = motor
        self.encoder = encoder
        self.cfg = cfg
        self._now = now
        self._sleep = sleep
        self._stop_flag = False

    def emergency_stop(self) -> None:
        self._stop_flag = True
        self.motor.brake()
        LOG.warning("%s emergency stop triggered", self.cfg.name)

    def spin_for(self, duty: float, seconds: float) -> MoveResult:
        """
        Spin at a fixed duty cycle for a duration (no position target).
        """
        duty = _clamp(duty)
        start = self._now()
        deadline = start + min(seconds, self.cfg.limits.max_runtime_s)
        LOG.info("%s spin_for duty=%.2f duration=%.2fs", self.cfg.name, duty, seconds)
        self.motor.set_throttle(duty)
        while self._now() < deadline and not self._stop_flag:
            self._sleep(self.cfg.limits.poll_interval_s)
        self.motor.brake()
        end_count = self.encoder.read()
        elapsed = self._now() - start
        return MoveResult(target=end_count, final_count=end_count, elapsed_s=elapsed, reached=not self._stop_flag)

    def move_to_count(
        self,
        target_count: int,
        *,
        duty: Optional[float] = None,
        timeout_s: Optional[float] = None,
    ) -> MoveResult:
        """
        Move until the encoder count reaches target_count within tolerance.

        Stops on:
        - reaching target within tolerance
        - timeout
        - bounds violation
        - emergency_stop flag
        """
        limits = self.cfg.limits
        if target_count < limits.min_count or target_count > limits.max_count:
            raise ValueError(f"target_count {target_count} is outside [{limits.min_count}, {limits.max_count}]")

        duty = abs(duty if duty is not None else self.cfg.shield.default_duty)
        duty = _clamp(duty, 0.0, 1.0)

        start_count = self.encoder.read()
        direction = 1 if target_count >= start_count else -1
        timeout = timeout_s if timeout_s is not None else limits.max_runtime_s
        start_time = self._now()
        deadline = start_time + timeout

        LOG.info(
            "%s move_to target=%s from=%s duty=%.2f dir=%+d timeout=%.1fs",
            self.cfg.name,
            target_count,
            start_count,
            duty,
            direction,
            timeout,
        )

        self.motor.set_throttle(direction * duty)
        reached = False
        while not self._stop_flag:
            current = self.encoder.read()
            if _within_tolerance(current, target_count, limits.stop_tolerance):
                reached = True
                break
            if self._now() > deadline:
                LOG.warning("%s move_to timeout current=%s target=%s", self.cfg.name, current, target_count)
                break
            if current < limits.min_count or current > limits.max_count:
                LOG.error(
                    "%s count %s exceeded limits [%s,%s]; braking",
                    self.cfg.name,
                    current,
                    limits.min_count,
                    limits.max_count,
                )
                break
            self._sleep(limits.poll_interval_s)

        self.motor.brake()
        elapsed = self._now() - start_time
        final_count = self.encoder.read()
        if not reached and self._stop_flag:
            LOG.warning("%s move_to interrupted by stop", self.cfg.name)
        return MoveResult(target=target_count, final_count=final_count, elapsed_s=elapsed, reached=reached)


def _within_tolerance(value: int, target: int, tol: int) -> bool:
    if tol <= 0:
        return value == target
    return target - tol <= value <= target + tol
