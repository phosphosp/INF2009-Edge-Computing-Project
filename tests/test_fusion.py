# Tests the fusion engine with no hardware required
# Runs through every sensor combination and all simulation overrides

import json
import os
import sys

# Allow running from tests folder
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from utils.fusion import evaluate, FireDecision

PASS = "\033[92m PASS\033[0m"
FAIL = "\033[91m FAIL\033[0m"

def check(label, result, expected_decision, expected_score_min, expected_score_max):
    score_ok = expected_score_min <= result.fire_score <= expected_score_max
    decision_ok = result.decision == expected_decision
    ok = score_ok and decision_ok
    status = PASS if ok else FAIL
    print(f"{status} | {label:<35} | score={result.fire_score:.3f} "
          f"[{expected_score_min}–{expected_score_max}] | "
          f"decision={result.decision.value} (expected {expected_decision.value})")
    return ok


print("\n=== Fusion Engine Test ===\n")
print(f"Weights  → gas={config.WEIGHT_GAS}  temp={config.WEIGHT_TEMP}  "
      f"vision={config.WEIGHT_VISION}")
print(f"Threshold → fire={config.FIRE_THRESHOLD}\n")

all_pass = True

# No sensors triggered
r = evaluate(gas_detected=False, temp_flagged=False)
all_pass &= check("No sensors", r, FireDecision.CLEAR, 0.0, 0.0)

# Gas only
r = evaluate(gas_detected=True, temp_flagged=False)
all_pass &= check("Gas only", r, FireDecision.WARNING, 0.4, 0.4)

# Temp only
r = evaluate(gas_detected=False, temp_flagged=True)
all_pass &= check("Temp only", r, FireDecision.WARNING, 0.2, 0.2)

# Gas + Temp (no vision) - should cross fire threshold ---
r = evaluate(gas_detected=True, temp_flagged=True)
all_pass &= check("Gas + Temp (no vision)", r, FireDecision.FIRE, 0.6, 0.6)

# Gas + Temp + Vision at 0.5
r = evaluate(gas_detected=True, temp_flagged=True, vision_confidence=0.5)
all_pass &= check("Gas + Temp + Vision 0.5", r, FireDecision.FIRE, 0.8, 0.8)

# Vision only at full confidence
r = evaluate(gas_detected=False, temp_flagged=False, vision_confidence=1.0)
# With WEIGHT_VISION=0.4 and FIRE_THRESHOLD=0.5: vision alone < threshold → WARNING
r_decision = FireDecision.WARNING if config.WEIGHT_VISION < config.FIRE_THRESHOLD else FireDecision.FIRE
all_pass &= check("Vision only (1.0 conf)", r, r_decision,
                  config.WEIGHT_VISION, config.WEIGHT_VISION)

print()

# Simulation flag: fire_sim
print("--- Simulation overrides ---\n")

sim_flags = {"fire_sim": True, "gas_only_sim": False, "temp_only_sim": False,
             "manual_alarm": False, "manual_lock": False, "manual_unlock": False}
with open(config.SIM_FLAG_FILE, "w") as f:
    json.dump(sim_flags, f)

r = evaluate(gas_detected=False, temp_flagged=False) # raw sensors clear
all_pass &= check("fire_sim flag (raw sensors clear)", r, FireDecision.FIRE, 0.9, 1.0)

# gas_only_sim
sim_flags = {**config.SIM_DEFAULT_FLAGS, "gas_only_sim": True}
with open(config.SIM_FLAG_FILE, "w") as f:
    json.dump(sim_flags, f)

r = evaluate(gas_detected=False, temp_flagged=False)
all_pass &= check("gas_only_sim flag", r, FireDecision.WARNING, 0.4, 0.4)

# temp_only_sim
sim_flags = {**config.SIM_DEFAULT_FLAGS, "temp_only_sim": True}
with open(config.SIM_FLAG_FILE, "w") as f:
    json.dump(sim_flags, f)

r = evaluate(gas_detected=False, temp_flagged=False)
all_pass &= check("temp_only_sim flag", r, FireDecision.WARNING, 0.2, 0.2)

# Clean up sim flag file
sim_flags = config.SIM_DEFAULT_FLAGS.copy()
with open(config.SIM_FLAG_FILE, "w") as f:
    json.dump(sim_flags, f)

print()

# Missing flag file (should use defaults gracefully)
if os.path.exists(config.SIM_FLAG_FILE):
    os.remove(config.SIM_FLAG_FILE)

r = evaluate(gas_detected=False, temp_flagged=False)
all_pass &= check("Missing flag file (graceful)", r, FireDecision.CLEAR, 0.0, 0.0)

# Result
print()
if all_pass:
    print("\033[92mAll tests passed.\033[0m")
else:
    print("\033[91mSome tests FAILED - check weights and thresholds in config.py\033[0m")
