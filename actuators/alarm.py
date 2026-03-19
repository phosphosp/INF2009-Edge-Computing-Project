# Controls LED and buzzer

# Three alarm states:
#   CLEAR: everything off
#   WARNING: LED on, buzzer silent (1 sensor triggered, not confirmed fire)
#   FIRE: LED on, buzzer on (fusion score >= FIRE_THRESHOLD)

# The alarm only moves to a higher state, never skips back silently
# Clearing requires an explicit call to clear()

from gpiozero import LED, PWMOutputDevice
from enum import Enum
import config

class AlarmState(Enum):
    CLEAR = "CLEAR"
    WARNING = "WARNING"
    FIRE = "FIRE"

class Alarm:
    def __init__(self):
        # LED
        self._led = LED(config.LED_PIN)

        # BUZZER
        self._buzzer = PWMOutputDevice(
            config.BUZZER_PIN,
            frequency=config.BUZZ_FREQ
        )

        # State
        self._state = AlarmState.CLEAR
        self._apply_state()
        print(f"[Alarm] Initialised - LED on GPIO {config.LED_PIN}, Buzzer on GPIO {config.BUZZER_PIN}")

    # Public interface
    @property
    def state(self) -> AlarmState:
        return self._state

    def set_state(self, new_state: AlarmState):
        """
        Transition to a new alarm state
        Applies hardware changes only if the state actually changed
        """
        if new_state == self._state:
            return

        prev = self._state
        self._state = new_state
        self._apply_state()
        print(f"[Alarm] {prev.value} → {new_state.value}")

    def trigger_fire(self):
        """Convenience method - set state to FIRE"""
        self.set_state(AlarmState.FIRE)

    def trigger_warning(self):
        """Convenience method - set state to WARNING"""
        self.set_state(AlarmState.WARNING)

    def clear(self):
        """Convenience method - set state to CLEAR"""
        self.set_state(AlarmState.CLEAR)

    def is_active(self) -> bool:
        """True if alarm is in WARNING or FIRE state"""
        return self._state != AlarmState.CLEAR

    # Internal
    def _apply_state(self):
        """Push current state to hardware"""
        if self._state == AlarmState.CLEAR:
            self._led.off()
            self._buzzer.value = 0

        elif self._state == AlarmState.WARNING:
            self._led.on()
            self._buzzer.value = 0  # silent warning, LED only

        elif self._state == AlarmState.FIRE:
            self._led.on()
            self._buzzer.value = config.BUZZ_DUTY

    def cleanup(self):
        """Turn everything off and release GPIO pins"""
        self._led.off()
        self._buzzer.value = 0
        self._led.close()
        self._buzzer.close()
        print("[Alarm] Cleaned up.")