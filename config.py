import os
from dotenv import load_dotenv

load_dotenv()

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
TEMP_ON_THRESHOLD = 31.6 # °C - trigger if avg exceeds this
TEMP_OFF_THRESHOLD = 31.3 # °C - clear flag when avg drops below this

# MQ2 Gas Sensor Settings
GAS_CONSECUTIVE_REQ = 2 # consecutive positive reads before flagging (debounce against single-sample noise)

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
WEIGHT_GAS = 0.4 # MQ2 is fast and sensitive - high weight
WEIGHT_TEMP = 0.2 # DHT22 is slow and ambient - lower weight
WEIGHT_VISION = 0.4 # Jetson AI result - slotted in later (0.0 until then)

FIRE_THRESHOLD = 0.5 # score >= this triggers fire response
# Without vision: max possible = 0.6 (gas + temp)
# Tune down to 0.4 to trigger on gas alone if needed

# Main Loop
LOOP_INTERVAL = 0.1 # seconds - main loop polling rate (100 ms)
