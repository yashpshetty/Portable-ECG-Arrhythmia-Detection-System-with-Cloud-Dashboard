"""Stands in for the ESP32 until it is ready: replays your recorded ECG over MQTT.

  python simulate_device.py ECG1234                 normal rhythm
  python simulate_device.py ECG1234 --mode tachy    fast heart rate  -> triggers alert + SMS
  python simulate_device.py ECG1234 --mode brady    slow heart rate  -> triggers alert + SMS

(tachy/brady just speed up / slow down your normal recording - for demo only.)
"""
import argparse, json, secrets, time
import numpy as np, pandas as pd
import paho.mqtt.client as mqtt
from scipy.signal import find_peaks
import config

ap = argparse.ArgumentParser()
ap.add_argument("patient", help="Patient ID, e.g. ECG1234")
ap.add_argument("--csv", default="dataset/ECG_real_time_dataset.csv")
ap.add_argument("--mode", choices=["normal", "tachy", "brady"], default="normal")
a = ap.parse_args()

FS, BATCH = 360, 90                      # 90 samples = 0.25 s per MQTT message
d = pd.read_csv(a.csv)
d = d[(d["label"] == "normal") & (d["lead_off"] == 0)]
x = d["filtered"].values.astype(float)
if len(x) < FS * 10:
    raise SystemExit("Need at least 10 s of 'normal' data (lead_off=0) in the CSV.")

speed = {"normal": 1.0, "tachy": 1.8, "brady": 0.6}[a.mode]
n = int(len(x) / speed)
x = np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x)

def bpm_of(win):
    if len(win) < FS * 4:
        return 0
    prom = 0.4 * (np.max(win) - np.median(win))          # R-peaks stand far above the rest
    pk, _ = find_peaks(win, prominence=max(prom, 20), distance=int(0.3 * FS))
    return int(round(len(pk) / (len(win) / FS) * 60))

c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"sim-{secrets.token_hex(3)}")
c.connect(config.MQTT_HOST, config.MQTT_PORT, 60)
c.loop_start()
topic = f"{config.TOPIC_ROOT}/{a.patient}/live"
print("Publishing to", topic, "- Ctrl+C to stop")

pos, sent, battery, t_next = 0, [], 92.0, time.time()
while True:
    batch = np.take(x, range(pos, pos + BATCH), mode="wrap")
    pos = (pos + BATCH) % len(x)
    sent = (sent + list(batch))[-FS * 10:]
    bpm = bpm_of(np.array(sent))
    rhythm = "Normal" if bpm == 0 or config.BPM_LOW <= bpm <= config.BPM_HIGH else \
             ("Tachycardia" if bpm > config.BPM_HIGH else "Bradycardia")
    battery = max(5.0, battery - 0.002)
    c.publish(topic, json.dumps(dict(fs=FS, samples=[int(v) for v in batch], bpm=bpm,
                                     rhythm=rhythm, battery=int(battery), patch=True, ts=int(time.time()))))
    t_next += BATCH / FS
    time.sleep(max(0, t_next - time.time()))
