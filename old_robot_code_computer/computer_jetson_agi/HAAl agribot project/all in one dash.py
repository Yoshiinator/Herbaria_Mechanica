"""
Agri Telemetry Dashboard — Offline, Real LiDAR + Dual Cameras + RTK

- No internet/CDN: no external styles, no map tiles.
- Real RPLiDAR with start/stop motor control.
- Port dropdowns for LiDAR (auto-enumerated) and camera index pickers.
- RTK card always shows fields (even if empty) + last NMEA line.

Install:
  pip install dash plotly opencv-python pyserial pynmea2 rplidar pillow

Run:
  python agri_telemetry_dashboard.py
Open:
  http://127.0.0.1:8050
"""

import io, math, threading, time
from collections import deque
from dataclasses import dataclass, field
from typing import Optional, Tuple, List

import dash
from dash import dcc, html, Input, Output
import plotly.graph_objs as go

# --- Optional hw deps ---
try:
    import serial, pynmea2
    from serial.tools import list_ports
except Exception:
    serial = None; pynmea2 = None
    list_ports = None
try:
    from rplidar import RPLidar
except Exception:
    RPLidar = None
try:
    import cv2
except Exception:
    cv2 = None
from flask import Response

# ===================== CONFIG =====================
# Adjust defaults; you can change ports at runtime from the UI.
GPS_PORT = "COM13"
GPS_BAUD = 115200

LIDAR_PORT = "COM14"      # your working example used COM14
LIDAR_BAUD = 115200       # A1/A1M8 typically 115200; A2/A3 often 256000
LIDAR_MAX_POINTS = 4000

CAM0_INDEX = 0
CAM1_INDEX = 1
CAM_FPS = 15
MJPEG_JPEG_QUALITY = 70
CAM_MAX_PROBE = 6         # offer indices 0..5 in dropdown

# Mocks (keep all False for real hardware)
USE_MOCK_GPS = False
USE_MOCK_LIDAR = False    # REAL by default
USE_MOCK_CAMERAS = False

# ===================== STATE =====================
now_ts = lambda: time.time()

def port_list() -> List[str]:
    try:
        return [p.device for p in list_ports.comports()] if list_ports else []
    except Exception:
        return []

@dataclass
class GPSState:
    fix_mode: str = "NO DATA"
    lat: Optional[float] = None
    lon: Optional[float] = None
    alt_m: Optional[float] = None
    sats: Optional[int] = None
    hdop: Optional[float] = None
    speed_mps: Optional[float] = None
    last_sentence: Optional[str] = None
    last_update_ts: float = field(default_factory=now_ts)
    def to_status_badge(self) -> Tuple[str, str]:
        mode = (self.fix_mode or "NO DATA").upper()
        if "RTK FIX" in mode: return mode, "#15a34a"   # green
        if "RTK FLOAT" in mode: return mode, "#f59e0b" # amber
        if "3D" in mode or "DGPS" in mode: return mode, "#3b82f6"
        if "2D" in mode or "GPS" in mode: return mode, "#38bdf8"
        if "NO FIX" in mode or "NO DATA" in mode: return mode, "#6b7280"
        return mode, "#6b7280"

@dataclass
class LidarState:
    points_xy: deque = field(default_factory=lambda: deque(maxlen=LIDAR_MAX_POINTS))
    last_update_ts: float = field(default_factory=now_ts)
    status: str = "INIT"     # INIT/LIVE/ERROR/MOCK
    last_error: Optional[str] = None

@dataclass
class CamState:
    frame_jpeg: Optional[bytes] = None
    last_update_ts: float = field(default_factory=now_ts)

# Live-selectable settings (controlled via UI)
SELECTED_GPS_PORT = GPS_PORT
SELECTED_LIDAR_PORT = LIDAR_PORT
CAM0_DESIRED_INDEX = CAM0_INDEX
CAM1_DESIRED_INDEX = CAM1_INDEX

