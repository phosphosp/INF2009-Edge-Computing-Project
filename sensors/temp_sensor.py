# Reads DHT22 temperature + humidity sensor

# DHT22 is SLOW (~2s per read) and cannot be polled on every 100ms loop tick
# This module runs its own background thread that reads the sensor every
# TEMP_READ_INTERVAL seconds and caches the result
# The main loop calls read() which returns the latest cached value instantly

# Applies warmup, rolling average, and hysteresis

import threading
import time
import board
import adafruit_dht
import config

class TempSensor:
    def __init__(self):
        pin = getattr(board, f"D{config.TEMP_PIN}")
        self._dht = adafruit_dht.DHT22(pin, use_pulseio=False)

        self._temp = None
        self._humidity = None
        self._avg_temp = None
        self._flagged = False

        self._temp_history = []
        self._high_count = 0
        self._read_count = 0
        self._error_count = 0

        self._lock = threading.Lock()
        self._stop_event = threading.Event()

        # Start background polling thread
        self._thread = threading.Thread(
            target=self._poll_loop,
            daemon=True, # dies automatically when main program exits
            name="TempSensorThread"
        )
        self._thread.start()
        print(f"[TempSensor] Initialised on GPIO {config.TEMP_PIN}, "
              f"polling every {config.TEMP_READ_INTERVAL}s")

    # Background thread
    def _poll_loop(self):
        """
        Runs in background thread
        Reads DHT22 and updates cached state
        """
        while not self._stop_event.is_set():
            try:
                raw_temp = self._dht.temperature
                humidity = self._dht.humidity

                if raw_temp is None or humidity is None:
                    with self._lock:
                        self._error_count += 1
                    print("[TempSensor] DHT22 returned None")
                else:
                    with self._lock:
                        self._error_count = 0
                        self._read_count += 1
                        self._temp = raw_temp
                        self._humidity = humidity

                        # Update rolling average
                        self._temp_history.append(raw_temp)
                        if len(self._temp_history) > config.TEMP_AVG_SAMPLES:
                            self._temp_history.pop(0)

                        self._avg_temp = (
                            sum(self._temp_history) / len(self._temp_history)
                        )

                        # Skip alarm logic during warmup
                        if self._read_count <= config.TEMP_WARMUP_READS:
                            print(f"[TempSensor] Warming up... "
                                  f"Temp={raw_temp:.1f}°C  "
                                  f"Hum={humidity:.1f}%  "
                                  f"({self._read_count}/{config.TEMP_WARMUP_READS})")
                        else:
                            self._update_flag()

            except RuntimeError as e:
                with self._lock:
                    self._error_count += 1
                print(f"[TempSensor] Read error: {e}")
                if self._error_count >= 5:
                    print("[TempSensor] WARNING: 5 consecutive read errors")

            time.sleep(config.TEMP_READ_INTERVAL)

    def _update_flag(self):
        """
        Applies hysteresis logic to set/clear self._flagged
        Must be called with self._lock already held
        """
        avg = self._avg_temp

        if not self._flagged:
            # Alarm ON logic: need HIGH_COUNT_REQ consecutive high readings
            if avg >= config.TEMP_ON_THRESHOLD:
                self._high_count += 1
            else:
                self._high_count = 0

            if self._high_count >= config.TEMP_HIGH_COUNT_REQ:
                self._flagged = True
                print(f"[TempSensor] FLAGGED - avg {avg:.1f}°C >= "
                      f"{config.TEMP_ON_THRESHOLD}°C")
        else:
            # Alarm OFF logic: only clear when avg drops below OFF_THRESHOLD
            if avg <= config.TEMP_OFF_THRESHOLD:
                self._flagged = False
                self._high_count = 0
                print(f"[TempSensor] Cleared - avg {avg:.1f}°C <= "
                      f"{config.TEMP_OFF_THRESHOLD}°C")

    # Public interface
    @property
    def flagged(self) -> bool:
        """True when temperature anomaly has been confirmed."""
        with self._lock:
            return self._flagged

    @property
    def avg_temp(self):
        """Current rolling average temperature, or None during warmup."""
        with self._lock:
            return self._avg_temp

    def read(self) -> dict:
        """
        Returns the latest cached sensor state as a dict
        Non-blocking, always returns immediately
        """
        with self._lock:
            return {
                "temp": self._temp,
                "humidity": self._humidity,
                "avg_temp": self._avg_temp,
                "flagged": self._flagged,
                "high_count": self._high_count,
                "read_count": self._read_count,
                "error_count": self._error_count,
                "warming_up": self._read_count <= config.TEMP_WARMUP_READS,
            }

    def cleanup(self):
        """Stop background thread and release DHT22"""
        self._stop_event.set()
        self._thread.join(timeout=5)
        try:
            self._dht.exit()
        except Exception:
            pass
        print("[TempSensor] Cleaned up.")
