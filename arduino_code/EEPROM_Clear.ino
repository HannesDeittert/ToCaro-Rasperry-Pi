#include <EEPROM.h>

void setup() {
  Serial.begin(115200);
  Serial.println("EEPROM wird gelöscht...");

  for (int i = 0; i < EEPROM.length(); i++) {
    EEPROM.update(i, 0xFF);   // oder 0, wenn du lieber nullen willst
  }

  Serial.println("EEPROM komplett gelöscht!");
}

void loop() {
  // nichts mehr zu tun
}
