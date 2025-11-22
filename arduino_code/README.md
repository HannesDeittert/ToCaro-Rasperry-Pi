# Arduino sketches overview

Reference notes for the existing Arduino implementations that drive the Adafruit Motor Shield V2.3 (PCA9685 + dual TB6612). This summarizes wiring, data flow, and behavior to inform the Raspberry Pi port.

## Wiring / pinout
- Motor Shield V2.3 on I2C (addr 0x60 by default) using Arduino SDA/SCL.
- Motors: M1, M2, M3 outputs on the shield (no M4 in current code).
- Hall encoders (quadrature) per motor:  
  - Motor 1: `ENC1_A = 2`, `ENC1_B = 3`  
  - Motor 2: `ENC2_A = 8`, `ENC2_B = 9`  
  - Motor 3: `ENC3_A = 6`, `ENC3_B = 7`
- Interrupts are attached on the A channels only (`CHANGE` on ENC*_A). ISR reads A and B to determine direction.
- Pull-ups: all encoder inputs use `INPUT_PULLUP`.

## Sketch summaries
### Three_Motors_Chat.ino (main logic)
- Initializes three DC motors and three quadrature encoders.
- Persisted position per motor in EEPROM as signed long; guarded by magic value `0xBEEF`.
- Encoder ISR per motor:
  - Runs on A channel edges, reads A/B to increment or decrement a volatile count.
  - Updates `lastChange*` timestamps used to decide when to write EEPROM.
- Setup:
  - Loads encoder counts from EEPROM (or zeros and writes defaults).
  - Computes target steps from desired travel distances:  
    `stepsPerMM = hall_feedback_resolution / (2π * (winch_diameter/2))`  
    Targets: distance1=25mm, distance2=35mm, distance3=35mm.
  - Motors: speeds set to 30/40/40; initial direction FORWARD.
- Loop behavior:
  - Copies volatile counts atomically.
  - Direction control per motor: if count >= steps target, run BACKWARD; if count < 0, run FORWARD. This creates a back-and-forth motion between 0 and the target count.
  - Every `T_IDLE = 5000ms`, if a motor’s count changed since last save, writes all three counts to EEPROM.
  - Prints counts vs targets for all motors, then delays `delaytime = 100ms`.

### Wire_Tensioning.ino
- Minimal setup to spin only motor 2 at speed 20 (M1 and M3 are stopped).
- No encoder usage; likely a quick tensioning/smoke test.

### EEPROM_Clear.ino
- Utility to clear the entire EEPROM to `0xFF` via `EEPROM.update` loop; prints progress over Serial.

## Behavioral notes / assumptions
- Control loop is open-loop on PWM speed with closed-loop only on position count bounds (no PID). The motor reverses at 0 and at the computed step limit.
- Encoder resolution constant: `hall_feedback_resolution = 1050/2` (counts per revolution / 2?). Winch diameter = 7.0 units (likely mm).
- Persistence occurs only after 5s of inactivity per motor to reduce EEPROM wear.
- Serial output at 115200 baud: simple telemetry of counts/targets.

## Raspberry Pi porting considerations
- Replace Adafruit_MotorShield C++ library with `adafruit-circuitpython-motorkit` (PCA9685 + TB6612) over I2C.
- Use GPIO edge detection for encoder A channels; read B to determine direction. Apply debouncing if needed.
- Provide configurable pin mapping, winch diameter, encoder resolution, speed/limit values.
- Add safety: max runtime/travel, faulted motor disable, optional soft-start on speed changes.
- Mirror EEPROM persistence via a JSON/state file (or skip) to preserve position across reboots if required.

These notes should keep Arduino intent visible while we build the Raspberry Pi implementation.
