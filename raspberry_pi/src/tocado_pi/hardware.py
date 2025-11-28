"""
Hardware adapters for the Adafruit Motor Shield V2.3 and quadrature encoders.

The goal is to keep hardware-specific code isolated so the controller can be
unit-tested with fakes. Imports of `adafruit_motorkit` and `RPi.GPIO` are kept
lazy to avoid failures on non-Pi development machines.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Optional

from .config import EncoderConfig, MotorShieldConfig

LOG = logging.getLogger(__name__)


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


class MotorDriver:
    """
    Thin wrapper around an Adafruit DC motor to normalize throttle/brake calls.
    Keeps the rest of the code independent from the underlying library.
    """

    def __init__(self, motor, name: str = "motor"):
        self._motor = motor
        self.name = name

    def set_throttle(self, duty: float) -> None:
        """
        Set normalized duty cycle: -1..1 where sign controls direction.
        """
        duty = _clamp(duty)
        LOG.debug("%s throttle -> %.3f", self.name, duty)
        self._motor.throttle = duty

    def brake(self) -> None:
        """Active brake the motor."""
        LOG.debug("%s brake", self.name)
        self._motor.throttle = 0.0

    def release(self) -> None:
        """Release (coast) the motor."""
        LOG.debug("%s release", self.name)
        self._motor.throttle = None


def build_motorkit_driver(cfg: MotorShieldConfig, *, i2c=None) -> MotorDriver:
    """
    Instantiate a MotorDriver using adafruit-circuitpython-motorkit.

    The optional `i2c` parameter allows passing a pre-created I2C bus.
    """
    try:
        from adafruit_motorkit import MotorKit
    except ImportError as exc:  # pragma: no cover - exercised on hardware
        raise RuntimeError(
            "adafruit-circuitpython-motorkit is not available; "
            "install requirements and run on a Raspberry Pi."
        ) from exc

    kit = MotorKit(address=cfg.i2c_address, i2c=i2c)
    motor_map = {
        1: kit.motor1,
        2: kit.motor2,
        3: kit.motor3,
        4: kit.motor4,
    }
    motor = motor_map.get(cfg.motor_channel)
    if motor is None:
        raise ValueError(f"motor_channel must be 1-4, got {cfg.motor_channel}")
    return MotorDriver(motor, name=f"motor{cfg.motor_channel}")


class EncoderReader:
    """
    Quadrature encoder reader driven by GPIO edge interrupts on channel A.

    Expected wiring:
    - Encoder powered at 3.3 V (recommended to keep GPIO safe), common GND.
    - A/B connected to BCM pins configured with pull-ups (default).
    - If encoder must be at 5 V: use level shifting or pull-ups to 3.3 V.
    """

    def __init__(
        self,
        cfg: EncoderConfig,
        *,
        gpio=None,
        name: str = "encoder",
    ) -> None:
        self.cfg = cfg
        self.name = name
        self._gpio = gpio  # allows injecting fake GPIO in tests
        self._count = 0
        self._lock = threading.Lock()
        self._started = False

    def _ensure_gpio(self):
        if self._gpio:
            return self._gpio
        try:
            import RPi.GPIO as GPIO  # type: ignore
        except ImportError as exc:  # pragma: no cover - exercised on hardware
            raise RuntimeError(
                "RPi.GPIO not available; run on Raspberry Pi or inject a GPIO stub."
            ) from exc
        self._gpio = GPIO
        return GPIO

    def start(self) -> None:
        """
        Configure GPIO pins and register an interrupt on channel A.
        Call once before reading; safe to call multiple times.
        """
        if self._started:
            return
        GPIO = self._ensure_gpio()
        GPIO.setmode(GPIO.BCM)
        pull = GPIO.PUD_UP if self.cfg.pull_up else GPIO.PUD_OFF
        GPIO.setup(self.cfg.pin_a, GPIO.IN, pull_up_down=pull)
        GPIO.setup(self.cfg.pin_b, GPIO.IN, pull_up_down=pull)
        kwargs = {}
        if self.cfg.debounce_ms and self.cfg.debounce_ms > 0:
            kwargs["bouncetime"] = self.cfg.debounce_ms
        GPIO.add_event_detect(
            self.cfg.pin_a,
            GPIO.BOTH,
            callback=self._handle_edge,
            **kwargs,
        )
        self._started = True
        LOG.info("%s listening on A=%s B=%s", self.name, self.cfg.pin_a, self.cfg.pin_b)

    def stop(self) -> None:
        if not self._started:
            return
        GPIO = self._ensure_gpio()
        if GPIO.getmode() is not None:
            GPIO.remove_event_detect(self.cfg.pin_a)
        self._started = False

    def _handle_edge(self, channel) -> None:
        GPIO = self._ensure_gpio()
        a_state = GPIO.input(self.cfg.pin_a)
        b_state = GPIO.input(self.cfg.pin_b)
        delta = 1 if a_state == b_state else -1
        with self._lock:
            self._count += delta

    def read(self) -> int:
        """
        Return the latest signed count.
        """
        with self._lock:
            return int(self._count)

    def reset(self, value: int = 0) -> None:
        with self._lock:
            self._count = value

    # Convenience for offline tests without GPIO callbacks
    def simulate_ticks(self, delta: int) -> None:
        with self._lock:
            self._count += delta
