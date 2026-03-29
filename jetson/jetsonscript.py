import os
# Ensure CUDA libraries can be found by PyTorch and ONNX Runtime
os.environ["LD_LIBRARY_PATH"] = f"/usr/local/cuda-12.6/lib64:/usr/local/cuda/lib64:{os.environ.get('LD_LIBRARY_PATH', '')}"

import sys
import importlib.util

# Surgically import system OpenCV to avoid version conflicts with other packages like 'sympy'
try:
    spec = importlib.util.spec_from_file_location("cv2", "/usr/lib/python3/dist-packages/cv2.cpython-310-aarch64-linux-gnu.so")
    cv2 = importlib.util.module_from_spec(spec)
    sys.modules["cv2"] = cv2
    spec.loader.exec_module(cv2)
    print("✅ Successfully loaded system OpenCV with GStreamer support.")
except Exception as e:
    print(f"⚠️ Warning: Could not surgically load system OpenCV ({e}). Falling back to default import.")
    import cv2
import json
import time
from collections import deque
from ultralytics import YOLO
import paho.mqtt.client as mqtt

# --- CONFIGURATION ---
PI_IP = "192.168.1.6"  # Replace with actual Raspberry Pi IP address
MQTT_TOPIC_VISION = "fire_detection/vision"

# Path logic to find the model from either the root or /jetson folder
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
MODEL_PATH = os.path.join(ROOT_DIR, "fire_orin_v1", "fire_orin_best.engine")

