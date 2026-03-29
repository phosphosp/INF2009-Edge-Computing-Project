import os
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
MODEL_PATH = os.path.join(ROOT_DIR, "fire_orin_v1", "fire_orin_best.onnx")

CONF_THRESHOLD = 0.4
HISTORY_WINDOW = 5
ALERT_THRESHOLD = 3

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

    # Calculate metrics
    capture_ms = (capture_done - loop_start) * 1000
    inference_ms = (inference_done - capture_done) * 1000
    fps = 1.0 / (time.time() - loop_start)

    # Print performance every 30 frames (about once a second)
    if int(time.time() % 1.0) == 0:
        print(f"📊 Perf: Capture {capture_ms:.1f}ms | Inference {inference_ms:.1f}ms | {fps:.1f} FPS", end='\r')

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
    payload = {"confidence": 1.0 if is_fire_confirmed else 0.0}
    try:
        # Debug: Print when we attempt to send a confirmation
        if is_fire_confirmed:
            print(f"🔥 ATTENTION: Sending Fire Alert to Pi! Queue: {list(detection_history)}")
        
        mqtt_client.publish(MQTT_TOPIC_VISION, json.dumps(payload))
    except Exception as e:
        print(f"⚠️ MQTT Publish failed: {e}")

    # --- LOCAL UI ---
    if is_fire_confirmed:
        cv2.putText(frame, "🔥 FIRE ALERT CONFIRMED", (50, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

    annotated_frame = results[0].plot()
    cv2.imshow("Jetson Fire Detection", annotated_frame)
    if cv2.waitKey(1) & 0xFF == ord('q'): break

cap.release()
mqtt_client.loop_stop()
cv2.destroyAllWindows()
