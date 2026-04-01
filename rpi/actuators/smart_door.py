# Controls RFID reader + servo as a smart door lock

# Normal mode:
#   Continuously polls RFID. Authorised card → unlocks servo,
#   then auto-relocks after SERVO_HOLD_TIME. Unauthorised cards are ignored.

# Fire mode:
#   Triggered by main.py on FIRE. RFID disabled, door forced open
#   for evacuation until fire mode is cleared.

# Background threads:
#   RFID poll: runs continuously (MFRC522 blocks ~300ms, so not in main loop)
#   Servo detach: briefly runs after movement to stop PWM jitter

# Thread safety:
#   _lock protects shared state. _move_servo() is non-blocking (spawns thread).

import time
import threading
from gpiozero import AngularServo
from mfrc522 import MFRC522
import RPi.GPIO as GPIO
import config

class DoorState:
    LOCKED   = "LOCKED"
    UNLOCKED = "UNLOCKED"

class SmartDoor:

    RFID_COOLDOWN_SEC = 1.0   # suppress repeated scans of same card

    def __init__(self):
        # Servo
        self._servo = AngularServo(
            config.SERVO_PIN,
            min_angle=0,
            max_angle=180,
            min_pulse_width=0.0005,
            max_pulse_width=0.0025,
        )

        # RFID
        self._rfid = MFRC522()

        # State
        self._fire_mode  = False
        self._door_state = DoorState.LOCKED
        self._lock       = threading.Lock()

        # Relock timer
        self._unlock_timer = None

        # RFID event cache: written by _rfid_poll_loop, consumed by update()
        self._pending_event   = None
        self._pending_card_id = None

        # Cooldown tracking (used only inside _rfid_poll_loop thread)
        self._last_scan_id   = None
        self._last_scan_time = 0.0

        # Background RFID thread
        self._rfid_stop   = threading.Event()
        self._rfid_thread = threading.Thread(
            target=self._rfid_poll_loop,
            daemon=True,
            name="RFIDPollThread",
        )

        # Start locked, non-blocking now
        self._move_servo(config.SERVO_LOCKED_ANGLE)

        # Give servo its first command before RFID thread starts competing for SPI
        time.sleep(0.05)
        self._rfid_thread.start()

        print(f"[SmartDoor] Initialised - Servo GPIO {config.SERVO_PIN}, RFID polling in background")
        print(f"[SmartDoor] Authorised cards: {config.AUTHORISED_CARDS or 'NONE SET'}")

    # Public interface
    def update(self) -> dict:
        """
        Call once per main loop tick
        Consumes any RFID event queued by the background thread
        Never blocks, always returns immediately
        """
        with self._lock:
            event = self._pending_event
            card_id = self._pending_card_id
            self._pending_event = None   # consume
            self._pending_card_id = None

            return {
                "event": event,
                "card_id": card_id,
                "door_state": self._door_state,
                "fire_mode": self._fire_mode,
            }

    def set_fire_mode(self, active: bool):
        """
        Enter or exit fire mode.
        No-op if state hasn't changed, safe to call every tick
        """
        with self._lock:
            if active == self._fire_mode:
                return # <1ms, no servo call

            self._fire_mode = active
            self._cancel_unlock_timer_locked()

            if active:
                self._door_state = DoorState.UNLOCKED
                self._move_servo(config.SERVO_UNLOCKED_ANGLE)
                print("[SmartDoor] FIRE MODE - door open, RFID disabled")
            else:
                self._door_state = DoorState.LOCKED
                self._move_servo(config.SERVO_LOCKED_ANGLE)
                print("[SmartDoor] Normal mode - door relocked")

    def force_lock(self):
        with self._lock:
            if self._door_state == DoorState.LOCKED:
                return
            self._cancel_unlock_timer_locked()
            self._door_state = DoorState.LOCKED
            self._move_servo(config.SERVO_LOCKED_ANGLE)
            print("[SmartDoor] Manually locked")

    def force_unlock(self):
        with self._lock:
            if self._door_state == DoorState.UNLOCKED:
                return
            self._cancel_unlock_timer_locked()
            self._door_state = DoorState.UNLOCKED
            self._move_servo(config.SERVO_UNLOCKED_ANGLE)
            print("[SmartDoor] Manually unlocked")

    @property
    def door_state(self) -> str:
        with self._lock:
            return self._door_state

    @property
    def fire_mode(self) -> bool:
        with self._lock:
            return self._fire_mode

    # RFID background thread
    def _rfid_poll_loop(self):
        """
        Runs in background thread
        MFRC522_Request() blocks ~300ms per call, isolated here so main loop is never affected
        Events are cached for update() to pick up
        """
        while not self._rfid_stop.is_set():

            # Pause polling during fire mode
            with self._lock:
                in_fire_mode = self._fire_mode
            if in_fire_mode:
                time.sleep(0.1)
                continue

            event, card_id = self._poll_rfid_once()

            if event is not None:
                with self._lock:
                    if self._pending_event is None:
                        self._pending_event = event
                        self._pending_card_id = card_id

    def _poll_rfid_once(self):
        """
        Single RFID poll
        Returns (event_str, card_id) or (None, None)
        Called only from _rfid_poll_loop, never from main thread
        """
        status, _ = self._rfid.MFRC522_Request(self._rfid.PICC_REQIDL)
        if status != self._rfid.MI_OK:
            return None, None

        status, uid = self._rfid.MFRC522_Anticoll()
        if status != self._rfid.MI_OK:
            return None, None

        card_id = "".join(str(x) for x in uid)
        now     = time.time()

        if (self._last_scan_id == card_id and (now - self._last_scan_time) < self.RFID_COOLDOWN_SEC):
            return None, None

        self._last_scan_id   = card_id
        self._last_scan_time = now

        print(f"[SmartDoor] Card scanned: {card_id}")

        if card_id in config.AUTHORISED_CARDS:
            self._grant_access()
            return "authorised", card_id

        print(f"[SmartDoor] Unauthorised card: {card_id}")
        return "unauthorised", card_id

    # Access grant + relock timer
    def _grant_access(self):
        """
        Unlock and schedule relock
        Called from RFID background thread
        """
        with self._lock:
            if self._fire_mode:
                return
            self._cancel_unlock_timer_locked()
            self._door_state = DoorState.UNLOCKED
            self._move_servo(config.SERVO_UNLOCKED_ANGLE)
            print(f"[SmartDoor] Access granted - open for {config.SERVO_HOLD_TIME}s")

            self._unlock_timer = threading.Timer(
                config.SERVO_HOLD_TIME, self._relock
            )
            self._unlock_timer.daemon = True
            self._unlock_timer.start()

    def _relock(self):
        """Timer callback, relock after hold time"""
        with self._lock:
            self._unlock_timer = None
            if self._fire_mode:
                return
            self._door_state = DoorState.LOCKED
            self._move_servo(config.SERVO_LOCKED_ANGLE)
            print("[SmartDoor] Relocked after hold time")

    def _cancel_unlock_timer_locked(self):
        """
        Cancel pending relock timer
        Must be called with self._lock held
        """
        if self._unlock_timer is not None:
            try:
                self._unlock_timer.cancel()
            except Exception:
                pass
            self._unlock_timer = None

    # Servo control
    def _move_servo(self, angle: int):
        """
        Set servo angle instantly, detach PWM in background thread
        Returns in <1ms, safe to call with self._lock held
        """
        self._servo.angle = angle

        def _detach():
            time.sleep(0.8)
            try:
                self._servo.angle = None
            except Exception:
                pass

        threading.Thread(target=_detach, daemon=True, name="ServoDetach").start()

    # Cleanup
    def cleanup(self):
        """Stop RFID thread, relock, release hardware"""
        print("[SmartDoor] Cleaning up...")
        self._rfid_stop.set()
        self._rfid_thread.join(timeout=2)

        with self._lock:
            self._cancel_unlock_timer_locked()
            self._fire_mode  = False
            self._door_state = DoorState.LOCKED
            self._move_servo(config.SERVO_LOCKED_ANGLE)

        time.sleep(0.9) # let final detach thread finish

        try:
            self._servo.close()
        except Exception:
            pass

        try:
            GPIO.cleanup()
        except Exception:
            pass

        print("[SmartDoor] Cleaned up.")