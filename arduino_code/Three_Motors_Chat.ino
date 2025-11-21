#include <Wire.h>
#include <Adafruit_MotorShield.h>
#include <EEPROM.h>
#include <Arduino.h>

// Encoder-Pins
const uint8_t ENC1_A=2, ENC1_B=3, ENC2_A=8, ENC2_B=9, ENC3_A=6, ENC3_B=7;

// Motor Shield V2
Adafruit_MotorShield AFMS = Adafruit_MotorShield();
Adafruit_DCMotor *m1, *m2, *m3;

// Encoder-Zähler
volatile long cnt1=0, cnt2=0, cnt3=0;

// Ziele/Parameter
float distance1=25, distance2=35, distance3=35;
int motorspeed1 = 30, motorspeed2 =40, motorspeed3 = 40;
float winch_diameter=7.0;
float hall_feedback_resolution=1050.0/2.0;
int steps1=0, steps2=0, steps3=0;
int delaytime = 100;

// EEPROM
struct Persist { long p1,p2,p3; uint16_t magic; };
const uint16_t MAGIC=0xBEEF;
bool loadEEPROM(long &o1,long &o2,long &o3){
  Persist p; EEPROM.get(0,p);
  if(p.magic==MAGIC){ o1=p.p1; o2=p.p2; o3=p.p3; return true; }
  return false;
}
void saveEEPROM(long o1,long o2,long o3){
  Persist p{ o1,o2,o3,MAGIC }; EEPROM.put(0,p);
}

// Zeitstempel je Motor
unsigned long lastChange1=0,lastChange2=0,lastChange3=0;
long lastSaved1=0,lastSaved2=0,lastSaved3=0;

// ISRs – jede liest nur ihren Encoder
void isrEnc1(){ bool a=digitalRead(ENC1_A), b=digitalRead(ENC1_B); (a==b)?cnt1++:cnt1--; lastChange1=millis(); }
void isrEnc2(){ bool a=digitalRead(ENC2_A), b=digitalRead(ENC2_B); (a==b)?cnt2++:cnt2--; lastChange2=millis(); }
void isrEnc3(){ bool a=digitalRead(ENC3_A), b=digitalRead(ENC3_B); (a==b)?cnt3++:cnt3--; lastChange3=millis(); }

void setup(){
  Serial.begin(115200);
  pinMode(ENC1_A,INPUT_PULLUP); pinMode(ENC1_B,INPUT_PULLUP);
  pinMode(ENC2_A,INPUT_PULLUP); pinMode(ENC2_B,INPUT_PULLUP);
  pinMode(ENC3_A,INPUT_PULLUP); pinMode(ENC3_B,INPUT_PULLUP);

  long o1=0,o2=0,o3=0;
  if(!loadEEPROM(o1,o2,o3)){ o1=o2=o3=0; saveEEPROM(o1,o2,o3); }
  noInterrupts(); cnt1=o1; cnt2=o2; cnt3=o3; interrupts();
  lastSaved1=cnt1; lastSaved2=cnt2; lastSaved3=cnt3;

  float stepsPerMM = hall_feedback_resolution / (2.0*PI*(winch_diameter/2.0));
  steps1 = int(distance1*stepsPerMM);
  steps2 = int(distance2*stepsPerMM);
  steps3 = int(distance3*stepsPerMM);

  // UNO R4: attachInterrupt auf A-Kanäle
  attachInterrupt(digitalPinToInterrupt(ENC1_A), isrEnc1, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ENC2_A), isrEnc2, CHANGE);
  attachInterrupt(digitalPinToInterrupt(ENC3_A), isrEnc3, CHANGE);

  AFMS.begin(); // Motor Shield initialisieren
  m1=AFMS.getMotor(1); m2=AFMS.getMotor(2); m3=AFMS.getMotor(3);
  m1->setSpeed(motorspeed1); m1->run(FORWARD);
  m2->setSpeed(motorspeed2); m2->run(FORWARD);
  m3->setSpeed(motorspeed3); m3->run(FORWARD);
}

void loop(){
  noInterrupts(); long c1=cnt1,c2=cnt2,c3=cnt3; interrupts();

  if(c1>=steps1) m1->run(BACKWARD); else if(c1<0) m1->run(FORWARD);
  if(c2>=steps2) m2->run(BACKWARD); else if(c2<0) m2->run(FORWARD);
  if(c3>=steps3) m3->run(BACKWARD); else if(c3<0) m3->run(FORWARD);

  const unsigned long T_IDLE=5000;
  if(millis()-lastChange1>T_IDLE && c1!=lastSaved1){ lastSaved1=c1; saveEEPROM(lastSaved1,lastSaved2,lastSaved3); }
  if(millis()-lastChange2>T_IDLE && c2!=lastSaved2){ lastSaved2=c2; saveEEPROM(lastSaved1,lastSaved2,lastSaved3); }
  if(millis()-lastChange3>T_IDLE && c3!=lastSaved3){ lastSaved3=c3; saveEEPROM(lastSaved1,lastSaved2,lastSaved3); }

  Serial.print("M1 "); Serial.print(c1); Serial.print('/'); Serial.print(steps1);
  Serial.print("  M2 "); Serial.print(c2); Serial.print('/'); Serial.print(steps2);
  Serial.print("  M3 "); Serial.print(c3); Serial.print('/'); Serial.println(steps3);


  delay(delaytime);
}

