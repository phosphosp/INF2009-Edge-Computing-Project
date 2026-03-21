# Verifies MQTT publishing without any hardware.
# Requires mosquitto broker running on the Pi:
#   sudo apt install mosquitto mosquitto-clients
#   sudo systemctl start mosquitto

# Run the subscriber in one terminal to watch messages arrive:
#   mosquitto_sub -h localhost -t "fire_detection/#" -v

# Then run this test in another terminal:
#   python test_mqtt.py

import time
import sys
import os

# Allow running from tests folder
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from comms.mqtt_client import MQTTClient
from utils.fusion import FusionResult, FireDecision

print("=" * 50)
print("MQTT Client Test")
print("=" * 50)
print(f"Broker: {config.MQTT_BROKER}:{config.MQTT_PORT}")
print(f"Client ID: {config.MQTT_CLIENT_ID}")
print(f"Auth user: {config.MQTT_USERNAME if config.MQTT_USERNAME else '(anonymous)'}")
print(f"Topics: {config.MQTT_TOPIC_EVENTS}")
print(f"        {config.MQTT_TOPIC_STATUS}")
print()
print("Watch messages in another terminal with:")
print(f"  mosquitto_sub -h {config.MQTT_BROKER} -p {config.MQTT_PORT} -t '{config.BASE_TOPIC}/#' -v")
print()

mqtt = MQTTClient()

# Give connection a moment to establish
time.sleep(1.5)

print(f"Connected: {mqtt.connected}\n")

start_time = time.time()

# Helper: build a mock FusionResult
def make_result(decision, score, gas, temp, sim=False):
    return FusionResult(
        decision = decision,
        fire_score = score,
        gas_detected = gas,
        temp_flagged = temp,
        vision_confidence = 0.0,
        raw_gas_detected = gas,
        raw_temp_flagged = temp,
        raw_avg_temp = 28.5,
        sim_active = sim,
        active_sim_flags = ["fire_sim"] if sim else [],
    )

# Test 1: CLEAR state
print("Publishing CLEAR event...")
r = make_result(FireDecision.CLEAR, 0.0, False, False)
mqtt.publish_event(r, door_state="LOCKED")
time.sleep(0.5)

# Test 2: WARNING state (dedup check - publish once not twice)
print("Publishing WARNING event (should publish once)...")
r = make_result(FireDecision.WARNING, 0.4, True, False)
mqtt.publish_event(r, door_state="LOCKED")
mqtt.publish_event(r, door_state="LOCKED") # same decision - should be skipped
time.sleep(0.5)

# Test 3: FIRE state
print("Publishing FIRE event...")
r = make_result(FireDecision.FIRE, 0.6, True, True)
mqtt.publish_event(r, door_state="UNLOCKED")
time.sleep(0.5)

# Test 4: Simulated fire
print("Publishing simulated FIRE event...")
r = make_result(FireDecision.CLEAR, 0.0, False, False) # reset decision
mqtt._last_decision = None # force republish
r = make_result(FireDecision.FIRE, 0.9, True, True, sim=True)
mqtt.publish_event(r, door_state="UNLOCKED")
time.sleep(0.5)

# Test 5: Status heartbeat
print("Publishing status heartbeat...")
mqtt._last_status_time = 0 # force immediate publish
r = make_result(FireDecision.FIRE, 0.9, True, True)
mqtt.publish_status(r, door_state="UNLOCKED",
                    uptime_seconds=time.time() - start_time)
time.sleep(0.5)

mqtt.cleanup()

print()
print("Done. Check your mosquitto_sub terminal for 4 event messages + 1 status.")