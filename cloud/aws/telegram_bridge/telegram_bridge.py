import json
import logging
import os
import time
from typing import Optional

import paho.mqtt.client as mqtt
import requests


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "y", "on")


def _format_message(payload: dict) -> str:
    decision = payload.get("decision", "UNKNOWN")
    fire_score = payload.get("fire_score", None)
    door_state = payload.get("door_state", "UNKNOWN")
    gas_detected = payload.get("gas_detected", None)
    temp_flagged = payload.get("temp_flagged", None)
    raw_avg_temp = payload.get("raw_avg_temp", None)
    sim_active = payload.get("sim_active", False)
    active_sim_flags = payload.get("active_sim_flags", [])
    timestamp = payload.get("timestamp", "")

    score_txt = (
        f"{fire_score:.3f}" if isinstance(fire_score, (int, float)) else str(fire_score)
    )
    temp_txt = (
        f"{raw_avg_temp:.1f}C" if isinstance(raw_avg_temp, (int, float)) else str(raw_avg_temp)
    )

    sim_txt = ""
    if sim_active:
        sim_flags = ",".join(active_sim_flags) if active_sim_flags else "sim_active"
        sim_txt = f"\nSim Mode: {sim_flags}"

    ts_txt = f"\nTime: {timestamp}" if timestamp else ""
    return (
        f"Fire Detection Alert: {decision}\n"
        f"Score: {score_txt}\n"
        f"Gas detected: {gas_detected}\n"
        f"Temp flagged: {temp_flagged}\n"
        f"Avg temp: {temp_txt}\n"
        f"Door state: {door_state}"
        f"{sim_txt}"
        f"{ts_txt}"
    )


def _telegram_send(bot_token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    # Keep payload minimal to reduce failure modes.
    resp = requests.post(
        url,
        timeout=10,
        json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": True,
        },
    )
    resp.raise_for_status()


