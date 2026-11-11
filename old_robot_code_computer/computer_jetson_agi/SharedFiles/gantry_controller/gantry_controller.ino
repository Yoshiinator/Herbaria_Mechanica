const int X_STEP_PIN = 9,  X_DIR_PIN = 8;
const int Y_STEP_PIN = 7,  Y_DIR_PIN = 6;
const int Z_STEP_PIN = 5,  Z_DIR_PIN = 4;
const int EN_PIN = 2;

bool X_DIR_FLIP = false;
bool Y_DIR_FLIP = false;
bool Z_DIR_FLIP = true;

const int STEP_DELAY = 500;

const float X_STEPS_PER_CM = 10000.0 / 24.0;
const float Y_STEPS_PER_CM = 10000.0 / 24.0;
const float Z_STEPS_PER_CM = 10000.0 / 25.0;

long homeX = 0, homeY = 0, homeZ = 0;

void enableMotors(bool enable) {
  digitalWrite(EN_PIN, enable ? LOW : HIGH);
}

void setDir(int dirPin, bool dirFlip, bool dirHigh) {
  digitalWrite(dirPin, dirHigh ^ dirFlip ? HIGH : LOW);
  delay(2);
}

void doStep(int stepPin, int speedDelay) {
  digitalWrite(stepPin, HIGH);
  delayMicroseconds(speedDelay);
  digitalWrite(stepPin, LOW);
  delayMicroseconds(speedDelay);
}

void goTo(long dx, long dy, long dz) {
  if (dx == 0 && dy == 0 && dz == 0) return;

  enableMotors(false);
  delay(20);
  enableMotors(true);
  delay(20);

  if (dx != 0) {
    setDir(X_DIR_PIN, X_DIR_FLIP, dx > 0);
    delay(10);
    for (long i = 0; i < abs(dx); i++) doStep(X_STEP_PIN, STEP_DELAY);
    delay(5);
  }
  if (dy != 0) {
    setDir(Y_DIR_PIN, Y_DIR_FLIP, dy > 0);
    delay(10);
    for (long i = 0; i < abs(dy); i++) doStep(Y_STEP_PIN, STEP_DELAY);
    delay(5);
  }
  if (dz != 0) {
    setDir(Z_DIR_PIN, Z_DIR_FLIP, dz > 0);
    delay(10);
    for (long i = 0; i < abs(dz); i++) doStep(Z_STEP_PIN, STEP_DELAY);
    delay(5);
  }

  enableMotors(false);
  homeX += dx; homeY += dy; homeZ += dz;
}

void goHome() {
  // Move to physical home by going negative of current position
  long negX = -homeX;
  long negY = -homeY;
  long negZ = -homeZ;

  enableMotors(false);
  delay(20);
  enableMotors(true);
  delay(20);

  if (negX != 0) {
    setDir(X_DIR_PIN, X_DIR_FLIP, negX < 0);
    delay(10);
    for (long i = 0; i < abs(negX); i++) doStep(X_STEP_PIN, STEP_DELAY);
    delay(5);
  }
  if (negY != 0) {
    setDir(Y_DIR_PIN, Y_DIR_FLIP, negY < 0);
    delay(10);
    for (long i = 0; i < abs(negY); i++) doStep(Y_STEP_PIN, STEP_DELAY);
    delay(5);
  }
  if (negZ != 0) {
    setDir(Z_DIR_PIN, Z_DIR_FLIP, negZ < 0);
    delay(10);
    for (long i = 0; i < abs(negZ); i++) doStep(Z_STEP_PIN, STEP_DELAY);
    delay(5);
  }

  enableMotors(false);
  homeX = 0; homeY = 0; homeZ = 0;
  Serial.println("OK: homed");
}