# Shared state
gps_state = GPSState()
lidar_state = LidarState()
cam0_state = CamState()
cam1_state = CamState()

# ===================== THREADS =====================

def gps_thread():
    global SELECTED_GPS_PORT
    if USE_MOCK_GPS or serial is None or pynmea2 is None:
        while True:
            gps_state.fix_mode = "NO DATA"; gps_state.last_update_ts = now_ts()
            time.sleep(1)
    else:
        current_port = None
        ser = None
        while True:
            try:
                if current_port != SELECTED_GPS_PORT or ser is None:
                    if ser:
                        try: ser.close()
                        except: pass
                    current_port = SELECTED_GPS_PORT
                    ser = serial.Serial(current_port, GPS_BAUD, timeout=1)
                line = ser.readline().decode(errors="ignore").strip()
                if not line or not line.startswith("$"):
                    continue
                gps_state.last_sentence = line
                try:
                    msg = pynmea2.parse(line)
                except Exception:
                    continue
                if msg.sentence_type == "GGA":
                    fix_map = {0:"NO FIX", 1:"GPS", 2:"DGPS", 4:"RTK FIX", 5:"RTK FLOAT"}
                    fixq = getattr(msg, 'gps_qual', None)
                    gps_state.fix_mode = fix_map.get(int(fixq or 0), str(fixq))
                    gps_state.lat = float(msg.latitude) if msg.latitude else None
                    gps_state.lon = float(msg.longitude) if msg.longitude else None
                    gps_state.alt_m = float(msg.altitude) if msg.altitude else None
                    gps_state.sats = int(getattr(msg,'num_sats',0) or 0)
                    gps_state.hdop = float(getattr(msg,'hdop',0) or 0)
                    gps_state.last_update_ts = now_ts()
                elif msg.sentence_type == "VTG":
                    spd_kmh = getattr(msg, 'spd_over_grnd_kmph', None)
                    try: gps_state.speed_mps = (float(spd_kmh)/3.6) if spd_kmh is not None else gps_state.speed_mps
                    except: pass
            except Exception:
                time.sleep(0.5)

def lidar_thread():
    """Real RPLiDAR with explicit motor control; reconnect on port change/errors."""
    global SELECTED_LIDAR_PORT
    if USE_MOCK_LIDAR or RPLidar is None:
        lidar_state.status = "MOCK"
        while True:
            time.sleep(0.5)
    else:
        current_port = None
        lidar = None
        while True:
            try:
                # (Re)connect on port change or first run
                if current_port != SELECTED_LIDAR_PORT or lidar is None:
                    # tear down previous
                    if lidar:
                        try: lidar.stop()
                        except: pass
                        try: lidar.stop_motor()
                        except: pass
                        try: lidar.disconnect()
                        except: pass
                    current_port = SELECTED_LIDAR_PORT
                    if not current_port:
                        lidar_state.status = "ERROR"; lidar_state.last_error = "No LiDAR port selected"
                        time.sleep(0.5); continue

                    lidar = RPLidar(current_port, baudrate=LIDAR_BAUD, timeout=2)
                    # Start motor and let it spin up
                    try:
                        lidar.start_motor()
                    except Exception:
                        # Some drivers auto-start; ignore
                        pass
                    time.sleep(0.8)
                    lidar_state.status = "LIVE"; lidar_state.last_error = None

                # Read scans continuously
                for scan in lidar.iter_scans(max_buf_meas=5000, min_len=5):
                    pts = []
                    # Each scan: list of (quality, angle_deg, distance_mm)
                    for (_, angle, distance_mm) in scan:
                        if distance_mm > 0:
                            r = distance_mm / 1000.0  # meters
                            rad = math.radians(angle)
                            pts.append((r*math.cos(rad), r*math.sin(rad)))
                    # keep most recent points
                    lidar_state.points_xy = deque(pts[-LIDAR_MAX_POINTS:], maxlen=LIDAR_MAX_POINTS)
                    lidar_state.last_update_ts = now_ts()
            except Exception as e:
                lidar_state.status = "ERROR"; lidar_state.last_error = str(e)
                # attempt to stop before retrying
                if lidar:
                    try: lidar.stop()
                    except: pass
                    try: lidar.stop_motor()
                    except: pass
                    try: lidar.disconnect()
                    except: pass
                    lidar = None
                time.sleep(0.5)

