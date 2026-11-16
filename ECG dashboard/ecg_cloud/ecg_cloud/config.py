import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY    = os.getenv("SECRET_KEY", "dev-only-change-me")
DB_PATH       = os.getenv("DB_PATH", "ecg_cloud.db")

MQTT_HOST     = os.getenv("MQTT_HOST", "broker.hivemq.com")
MQTT_PORT     = int(os.getenv("MQTT_PORT", "1883"))
MQTT_WS_URL   = os.getenv("MQTT_WS_URL", "wss://broker.hivemq.com:8884/mqtt")
TOPIC_ROOT    = os.getenv("TOPIC_ROOT", "ecgproject-demo")

SMS_PROVIDER  = os.getenv("SMS_PROVIDER", "console")
FAST2SMS_KEY  = os.getenv("FAST2SMS_KEY", "")
TWILIO_SID    = os.getenv("TWILIO_SID", "")
TWILIO_TOKEN  = os.getenv("TWILIO_TOKEN", "")
TWILIO_FROM   = os.getenv("TWILIO_FROM", "")

BPM_HIGH         = int(os.getenv("BPM_HIGH", "120"))
BPM_LOW          = int(os.getenv("BPM_LOW", "50"))
ALERT_COOLDOWN_S = 60     # same alert type at most once a minute
STORE_EVERY_S    = 5      # save one reading every 5 s
