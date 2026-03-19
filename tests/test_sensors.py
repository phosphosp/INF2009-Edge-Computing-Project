# Run this directly on the Pi to verify both sensors
# Does NOT require any actuators to be wired up

import time
import sys
import os

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

try:
    while True:
        g = gas.read()
        t = temp.read()

        print(
            f"GAS -> raw={g['raw']}  detected={g['detected']}  "
            f"consec={g['consec_count']}   |   "
            f"TEMP -> {t['temp']}°C  avg={t['avg_temp']}  "
            f"flagged={t['flagged']}  warmup={t['warming_up']}"
        )
        time.sleep(0.5)

except KeyboardInterrupt:
    print("\nStopping...")

finally:
    gas.cleanup()
    temp.cleanup()
    print("Done.")