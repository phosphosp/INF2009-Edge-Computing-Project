# Reads MQ2 gas sensor digital output (DO pin)
# Applies consecutive-read debounce before flagging gas as detected

from gpiozero import DigitalInputDevice
import config

class GasSensor:
    def __init__(self):
        self._device = DigitalInputDevice(config.GAS_PIN)
        self._consecutive_count = 0
        self._detected = False
        print(f"[GasSensor] Initialised on GPIO {config.GAS_PIN}")

    def update(self):
        """
        Call this every main loop iteration
        Updates internal debounce state
        Does not return a value
        """
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
    def raw_value(self) -> int:
        """Raw pin value: 0 = gas present, 1 = clear"""
        return self._device.value

    def read(self) -> dict:
        """
        Convenience method: calls update() then returns current state
        Returns a dict so callers always get a consistent data shape
        """
        self.update()
        return {
            "detected": self._detected,
            "raw": self.raw_value,
            "consec_count": self._consecutive_count
        }

    def cleanup(self):
        """Release the GPIO pin cleanly"""
        self._device.close()
        print("[GasSensor] Cleaned up.")
