# Clean API for reading and writing the simulation flag file.

# This is the only place that touches SIM_FLAG_FILE directly.
# Both sim_gui.py (writer) and fusion.py (reader) go through this API,
# so if the file path or format ever changes, it changes in one place.
import json
import os
import config

def _safe_read() -> dict:
    """Read current flags from file. Returns defaults on any failure"""
    try:
        if not os.path.exists(config.SIM_FLAG_FILE):
            return config.SIM_DEFAULT_FLAGS.copy()
        with open(config.SIM_FLAG_FILE, "r") as f:
            flags = json.load(f)
        merged = config.SIM_DEFAULT_FLAGS.copy()
        merged.update(flags)
        return merged
    except Exception:
        return config.SIM_DEFAULT_FLAGS.copy()

def _write(flags: dict):
    """Write flags dict to file atomically"""
    try:
        tmp = config.SIM_FLAG_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(flags, f, indent=2)
        os.replace(tmp, config.SIM_FLAG_FILE) # atomic on Linux
    except Exception as e:
        print(f"[SimFlags] Write error: {e}")

def get_all() -> dict:
    """Return current flags dict."""
    return _safe_read()

def set_flag(key: str, value: bool):
    """Set a single flag by name."""
    flags = _safe_read()
    if key not in flags:
        print(f"[SimFlags] Unknown flag: {key}")
        return
    flags[key] = value
    _write(flags)

def set_scenario(scenario: str):
    """
    Activate a named scenario. All other scenario flags are cleared first
    so only one scenario is ever active at once

    Scenarios:
      "fire" -> full fire (gas + temp + vision)
      "gas_only" -> gas sensor only
      "temp_only" -> temp sensor only
      "clear" -> all scenarios off (manual overrides untouched)
    """
    flags = _safe_read()

    # Clear all scenario flags first
    flags["fire_sim"] = False
    flags["gas_only_sim"] = False
    flags["temp_only_sim"] = False

    if scenario == "fire":
        flags["fire_sim"] = True
    elif scenario == "gas_only":
        flags["gas_only_sim"] = True
    elif scenario == "temp_only":
        flags["temp_only_sim"] = True
    elif scenario == "clear":
        pass # all already cleared above

    _write(flags)

def reset_all():
    """Reset every flag to its default (all False)"""
    _write(config.SIM_DEFAULT_FLAGS.copy())
    print("[SimFlags] All flags reset.")