def camera_thread(name: str, cam_state: CamState):
    global CAM0_DESIRED_INDEX, CAM1_DESIRED_INDEX
    cap = None
    last_index = None
    while True:
        try:
            desired_index = (CAM0_DESIRED_INDEX if name == 'cam0' else CAM1_DESIRED_INDEX)
            if USE_MOCK_CAMERAS or cv2 is None:
                from PIL import Image, ImageDraw
                import numpy as np
                img = np.zeros((240, 320, 3), dtype=np.uint8)
                pil = Image.fromarray(img)
                d = ImageDraw.Draw(pil)
                d.text((8, 8), f"{name.upper()} MOCK", fill=(255,255,255))
                buf = io.BytesIO(); pil.save(buf, format='JPEG', quality=70)
                cam_state.frame_jpeg = buf.getvalue(); cam_state.last_update_ts = now_ts()
                time.sleep(1.0); continue

            # open/reopen if needed or index changed
            if cap is None or not cap.isOpened() or last_index != desired_index:
                if cap is not None:
                    try: cap.release()
                    except: pass
                # Prefer DirectShow on Windows; fallback to MSMF then default
                backends = [getattr(cv2,'CAP_DSHOW',700), getattr(cv2,'CAP_MSMF',1400), 0]
                opened = False
                for be in backends:
                    cap = cv2.VideoCapture(int(desired_index), be)
                    if cap is not None and cap.isOpened(): opened = True; break
                    if cap is not None:
                        try: cap.release()
                        except: pass
                last_index = desired_index
                if not opened:
                    time.sleep(0.5); continue
                cap.set(cv2.CAP_PROP_FPS, CAM_FPS)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            ret, frame = cap.read()
            if not ret or frame is None:
                time.sleep(0.05); continue
            ok, jpeg = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), MJPEG_JPEG_QUALITY])
            if ok:
                cam_state.frame_jpeg = jpeg.tobytes(); cam_state.last_update_ts = now_ts()
            else:
                time.sleep(0.05)
        except Exception:
            time.sleep(0.2)

# ===================== DASH (no external styles) =====================
app = dash.Dash(__name__)
server = app.server

@server.route('/cam0.jpg')
def cam0_jpg():
    return Response(cam0_state.frame_jpeg or b"", mimetype='image/jpeg')

@server.route('/cam1.jpg')
def cam1_jpg():
    return Response(cam1_state.frame_jpeg or b"", mimetype='image/jpeg')

# Simple inline CSS
CSS = {
    'card': {'border':'1px solid #333','borderRadius':'8px','padding':'10px','marginBottom':'12px','background':'#111','color':'#ddd'},
    'h3': {'color':'#eee'},
    'badge': {'display':'inline-block','padding':'4px 8px','borderRadius':'6px','background':'#333','color':'#eee'},
    'label': {'fontSize':'12px','color':'#aaa','marginBottom':'4px'},
}

def port_options():
    ports = port_list()
    if not ports:
        base = []
        for p in [GPS_PORT, LIDAR_PORT]:
            if p and p not in base: base.append(p)
        ports = base
    return [{'label': p, 'value': p} for p in ports]

