// LED & Servo Controller - Arduino Mega on COM7
// LED on pin 13, Servos on pins 8,9,10,11 (manual PWM)
// Serial: 9600 baud

const int LED_PIN = 13;
const int SERVO_PINS[4] = {8, 9, 10, 11};
int angles[4] = {90, 90, 90, 90};

void setup() {
  Serial.begin(9600);
  while (!Serial) delay(10);
  
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);
  
  for (int i = 0; i < 4; i++) {
    pinMode(SERVO_PINS[i], OUTPUT);
    digitalWrite(SERVO_PINS[i], LOW);
  }
  
  delay(500);
  Serial.println("READY");
}

void setServoAngle(int pin, int angle) {
  angle = constrain(angle, 0, 180);
  int pw = map(angle, 0, 180, 1000, 2000);
  digitalWrite(pin, HIGH);
  delayMicroseconds(pw);
  digitalWrite(pin, LOW);
}

void handleCmd(String cmd) {
  cmd.trim();
  cmd.toUpperCase();
  
  if (cmd == "LEDON") { digitalWrite(LED_PIN, HIGH); Serial.println("OK LED ON"); }
  else if (cmd == "LEDOFF") { digitalWrite(LED_PIN, LOW); Serial.println("OK LED OFF"); }
  else if (cmd == "LEDTOGGLE") { digitalWrite(LED_PIN, !digitalRead(LED_PIN)); Serial.println("OK LED TOGGLE"); }
  else if (cmd == "PING") Serial.println("PONG");
  else if (cmd.startsWith("S")) {
    int comma = cmd.indexOf(',');
    if (comma > 1) {
      int num = cmd.substring(1, comma).toInt();
      int angle = cmd.substring(comma + 1).toInt();
      if (num >= 1 && num <= 4) {
        angles[num - 1] = constrain(angle, 0, 180);
        Serial.print("OK S"); Serial.print(num); Serial.print(","); Serial.println(angles[num - 1]);
      } else {
        Serial.println("ERR servo 1-4");
      }
    } else Serial.println("ERR format S<num>,<angle>");
  }
  else if (cmd == "A") {
    Serial.print("A:");
    for (int i = 0; i < 4; i++) { Serial.print(angles[i]); if (i < 3) Serial.print(","); }
    Serial.println();
  }
  else if (cmd == "G") { angles[0] = 100; Serial.println("OK G"); }
  else if (cmd == "L") { angles[0] = 0; Serial.println("OK L"); }
  else { Serial.print("ERR "); Serial.println(cmd); }
}

unsigned long lastPulse = 0;

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    handleCmd(cmd);
  }
  
  // Servo pulses at 50Hz
  if (micros() - lastPulse >= 20000) {
    lastPulse = micros();
    for (int i = 0; i < 4; i++) {
      setServoAngle(SERVO_PINS[i], angles[i]);
    }
  }
}
