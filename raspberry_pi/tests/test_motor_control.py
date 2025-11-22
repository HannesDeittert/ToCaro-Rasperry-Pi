import math

import pytest

from tocado_pi.config import EncoderConfig, MotorConfig, MotionLimits, MotorShieldConfig
from tocado_pi.hardware import MotorDriver
from tocado_pi.motor_control import MotorController


class DummyMotor:
    def __init__(self):
        self.history = []
        self._throttle = None

    @property
    def throttle(self):
        return self._throttle

    @throttle.setter
    def throttle(self, value):
        self._throttle = value
        self.history.append(value)


class FakeEncoder:
    def __init__(self, count=0):
        self.count = count

    def read(self):
        return self.count

    def bump(self, delta):
        self.count += delta


class TimeStub:
    def __init__(self, encoder: FakeEncoder | None = None, step: int = 1):
        self.t = 0.0
        self.encoder = encoder
        self.step = step

    def now(self):
        return self.t

    def sleep(self, dt):
        self.t += dt
        if self.encoder:
            self.encoder.bump(self.step)


def make_controller(
    *,
    encoder_start=0,
    limits: MotionLimits | None = None,
    time_stub: TimeStub | None = None,
):
    motor = MotorDriver(DummyMotor(), name="test-motor")
    encoder = FakeEncoder(encoder_start)
    limits = limits or MotionLimits(max_runtime_s=1.0, poll_interval_s=0.01, stop_tolerance=1)
    cfg = MotorConfig(
        shield=MotorShieldConfig(default_duty=0.5),
        encoder=EncoderConfig(pin_a=17, pin_b=27),
        limits=limits,
        name="test",
    )
    stub = time_stub or TimeStub(encoder=encoder, step=1)
    ctrl = MotorController(motor, encoder, cfg, now=stub.now, sleep=stub.sleep)
    return ctrl, motor, encoder, stub


def test_move_reaches_target_forward():
    ctrl, motor, encoder, stub = make_controller(encoder_start=0)

    result = ctrl.move_to_count(5, duty=0.6)

    assert result.reached is True
    assert result.final_count >= 4
    assert math.isclose(motor._motor.history[0], 0.6, rel_tol=1e-5)  # initial throttle forward
    assert motor._motor.history[-1] == 0.0  # brake at the end


def test_move_respects_timeout_when_stalled():
    limits = MotionLimits(max_runtime_s=0.05, poll_interval_s=0.01, stop_tolerance=0)
    stub = TimeStub(encoder=None, step=0)  # encoder never advances
    ctrl, motor, encoder, stub = make_controller(encoder_start=0, limits=limits, time_stub=stub)

    result = ctrl.move_to_count(3, duty=0.5, timeout_s=0.05)

    assert result.reached is False
    assert result.final_count == 0
    assert result.elapsed_s >= 0.05
    assert motor._motor.history[-1] == 0.0


def test_spin_for_runs_for_duration():
    limits = MotionLimits(max_runtime_s=0.2, poll_interval_s=0.01)
    stub = TimeStub()
    ctrl, motor, encoder, stub = make_controller(limits=limits, time_stub=stub)

    result = ctrl.spin_for(0.4, seconds=0.1)

    assert result.reached is True
    assert result.elapsed_s >= 0.1
    assert motor._motor.history[0] == 0.4
    assert motor._motor.history[-1] == 0.0