app.layout = html.Div([
    html.H3("Agri Telemetry Dashboard", style=CSS['h3']),
    html.Div([
        # Left column
        html.Div([
            html.Div([
                html.Div("RTK GPS Status", style={'fontWeight':'600','marginBottom':'6px'}),
                html.Div(id='gps-fix', style=CSS['badge']),
                html.Div(id='gps-stats', style={'marginTop':'8px'})
            ], style=CSS['card']),
            html.Div([
                html.Div("Map (offline)", style={'fontWeight':'600','marginBottom':'6px'}),
                dcc.Graph(id='map-graph', style={'height': '320px'})
            ], style=CSS['card']),
        ], style={'width':'32%','display':'inline-block','verticalAlign':'top','paddingRight':'8px'}),

        # Right column
        html.Div([
            html.Div([
                html.Div("LiDAR", style={'fontWeight':'600','marginBottom':'6px'}),
                html.Div([
                    html.Span("Port:", style=CSS['label']),
                    dcc.Dropdown(id='lidar-port', options=port_options(), value=LIDAR_PORT, clearable=False,
                                 style={'marginBottom':'6px'}),
                    html.Span("Status: ", style=CSS['label']), html.Span(id='lidar-status'),
                    html.Div("Tip: If you're on A2/A3, set LIDAR_BAUD=256000 in the code.", style={'color':'#888','fontSize':'12px','marginTop':'4px'})
                ]),
                dcc.Graph(id='lidar-graph', style={'height': '320px','marginTop':'6px'})
            ], style=CSS['card']),

            html.Div([
                html.Div("Cameras", style={'fontWeight':'600','marginBottom':'6px'}),
                html.Div([
                    html.Div([html.Span("Cam0 index", style=CSS['label']),
                              dcc.Dropdown(id='cam0-select', options=[{'label':str(i),'value':i} for i in range(CAM_MAX_PROBE)],
                                           value=CAM0_INDEX, clearable=False)], style={'width':'49%','display':'inline-block'}),
                    html.Div([html.Span("Cam1 index", style=CSS['label']),
                              dcc.Dropdown(id='cam1-select', options=[{'label':str(i),'value':i} for i in range(CAM_MAX_PROBE)],
                                           value=CAM1_INDEX, clearable=False)], style={'width':'49%','display':'inline-block','marginLeft':'2%'}),
                ]),
                html.Div([
                    html.Div([
                        html.Img(id='cam0-feed', style={'width':'100%','borderRadius':'8px'}),
                        html.Div("Cam0 inactive", id='cam0-msg', style={'textAlign':'center','color':'#aaa','marginTop':'4px'})
                    ], style={'width':'49%','display':'inline-block','verticalAlign':'top'}),
                    html.Div([
                        html.Img(id='cam1-feed', style={'width':'100%','borderRadius':'8px'}),
                        html.Div("Cam1 inactive", id='cam1-msg', style={'textAlign':'center','color':'#aaa','marginTop':'4px'})
                    ], style={'width':'49%','display':'inline-block','marginLeft':'2%','verticalAlign':'top'}),
                ], style={'marginTop':'8px'})
            ], style=CSS['card'])
        ], style={'width':'66%','display':'inline-block','verticalAlign':'top','paddingLeft':'8px'}),
    ]),
    html.Div(id='diag', style={'marginTop':'6px','color':'#888','fontSize':'12px'}),
    dcc.Interval(id='tick', interval=800, n_intervals=0)
])

