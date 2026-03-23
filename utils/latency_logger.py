# Latency logger for fire detection pipeline

# Measures timing of each implemented stage in the main loop
# Logs to console (throttled) and to a CSV file for analysis

import time
import csv
import os
from collections import deque

# How many recent samples to keep for rolling stats
_ROLLING_WINDOW = 100

# How many loop ticks between console prints
_LOG_EVERY_N_TICKS = 50 # 50 ticks x 100ms = ~every 5 seconds

# CSV output path
_CSV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs", "latency_log.csv")


class LatencyLogger:
    def __init__(self, csv_path: str = _CSV_PATH, enabled: bool = True):
        self.enabled = enabled
        self._tick = 0
        self._loop_start = 0.0
        self._marks: dict[str, float] = {} # stage -> absolute timestamp
        self._last_mark_time = 0.0 # for delta calculation

        # Rolling windows per stage: stage -> deque of ms values
        self._rolling: dict[str, deque] = {}

        # CSV setup
        self._csv_path = csv_path
        self._csv_file = None
        self._csv_writer = None

        if self.enabled:
            self._init_csv()
            print(f"[LatencyLogger] Logging to {self._csv_path}")

    # CSV initialisation
    def _init_csv(self):
        os.makedirs(os.path.dirname(self._csv_path), exist_ok=True)
        write_header = not os.path.exists(self._csv_path)
        self._csv_file = open(self._csv_path, "a", newline="", buffering=1)
        self._csv_writer = csv.writer(self._csv_file)
        if write_header:
            self._csv_writer.writerow([
                "tick", "timestamp",
                "gas_read_ms", "temp_read_ms", "fusion_ms",
                "actuation_ms", "mqtt_publish_ms",
                "total_loop_ms", "budget_ok"
            ])

    # Public API
    def start(self):
        """
        Call at the very top of the main loop, before any stage
        Records loop start time and resets stage marks
        """
        if not self.enabled:
            return
        self._tick += 1
        self._loop_start = time.perf_counter()
        self._last_mark_time = self._loop_start
        self._marks = {}

    def mark(self, stage: str):
        """
        Call immediately after a stage completes
        Records the elapsed time since the previous mark (or loop start)
        """
        if not self.enabled:
            return
        now = time.perf_counter()
        delta_ms = (now - self._last_mark_time) * 1000
        self._marks[stage] = delta_ms
        self._last_mark_time = now

        # Update rolling window
        if stage not in self._rolling:
            self._rolling[stage] = deque(maxlen=_ROLLING_WINDOW)
        self._rolling[stage].append(delta_ms)

    def finish(self):
        """
        Call at the end of the main loop tick (before sleep)
        Computes total loop time, logs to CSV, prints throttled console summary
        """
        if not self.enabled:
            return

        total_ms = (time.perf_counter() - self._loop_start) * 1000
        budget_ok = total_ms <= 100.0

        # Update rolling for total
        if "total" not in self._rolling:
            self._rolling["total"] = deque(maxlen=_ROLLING_WINDOW)
        self._rolling["total"].append(total_ms)

        # Write CSV row
        if self._csv_writer:
            self._csv_writer.writerow([
                self._tick,
                time.strftime("%H:%M:%S"),
                round(self._marks.get("gas_read",     0.0), 3),
                round(self._marks.get("temp_read",    0.0), 3),
                round(self._marks.get("fusion",       0.0), 3),
                round(self._marks.get("actuation",    0.0), 3),
                round(self._marks.get("mqtt_publish", 0.0), 3),
                round(total_ms, 3),
                budget_ok,
            ])

        # Throttled console print
        if self._tick % _LOG_EVERY_N_TICKS == 0:
            self._print_summary(total_ms, budget_ok)

    # Console summary
    def _print_summary(self, total_ms: float, budget_ok: bool):
        status = "OK" if budget_ok else "OVER BUDGET"

        def _fmt(stage: str) -> str:
            val = self._marks.get(stage, 0.0)
            avg = self._avg(stage)
            worst = self._worst(stage)
            return f"{val:6.2f}ms  (avg {avg:5.2f}  worst {worst:5.2f})"

        avg_total   = self._avg("total")
        worst_total = self._worst("total")

        print(
            f"\n[Latency] tick={self._tick}  total={total_ms:.2f}ms "
            f"(avg {avg_total:.2f}  worst {worst_total:.2f})  [{status}]"
        )
        print(f"  gas_read     : {_fmt('gas_read')}")
        print(f"  temp_read    : {_fmt('temp_read')}")
        print(f"  fusion       : {_fmt('fusion')}")
        print(f"  actuation    : {_fmt('actuation')}")
        print(f"  mqtt_publish : {_fmt('mqtt_publish')}")

        if not budget_ok:
            print(f"  *** WARNING: loop exceeded 100ms budget ({total_ms:.2f}ms) ***")

    # Rolling stat helpers
    def _avg(self, stage: str) -> float:
        w = self._rolling.get(stage)
        return sum(w) / len(w) if w else 0.0

    def _worst(self, stage: str) -> float:
        w = self._rolling.get(stage)
        return max(w) if w else 0.0

    # Cleanup
    def cleanup(self):
        if self._csv_file:
            try:
                self._csv_file.close()
            except Exception:
                pass
        print("[LatencyLogger] Closed log file.")