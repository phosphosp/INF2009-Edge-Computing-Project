import os
import cv2
import json
from collections import deque
from ultralytics import YOLO
import paho.mqtt.client as mqtt

# --- CONFIGURATION ---
PI_IP = "192.168.2.4"  # Replace with actual Raspberry Pi IP address
MQTT_TOPIC_VISION = "fire_detection/vision"

# Path logic to find the model from either the root or /jetson folder
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(SCRIPT_DIR)
MODEL_PATH = os.path.join(ROOT_DIR, "fire_orin_v1", "fire_orin_best.engine")

CONF_THRESHOLD = 0.4
HISTORY_WINDOW = 5
ALERT_THRESHOLD = 3

# 1. Initialize MQTT for communication with Raspberry Pi
mqtt_client = mqtt.Client()
try:
    mqtt_client.connect(PI_IP, 1883, 60)
    print(f"✅ Connected to Pi MQTT Broker at {PI_IP}")
except Exception as e:
    print(f"❌ MQTT Connection failed: {e}. Running in local-only mode.")

# 2. Load the optimized TensorRT engine
# Ensure the .engine file is in the same directory as this script
model = YOLO(MODEL_PATH, task='detect')

# 3. Initialize Temporal Consistency Queue
detection_history = deque(maxlen=HISTORY_WINDOW)

cap = cv2.VideoCapture(0)
print("🚀 Starting Stream...")

while cap.isOpened():
    ret, frame = cap.read()
    if not ret: break

    results = model.predict(frame, conf=CONF_THRESHOLD, verbose=False)

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
        mqtt_client.publish(MQTT_TOPIC_VISION, json.dumps(payload))
    except:
        pass

    # --- LOCAL UI ---
    if is_fire_confirmed:
        cv2.putText(frame, "🔥 FIRE ALERT CONFIRMED", (50, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)

    annotated_frame = results[0].plot()
    cv2.imshow("Jetson Fire Detection", annotated_frame)
    if cv2.waitKey(1) & 0xFF == ord('q'): break

cap.release()
cv2.destroyAllWindows()