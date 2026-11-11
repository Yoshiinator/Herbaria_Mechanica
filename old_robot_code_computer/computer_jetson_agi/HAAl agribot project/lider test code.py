# rplidar_polar_live.py
from rplidar import RPLidar
import math, time
import matplotlib.pyplot as plt

PORT='COM14'; BAUD=115200

lid = RPLidar(PORT, baudrate=BAUD, timeout=2)
try:
    lid.start_motor(); time.sleep(0.8)

    plt.ion()
    fig = plt.figure()
    ax = fig.add_subplot(111, projection='polar')
    scat = ax.scatter([], [], s=2)
    ax.set_rlim(0, 6000)              # show up to 6 m
    ax.set_title("RPLIDAR A1M8 — live", pad=20)

    for i, scan in enumerate(lid.iter_scans(max_buf_meas=5000), 1):
        th = []; r = []
        for q,a,d in scan:
            if d > 0:
                th.append(math.radians(a))  # deg → rad
                r.append(d)                 # mm
        scat.remove()
        scat = ax.scatter(th, r, s=2)
        plt.pause(0.001)
        if i >= 200: break   # stop after ~200 revolutions
finally:
    try: lid.stop()
    except: pass
    try: lid.stop_motor()
    except: pass
    lid.disconnect()
