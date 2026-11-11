/*
  Arduino MEGA + DM542T (XYZ) — Serial coordinate control
  Wiring (PUL+ = STEP, DIR+ = DIR):
    X: STEP=6,  DIR=7
    Y: STEP=8,  DIR=9
    Z: STEP=10, DIR=11
  PUL- and DIR- to Arduino GND (common ground with 48V PSU).
*/

//// ---------- USER CALIBRATION ----------
const float X_STEPS_PER_MM = 10000.0 / 249.0;  // ≈ 40.16064
const float Y_STEPS_PER_MM = 8000.0  / 200.0;  // = 40.0
const float Z_STEPS_PER_MM = 400.0;            // <-- set this to YOUR Z calibration
//// -------------------------------------

// Speed/shape of pulses
const int   stepPeriodMicros  = 1000; // whole tick period (lower = faster). Try 800–2000
const int   pulseWidthMicros  = 5;    // DM542T needs ≥5 µs high

// Pins (MEGA)
const int X_STEP_PIN = 9,  X_DIR_PIN = 8;
const int Y_STEP_PIN = 7,  Y_DIR_PIN = 6;
const int Z_STEP_PIN = 5, Z_DIR_PIN = 4;

// Software position (mm)
float posXmm = 0.0, posYmm = 0.0, posZmm = 0.0;

void setup() {
  Serial.begin(115200);

  pinMode(X_STEP_PIN, OUTPUT); pinMode(X_DIR_PIN, OUTPUT);
  pinMode(Y_STEP_PIN, OUTPUT); pinMode(Y_DIR_PIN, OUTPUT);
  pinMode(Z_STEP_PIN, OUTPUT); pinMode(Z_DIR_PIN, OUTPUT);

  digitalWrite(X_STEP_PIN, LOW);
  digitalWrite(Y_STEP_PIN, LOW);
  digitalWrite(Z_STEP_PIN, LOW);

  delay(500);
  Serial.println(F("XYZ Gantry Ready."));
  Serial.println(F("Send like:  X100 Y50 Z10   (mm)"));
  Serial.println(F("Only specify axes you want to change, e.g.  X0  or  Y120"));
}

void loop() {
  if (!Serial.available()) return;

  String line = Serial.readStringUntil('\n');
  line.trim();
  if (line.length() == 0) return;

  // Defaults: keep current unless provided
  float tx = posXmm, ty = posYmm, tz = posZmm;

  // crude parsing for X/Y/Z numbers anywhere in the line
  parseAxis(line, 'X', tx);
  parseAxis(line, 'Y', ty);
  parseAxis(line, 'Z', tz);

  Serial.print(F("Move to  X=")); Serial.print(tx);
  Serial.print(F("  Y=")); Serial.print(ty);
  Serial.print(F("  Z=")); Serial.println(tz);

  moveToXYZ(tx, ty, tz);

  posXmm = tx; posYmm = ty; posZmm = tz;
  Serial.println(F("Done."));
}

// ---- helpers ----
void parseAxis(const String& s, char ax, float &outVal) {
  int i = s.indexOf(ax);
  if (i < 0) return;
  // take substring after the letter up to next space
  int j = i + 1;
  while (j < (int)s.length() && s[j] == ' ') j++;
  int k = j;
  while (k < (int)s.length() && (isDigit(s[k]) || s[k]=='-' || s[k]=='+' || s[k]=='.' || s[k]=='e' || s[k]=='E')) k++;
  String num = s.substring(j, k);
  if (num.length() > 0) outVal = num.toFloat();
}

// Synchronized 3-axis move using DDA (Bresenham-like)
void moveToXYZ(float tx_mm, float ty_mm, float tz_mm) {
  long cx = lround(posXmm * X_STEPS_PER_MM);
  long cy = lround(posYmm * Y_STEPS_PER_MM);
  long cz = lround(posZmm * Z_STEPS_PER_MM);

  long txs = lround(tx_mm * X_STEPS_PER_MM);
  long tys = lround(ty_mm * Y_STEPS_PER_MM);
  long tzs = lround(tz_mm * Z_STEPS_PER_MM);

  long dx = txs - cx;
  long dy = tys - cy;
  long dz = tzs - cz;

  // Set directions (LOW/HIGH may invert depending on wiring; flip if needed)
  digitalWrite(X_DIR_PIN, (dx >= 0) ? LOW : HIGH);
  digitalWrite(Y_DIR_PIN, (dy >= 0) ? LOW : HIGH);
  digitalWrite(Z_DIR_PIN, (dz >= 0) ? LOW : HIGH);

  unsigned long ax = labs(dx), ay = labs(dy), az = labs(dz);
  unsigned long n  = ax;
  if (ay > n) n = ay;
  if (az > n) n = az;
  if (n == 0) return;

  unsigned long accX = 0, accY = 0, accZ = 0;

  for (unsigned long i = 0; i < n; i++) {
    bool sx = false, sy = false, sz = false;

    accX += ax; if (accX >= n) { accX -= n; sx = true; }
    accY += ay; if (accY >= n) { accY -= n; sy = true; }
    accZ += az; if (accZ >= n) { accZ -= n; sz = true; }

    if (sx) digitalWrite(X_STEP_PIN, HIGH);
    if (sy) digitalWrite(Y_STEP_PIN, HIGH);
    if (sz) digitalWrite(Z_STEP_PIN, HIGH);
    delayMicroseconds(pulseWidthMicros);
    if (sx) digitalWrite(X_STEP_PIN, LOW);
    if (sy) digitalWrite(Y_STEP_PIN, LOW);
    if (sz) digitalWrite(Z_STEP_PIN, LOW);

    int remain = stepPeriodMicros - pulseWidthMicros;
    if (remain > 0) delayMicroseconds(remain);
  }
}
