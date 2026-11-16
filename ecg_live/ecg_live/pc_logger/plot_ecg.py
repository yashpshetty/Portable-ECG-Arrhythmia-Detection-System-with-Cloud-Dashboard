# Plots the last recorded session: raw vs filtered
# pip install pandas matplotlib
import os, pandas as pd, matplotlib.pyplot as plt
here = os.path.dirname(os.path.abspath(__file__))
d = pd.read_csv(os.path.join(here, "..", "dataset", "ECG_real_time_dataset.csv"))
d = d[d["session"] == d["session"].iloc[-1]]
d = d.iloc[:360 * 10]                       # first 10 seconds
fig, ax = plt.subplots(2, 1, sharex=True, figsize=(11, 6))
ax[0].plot(d["time_s"], d["raw_adc"]);  ax[0].set_title("Raw ECG (AD8232, ADC counts)")
ax[1].plot(d["time_s"], d["filtered"]); ax[1].set_title("Filtered on MSP430")
ax[1].set_xlabel("Time (s)")
plt.tight_layout(); plt.show()