# Latency log — reset on every script start (open in write mode)
LATENCY_LOG_PATH = os.path.join(SCRIPT_DIR, "first_detection_latency.txt")
with open(LATENCY_LOG_PATH, "w") as _f:
    _f.write(f"Jetson first-detection latency log\nScript started: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
_first_detection_logged = False
_detection_count = 0       # skip first N confirmed detections before logging
_DETECTION_SKIP = 3        # ignore first 3 detections (warm-up artifact)

CONF_THRESHOLD = 0.4
HISTORY_WINDOW = 5
ALERT_THRESHOLD = 1

# 1. Initialize MQTT for communication with Raspberry Pi
mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
try:
    mqtt_client.connect(PI_IP, 1883, 60)
    mqtt_client.loop_start()  # Start the background network loop
    print(f"✅ Connected and started MQTT loop for Pi at {PI_IP}")
except Exception as e:
    print(f"❌ MQTT Connection failed: {e}. Running in local-only mode.")

# 2. Load the optimized TensorRT engine
# Ensure the .engine file is in the same directory as this script
model = YOLO(MODEL_PATH, task='detect')

# 3. Initialize Temporal Consistency Queue
detection_history = deque(maxlen=HISTORY_WINDOW)

def gstreamer_pipeline(
    sensor_id=0,
    capture_width=1280,
    capture_height=720,
    display_width=1280,
    display_height=720,
    framerate=30,
    flip_method=0,
):
    return (
        "nvarguscamerasrc sensor-id=%d ! "
        "video/x-raw(memory:NVMM), "
        "width=(int)%d, height=(int)%d, "
        "format=(string)NV12, framerate=(fraction)%d/1 ! "
        "nvvidconv flip-method=%d ! "
        "video/x-raw, width=(int)%d, height=(int)%d, format=(string)BGRx ! "
        "videoconvert ! "
        "video/x-raw, format=(string)BGR ! appsink"
        % (
            sensor_id,
            capture_width,
            capture_height,
            framerate,
            flip_method,
            display_width,
            display_height,
        )
    )

pipeline = gstreamer_pipeline(flip_method=0)
cap = cv2.VideoCapture(pipeline, cv2.CAP_GSTREAMER)

if not cap.isOpened():
    print("❌ ERROR: Could not open camera with GStreamer pipeline. Please check your camera connection or nvargus-daemon.")
    exit(1)

print("🔥 Warming up TensorRT engine with real camera frames...")
_WARMUP_FRAMES = 10
_warmed = 0
while _warmed < _WARMUP_FRAMES:
    ret, _wframe = cap.read()
    if not ret:
        break
    model.predict(_wframe, conf=CONF_THRESHOLD, verbose=False)
    _warmed += 1
    print(f"  Warm-up {_warmed}/{_WARMUP_FRAMES}", end='\r')
print("\n✅ Warm-up done.")
del _wframe, _warmed

print("🚀 Starting Stream...")

while cap.isOpened():
    loop_start = time.time()
    
    # 1. Capture Time
    ret, frame = cap.read()
    if not ret: break
    capture_done = time.time()

    # 2. Inference Time
    results = model.predict(frame, conf=CONF_THRESHOLD, verbose=False)
    inference_done = time.time()

    detected_in_frame = False
    for box in results[0].boxes:
        if box.cls[0] in [0, 1]: # 0=fire, 1=smoke
            detected_in_frame = True
            break

    detection_history.append(detected_in_frame)

    # Confirmed alert if detected in majority of recent frames
    is_fire_confirmed = sum(detection_history) >= ALERT_THRESHOLD

    # --- NETWORK UPDATE ---
    # Send confidence to the Pi (1.0 if confirmed, 0.0 otherwise)
    # t_sent is embedded so the Pi can measure MQTT transit time
    payload = {
        "confidence": 1.0 if is_fire_confirmed else 0.0,
        "t_sent": time.time(),
    }
    mqtt_start = time.time()
    try:
        if is_fire_confirmed:
            print(f"🔥 ATTENTION: Sending Fire Alert to Pi! Queue: {list(detection_history)}")
        mqtt_client.publish(MQTT_TOPIC_VISION, json.dumps(payload))
    except Exception as e:
        print(f"⚠️ MQTT Publish failed: {e}")
    mqtt_done = time.time()

    # Calculate metrics
    capture_ms  = (capture_done - loop_start) * 1000
    inference_ms = (inference_done - capture_done) * 1000
    mqtt_ms     = (mqtt_done - mqtt_start) * 1000
    total_jetson_ms = (mqtt_done - loop_start) * 1000
    fps = 1.0 / (mqtt_done - loop_start)

    # One-time write after first confirmed detection + publish
    # Skip the first _DETECTION_SKIP detections to avoid warm-up artifacts
    if is_fire_confirmed:
        _detection_count += 1
    if is_fire_confirmed and _detection_count > _DETECTION_SKIP and not _first_detection_logged:
        _first_detection_logged = True
        with open(LATENCY_LOG_PATH, "a") as _f:
            _f.write(f"First detection at: {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            _f.write(f"  capture_ms     : {capture_ms:.3f}\n")
            _f.write(f"  inference_ms   : {inference_ms:.3f}\n")
            _f.write(f"  mqtt_publish_ms: {mqtt_ms:.3f}\n")
            _f.write(f"  total_jetson_ms: {total_jetson_ms:.3f}\n")
        print(f"[Latency] First detection logged to {LATENCY_LOG_PATH}")

    # Print performance every 30 frames (about once a second)
    if int(time.time() % 1.0) == 0:
        print(
            f"📊 Jetson: Capture {capture_ms:.1f}ms | "
            f"Inference {inference_ms:.1f}ms | "
            f"MQTT pub {mqtt_ms:.1f}ms | "
            f"Total {total_jetson_ms:.1f}ms | "
            f"{fps:.1f} FPS",
            end='\r'
        )

    # --- LOCAL UI ---
    if is_fire_confirmed:
        cv2.putText(frame, "🔥 FIRE ALERT CONFIRMED", (50, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

# commented out because it is taking up a lot of resources
    annotated_frame = results[0].plot()
    cv2.imshow("Jetson Fire Detection", annotated_frame)
    if cv2.waitKey(1) & 0xFF == ord('q'): break

cap.release()
mqtt_client.loop_stop()
cv2.destroyAllWindows()
