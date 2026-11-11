#!/usr/bin/env python3
"""Robot Bridge Host - All-in-one Serial to TCP Bridge + FastAPI."""

import asyncio
import json
import logging
import sys
from typing import Optional

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)-8s %(message)s')
log = logging.getLogger("bridge")

SERIAL_CONFIG = {
    "gps": {"port": "COM13", "baud": 115200, "enabled": True},
    "imu": {"port": "COM3", "baud": 115200, "enabled": True},
    "motor": {"port": "COM14", "baud": 115200, "enabled": True},
}

FASTAPI_HOST = "192.168.137.174"
FASTAPI_PORT = 9000


def parse_imu_line(line: str) -> Optional[dict]:
    try:
        parts = line.strip().split(",")
        if not parts or parts[0] != "IMU":
            return None
        data = {}
        for part in parts[1:]:
            if "=" in part:
                key, value = part.split("=", 1)
                try:
                    data[key] = float(value)
                except ValueError:
                    data[key] = value
        if not data:
            return None
        return {
            "yaw": data.get("yaw_deg", 0),
            "yaw_deg": data.get("yaw_deg", 0),
            "gyro_z_dps": data.get("gyro_z_dps", 0),
            "accel_x": data.get("ax", 0),
            "accel_y": data.get("ay", 0),
            "accel_z": data.get("az", 0),
            "t": data.get("t", 0),
        }
    except Exception:
        return None


def parse_gps_line(line: str) -> Optional[dict]:
    try:
        if "$" not in line or "RMC" not in line:
            return None
        parts = line.strip().split(",")
        if len(parts) < 10 or parts[2] != "A":
            return None
        lat = parts[3]
        lat_hemi = parts[4]
        lon = parts[5]
        lon_hemi = parts[6]
        if not lat or not lon:
            return None
        lat_val = float(lat[:2]) + float(lat[2:]) / 60
        if lat_hemi == "S":
            lat_val = -lat_val
        lon_val = float(lon[:3]) + float(lon[3:]) / 60
        if lon_hemi == "W":
            lon_val = -lon_val
        return {
            "lat": lat_val,
            "lon": lon_val,
            "heading": float(parts[8]) if parts[8] else 0,
            "speed": float(parts[7]) * 1.944 if parts[7] else 0,
        }
    except Exception:
        return None


def parse_motor_line(line: str) -> Optional[dict]:
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


class SerialReader:
    def __init__(self, name, port, baud, on_data):
        self.name = name
        self.port = port
        self.baud = baud
        self.on_data = on_data
        self._running = False
        self._serial = None

    async def start(self):
        import serial
        self._running = True
        while self._running:
            try:
                log.info(f"[{self.name}] Opening {self.port} at {self.baud}")
                self._serial = serial.Serial(self.port, self.baud, timeout=1)
                log.info(f"[{self.name}] Connected")
                buffer = ""
                while self._running:
                    if self._serial.in_waiting:
                        data = self._serial.read(self._serial.in_waiting)
                        buffer += data.decode('ascii', errors='ignore')
                        while '\n' in buffer:
                            line, buffer = buffer.split('\n', 1)
                            line = line.strip()
                            if line:
                                await self.on_data(line)
                    await asyncio.sleep(0.01)
                self._serial.close()
                self._serial = None
            except Exception as e:
                log.error(f"[{self.name}] Error: {e}")
            await asyncio.sleep(2)

    def stop(self):
        self._running = False

    def send_cmd(self, linear_x, angular_z):
        if self.name != "motor":
            return
        try:
            if self._serial and self._serial.is_open:
                cmd = json.dumps({"linear_x": linear_x, "angular_z": angular_z}, ensure_ascii=False) + "\n"
                self._serial.write(cmd.encode('utf-8'))
                log.info(f"[motor] cmd_vel: linear={linear_x:.2f}, angular={angular_z:.2f}")
            else:
                log.warning(f"[motor] Serial not connected, cannot send cmd")
        except Exception as e:
            log.error(f"[{self.name}] Send error: {e}")


class TcpBridge:
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self._writer = None
        self._reader = None
        self._motor_reader = None

    def set_motor_reader(self, reader):
        self._motor_reader = reader

    async def connect(self):
        self._reader, self._writer = await asyncio.open_connection(self.host, self.port)
        log.info(f"Connected to {self.host}:{self.port}")
        asyncio.create_task(self._receive_loop())

    async def _receive_loop(self):
        """Receive messages from ROBO NAV and forward to motor."""
        while True:
            try:
                line = await self._reader.readline()
                if not line:
                    break
                msg = json.loads(line.decode().strip())
                await self._handle_message(msg)
            except Exception as e:
                log.error(f"TCP receive error: {e}")
                break

    async def _handle_message(self, msg):
        msg_type = msg.get("type", "")
        if msg_type == "cmd_vel":
            data = msg.get("data", {})
            linear_x = data.get("linear_x", 0)
            angular_z = data.get("angular_z", 0)
            log.info(f"Received cmd_vel: linear={linear_x:.2f}, angular={angular_z:.2f}")
            if self._motor_reader:
                self._motor_reader.send_cmd(linear_x, angular_z)
        elif msg_type == "estop":
            log.info("Received E-STOP command")
            if self._motor_reader:
                self._motor_reader.send_cmd(0, 0)

    async def send(self, msg):
        if self._writer:
            line = json.dumps(msg) + "\n"
            self._writer.write(line.encode())
            await self._writer.drain()

    def close(self):
        if self._writer:
            self._writer.close()


bridges = []
motor_reader = None


async def main():
    global motor_reader
    
    tcp = TcpBridge(FASTAPI_HOST, FASTAPI_PORT)
    
    try:
        await tcp.connect()
    except Exception as e:
        log.error(f"Failed to connect to {FASTAPI_HOST}:{FASTAPI_PORT}: {e}")
        return

    async def on_serial_data(source, line):
        if source == "imu":
            data = parse_imu_line(line)
        elif source == "gps":
            data = parse_gps_line(line)
        elif source == "motor":
            data = parse_motor_line(line)
        else:
            try:
                data = json.loads(line)
            except:
                data = {"raw": line}

        if data:
            await tcp.send({"type": f"sensor_{source}", "data": data})
        else:
            await tcp.send({"type": f"raw_{source}", "raw": line})

    for name, cfg in SERIAL_CONFIG.items():
        if cfg.get("enabled") and cfg.get("port"):
            b = SerialReader(name, cfg["port"], cfg["baud"],
                           lambda l, s=name: on_serial_data(s, l))
            bridges.append(b)
            if name == "motor":
                motor_reader = b
                tcp.set_motor_reader(b)
            asyncio.create_task(b.start())

    log.info("=" * 50)
    log.info("Robot Bridge Host Running")
    log.info(f"Sending to: {FASTAPI_HOST}:{FASTAPI_PORT}")
    for name, cfg in SERIAL_CONFIG.items():
        if cfg.get("enabled"):
            log.info(f"  {name}: {cfg['port']} @ {cfg['baud']}")
    log.info("=" * 50)

    await asyncio.sleep(86400)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        log.info("Stopped")
