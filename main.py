# Fire Detection System Orchestrator

# Startup order:
#   1. Initialise all hardware (sensors, actuators, comms)
#   2. Enter main loop at LOOP_INTERVAL (100ms)
#   3. Each tick:
#       a. Read sensors (gas instant, temp from cache)
#       b. Apply sim flags via fusion engine
#       c. Decide alarm state from FusionResult (with fire latch)
#       d. Apply manual overrides (force alarm/lock/unlock/reset)
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
from datetime import datetime

# Allow running from root folder
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import config
from sensors.gas_sensor import GasSensor
from sensors.temp_sensor import TempSensor
from actuators.alarm import Alarm, AlarmState
from actuators.smart_door import SmartDoor
from comms.mqtt_client import MQTTClient
from utils.fusion import evaluate, FireDecision
from utils.latency_logger import LatencyLogger
from sim.sim_flags import get_all as get_sim_flags, set_flag

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

def _now_ms() -> str:
    """Return current time as HH:MM:SS:mmm"""
    now = datetime.now()
    return now.strftime('%H:%M:%S:') + f"{now.microsecond // 1000:03d}"

def _log(tick: int, result, door_state: str, door_event, alarm_latched: bool):
    if tick % LOG_EVERY_N_TICKS != 0:
        return

    avg_str   = f"{result.raw_avg_temp:.1f}C" if result.raw_avg_temp else "N/A"
    latch_str = "  LATCHED" if alarm_latched else ""
    sim_str   = f"  SIM:{','.join(result.active_sim_flags)}" if result.sim_active else ""
    rfid_str  = f"  rfid:{door_event}" if door_event else ""

    # Line 1: time, decision, score, vision, latch/sim flags
    print(
        f"[{_now_ms()}] {result.decision.value:<8} "
        f"score={result.fire_score:.2f}  vision={result.vision_confidence:.2f}"
        f"{latch_str}{sim_str}"
    )
    # Line 2: indented sensor readings and door state
    print(
        f"             "
        f"gas={str(result.gas_detected):<6}"
        f"temp={str(result.temp_flagged):<6}"
        f"avg={avg_str:<8}"
        f"door={door_state}"
        f"{rfid_str}"
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

    print("[Main] Initialising latency logger...")
    logger = LatencyLogger()

    start_time = time.time()
    tick = 0

    # Fire latch state
    # Once FIRE is triggered, alarm holds until manual_reset is pressed
    # even if sensors clear. WARNING clears freely.
    _alarm_latched = False

    print("\n[Main] System ready. Entering main loop.")
    print("[Main] Press Ctrl+C to stop.\n")

    # Main loop
    try:
        while not _shutdown_requested:

            # Latency tracking start
            loop_start = time.time()
            tick += 1
            logger.start()

            # 1. Read sensors
            gas_data  = gas.read()
            temp_data = temp.read()

            gas_detected = gas_data["detected"]
            temp_flagged = temp_data["flagged"]
            avg_temp = temp_data["avg_temp"]

            logger.mark("gas_read") # includes both gas + temp (both are fast/cached)

            # temp_read mark is separated for clarity even though TempSensor.read()
            # is non-blocking (returns cached value from background thread)
            logger.mark("temp_read")

            # 2. Fusion - compute fire score + apply sim overrides
            result = evaluate(
                gas_detected = gas_detected,
                temp_flagged = temp_flagged,
                vision_confidence = 0.0, # placeholder until Jetson integrated
            )
            # Attach raw avg_temp for logging/MQTT (fusion doesn't read it directly)
            result.raw_avg_temp = avg_temp

            logger.mark("fusion")

            # Vision mark - always 0.0 until Jetson TCP client is integrated
            logger.mark("vision")

            # 3. Load sim flags early - needed for latch reset and overrides
            flags = get_sim_flags()

            # 4. Handle manual reset - clears fire latch if sensors are now safe
            # Auto-clears the flag after consuming it so it acts as a one-shot pulse
            if flags.get("manual_reset"):
                if result.decision != FireDecision.FIRE and not flags.get("manual_alarm"):
                    _alarm_latched = False
                    print("[Main] Fire latch reset - system returning to normal")
                else:
                    print("[Main] Reset ignored - fire condition still active")
                set_flag("manual_reset", False)

            # 5. Latch fire state
            # Once FIRE is reached, hold it until manually reset
            if result.decision == FireDecision.FIRE:
                _alarm_latched = True

            # 6. Drive alarm from fusion decision + latch
            if _alarm_latched:
                alarm.set_state(AlarmState.FIRE)
            elif result.decision == FireDecision.WARNING:
                alarm.set_state(AlarmState.WARNING)
            else:
                alarm.set_state(AlarmState.CLEAR)

            # 7. Apply manual overrides from sim GUI
            # These bypass the score - direct hardware control for demos
            if flags.get("manual_alarm"):
                alarm.set_state(AlarmState.FIRE)

            if flags.get("manual_lock"):
                door.force_lock()
            elif flags.get("manual_unlock"):
                door.force_unlock()

            # 8. Sync smart door fire mode with current decision
            # Fire mode = latched FIRE OR manual_alarm override active
            fire_active = (
                _alarm_latched
                or flags.get("manual_alarm", False)
            )
            door.set_fire_mode(fire_active)

            # 9. Poll RFID + get door event (non-blocking)
            door_result = door.update()
            door_event = door_result.get("event")   # None | "authorised" | "unauthorised"
            door_state = door_result["door_state"]

            logger.mark("actuation")

            # 10. Publish MQTT
            uptime = time.time() - start_time
            mqtt.publish_event(result, door_state)
            mqtt.publish_status(result, door_state, uptime)

            logger.mark("mqtt_publish")

            # 11. Console log (throttled)
            _log(tick, result, door_state, door_event, _alarm_latched)

            # 12. Finish latency tick (writes CSV row, throttled console print)
            logger.finish()

            # 13. Maintain loop timing
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

        try:
            logger.cleanup()
        except Exception:
            pass

        print("[Main] Shutdown complete.")

if __name__ == "__main__":
    main()