@app.callback(
    Output('gps-fix','children'), Output('gps-fix','style'), Output('gps-stats','children'),
    Output('map-graph','figure'),
    Output('lidar-graph','figure'), Output('lidar-status','children'),
    Output('cam0-feed','src'), Output('cam1-feed','src'), Output('cam0-msg','children'), Output('cam1-msg','children'),
    Output('diag','children'),
    Input('tick','n_intervals'), Input('cam0-select','value'), Input('cam1-select','value'), Input('lidar-port','value')
)
def update_ui(_, cam0_idx, cam1_idx, lidar_port_value):
    global CAM0_DESIRED_INDEX, CAM1_DESIRED_INDEX, SELECTED_LIDAR_PORT
    if cam0_idx is not None: CAM0_DESIRED_INDEX = int(cam0_idx)
    if cam1_idx is not None: CAM1_DESIRED_INDEX = int(cam1_idx)
    if lidar_port_value:
        if SELECTED_LIDAR_PORT != str(lidar_port_value):
            SELECTED_LIDAR_PORT = str(lidar_port_value)
            # LiDAR thread notices the change and reconnects (stopping/starting motor appropriately)

    # GPS card
    fix_label, fix_color = gps_state.to_status_badge()
    fix_style = CSS['badge'] | {'background': fix_color}
    last_nmea = gps_state.last_sentence if gps_state.last_sentence else "—"
    gps_stats = html.Div([
        f"Lat: {gps_state.lat if gps_state.lat is not None else '—'}", html.Br(),
        f"Lon: {gps_state.lon if gps_state.lon is not None else '—'}", html.Br(),
        f"Alt: {gps_state.alt_m if gps_state.alt_m is not None else '—'} m", html.Br(),
        f"Sats: {gps_state.sats if gps_state.sats is not None else '—'}", html.Br(),
        f"HDOP: {gps_state.hdop if gps_state.hdop is not None else '—'}", html.Br(),
        f"Speed: {gps_state.speed_mps if gps_state.speed_mps is not None else '—'} m/s", html.Br(),
        f"Last update: {time.strftime('%H:%M:%S', time.localtime(gps_state.last_update_ts))}", html.Br(),
        html.Small(f"Last NMEA: {last_nmea}")
    ])

    # Map (offline)
    fig_map = go.Figure()
    if gps_state.lat is not None and gps_state.lon is not None:
        fig_map.add_trace(go.Scattergeo(lat=[gps_state.lat], lon=[gps_state.lon], mode='markers'))
    fig_map.update_layout(margin=dict(l=0, r=0, t=0, b=0))

    # LiDAR
    pts = list(lidar_state.points_xy)
    xs, ys = zip(*pts) if pts else ([], [])
    lidar_fig = go.Figure(go.Scatter(x=xs, y=ys, mode='markers', marker=dict(size=2)))
    lidar_fig.update_layout(
        title = f"LiDAR {lidar_state.status}" + (f" — {lidar_state.last_error}" if lidar_state.last_error else ""),
        xaxis=dict(scaleanchor='y', range=[-6, 6]),   # 6 m to match your polar example
        yaxis=dict(range=[-6, 6])
    )
    lidar_status = f"{lidar_state.status}" + (f" — {lidar_state.last_error}" if lidar_state.last_error else "")

    # Cameras
    cam0_live = (time.time() - cam0_state.last_update_ts) < 2.0 and (cam0_state.frame_jpeg is not None)
    cam1_live = (time.time() - cam1_state.last_update_ts) < 2.0 and (cam1_state.frame_jpeg is not None)
    cam0_msg = "Cam0 live ✅" if cam0_live else "Cam0 inactive"
    cam1_msg = "Cam1 live ✅" if cam1_live else "Cam1 inactive"
    cam0_src = f"/cam0.jpg?rand={time.time()}"
    cam1_src = f"/cam1.jpg?rand={time.time()}"

    diag = f"GPS_PORT={SELECTED_GPS_PORT} | LIDAR_PORT={SELECTED_LIDAR_PORT} ({lidar_status}) | Cams {CAM0_DESIRED_INDEX},{CAM1_DESIRED_INDEX}"
    return fix_label, fix_style, gps_stats, fig_map, lidar_fig, lidar_status, cam0_src, cam1_src, cam0_msg, cam1_msg, diag

# ===================== START =====================

def start_threads():
    threading.Thread(target=gps_thread, daemon=True).start()
    threading.Thread(target=lidar_thread, daemon=True).start()
    threading.Thread(target=camera_thread, args=("cam0", cam0_state), daemon=True).start()
    threading.Thread(target=camera_thread, args=("cam1", cam1_state), daemon=True).start()

if __name__ == '__main__':
    start_threads()
    app.run(debug=False, host='0.0.0.0', port=8050)
