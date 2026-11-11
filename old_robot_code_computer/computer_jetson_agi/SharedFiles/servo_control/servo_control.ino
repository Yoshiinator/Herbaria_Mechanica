#include <Servo.h>

Servo servo[4];
const int servoPins[4] = {4, 5, 6, 7};

void setup() {
  Serial.begin(9600);
  for (int i = 0; i < 4; i++) {
    servo[i].attach(servoPins[i]);
    servo[i].write(0);
  }
}

void loop() {
  if (Serial.available()) {
    char cmd = Serial.read();

    if (cmd == 'S' || cmd == 's') {
      delay(10);
      String input = "";
      while (Serial.available() && input.length() < 20) {
        char c = Serial.read();
        if (c == '\n' || c == '\r') break;
        input += c;
      }

      int commaIndex = input.indexOf(',');
      int servoNum, angle;

      if (commaIndex != -1) {
        servoNum = input.substring(0, commaIndex).toInt();
        angle = input.substring(commaIndex + 1).toInt();
      } else {
        int spaceIndex = input.indexOf(' ');
        if (spaceIndex != -1) {
          servoNum = input.substring(0, spaceIndex).toInt();
          angle = input.substring(spaceIndex + 1).toInt();
        } else {
          return;
        }
      }

      servoNum -= 1;
      if (servoNum >= 0 && servoNum < 4 && angle >= 0 && angle <= 180) {
        servo[servoNum].write(angle);
        Serial.print("OK:");
        Serial.println(angle);
      }
    }
    else if (cmd == 'A' || cmd == 'a') {
      for (int i = 0; i < 4; i++) {
        Serial.print(i + 1);
        Serial.print(":");
        Serial.print(servo[i].read());
        if (i < 3) Serial.print(",");
      }
      Serial.println();
    }
    else if (cmd == 'R' || cmd == 'r') {
      for (int i = 0; i < 4; i++) servo[i].write(0);
      Serial.println("OK:reset");
    }
  }
}