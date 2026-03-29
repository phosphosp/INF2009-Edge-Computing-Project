# Weighted evidence fusion engine.

# Takes sensor readings + optional simulation overrides and produces:
#   A float fire_score (0.0 – 1.0)
#   A FusionResult describing the system decision

# Score breakdown (weights sum to 1.0, defined in config.py):
#   Gas detected -> contributes WEIGHT_GAS  (currently 0.4)
#   Temp flagged -> contributes WEIGHT_TEMP (currently 0.2)
#   Vision conf -> contributes WEIGHT_VISION * confidence (currently 0.0, no AI yet)

# Without AI (vision_confidence=0.0):
#   Max possible score = 0.6 (gas + temp both triggered)
#   Fire threshold = 0.5 (gas + temp both needed to confirm fire)
#   Warning threshold = 0.2 (any single sensor = early warning)

# Decision ladder:
#   score >= FIRE_THRESHOLD -> FIRE
#   score >= WARNING_THRESHOLD -> WARNING
#   score == 0.0 -> CLEAR

# Simulation overrides:
#   Flags from sim_flags.json are applied BEFORE scoring
#   They inject synthetic sensor values into the score calculation,
#   so the fusion logic itself is always exercised, not bypassed
#   manual_alarm, manual_lock, manual_unlock are post-score overrides handled by main.py directly.

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
import config

# Data types
class FireDecision(Enum):
    CLEAR = "CLEAR"
    WARNING = "WARNING"
    FIRE = "FIRE"

@dataclass
class FusionResult:
    """
    Full output of one fusion cycle.
    Passed from fusion.py -> main.py -> mqtt_client.py for logging.
    """
    decision: FireDecision
    fire_score: float

    # Effective sensor values used in this cycle (after sim overrides applied)
    gas_detected: bool
    temp_flagged: bool
    vision_confidence: float

    # Raw sensor readings (before sim overrides - for diagnostics)
    raw_gas_detected: bool
    raw_temp_flagged: bool
    raw_avg_temp: Optional[float]

    # Sim state
    sim_active: bool
    active_sim_flags: list = field(default_factory=list)

    def to_dict(self) -> dict:
        """Serialisable dict for MQTT publishing."""
        return {
            "decision": self.decision.value,
            "fire_score": round(self.fire_score, 3),
            "gas_detected": self.gas_detected,
            "temp_flagged": self.temp_flagged,
            "vision_confidence": self.vision_confidence,
            "raw_avg_temp": round(self.raw_avg_temp, 2) if self.raw_avg_temp is not None else None,
            "sim_active": self.sim_active,
            "active_sim_flags": self.active_sim_flags,
        }

# Thresholds (local constants - derive from config)
_nonzero_weights = [
    w for w in (config.WEIGHT_GAS, config.WEIGHT_TEMP, config.WEIGHT_VISION)
    if w > 0
]
WARNING_THRESHOLD = min(_nonzero_weights) if _nonzero_weights else 0.0
# Simplest definition: any single sensor contributing its weight crosses warning.
# With current weights: WARNING_THRESHOLD = 0.2 (temp weight, the smallest non-zero)

# Simulation flag loader
def _load_sim_flags() -> dict:
    """
    Read the simulation flag file written by sim_gui.py
    Returns default flags if file is missing, unreadable, or malformed
    Falls back gracefully - never crashes the main loop
    """
    try:
        if not os.path.exists(config.SIM_FLAG_FILE):
            return config.SIM_DEFAULT_FLAGS.copy()

        with open(config.SIM_FLAG_FILE, "r") as f:
            flags = json.load(f)

        # Merge with defaults so missing keys don't cause KeyErrors
        merged = config.SIM_DEFAULT_FLAGS.copy()
        merged.update(flags)
        return merged

    except Exception as e:
        print(f"[Fusion] Warning: could not read sim flags: {e}")
        return config.SIM_DEFAULT_FLAGS.copy()


# Main fusion function
def evaluate(
    gas_detected: bool,
    temp_flagged: bool,
    vision_confidence: float = 0.0, # 0.0 until Jetson AI is integrated
) -> FusionResult:
    """
    Core fusion function. Call once per main loop iteration

    Parameters:
    gas_detected: bool          - from GasSensor.detected
    temp_flagged: bool          - from TempSensor.flagged
    vision_confidence: float    - from Jetson result, 0.0-1.0 (default 0.0)
    raw_avg_temp: float         - passed through for logging only

    Returns:
    FusionResult with decision, score, and full diagnostic info
    """
    # Store raw values for diagnostics
    raw_gas  = gas_detected
    raw_temp = temp_flagged

    # Load simulation flags
    flags = _load_sim_flags()
    active_flags = [k for k, v in flags.items() if v and k != "manual_alarm"
                    and k != "manual_lock" and k != "manual_unlock"]
    sim_active = len(active_flags) > 0

    # Apply simulation overrides to sensor values
    # Overrides inject synthetic readings, 
    # score calculation below runs exactly the same path whether real or simulated
    if flags.get("fire_sim"):
        gas_detected = True
        temp_flagged = True
        vision_confidence = 0.9 # simulated AI confidence

    elif flags.get("gas_only_sim"):
        gas_detected = True
        temp_flagged = False
        vision_confidence = 0.0

    elif flags.get("temp_only_sim"):
        gas_detected = False
        temp_flagged = True
        vision_confidence = 0.0

    # HARD TRIGGER: If vision is > 80% sure, force a FIRE state immediately
    if vision_confidence >= 0.8:
        return FusionResult(
            decision=FireDecision.FIRE,
            fire_score=1.0,
            gas_detected=gas_detected,
            temp_flagged=temp_flagged,
            vision_confidence=vision_confidence,
            raw_gas_detected=raw_gas,
            raw_temp_flagged=raw_temp,
            raw_avg_temp=None, 
            sim_active=sim_active,
            active_sim_flags=active_flags,
        )

    # Compute weighted score
    score = 0.0
    if gas_detected:
        score += config.WEIGHT_GAS
    if temp_flagged:
        score += config.WEIGHT_TEMP
    score += config.WEIGHT_VISION * vision_confidence

    score = round(min(score, 1.0), 4)  # clamp to 1.0, round for clean logs

    # Decision ladder
    if score >= config.FIRE_THRESHOLD:
        decision = FireDecision.FIRE
    elif score >= WARNING_THRESHOLD:
        decision = FireDecision.WARNING
    else:
        decision = FireDecision.CLEAR

    return FusionResult(
        decision = decision,
        fire_score = score,
        gas_detected = gas_detected,
        temp_flagged = temp_flagged,
        vision_confidence = vision_confidence,
        raw_gas_detected = raw_gas,
        raw_temp_flagged = raw_temp,
        raw_avg_temp = None,   # main.py sets this after calling evaluate()
        sim_active = sim_active,
        active_sim_flags = active_flags,
    )

# For future AI integration
def evaluate_with_vision(
    gas_detected: bool,
    temp_flagged: bool,
    vision_confidence: float,
) -> FusionResult:
    """
    Switch main.py to call this instead of evaluate() when ready
    """
    return evaluate(gas_detected, temp_flagged, vision_confidence)