class TelegramBridge:
    def __init__(self):
        self.mqtt_host = os.getenv("MQTT_HOST", "localhost")
        self.mqtt_port = int(os.getenv("MQTT_PORT", "1883"))
        self.mqtt_username = os.getenv("MQTT_USERNAME", "")
        self.mqtt_password = os.getenv("MQTT_PASSWORD", "")
        self.base_topic = os.getenv("MQTT_BASE_TOPIC", "fire_detection")
        self.events_topic = f"{self.base_topic}/events"
        raw_subscribe_topic = os.getenv("MQTT_SUBSCRIBE_TOPIC")
        self.subscribe_topic = (
            raw_subscribe_topic.strip()
            if raw_subscribe_topic and raw_subscribe_topic.strip()
            else f"{self.base_topic}/#"
        )

        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

        self.send_fire = _env_bool("TELEGRAM_SEND_FIRE", True)
        self.send_warning = _env_bool("TELEGRAM_SEND_WARNING", True)
        self.send_clear = _env_bool("TELEGRAM_SEND_CLEAR", False)

        self.rate_limit_seconds = int(os.getenv("TELEGRAM_RATE_LIMIT_SECONDS", "60"))
        self.dup_window_seconds = int(os.getenv("TELEGRAM_DUP_WINDOW_SECONDS", "10"))
        self.connect_timeout_seconds = int(os.getenv("MQTT_CONNECT_TIMEOUT_SECONDS", "10"))

        # Simple dedup/rate limiting to prevent Telegram spam on reconnects.
        self._last_sent_at_by_decision: dict[str, float] = {}
        self._last_fingerprint: Optional[str] = None
        self._last_fingerprint_at: float = 0.0

        self._logger = logging.getLogger("telegram_bridge")
        self._fallback_to_anonymous_attempted = False

    @staticmethod
    def _mask_present(secret: str) -> str:
        return "set" if bool(secret) else "missing"

    @staticmethod
    def _is_supported_decision(decision: str) -> bool:
        return decision in {"FIRE", "WARNING", "CLEAR"}

    def _should_send_decision(self, decision: str) -> bool:
        decision = str(decision).upper()
        if decision == "FIRE":
            return self.send_fire
        if decision == "WARNING":
            return self.send_warning
        if decision == "CLEAR":
            return self.send_clear
        return False

    def _rate_limited(self, decision: str) -> bool:
        now = time.time()
        last = self._last_sent_at_by_decision.get(decision)
        if last is None:
            return False
        return (now - last) < self.rate_limit_seconds

    def _dedup_fingerprint(self, payload: dict) -> bool:
        """
        Returns True when message should be ignored as a duplicate.
        """
        now = time.time()
        # Fingerprint on fields we care about. Avoid including entire payload.
        fingerprint = json.dumps(
            {
                "decision": payload.get("decision"),
                "fire_score": payload.get("fire_score"),
                "door_state": payload.get("door_state"),
                "raw_avg_temp": payload.get("raw_avg_temp"),
                "timestamp": payload.get("timestamp"),
                "sim_active": payload.get("sim_active"),
            },
            sort_keys=True,
            default=str,
        )
        if (
            self._last_fingerprint is not None
            and fingerprint == self._last_fingerprint
            and (now - self._last_fingerprint_at) < self.dup_window_seconds
        ):
            return True
        self._last_fingerprint = fingerprint
        self._last_fingerprint_at = now
        return False

    def run_forever(self) -> None:
        if not self.bot_token or not self.chat_id:
            raise RuntimeError(
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set to enable notifications."
            )

        logging.basicConfig(
            level=os.getenv("LOG_LEVEL", "INFO"),
            format="[telegram-bridge] %(asctime)s %(levelname)s: %(message)s",
        )
        self._logger.info(
            (
                "Startup config: MQTT_HOST=%s MQTT_PORT=%s MQTT_BASE_TOPIC=%s "
                "MQTT_SUBSCRIBE_TOPIC=%s TELEGRAM_BOT_TOKEN=%s TELEGRAM_CHAT_ID=%s"
            ),
            self.mqtt_host,
            self.mqtt_port,
            self.base_topic,
            self.subscribe_topic,
            self._mask_present(self.bot_token),
            self._mask_present(self.chat_id),
        )

        client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            client_id="fire_telegram_bridge",
        )
        use_auth = bool(self.mqtt_username and self.mqtt_password)
        if use_auth:
            client.username_pw_set(self.mqtt_username, self.mqtt_password)

        def on_connect(c, userdata, flags, reason_code, properties):
            nonlocal use_auth
            reason_text = str(reason_code)
            is_success = (reason_code == 0) or ("success" in reason_text.lower())

            if is_success:
                self._logger.info("MQTT connected to %s:%s", self.mqtt_host, self.mqtt_port)
                c.subscribe(self.subscribe_topic)
                return

            # Allow anonymous local testing even when auth env vars exist.
            if (
                "not authorized" in reason_text.lower()
                and use_auth
                and not self._fallback_to_anonymous_attempted
            ):
                self._fallback_to_anonymous_attempted = True
                use_auth = False
                c.username_pw_set(None, None)
                self._logger.info("MQTT auth rejected, retrying anonymous once")
                c.reconnect()
                return

            self._logger.error("MQTT connect rejected: %s", reason_text)

        def on_subscribe(c, userdata, mid, reason_codes, properties):
            self._logger.info("MQTT subscribed to %s", self.subscribe_topic)

        def on_disconnect(c, userdata, disconnect_flags, reason_code, properties):
            self._logger.info("MQTT disconnected reason=%s", reason_code)

        def on_log(c, userdata, level, buf):
            # Keep this low-noise: only emit when explicit DEBUG is requested.
            if self._logger.isEnabledFor(logging.DEBUG):
                self._logger.debug("MQTT log: %s", buf)

        def on_message(c, userdata, msg):
            raw_payload = msg.payload.decode("utf-8", errors="replace")
            self._logger.info("MQTT message received topic=%s payload=%s", msg.topic, raw_payload)
            if msg.topic != self.events_topic:
                self._logger.info("MQTT skip: topic %s is not %s", msg.topic, self.events_topic)
                return
            try:
                payload = json.loads(raw_payload)
            except Exception:
                self._logger.info("MQTT skip: non-JSON payload")
                return

            decision = str(payload.get("decision", "UNKNOWN")).upper()
            if not self._is_supported_decision(decision):
                self._logger.info("MQTT skip: unsupported decision=%s", decision)
                return

            if not self._should_send_decision(decision):
                self._logger.info("MQTT skip: filtered decision=%s", decision)
                return
            if self._rate_limited(decision):
                self._logger.info("MQTT skip: rate-limited decision=%s", decision)
                return
            if self._dedup_fingerprint(payload):
                self._logger.info("MQTT skip: duplicate payload")
                return

            text = _format_message(payload)
            try:
                _telegram_send(self.bot_token, self.chat_id, text)
                self._last_sent_at_by_decision[decision] = time.time()
                self._logger.info("Telegram send success for decision=%s", decision)
            except Exception as e:
                self._logger.error("Telegram send failed: %s", e)

        client.on_connect = on_connect
        client.on_subscribe = on_subscribe
        client.on_disconnect = on_disconnect
        client.on_message = on_message
        client.on_log = on_log
        client.reconnect_delay_set(min_delay=1, max_delay=60)

        while True:
            try:
                client.connect(self.mqtt_host, self.mqtt_port, keepalive=60)
                client.loop_forever(timeout=self.connect_timeout_seconds)
            except Exception as e:
                self._logger.error("MQTT loop error: %s. Retrying in 5s...", e)
                time.sleep(5)


if __name__ == "__main__":
    TelegramBridge().run_forever()

