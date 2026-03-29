# Non-blocking MQTT publisher.

# Responsibilities:
# Connect to broker on startup (non-fatal if broker is unavailable)
# Publish fire/warning/clear EVENTS when decision state changes
# Publish a periodic STATUS heartbeat every MQTT_STATUS_INTERVAL seconds
# Reconnect automatically if connection drops
# Never block or crash the main loop if broker is unreachable

# Topics:
#   fire_detection/events, state change alerts (fire, warning, clear)
#   fire_detection/status, periodic heartbeat with full sensor snapshot

# Payload format: JSON string

import json
import time
import paho.mqtt.client as mqtt
import config
from utils.fusion import FusionResult

class MQTTClient:
    def __init__(self):
        self._client = mqtt.Client(client_id=config.MQTT_CLIENT_ID)
        self._connected = False
        self._last_status_time = 0.0

        # Track last published decision to avoid duplicate event publishes
        self._last_decision = None

        # Store latest vision result from Jetson
        self.vision_confidence = 0.0

        # Callbacks
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
        
        # Optional auth/TLS settings for cloud brokers
        if config.MQTT_USERNAME:
            self._client.username_pw_set(
                username=config.MQTT_USERNAME,
                password=config.MQTT_PASSWORD or None,
            )

        if config.MQTT_TLS_ENABLED:
            tls_kwargs = {}
            if config.MQTT_CA_CERT:
                tls_kwargs["ca_certs"] = config.MQTT_CA_CERT
            self._client.tls_set(**tls_kwargs)
            self._client.tls_insecure_set(config.MQTT_TLS_INSECURE)

        # Start paho's background network loop (non-blocking)
        self._client.loop_start()

        # Attempt initial connection
        self._connect()

        print(f"[MQTT] Client initialised -> {config.MQTT_BROKER}:{config.MQTT_PORT}")

    # Connection management
    def _connect(self):
        """Attempt connection to broker. Non-fatal on failure."""
        try:
            self._client.connect(
                config.MQTT_BROKER,
                config.MQTT_PORT,
                keepalive=60
            )
        except Exception as e:
            print(f"[MQTT] Connection failed: {e} - running offline")

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self._connected = True
            print(f"[MQTT] Connected to broker at {config.MQTT_BROKER}:{config.MQTT_PORT}")
            
            # Subscribe to vision AI topic on startup
            self._client.subscribe(config.MQTT_TOPIC_VISION)
            print(f"[MQTT] Subscribed to {config.MQTT_TOPIC_VISION}")
        else:
            self._connected = False
            print(f"[MQTT] Connection refused - rc={rc}")

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        
        if rc == 0:
            print("[MQTT] Clean disconnect")
            return

        print(f"[MQTT] Unexpected disconnect (rc={rc}) - will retry")

        delay = 2
        max_delay = 30

        while True:
            print(f"[MQTT] Reconnecting in {delay}s...")
            time.sleep(delay)

            try:
                client.reconnect()
                print("[MQTT] Reconnected successfully")
                break
            except Exception:
                delay = min(delay * 2, max_delay)

    @property
    def connected(self) -> bool:
        return self._connected

    def _on_message(self, client, userdata, msg):
        """Callback for received messages (Jetson -> Pi)"""
        try:
            if msg.topic == config.MQTT_TOPIC_VISION:
                payload = json.loads(msg.payload.decode())
                # Update local confidence value used by main.py fusion loop
                self.vision_confidence = float(payload.get("confidence", 0.0))
        except Exception as e:
            print(f"[MQTT] Error parsing incoming vision message: {e}")

    # Publishing
    def publish_event(self, result: FusionResult, door_state: str):
        """
        Publish a state-change event when the fire decision changes
        Only publishes if the decision is different from the last published one
        This prevents flooding the broker with identical messages every loop tick
        Call this every loop tick, dedup logic is internal
        """
        if result.decision == self._last_decision:
            return  # no change, skip

        self._last_decision = result.decision

        payload = result.to_dict()
        payload["door_state"] = door_state
        payload["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        payload["type"] = "event"

        self._publish(config.MQTT_TOPIC_EVENTS, payload, retain=False)
        print(f"[MQTT] Event published: {result.decision.value} score={result.fire_score:.3f}")

    def publish_status(self, result: FusionResult, door_state: str, uptime_seconds: float):
        """
        Publish a periodic heartbeat status message
        Call this every loop tick - internal timer controls publish rate
        """
        now = time.time()
        if now - self._last_status_time < config.MQTT_STATUS_INTERVAL:
            return  # not time yet

        self._last_status_time = now

        payload = result.to_dict()
        payload["door_state"] = door_state
        payload["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        payload["type"] = "status"
        payload["uptime_seconds"] = round(uptime_seconds, 1)

        self._publish(config.MQTT_TOPIC_STATUS, payload, retain=True)

    def _publish(self, topic: str, payload: dict, retain: bool = False):
        """Internal publish with connection guard and error handling"""
        if not self._connected:
            return

        try:
            result = self._client.publish(
                topic,
                json.dumps(payload),
                qos=1, # at-least-once delivery
                retain=retain
            )

            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                print(f"[MQTT] Publish failed on {topic} rc={result.rc}")
        except Exception as e:
            print(f"[MQTT] Publish error on {topic}: {e}")

    # Cleanup
    def cleanup(self):
        """Disconnect cleanly and stop the network loop."""
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass
        print("[MQTT] Disconnected.")
