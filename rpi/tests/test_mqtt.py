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
def make_result(
    decision,
    score,
    gas,
    temp,
    sim=False,
    vision=0.0,
    raw_avg_temp=28.5,
    sim_flags=None,
):
    return FusionResult(
        decision = decision,
        fire_score = score,
        gas_detected = gas,
        temp_flagged = temp,
        vision_confidence = vision,
        raw_gas_detected = gas,
        raw_temp_flagged = temp,
        raw_avg_temp = raw_avg_temp,
        sim_active = sim,
        active_sim_flags = sim_flags if sim_flags is not None else (["fire_sim"] if sim else []),
    )

# Events: cover decision states, threshold-like scores, door states, sim flags, and varied sensor values
event_scenarios = [
    ("CLEAR baseline", make_result(FireDecision.CLEAR, 0.0, False, False, raw_avg_temp=26.2), "LOCKED"),
    ("WARNING temp-only boundary", make_result(FireDecision.WARNING, 0.2, False, True, raw_avg_temp=31.6), "LOCKED"),
    ("WARNING gas-only", make_result(FireDecision.WARNING, 0.4, True, False, raw_avg_temp=29.4), "LOCKED"),
    ("FIRE gas+temp threshold", make_result(FireDecision.FIRE, 0.5, True, True, raw_avg_temp=35.2), "UNLOCKED"),
    ("FIRE high confidence vision", make_result(FireDecision.FIRE, 0.98, True, True, vision=0.95, raw_avg_temp=68.8), "OPEN"),
    (
        "FIRE simulation",
        make_result(
            FireDecision.FIRE,
            0.9,
            True,
            True,
            sim=True,
            vision=0.9,
            raw_avg_temp=58.1,
            sim_flags=["fire_sim"],
        ),
        "UNLOCKED",
    ),
    (
        "WARNING simulated gas-only",
        make_result(
            FireDecision.WARNING,
            0.4,
            True,
            False,
            sim=True,
            raw_avg_temp=30.4,
            sim_flags=["gas_only_sim"],
        ),
        "LOCKED",
    ),
]

for label, result, door_state in event_scenarios:
    print(f"Publishing event: {label} ...")
    mqtt._last_decision = None  # force event publish so every scenario is emitted
    mqtt.publish_event(result, door_state=door_state)
    time.sleep(0.4)

# Explicit dedup check (same decision twice without reset should skip second publish)
print("Publishing dedup check (second WARNING should be skipped)...")
r = make_result(FireDecision.WARNING, 0.4, True, False, raw_avg_temp=30.0)
mqtt._last_decision = None
mqtt.publish_event(r, door_state="LOCKED")
mqtt.publish_event(r, door_state="LOCKED")
time.sleep(0.4)

# Status heartbeats: cover different payload combinations and uptimes
status_scenarios = [
    make_result(FireDecision.CLEAR, 0.0, False, False, raw_avg_temp=27.1),
    make_result(FireDecision.WARNING, 0.4, True, False, raw_avg_temp=30.5),
    make_result(FireDecision.FIRE, 0.9, True, True, vision=0.8, raw_avg_temp=55.0),
]

for idx, result in enumerate(status_scenarios, start=1):
    print(f"Publishing status heartbeat {idx}/{len(status_scenarios)} ...")
    mqtt._last_status_time = 0  # force immediate publish every loop
    mqtt.publish_status(
        result,
        door_state="UNLOCKED" if result.decision == FireDecision.FIRE else "LOCKED",
        uptime_seconds=(time.time() - start_time) + (idx * 123.4),
    )
    time.sleep(0.4)

mqtt.cleanup()

print()
print("Done. Check your mosquitto_sub terminal for expanded event + status coverage.")