# Arduino Pump Controller Integration Session

**Session ID:** `20260521_154703_6ea7987b`  
**Date:** May 21, 2026  
**Source:** Telegram  
**Model:** MiniMax-M2.1

---

## Goal

Integrate a new Arduino pump controller with the MATI Bot system to control 4 pumps with speed control and on/off functionality.

## Hardware Setup

- **Arduino:** Mega 2560 on COM5 (9600 baud)
- **Pumps:** 4 pumps connected on pins 8, 9, 10, 11 (PWM for speed control)
- **Existing integrations:**
  - COM3: Servo arm
  - COM4: Gantry (robot)

---

## Arduino Sketch (pump_controller.ino)

```cpp
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

char buffer[32];
uint8_t parseIndex = 0;

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
```

## API Endpoints

Integrated into the FastAPI server at `http://192.168.1.2:8000`:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/pump/{n}/set` | POST | Set pump speed (0-255) |
| `/api/pump/{n}/status` | GET | Get pump status |
| `/api/pump/all/status` | GET | Get all pumps status |
| `/api/pump/all/off` | POST | Turn all pumps off |
| `/api/howto` | GET | Full API documentation |

### Using Timed Pump

For timed operation, use:
```json
POST /api/pump/{n}/set_time
{"speed": 255, "time": 10}
```
- `speed`: 0-255
- `time`: seconds

---

## Results

✅ Successfully integrated:
- Arduino uploaded with pump sketch on COM5
- API running on port 8000
- 4 pumps controllable via HTTP endpoints

---

## Files

- **Sketch:** `/home/pairaiworkstation/maati-sketches/pump_controller/pump_controller.ino`
- **API on NUC:** `C:/Users/mahim/arduino_fastapi.py`