float parseRelativeValue(const String& cmd, int startIdx) {
  int idx = startIdx;
  bool neg = false;
  if (idx < cmd.length() && cmd.charAt(idx) == '-') { neg = true; idx++; }
  else if (idx < cmd.length() && cmd.charAt(idx) == '+') { idx++; }
  float val = 0;
  bool foundDigit = false;
  while (idx < cmd.length() && (isdigit(cmd.charAt(idx)) || cmd.charAt(idx) == '.')) {
    if (cmd.charAt(idx) == '.') {
      idx++; float fraction = 0.1;
      while (idx < cmd.length() && isdigit(cmd.charAt(idx))) {
        val += (cmd.charAt(idx) - '0') * fraction; fraction *= 0.1; idx++;
      }
      break;
    }
    val = val * 10 + (cmd.charAt(idx) - '0'); idx++; foundDigit = true;
  }
  if (!foundDigit) return 999999.0;
  return neg ? -val : val;
}

void parseAndMove(const String& cmd) {
  long dx = 0, dy = 0, dz = 0;

  for (int i = 0; i < cmd.length(); i++) {
    char c = cmd.charAt(i);
    if (c == 'x' || c == 'X') {
      float v = parseRelativeValue(cmd, i + 1);
      if (v > 999998.0) { Serial.println("ERR: missing value after x"); return; }
      dx = v * X_STEPS_PER_CM;
      while (i < cmd.length() && (cmd.charAt(i) == 'x' || cmd.charAt(i) == 'X' || cmd.charAt(i) == '-' || cmd.charAt(i) == '+' || isdigit(cmd.charAt(i)) || cmd.charAt(i) == '.')) i++;
      i--;
    } else if (c == 'y' || c == 'Y') {
      float v = parseRelativeValue(cmd, i + 1);
      if (v > 999998.0) { Serial.println("ERR: missing value after y"); return; }
      dy = v * Y_STEPS_PER_CM;
      while (i < cmd.length() && (cmd.charAt(i) == 'y' || cmd.charAt(i) == 'Y' || cmd.charAt(i) == '-' || cmd.charAt(i) == '+' || isdigit(cmd.charAt(i)) || cmd.charAt(i) == '.')) i++;
      i--;
    } else if (c == 'z' || c == 'Z') {
      float v = parseRelativeValue(cmd, i + 1);
      if (v > 999998.0) { Serial.println("ERR: missing value after z"); return; }
      dz = v * Z_STEPS_PER_CM;
      while (i < cmd.length() && (cmd.charAt(i) == 'z' || cmd.charAt(i) == 'Z' || cmd.charAt(i) == '-' || cmd.charAt(i) == '+' || isdigit(cmd.charAt(i)) || cmd.charAt(i) == '.')) i++;
      i--;
    }
  }

  goTo(dx, dy, dz);
  Serial.println("OK: (" + String(homeX / X_STEPS_PER_CM, 2) + "," + String(homeY / Y_STEPS_PER_CM, 2) + "," + String(homeZ / Z_STEPS_PER_CM, 2) + ") cm");
}

void setup() {
  pinMode(X_STEP_PIN, OUTPUT); pinMode(X_DIR_PIN, OUTPUT);
  pinMode(Y_STEP_PIN, OUTPUT); pinMode(Y_DIR_PIN, OUTPUT);
  pinMode(Z_STEP_PIN, OUTPUT); pinMode(Z_DIR_PIN, OUTPUT);
  pinMode(EN_PIN, OUTPUT);
  enableMotors(false);
  Serial.begin(115200);
  while (!Serial) delay(10);
  Serial.println("Gantry Ready");
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();
    cmd.toLowerCase();

    if (cmd.length() == 0) return;
    else if (cmd == "pos") Serial.println("OK: (" + String(homeX / X_STEPS_PER_CM, 2) + "," + String(homeY / Y_STEPS_PER_CM, 2) + "," + String(homeZ / Z_STEPS_PER_CM, 2) + ") cm");
    else if (cmd == "reset") { homeX = 0; homeY = 0; homeZ = 0; Serial.println("OK: reset"); }
    else if (cmd == "home") { goHome(); }
    else parseAndMove(cmd);
  }
}