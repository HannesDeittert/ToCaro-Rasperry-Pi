"""
Configuration helpers for Raspberry Pi motor control.

Quick wiring reference (defaults mirror the Arduino-side intent):
- Motor Shield V2.3 on I2C address 0x60 (bus 1 on Pi).
- Motor channel defaults to M1; change to 2/3/4 as needed.
- Encoder pins: supply encoder with 3.3 V, tie GNDs together, connect
  A/B to Pi GPIOs (BCM numbers) with pull-ups (code sets INPUT_PULLUP).
  Pi GPIOs are *not* 5 V tolerant; keep signals at 3.3 V or level-shift.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class EncoderConfig:
    """Quadrature encoder wiring."""

    pin_a: int
    pin_b: int
    pull_up: bool = True
    debounce_ms: int = 2  # hardware debouncing is preferred; this is a fallback


@dataclass
class MotorShieldConfig:
    """Adafruit Motor Shield V2.3 settings."""

    i2c_address: int = 0x60
    i2c_busnum: int = 1
    motor_channel: int = 1  # 1-4 on the shield
    default_duty: float = 0.5  # normalized throttle (-1..1 sign controls direction)


@dataclass
class MotionLimits:
    """Bounds and safeguards for motion commands."""

    min_count: int = 0
    max_count: int = 5_000
    max_runtime_s: float = 10.0
    poll_interval_s: float = 0.01
    stop_tolerance: int = 0  # acceptable error around target


@dataclass
class MotorConfig:
    """Combined configuration used by the controller."""

    shield: MotorShieldConfig
    encoder: EncoderConfig
    limits: MotionLimits
    name: str = "motor1"
    steps_per_mm: Optional[float] = None  # optional helper; not required for control
