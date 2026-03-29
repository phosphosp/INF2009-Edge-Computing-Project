import os
os.environ["LD_LIBRARY_PATH"] = f"/usr/local/cuda-12.6/lib64:/usr/local/cuda/lib64:{os.environ.get('LD_LIBRARY_PATH', '')}"

import sys
import importlib.util
import time
import json
import paho.mqtt.client as mqtt

spec = importlib.util.spec_from_file_location("cv2", "/usr/lib/python3/dist-packages/cv2.cpython-310-aarch64-linux-gnu.so")
cv2 = importlib.util.module_from_spec(spec)
sys.modules["cv2"] = cv2
spec.loader.exec_module(cv2)

from ultralytics import YOLO

SCRIPT_DIR       = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR         = os.path.dirname(SCRIPT_DIR)
MODEL_PATH       = os.path.join(ROOT_DIR, "fire_orin_v1", "fire_orin_best.engine")
OUT_PATH         = os.path.join(SCRIPT_DIR, "benchmark_results.txt")
CONF             = 0.4
N_WARMUP         = 10
N_RUNS           = 100
PI_IP            = "192.168.1.6"
MQTT_TOPIC       = "fire_detection/vision"

pipeline = (
    "nvarguscamerasrc sensor-id=0 ! "
    "video/x-raw(memory:NVMM), width=1280, height=720, format=NV12, framerate=30/1 ! "
    "nvvidconv ! video/x-raw, width=1280, height=720, format=BGRx ! "
    "videoconvert ! video/x-raw, format=BGR ! appsink"
)

print("Connecting to MQTT broker...")
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
try:
    mqtt_client.connect(PI_IP, 1883, 60)
    mqtt_client.loop_start()
    print(f"  Connected to {PI_IP}")
except Exception as e:
    print(f"  WARNING: MQTT connection failed ({e}) — mqtt_publish_ms will be 0")

print("Loading model...")
model = YOLO(MODEL_PATH, task="detect")

print("Opening camera...")
cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)
if not cap.isOpened():
    print("ERROR: Could not open camera.")
    sys.exit(1)

print(f"Warming up with {N_WARMUP} real frames...")
for i in range(N_WARMUP):
    ret, frame = cap.read()
    if ret:
        model.predict(frame, conf=CONF, verbose=False)
    print(f"  {i+1}/{N_WARMUP}", end="\r")
print("\nWarm-up done.")

print(f"Running {N_RUNS} inference measurements...")
capture_times  = []
inference_times = []
mqtt_times     = []
total_times    = []

for i in range(N_RUNS):
    loop_start   = time.perf_counter()
    ret, frame   = cap.read()
    capture_done = time.perf_counter()

    if not ret:
        print("Camera read failed, stopping.")
        break

    model.predict(frame, conf=CONF, verbose=False)
    inference_done = time.perf_counter()

    payload = json.dumps({"confidence": 1.0, "t_sent": time.time()})
    try:
        mqtt_client.publish(MQTT_TOPIC, payload)
    except Exception:
        pass
    mqtt_done = time.perf_counter()

    capture_times.append((capture_done - loop_start) * 1000)
    inference_times.append((inference_done - capture_done) * 1000)
    mqtt_times.append((mqtt_done - inference_done) * 1000)
    total_times.append((mqtt_done - loop_start) * 1000)

    print(f"  Run {i+1}/{N_RUNS}  infer={inference_times[-1]:.1f}ms  mqtt={mqtt_times[-1]:.2f}ms", end="\r")

cap.release()
mqtt_client.loop_stop()
mqtt_client.disconnect()
print("\nDone. Writing results...")

def stats(label, data):
    data_sorted = sorted(data)
    n = len(data_sorted)
    avg  = sum(data_sorted) / n
    mn   = data_sorted[0]
    mx   = data_sorted[-1]
    p50  = data_sorted[int(n * 0.50)]
    p95  = data_sorted[int(n * 0.95)]
    p99  = data_sorted[int(n * 0.99)]
    return (
        f"{label}:\n"
        f"  min={mn:.2f}ms  avg={avg:.2f}ms  max={mx:.2f}ms\n"
        f"  p50={p50:.2f}ms  p95={p95:.2f}ms  p99={p99:.2f}ms\n"
    )

lines = [
    f"Benchmark: {N_RUNS} runs on real camera frames\n"
    f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n",
    stats("capture_ms      (cap.read block time)", capture_times),
    stats("inference_ms    (model.predict)", inference_times),
    stats("mqtt_publish_ms (publish enqueue)", mqtt_times),
    stats("total_ms        (capture + inference + mqtt)", total_times),
    "\nAll inference_ms values:\n",
    "  " + "  ".join(f"{t:.1f}" for t in inference_times) + "\n",
    "\nAll mqtt_publish_ms values:\n",
    "  " + "  ".join(f"{t:.2f}" for t in mqtt_times) + "\n",
]

with open(OUT_PATH, "w") as f:
    f.writelines(lines)

for line in lines[:-2]:
    print(line)

print(f"Full results saved to {OUT_PATH}")
