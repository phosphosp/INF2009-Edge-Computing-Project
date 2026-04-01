# Run on the Pi to verify alarm and smart door
# Tests each component in isolation before combining them

import time
import sys
import os

# Allow running from tests folder
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from actuators.alarm import Alarm, AlarmState
from actuators.smart_door import SmartDoor

# Choose which test to run by setting TEST_MODE:
#   "alarm" - cycles through CLEAR -> WARNING -> FIRE -> CLEAR
#   "door" - waits for RFID scan, then tests fire mode
#   "both" - runs alarm test then door test sequentially
TEST_MODE = "both"

def test_alarm():
    print("\n--- Alarm Test ---")
    alarm = Alarm()

    print("State: CLEAR (2s)...")
    alarm.clear()
    time.sleep(2)

    print("State: WARNING - LED on, buzzer off (3s)...")
    alarm.trigger_warning()
    time.sleep(3)

    print("State: FIRE - LED on, buzzer on (3s)...")
    alarm.trigger_fire()
    time.sleep(3)

    print("State: CLEAR (2s)...")
    alarm.clear()
    time.sleep(2)

    alarm.cleanup()
    print("Alarm test complete.\n")

def test_door():
    print("\n--- Smart Door Test ---")
    print("Part 1: Scan an RFID card (waiting 10s)...")
    print("        If card ID not in AUTHORISED_CARDS, it will show as unauthorised.")
    print("        Copy the printed card ID into config.AUTHORISED_CARDS to authorise it.\n")

    door = SmartDoor()

    # Part 1: Normal mode - scan card
    start = time.time()
    while time.time() - start < 10:
        result = door.update()
        if result["event"]:
            print(f"  Event: {result['event']}  Card: {result.get('card_id')}  "
                  f"Door: {result['door_state']}")
        time.sleep(0.1)

    # Part 2: Simulate fire mode
    print("\nPart 2: Entering FIRE MODE (door forces open)...")
    door.set_fire_mode(True)
    time.sleep(3)

    print("Part 3: Exiting FIRE MODE (door relocks)...")
    door.set_fire_mode(False)
    time.sleep(2)

    door.cleanup()
    print("Door test complete.\n")

try:
    if TEST_MODE == "alarm":
        test_alarm()
    elif TEST_MODE == "door":
        test_door()
    elif TEST_MODE == "both":
        test_alarm()
        test_door()

except KeyboardInterrupt:
    print("\nStopped by user.")
