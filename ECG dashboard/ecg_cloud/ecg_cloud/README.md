# CardioWatch – ECG cloud dashboard

## Run it
```
cd ecg_cloud
pip install -r requirements.txt
copy .env.example .env          (then edit TOPIC_ROOT to something unique)
python app.py                    -> open http://127.0.0.1:5000
```
1. Sign up as a **Patient** -> you get a Patient ID like `ECG4821`.
2. Open a private window, sign up as a **Guardian** with that ID + relation.
3. Copy your recorded `ECG_real_time_dataset.csv` into `ecg_cloud/dataset/`.
4. Start the simulated device (replaces the ESP32 for now):
   ```
   python simulate_device.py ECG4821
   python simulate_device.py ECG4821 --mode tachy     (triggers alert + SMS)
   ```

## MQTT contract (the ESP32 must follow this)
Topic: `<TOPIC_ROOT>/<PATIENT_ID>/live`, about 4 messages per second, JSON:
```
{"fs":360,"samples":[... 90 ints ...],"bpm":72,"rhythm":"Normal","battery":88,"patch":true,"ts":1760000000}
```
`rhythm` is `Normal` or the name of the abnormal rhythm. Backend alerts go to `<TOPIC_ROOT>/<PATIENT_ID>/alert`.

## SMS
`SMS_PROVIDER=console` only prints messages. For real SMS set `fast2sms` (+ `FAST2SMS_KEY`) or `twilio` in `.env`.
