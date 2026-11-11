/*
  Pump Controller Sketch
  Pins: 8, 9, 10, 11 (PWM for speed control)
  Serial: 9600 baud
  Commands:
    P<n>,<speed> - Pump n (1-4) ON at speed (0-255)
    P<n>,0      - Pump n OFF
    P<n>?      - Query pump n status
    ALL?,      - Query all pumps
*/

#define PUMP1_PIN 8
#define PUMP2_PIN 9
#define PUMP3_PIN 10
#define PUMP4_PIN 11

const uint8_t pumpPins[4] = {PUMP1_PIN, PUMP2_PIN, PUMP3_PIN, PUMP4_PIN};
uint8_t pumpSpeeds[4] = {0, 0, 0, 0};

// Parser variables
char buffer[32];
uint8_t parseIndex = 0;

void setup() {
  for (int i = 0; i < 4; i++) {
    pinMode(pumpPins[i], OUTPUT);
    digitalWrite(pumpPins[i], LOW);
  }
  Serial.begin(9600);
}

void loop() {
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      processCommand();
      parseIndex = 0;
    } else {
      buffer[parseIndex++] = c;
      if (parseIndex >= 31) parseIndex = 30;
    }
  }
}

void processCommand() {
  buffer[parseIndex] = '\0';
  parseIndex = 0;
  
  // Parse: P<num>,<value>
  if (buffer[0] == 'P' && buffer[1] >= '1' && buffer[1] <= '4') {
    uint8_t pumpNum = buffer[1] - '1'; // 0-3
    
    if (buffer[2] == '?') {
      // Query pump status
      Serial.print("P");
      Serial.print(pumpNum + 1);
      Serial.print(":");
      Serial.println(pumpSpeeds[pumpNum]);
    } 
    else if (buffer[2] == ',') {
      // Set pump speed
      uint8_t speed = atoi(&buffer[3]);
      speed = min(speed, (uint8_t)255);
      pumpSpeeds[pumpNum] = speed;
      analogWrite(pumpPins[pumpNum], speed);
      Serial.print("P");
      Serial.print(pumpNum + 1);
      Serial.print(":");
      Serial.println(speed);
    }
  }
  else if (strncmp(buffer, "ALL?", 4) == 0) {
    // Query all pumps
    Serial.print("ALL:");
    for (int i = 0; i < 4; i++) {
      Serial.print(pumpSpeeds[i]);
      if (i < 3) Serial.print(",");
    }
    Serial.println();
  }
  else if (strncmp(buffer, "OFF", 3) == 0) {
    // Turn off all pumps
    for (int i = 0; i < 4; i++) {
      pumpSpeeds[i] = 0;
      digitalWrite(pumpPins[i], LOW);
    }
    Serial.println("ALL:OFF");
  }
}