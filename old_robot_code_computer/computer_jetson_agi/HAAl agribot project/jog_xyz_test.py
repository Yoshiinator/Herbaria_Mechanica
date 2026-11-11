# jog_xyz_mega.py
# Keyboard jog controller for Arduino MEGA XYZ gantry over serial.
# Requires: pip install pyserial pynput
#
# Matches the user's Arduino sketch (absolute XYZ commands over Serial):
#   - 115200 baud
#   - Example command: "X100 Y50 Z10\n"

import sys
import time
import threading
from dataclasses import dataclass
from typing import Dict, Tuple

import serial
from pynput import keyboard

# ---------- USER SETTINGS ----------
COM_PORT = "COM12"
BAUDRATE = 115200

BASE_STEP_MM = 1.0         # default per-tap step (mm)
REPEAT_INTERVAL = 0.15     # seconds between repeats while key is held
PRINT_ECHO = True          # print Arduino responses (non-blocking best-effort)
# Optional soft limits (set to None to disable)
X_LIMITS = (None, None)    # e.g., (0.0, 300.0)
Y_LIMITS = (None, None)
Z_LIMITS = (None, None)
# ----------------------------------

@dataclass
class Position:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0

class GantryJogger:
    def __init__(self):
        self.ser = None
        self.pos = Position(0.0, 0.0, 0.0)  # software-tracked absolute mm
        self.base_step = BASE_STEP_MM
        self.modifiers = set()              # currently pressed modifiers
        self.lock = threading.Lock()
        self.active: Dict[str, bool] = {}   # key name -> active repeat flag
        self.reader_thread = None
        self.reader_stop = threading.Event()

    # ----- Serial -----
    def connect(self):
        self.ser = serial.Serial(COM_PORT, BAUDRATE, timeout=0.05)
        # Allow Arduino to reset on port open
        time.sleep(2.0)
        print_banner()
        self.start_reader()

    def start_reader(self):
        def reader():
            while not self.reader_stop.is_set():
                try:
                    if self.ser and self.ser.in_waiting:
                        line = self.ser.readline().decode(errors="ignore").strip()
                        if line and PRINT_ECHO:
                            print(f"[MEGA] {line}")
                    else:
                        time.sleep(0.02)
                except Exception:
                    time.sleep(0.1)
        self.reader_thread = threading.Thread(target=reader, daemon=True)
        self.reader_thread.start()

    def close(self):
        self.reader_stop.set()
        if self.reader_thread:
            self.reader_thread.join(timeout=0.5)
        if self.ser:
            try:
                self.ser.close()
            except Exception:
                pass

    # ----- Helpers -----
    def get_step(self) -> float:
        step = self.base_step
        if keyboard.Key.shift in self.modifiers:
            step *= 5.0
        if keyboard.Key.ctrl in self.modifiers:
            step *= 0.1
        return step

    def clamp(self, axis: str, value: float) -> float:
        lims = {"X": X_LIMITS, "Y": Y_LIMITS, "Z": Z_LIMITS}[axis]
        lo, hi = lims
        if lo is not None:
            value = max(lo, value)
        if hi is not None:
            value = min(hi, value)
        return value

    def send_target(self):
        """Send absolute XYZ to Arduino."""
        cmd = f"X{self.pos.x:.3f} Y{self.pos.y:.3f} Z{self.pos.z:.3f}\n"
        try:
            self.ser.write(cmd.encode())
        except Exception as e:
            print(f"[ERR] Serial write failed: {e}")

    # ----- Jog logic -----
    def _repeat_move(self, key_name: str, delta: Tuple[float, float, float]):
        # Immediate move, then repeat while held
        while self.active.get(key_name, False):
            with self.lock:
                self.pos.x = self.clamp("X", self.pos.x + delta[0])
                self.pos.y = self.clamp("Y", self.pos.y + delta[1])
                self.pos.z = self.clamp("Z", self.pos.z + delta[2])
                self.send_target()
                print(f"→ Target  X={self.pos.x:.3f}  Y={self.pos.y:.3f}  Z={self.pos.z:.3f}")
            time.sleep(REPEAT_INTERVAL)

    def start_jog(self, key_name: str, axis: str, sign: int):
        step = self.get_step()
        dx = dy = dz = 0.0
        if axis == "X":
            dx = sign * step
        elif axis == "Y":
            dy = sign * step
        elif axis == "Z":
            dz = sign * step

        # Start only if not already active
        if not self.active.get(key_name, False):
            self.active[key_name] = True
            # kick one move immediately, then repeat loop
            threading.Thread(target=self._repeat_move, args=(key_name, (dx, dy, dz)), daemon=True).start()

    def stop_jog(self, key_name: str):
        self.active[key_name] = False

    # ----- Key handlers -----
    def on_press(self, key):
        # Track modifiers
        if key in (keyboard.Key.shift, keyboard.Key.ctrl):
            self.modifiers.add(key)
            return

        # Movement keys
        try:
            if key == keyboard.Key.left:
                self.start_jog("left", "X", -1)
            elif key == keyboard.Key.right:
                self.start_jog("right", "X", +1)
            elif key == keyboard.Key.up:
                self.start_jog("up", "Y", +1)
            elif key == keyboard.Key.down:
                self.start_jog("down", "Y", -1)
            elif key == keyboard.Key.page_up:
                self.start_jog("page_up", "Z", +1)
            elif key == keyboard.Key.page_down:
                self.start_jog("page_down", "Z", -1)
            elif key == keyboard.Key.esc:
                return False  # stop listener
            elif isinstance(key, keyboard.KeyCode):
                ch = (key.char or "").lower()

                if ch == '+':
                    self.base_step *= 1.5
                    print(f"[STEP] Base step = {self.base_step:.4f} mm")
                elif ch == '-':
                    self.base_step = max(0.001, self.base_step / 1.5)
                    print(f"[STEP] Base step = {self.base_step:.4f} mm")
                elif ch == 'h':
                    with self.lock:
                        self.pos = Position(0.0, 0.0, 0.0)
                        self.send_target()
                        print("Homing → X=0 Y=0 Z=0 (absolute)")
                elif ch == 'r':
                    with self.lock:
                        self.pos = Position(0.0, 0.0, 0.0)
                    print("Software position reset to (0,0,0) WITHOUT motion.")
        except AttributeError:
            pass  # non-character key fallthrough

    def on_release(self, key):
        # Unset modifiers
        if key in (keyboard.Key.shift, keyboard.Key.ctrl):
            if key in self.modifiers:
                self.modifiers.remove(key)
            return

        # Stop corresponding jog
        mapping = {
            keyboard.Key.left: "left",
            keyboard.Key.right: "right",
            keyboard.Key.up: "up",
            keyboard.Key.down: "down",
            keyboard.Key.page_up: "page_up",
            keyboard.Key.page_down: "page_down",
        }
        if key in mapping:
            self.stop_jog(mapping[key])

def print_banner():
    print(
"""------------------------------------------------------------
XYZ Gantry Keyboard Jog (COM12 @ 115200)
Arrow keys = X/Y, PageUp/PageDown = Z
Shift=×5, Ctrl=×0.1, +/- change base step
H = home to (0,0,0), R = reset software pos to (0,0,0)
ESC = quit
------------------------------------------------------------"""
    )

def main():
    jogger = GantryJogger()
    try:
        jogger.connect()
    except Exception as e:
        print(f"[ERR] Could not open {COM_PORT}: {e}")
        sys.exit(1)

    with keyboard.Listener(on_press=jogger.on_press, on_release=jogger.on_release) as listener:
        try:
            listener.join()
        except KeyboardInterrupt:
            pass
        finally:
            jogger.close()
            print("Goodbye.")

if __name__ == "__main__":
    main()
