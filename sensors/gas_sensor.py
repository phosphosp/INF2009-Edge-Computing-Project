# Reads MQ2 gas sensor digital output (DO pin)
# Applies consecutive-read debounce before flagging gas as detected
# Applies a warmup period on startup (~20s) before readings are trusted

from gpiozero import DigitalInputDevice
import time
import config

class GasSensor:
    def __init__(self):
        self._device = DigitalInputDevice(config.GAS_PIN)
        self._consecutive_count = 0
        self._detected = False

        # Warmup tracking
        self._start_time = time.time()
        self._warmed_up = False

        print(f"[GasSensor] Initialised on GPIO {config.GAS_PIN}")
        print(f"[GasSensor] Warming up for {config.GAS_WARMUP_SEC}s before readings are trusted...")

    def _check_warmup(self) -> bool:
        """
        Returns True once the warmup period has elapsed
        Prints a one-time message when warmup completes
        """
        if self._warmed_up:
            return True
 
        elapsed = time.time() - self._start_time
        if elapsed >= config.GAS_WARMUP_SEC:
            self._warmed_up = True
            print(f"[GasSensor] Warmup complete ({config.GAS_WARMUP_SEC}s elapsed) - readings now active")
            return True
 
        return False

    def update(self):
        """
        Call this every main loop iteration
        Updates internal debounce state
        Does not return a value
        Readings are suppressed during warmup
        """
        # Suppress all readings during warmup
        if not self._check_warmup():
            return
        
        # gpiozero: value = 0 means DO is LOW -> gas detected
        raw = self._device.value

        if raw == 0:
            self._consecutive_count += 1
        else:
            # Clear detected state only when sensor reads clean
            self._consecutive_count = 0
            self._detected = False

        # Latch detected=True once threshold consecutive reads are met
        if self._consecutive_count >= config.GAS_CONSECUTIVE_REQ:
            self._detected = True

    @property
    def detected(self) -> bool:
        """True if gas has been consistently detected, False otherwise"""
        return self._detected
    
    @property
    def warmed_up(self) -> bool:
        """True once the warmup period has elapsed"""
        return self._warmed_up

    @property
    def raw_value(self) -> int:
        """Raw pin value: 0 = gas present, 1 = clear"""
        return self._device.value

    def read(self) -> dict:
        """
        Convenience method: calls update() then returns current state
        Returns a dict so callers always get a consistent data shape
        """
        self.update()
        elapsed = time.time() - self._start_time
        return {
            "detected": self._detected,
            "raw": self.raw_value,
            "consec_count": self._consecutive_count,
            "warming_up": not self._warmed_up,
            "warmup_elapsed_sec": round(elapsed, 1),
        }

    def cleanup(self):
        """Release the GPIO pin cleanly"""
        self._device.close()
        print("[GasSensor] Cleaned up.")
