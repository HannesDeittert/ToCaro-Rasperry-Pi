# Raspberry Pi code guide

Raspberry Pi control code for the Adafruit Motor Shield V2.3 (PCA9685 + TB6612) with Hall encoders.

## Layout
- `src/tocado_pi/config.py` – config dataclasses (pins, I2C, motion limits).
- `src/tocado_pi/hardware.py` – hardware adapters (MotorKit driver + encoder GPIO reader).
- `src/tocado_pi/motor_control.py` – simple move/spin controls with limits and stop.
- `src/tocado_pi/cli.py` – CLI entrypoint (`spin`, `move`).
- `scripts/smoke_test.py` – minimal spin test helper.
- `scripts/debug_motor_shield.py` – interactive checker for supply, all 4 channels, and encoder ticks.
- `scripts/motor_web_ui.py` – small web UI to view encoder counts and jog one or several motor channels.
- `tests/` – pytest unit tests with fakes (no hardware needed).
- `requirements.txt` / `dev-requirements.txt` – runtime vs. dev deps.

## Quickstart (on the Pi)
```
cd raspberry_pi
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r dev-requirements.txt
```

Check I2C for the Motor Shield (expect address 0x60):
```
i2cdetect -y 1
```

Run tests (offline):
```
pytest
```

CLI examples (set your encoder GPIO BCM pins):
```
PYTHONPATH=src python -m tocado_pi.cli spin --duty 0.3 --seconds 2 --pin-a <BCM_A> --pin-b <BCM_B> --motor-channel 1
PYTHONPATH=src python -m tocado_pi.cli move --target 500 --duty 0.5 --pin-a <BCM_A> --pin-b <BCM_B>
```

Smoke test script (short spin):
```
PYTHONPATH=src python scripts/smoke_test.py --duty 0.4 --seconds 2 --pin-a <BCM_A> --pin-b <BCM_B>
```

Debug the shield (pulses M1–M4, prompts for terminal observations, reports encoder counts):
```
PYTHONPATH=src python scripts/debug_motor_shield.py --duty 1.0 --seconds 1 --pin-a <BCM_A> --pin-b <BCM_B>
```

Web UI (encoder readout + forward/reverse/brake controls):
```
PYTHONPATH=src python scripts/motor_web_ui.py --motor-channel 1 --pin-a <BCM_A> --pin-b <BCM_B>
# Multi-motor example with three encoders:
# PYTHONPATH=src python scripts/motor_web_ui.py --motor 1:17:27 --motor 2:22:23 --motor 3:24:25
# Then open http://<pi-ip>:8000 in your browser.
```

## Wiring notes
- Motor Shield uses only I2C to the Pi; motors on M1–M4 terminals with separate motor supply.
- Encoders: treat A/B as open-collector; power at 3.3 V, GND common, use Pi pull-ups (`INPUT_PULLUP` default in code). Pi GPIOs are not 5 V tolerant; if you must use 5 V on the encoder side, add level shifting or pull-ups to 3.3 V instead.

## Files and intent
- `hardware.py`: isolates MotorKit import and GPIO usage; supports injecting fakes for tests.
- `motor_control.py`: moves toward a target encoder count with bounds, timeout, stop flag; spins for a duration.
- `cli.py`: convenient manual control without writing code; logs at INFO by default.
- `tests/test_motor_control.py`: covers move/timeout/spin behavior using fake motor + encoder.
