# Non-blocking MQTT publisher with dual-broker support.

# Responsibilities:
# LOCAL broker (localhost) - subscribe to Jetson vision topic
# CLOUD broker (AWS)       - publish fire events and status heartbeats
# Both connections are non-fatal if broker is unavailable
# Reconnect automatically if connection drops

# Topics:
#   fire_detection/vision  - received from Jetson (local broker)
#   fire_detection/events  - state change alerts published to cloud
#   fire_detection/status  - periodic heartbeat published to cloud

# Payload format: JSON string

import json
import time
import paho.mqtt.client as mqtt
import config
from utils.fusion import FusionResult

class MQTTClient:
    def __init__(self):
        self._connected_local = False
        self._connected_cloud = False
        self._last_status_time = 0.0
        self._last_decision = None

        # Vision data received from Jetson via local broker
        self.vision_confidence = 0.0
        self.mqtt_transit_ms: float = 0.0
        self.vision_detected_at: float | None = None

        # Local client (Pi <-> Jetson)
        self._local = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=config.MQTT_CLIENT_ID)
        self._local.on_connect    = self._on_local_connect
        self._local.on_disconnect = self._on_local_disconnect
        self._local.on_message    = self._on_message
        self._local.loop_start()
        self._connect(self._local, config.MQTT_BROKER, config.MQTT_PORT, "local")

        # Cloud client (Pi -> Cloud dashboard)
        self._cloud = None
        if config.MQTT_CLOUD_BROKER:
            self._cloud = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1, client_id=config.MQTT_CLOUD_CLIENT_ID)
            self._cloud.on_connect    = self._on_cloud_connect
            self._cloud.on_disconnect = self._on_cloud_disconnect
            if config.MQTT_USERNAME:
                self._cloud.username_pw_set(
                    username=config.MQTT_USERNAME,
                    password=config.MQTT_PASSWORD or None,
                )
            if config.MQTT_TLS_ENABLED:
                tls_kwargs = {}
                if config.MQTT_CA_CERT:
                    tls_kwargs["ca_certs"] = config.MQTT_CA_CERT
                self._cloud.tls_set(**tls_kwargs)
                self._cloud.tls_insecure_set(config.MQTT_TLS_INSECURE)
            self._cloud.loop_start()
            self._connect(self._cloud, config.MQTT_CLOUD_BROKER, config.MQTT_CLOUD_PORT, "cloud")
        else:
            print("[MQTT] No MQTT_CLOUD_BROKER set - cloud publishing disabled")

        print(f"[MQTT] Local broker  -> {config.MQTT_BROKER}:{config.MQTT_PORT}")
        if config.MQTT_CLOUD_BROKER:
            print(f"[MQTT] Cloud broker  -> {config.MQTT_CLOUD_BROKER}:{config.MQTT_CLOUD_PORT}")

    # Connection helpers
    def _connect(self, client, host, port, label):
        try:
            client.connect(host, port, keepalive=60)
        except Exception as e:
            print(f"[MQTT] {label} connection failed: {e} - running offline")

    # Local broker callbacks
    def _on_local_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected_local = True
            print(f"[MQTT] Connected to local broker at {config.MQTT_BROKER}:{config.MQTT_PORT}")
            client.subscribe(config.MQTT_TOPIC_VISION, qos=1)
            print(f"[MQTT] Subscribed to {config.MQTT_TOPIC_VISION}")
        else:
            self._connected_local = False
            print(f"[MQTT] Local broker connection refused - rc={rc}")

    def _on_local_disconnect(self, client, userdata, rc):
        self._connected_local = False
        if rc == 0:
            print("[MQTT] Local broker clean disconnect")
            return
        print(f"[MQTT] Local broker unexpected disconnect (rc={rc}) - will retry")
        self._reconnect_loop(client, "local")

    # Cloud broker callbacks
    def _on_cloud_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected_cloud = True
            print(f"[MQTT] Connected to cloud broker at {config.MQTT_CLOUD_BROKER}:{config.MQTT_CLOUD_PORT}")
        else:
            self._connected_cloud = False
            print(f"[MQTT] Cloud broker connection refused - rc={rc}")

    def _on_cloud_disconnect(self, client, userdata, rc):
        self._connected_cloud = False
        if rc == 0:
            print("[MQTT] Cloud broker clean disconnect")
            return
        print(f"[MQTT] Cloud broker unexpected disconnect (rc={rc}) - will retry")
        self._reconnect_loop(client, "cloud")

    def _reconnect_loop(self, client, label):
        delay = 2
        max_delay = 30
        while True:
            print(f"[MQTT] {label} reconnecting in {delay}s...")
            time.sleep(delay)
            try:
                client.reconnect()
                print(f"[MQTT] {label} reconnected successfully")
                break
            except Exception:
                delay = min(delay * 2, max_delay)

    # Vision message handler (from Jetson via local broker)
    def _on_message(self, client, userdata, msg):
        if msg.topic != config.MQTT_TOPIC_VISION:
            return
        recv_wall = time.time()
        recv_perf = time.perf_counter()
        try:
            payload = json.loads(msg.payload.decode())
            confidence = float(payload.get("confidence", payload.get("fire_confidence", 0.0)))
            self.vision_confidence = max(0.0, min(1.0, confidence))
            t_sent = payload.get("t_sent")
            if t_sent:
                self.mqtt_transit_ms = (recv_wall - t_sent) * 1000
            prev_detected = self.vision_detected_at is not None
            if self.vision_confidence >= 0.5 and self.vision_detected_at is None:
                self.vision_detected_at = recv_perf
                transit_str = f"  network_transit={self.mqtt_transit_ms:.1f}ms" if t_sent else ""
                print(f"[MQTT] *** FIRE msg received  confidence={self.vision_confidence:.2f}{transit_str} ***")
            elif self.vision_confidence < 0.5:
                if prev_detected:
                    print(f"[MQTT] Vision confidence dropped ({self.vision_confidence:.2f}) - detection cleared")
                self.vision_detected_at = None
        except Exception as e:
            print(f"[MQTT] Failed to parse vision message: {e}")

    @property
    def connected(self) -> bool:
        return self._connected_local

    # Publishing (to cloud broker)
    def publish_event(self, result: FusionResult, door_state: str):
        """Publish state-change event when fire decision changes. Deduped internally."""
        if result.decision == self._last_decision:
            return
        self._last_decision = result.decision
        payload = result.to_dict()
        payload["door_state"] = door_state
        payload["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        payload["type"] = "event"
        self._publish_cloud(config.MQTT_TOPIC_EVENTS, payload, retain=False)
        print(f"[MQTT] Event published: {result.decision.value} score={result.fire_score:.3f}")

    def publish_status(self, result: FusionResult, door_state: str, uptime_seconds: float):
        """Publish periodic heartbeat. Rate-limited internally."""
        now = time.time()
        if now - self._last_status_time < config.MQTT_STATUS_INTERVAL:
            return
        self._last_status_time = now
        payload = result.to_dict()
        payload["door_state"] = door_state
        payload["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        payload["type"] = "status"
        payload["uptime_seconds"] = round(uptime_seconds, 1)
        self._publish_cloud(config.MQTT_TOPIC_STATUS, payload, retain=True)

    def _publish_cloud(self, topic: str, payload: dict, retain: bool = False):
        """Publish to cloud broker. Silently skips if cloud is not configured or connected."""
        if self._cloud is None or not self._connected_cloud:
            return
        try:
            result = self._cloud.publish(
                topic,
                json.dumps(payload),
                qos=1,
                retain=retain,
            )
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                print(f"[MQTT] Cloud publish failed on {topic} rc={result.rc}")
        except Exception as e:
            print(f"[MQTT] Cloud publish error on {topic}: {e}")

    # Cleanup
    def cleanup(self):
        try:
            self._local.loop_stop()
            self._local.disconnect()
        except Exception:
            pass
        if self._cloud:
            try:
                self._cloud.loop_stop()
                self._cloud.disconnect()
            except Exception:
                pass
        print("[MQTT] Disconnected.")
