# Records the live, MSP430-filtered ECG into dataset/ECG_real_time_dataset.csv
#
# pip install pyserial
# Usage:  python log_ecg_live.py COM6 60 normal
#                                 port seconds label
import serial, csv, os, sys, time
from datetime import datetime

PORT    = sys.argv[1] if len(sys.argv) > 1 else "COM6"
SECONDS = int(sys.argv[2]) if len(sys.argv) > 2 else 60
LABEL   = sys.argv[3] if len(sys.argv) > 3 else "normal"
BAUD    = 115200
FS      = 360            # must match the firmware

here   = os.path.dirname(os.path.abspath(__file__))
folder = os.path.join(here, "..", "dataset")
os.makedirs(folder, exist_ok=True)
path   = os.path.join(folder, "ECG_real_time_dataset.csv")
new_file = not os.path.exists(path)
session  = datetime.now().strftime("%Y%m%d_%H%M%S")

ser = serial.Serial(PORT, BAUD, timeout=1)
time.sleep(1)
ser.reset_input_buffer()
ser.readline()           # throw away a possibly half-received first line

n = 0
bad = 0
leadoff = 0
t0 = time.time()
with open(path, "a", newline="") as f:
    w = csv.writer(f)
    if new_file:
        w.writerow(["session", "sample", "time_s", "raw_adc", "filtered", "lead_off", "label"])
    while time.time() - t0 < SECONDS:
        line = ser.readline().decode(errors="ignore").strip()
        p = line.split(",")
        if len(p) != 3 or not all(x.lstrip("-").isdigit() for x in p):
            bad += 1
            continue
        raw, filt, lo = int(p[0]), int(p[1]), int(p[2])
        w.writerow([session, n, f"{n / FS:.4f}", raw, filt, lo, LABEL])
        leadoff += lo
        n += 1
        if n % FS == 0:
            print(f"{n // FS:4d} s  raw={raw:4d}  filtered={filt:5d}  lead_off={lo}", flush=True)
ser.close()

elapsed = time.time() - t0
print(f"\nSaved {n} samples to {os.path.abspath(path)}")
print(f"Measured rate: {n / elapsed:.1f} Hz (expected ~{FS})   bad lines: {bad}   lead-off samples: {leadoff}")
if n / elapsed < FS * 0.95:
    print("WARNING: samples are being lost - check the baud rate/COM port.")
