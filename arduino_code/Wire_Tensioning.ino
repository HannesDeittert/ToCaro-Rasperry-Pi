#include <Wire.h>
#include <Adafruit_MotorShield.h>
#include <Arduino.h>

// Motor Shield V2
Adafruit_MotorShield AFMS = Adafruit_MotorShield();
Adafruit_DCMotor *m1, *m2, *m3;


void setup() {
  // put your setup code here, to run once:
  AFMS.begin(); // Motor Shield initialisieren
  m1=AFMS.getMotor(1); m2=AFMS.getMotor(2); m3=AFMS.getMotor(3);
  m1->setSpeed(0); m1->run(FORWARD);
  m2->setSpeed(20); m2->run(FORWARD);
  m3->setSpeed(0); m3->run(FORWARD);
}

void loop() {
  // put your main code here, to run repeatedly:

}
