# Pi-side latency benchmark

# Measures the full Pi pipeline per message from Jetson:
#   network_transit_ms  = recv_time - t_sent  (requires chrony on both devices)
#   fusion_ms           = evaluate() call
#   actuation_ms        = alarm + door update
#   total_ms            = transit + fusion + actuation

# Run order:
#   1. Start this script on Pi first
#   2. Run benchmark_latency.py on Jetson

# Results written to: tests/latency_benchmark.csv

# Run with:
#   python tests/test_latency.py

import sys
import os
import time
import json
import csv
import statistics
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import paho.mqtt.client as mqtt
from utils.fusion import evaluate
from actuators.alarm import Alarm, AlarmState
from actuators.smart_door import SmartDoor

N_SAMPLES  = 100
OUT_CSV    = os.path.join(os.path.dirname(os.path.abspath(__file__)), "latency_benchmark.csv")


def stats(label, data):
    data_sorted = sorted(data)
    n   = len(data_sorted)
    avg = sum(data_sorted) / n
    p50 = data_sorted[int(n * 0.50)]
    p95 = data_sorted[int(n * 0.95)]
    p99 = data_sorted[int(n * 0.99)]
    print(
        f"  {label:<20} min={data_sorted[0]:.2f}ms  avg={avg:.2f}ms  "
        f"p50={p50:.2f}ms  p95={p95:.2f}ms  p99={p99:.2f}ms  max={data_sorted[-1]:.2f}ms"
    )


def main():
    alarm = Alarm()
    door  = SmartDoor()

    rows           = []
    transit_times  = []
    fusion_times   = []
    actuation_times= []
    total_times    = []
    done           = threading.Event()

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            client.subscribe(config.MQTT_TOPIC_VISION, qos=1)
            print(f"[Pi] Subscribed to {config.MQTT_TOPIC_VISION} — waiting for Jetson...")
        else:
            print(f"[Pi] Broker connection refused rc={rc}")

    def on_message(client, userdata, msg):
        recv_wall = time.time()

        try:
            payload = json.loads(msg.payload.decode())
        except Exception as e:
            print(f"[Pi] Bad payload: {e}")
            return

        t_sent = payload.get("t_sent")
        if t_sent is None:
            print("[Pi] No t_sent in payload — is Jetson sending it?")
            return

        transit_ms = (recv_wall - t_sent) * 1000

        # Fusion
        t0 = time.perf_counter()
        evaluate(gas_detected=True, temp_flagged=True, vision_confidence=1.0)
        fusion_ms = (time.perf_counter() - t0) * 1000

        # Actuation
        t1 = time.perf_counter()
        alarm.set_state(AlarmState.FIRE)
        door.set_fire_mode(True)
        door.update()
        actuation_ms = (time.perf_counter() - t1) * 1000

        total_ms = transit_ms + fusion_ms + actuation_ms
        sample   = len(rows) + 1

        transit_times.append(transit_ms)
        fusion_times.append(fusion_ms)
        actuation_times.append(actuation_ms)
        total_times.append(total_ms)
        rows.append([sample, round(transit_ms, 3), round(fusion_ms, 3),
                     round(actuation_ms, 3), round(total_ms, 3)])

        print(
            f"  [{sample:>3}/{N_SAMPLES}]  "
            f"transit={transit_ms:.1f}ms  "
            f"fusion={fusion_ms:.2f}ms  "
            f"actuation={actuation_ms:.2f}ms  "
            f"total={total_ms:.1f}ms"
        )

        if sample >= N_SAMPLES:
            done.set()

    client = mqtt.Client(client_id="pi_latency_bench")
    client.on_connect = on_connect
    client.on_message = on_message

    try:
        client.connect(config.MQTT_BROKER, config.MQTT_PORT, keepalive=60)
    except Exception as e:
        print(f"[Pi] Cannot connect to broker: {e}")
        return

    client.loop_start()

    print("=" * 65)
    print("  Pi Latency Benchmark — waiting for Jetson messages")
    print("=" * 65)

    done.wait(timeout=60)
    client.loop_stop()
    client.disconnect()

    try:
        alarm.clear()
        door.set_fire_mode(False)
        door.cleanup()
    except Exception:
        pass

    if not rows:
        print("[Pi] No messages received — check Jetson is running and connected.")
        return

    # Write CSV
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["sample", "transit_ms", "fusion_ms", "actuation_ms", "total_ms"])
        w.writerows(rows)
    print(f"\n[Pi] Results saved to {OUT_CSV}")

    # Print summary
    print("\n" + "=" * 65)
    print("  Summary")
    print("=" * 65)
    stats("transit_ms",   transit_times)
    stats("fusion_ms",    fusion_times)
    stats("actuation_ms", actuation_times)
    stats("total_ms",     total_times)
    print()


if __name__ == "__main__":
    main()
