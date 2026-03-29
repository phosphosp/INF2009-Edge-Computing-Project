
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment from project root first, then cloud/aws/.env as a fallback.
# This keeps edge scripts/tests and cloud docker settings consistent when running locally.
_ROOT_DIR = Path(__file__).resolve().parent
load_dotenv(_ROOT_DIR / ".env")
load_dotenv(_ROOT_DIR / "cloud" / "aws" / ".env", override=False)

# Single source of truth for all pins, thresholds, and timing
# All other modules import from here

# GPIO Pins (BCM numbering)
# Sensors
GAS_PIN = 17 # MQ2 digital output (DO) -> Physical Pin 11
TEMP_PIN = 4 # DHT22 data line -> Physical Pin 7

# Actuators
LED_PIN = 24 # LED signal -> Physical Pin 18
BUZZER_PIN = 23 # Buzzer PWM  -> Physical Pin 16
SERVO_PIN = 18 # Servo PWM signal -> Physical Pin 12

# RFID (SPI)
# SPI is handled by the mfrc522 library automatically via SPI0
# Physical wiring reminder:
#   SDA  -> Pin 24 (GPIO 8,  SPI CE0)
#   SCK  -> Pin 23 (GPIO 11, SPI CLK)
#   MOSI -> Pin 19 (GPIO 10, SPI MOSI)
#   MISO -> Pin 21 (GPIO 9,  SPI MISO)
#   RST  -> Pin 22 (GPIO 25)
#   3.3V -> Pin 1
#   GND  -> Pin 6

# DHT22 Temperature Sensor Settings
TEMP_READ_INTERVAL = 2 # seconds between DHT22 reads
TEMP_WARMUP_READS = 3 # ignore first N reads on startup
TEMP_AVG_SAMPLES = 3 # rolling average window size
TEMP_HIGH_COUNT_REQ = 3 # consecutive high readings before flagging
TEMP_ON_THRESHOLD = 31.6 # °C - trigger if avg exceeds this (should be 35 for real fire)
TEMP_OFF_THRESHOLD = 31.3 # °C - clear flag when avg drops below this (should be 34.5 for real fire)

# MQ2 Gas Sensor Settings
GAS_CONSECUTIVE_REQ = 2 # consecutive positive reads before flagging (debounce against single-sample noise)
GAS_WARMUP_SEC = 20 # seconds to preheat MQ2 before readings are trusted (per datasheet)

# Buzzer Settings
BUZZ_FREQ = 1000 # Hz
BUZZ_DUTY = 0.5 # 0.0–1.0 PWM duty cycle

# Servo / Smart Door Settings
SERVO_LOCKED_ANGLE = 0 # degrees - locked position
SERVO_UNLOCKED_ANGLE = 90 # degrees - unlocked / open position
SERVO_HOLD_TIME = 3 # seconds door stays unlocked after RFID scan (ignored during fire mode, stays open)

# RFID authorised card IDs
_raw_cards = os.getenv("AUTHORISED_CARDS", "")
AUTHORISED_CARDS = [c.strip() for c in _raw_cards.split(",") if c.strip()]

# Fusion / Scoring Weights
# Must sum to 1.0. Adjust based on sensor reliability in your environment
WEIGHT_GAS = 0.2     # Reduce other sensor influence
WEIGHT_TEMP = 0.1    
WEIGHT_VISION = 0.7  # Increased - Vision is now "The Boss"

FIRE_THRESHOLD = 0.4 # Reduced from 0.5 (Easier to trigger)
# Without vision: max possible = 0.6 (gas + temp)
# Tune down to 0.4 to trigger on gas alone if needed

# MQTT CONFIGURATION
# Accept MQTT_BROKER (edge/app convention) or MQTT_HOST (cloud compose convention).
MQTT_BROKER = os.getenv("MQTT_BROKER") or os.getenv("MQTT_HOST", "host.docker.internal")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "fire_detection_pi")
MQTT_USERNAME = os.getenv("MQTT_USERNAME", "")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", "")
MQTT_TLS_ENABLED = os.getenv("MQTT_TLS_ENABLED", "false").lower() in ("1", "true", "yes")
MQTT_CA_CERT = os.getenv("MQTT_CA_CERT", "")
MQTT_TLS_INSECURE = os.getenv("MQTT_TLS_INSECURE", "false").lower() in ("1", "true", "yes")

# Topic handling (supports BASE or direct override)
BASE_TOPIC = os.getenv("MQTT_BASE_TOPIC", "fire_detection")

MQTT_TOPIC_EVENTS = os.getenv(
    "MQTT_TOPIC_EVENTS",
    f"{BASE_TOPIC}/events"
)

MQTT_TOPIC_STATUS = os.getenv(
    "MQTT_TOPIC_STATUS",
    f"{BASE_TOPIC}/status"
)

MQTT_TOPIC_VISION = os.getenv(
    "MQTT_TOPIC_VISION",
    f"{BASE_TOPIC}/vision"
)

MQTT_STATUS_INTERVAL = 10 # seconds between heartbeat publishes

# Simulation Settings
# Path to the JSON flag file written by the simulation GUI
# main.py reads this file each loop iteration
SIM_FLAG_FILE = os.getenv("SIM_FLAG_FILE", "/tmp/fire_sim_flags.json")

# Default flag state (used if file is missing or unreadable)
SIM_DEFAULT_FLAGS = {
    "fire_sim": False, # full fire scenario (gas + temp + vision)
    "gas_only_sim": False, # only MQ2 triggered
    "temp_only_sim": False, # only DHT22 triggered
    "manual_alarm": False, # force alarm on regardless of score
    "manual_lock": False, # force door locked regardless of state
    "manual_unlock": False, # force door unlocked regardless of state
    "manual_reset": False, # reset fire latch - clears FIRE state when sensors are safe
}

# Main Loop
LOOP_INTERVAL = 0.1 # seconds - main loop polling rate (100 ms)
