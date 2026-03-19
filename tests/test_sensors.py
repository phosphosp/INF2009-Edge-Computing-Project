# Run this directly on the Pi to verify both sensors
# Does NOT require any actuators to be wired up

import time
import sys
import os
import config

# Allow running from tests folder
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sensors.gas_sensor import GasSensor
from sensors.temp_sensor import TempSensor

print("=" * 50)
print("Sensor test - press Ctrl+C to stop")
print("=" * 50)

gas = GasSensor()
temp = TempSensor()

# Give DHT22 time for first read
print("\nWaiting 3s for DHT22 first read...\n")
time.sleep(3)

print(f"Note: MQ2 warmup period is {config.GAS_WARMUP_SEC}s - gas readings suppressed until complete\n")

try:
    while True:
        g = gas.read()
        t = temp.read()

        # Gas warmup tag
        gas_tag = f"[WARMING UP {g['warmup_elapsed_sec']}s/{config.GAS_WARMUP_SEC}s]" \
                  if g['warming_up'] else "[READY]"

        print(
            f"GAS  {gas_tag} -> raw={g['raw']}  detected={g['detected']}  "
            f"consec={g['consec_count']}"
        )
        print(
            f"TEMP -> {t['temp']}°C  avg={t['avg_temp']}  "
            f"flagged={t['flagged']}  warmup={t['warming_up']}\n"
        )

        time.sleep(0.5)

except KeyboardInterrupt:
    print("\nStopping...")

finally:
    gas.cleanup()
    temp.cleanup()
    print("Done.")