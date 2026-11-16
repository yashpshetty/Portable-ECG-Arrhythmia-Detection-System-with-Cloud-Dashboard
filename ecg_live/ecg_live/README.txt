ECG LIVE (AD8232 -> MSP430 filter -> CSV)
1. Build firmware/main.c the same way you built your tested program -> main.elf, load with UniFlash, press RESET.
2. Close UniFlash/CCS, then:  python pc_logger/log_ecg_live.py COM6 60 normal
3. Data is appended to dataset/ECG_real_time_dataset.csv
4. Check it:  python pc_logger/plot_ecg.py
Wiring: AD8232 3.3V->3V3, GND->GND, OUTPUT->P1.4, LO+->P2.0, LO-->P2.1
Baud is 115200 (not 9600) - the live stream is too fast for 9600.
