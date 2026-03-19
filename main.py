# Fire Detection System Orchestrator

# Startup order:
#   1. Initialise all hardware (sensors, actuators, comms)
#   2. Enter main loop at LOOP_INTERVAL (100ms)
#   3. Each tick:
#       a. Read sensors (gas instant, temp from cache)
#       b. Apply sim flags via fusion engine
#       c. Decide alarm state from FusionResult
#       d. Apply manual overrides (force alarm/lock/unlock)
#       e. Update smart door (RFID poll + fire mode sync)
#       f. Publish MQTT event (on change) + status (on interval)
#       g. Log to console
#   4. On KeyboardInterrupt or exception: clean shutdown of all hardware

# Run with:
#   python main.py

# Run alongside simulation GUI in a second terminal:
#   python sim/sim_gui.py

import time
import signal
import sys
import os

# Allow running from root folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from sensors.gas_sensor import GasSensor
from sensors.temp_sensor import TempSensor
from actuators.alarm import Alarm, AlarmState
from actuators.smart_door import SmartDoor
from comms.mqtt_client import MQTTClient
from utils.fusion import evaluate, FireDecision
from sim.sim_flags import get_all as get_sim_flags

# Shutdown handler
_shutdown_requested = False

def _handle_signal(signum, frame):
    global _shutdown_requested
    print("\n[Main] Shutdown signal received...")
    _shutdown_requested = True

signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)

# Console logging helper
# How many loop ticks between console log lines (avoid spamming terminal)
LOG_EVERY_N_TICKS = 10 # 10 ticks × 100ms = log every ~1 second

def _log(tick: int, result, door_state: str, door_event):
    if tick % LOG_EVERY_N_TICKS != 0:
        return

    sim_tag = f" [SIM:{','.join(result.active_sim_flags)}]" if result.sim_active else ""
    door_tag = f" DOOR:{door_state}"
    event_tag = f" RFID:{door_event}" if door_event else ""

    print(
        f"[{time.strftime('%H:%M:%S')}] "
        f"{result.decision.value:<8} "
        f"score={result.fire_score:.2f}  "
        f"gas={result.gas_detected}  "
        f"temp={result.temp_flagged}  "
        f"avg={f'{result.raw_avg_temp:.1f}C' if result.raw_avg_temp else 'N/A':<8}"
        f"{door_tag}{event_tag}{sim_tag}"
    )

# Main
def main():
    print("=" * 60)
    print("  Fire Detection System - Starting up")
    print("=" * 60)

    # Initialise hardware
    print("[Main] Initialising sensors...")
    gas  = GasSensor()
    temp = TempSensor()

    print("[Main] Initialising actuators...")
    alarm = Alarm()
    door  = SmartDoor()

    print("[Main] Initialising MQTT...")
    mqtt = MQTTClient()

    start_time = time.time()
    tick = 0

    print("\n[Main] System ready. Entering main loop.")
    print("[Main] Press Ctrl+C to stop.\n")

    # Main loop
    try:
        while not _shutdown_requested:
            loop_start = time.time()
            tick += 1

            # 1. Read sensors
            gas_data  = gas.read()
            temp_data = temp.read()

            gas_detected = gas_data["detected"]
            temp_flagged = temp_data["flagged"]
            avg_temp = temp_data["avg_temp"]

            # 2. Fusion - compute fire score + apply sim overrides
            result = evaluate(
                gas_detected = gas_detected,
                temp_flagged = temp_flagged,
                vision_confidence = 0.0, # placeholder until Jetson integrated
            )
            # Attach raw avg_temp for logging/MQTT (fusion doesn't read it directly)
            result.raw_avg_temp = avg_temp

            # 3. Drive alarm from fusion decision
            if result.decision == FireDecision.FIRE:
                alarm.set_state(AlarmState.FIRE)

            elif result.decision == FireDecision.WARNING:
                alarm.set_state(AlarmState.WARNING)

            else:
                alarm.set_state(AlarmState.CLEAR)

            # 4. Apply manual overrides from sim GUI
            # These bypass the score - direct hardware control for demos
            flags = get_sim_flags()

            if flags.get("manual_alarm"):
                alarm.set_state(AlarmState.FIRE)

            if flags.get("manual_lock"):
                door.force_lock()

            elif flags.get("manual_unlock"):
                door.force_unlock()

            # 5. Sync smart door fire mode with current decision
            # Fire mode = FIRE decision OR manual_alarm override active
            fire_active = (
                result.decision == FireDecision.FIRE
                or flags.get("manual_alarm", False)
            )
            door.set_fire_mode(fire_active)

            # 6. Poll RFID + get door event (non-blocking)
            door_result = door.update()
            door_event = door_result.get("event")   # None | "authorised" | "unauthorised"
            door_state = door_result["door_state"]

            # 7. Publish MQTT
            uptime = time.time() - start_time
            mqtt.publish_event(result, door_state)
            mqtt.publish_status(result, door_state, uptime)

            # 8. Console log (throttled)
            _log(tick, result, door_state, door_event)

            # 9. Maintain loop timing
            elapsed = time.time() - loop_start
            sleep_time = config.LOOP_INTERVAL - elapsed
            if sleep_time > 0:
                time.sleep(sleep_time)
            elif elapsed > config.LOOP_INTERVAL * 2:
                # Only warn if significantly over budget
                print(f"[Main] WARNING: loop took {elapsed*1000:.1f}ms "
                      f"(budget: {config.LOOP_INTERVAL*1000:.0f}ms)")

    # Shutdown
    except Exception as e:
        print(f"\n[Main] Unexpected error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        print("\n[Main] Shutting down...")

        # Turn everything off in safe order:
        # 1. Alarm off first (stop noise immediately)
        # 2. Exit fire mode so door can relock
        # 3. Clean up all hardware
        try:
            alarm.clear()
        except Exception:
            pass

        try:
            door.set_fire_mode(False)
            door.cleanup()
        except Exception:
            pass

        try:
            gas.cleanup()
            temp.cleanup()
        except Exception:
            pass

        try:
            mqtt.cleanup()
        except Exception:
            pass

        print("[Main] Shutdown complete.")

if __name__ == "__main__":
    main()