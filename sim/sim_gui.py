# Demo simulation GUI - run as a separate process alongside main.py.

# Communicates with main.py only through the JSON flag file.
# Reads the flag file periodically to show live status.

import sys
import os
import tkinter as tk
from tkinter import font as tkfont

# Allow running from sim folder
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from sim.sim_flags import set_scenario, set_flag, reset_all, get_all

# Colour palette
BG = "#1e1e2e"
BG_CARD = "#2a2a3e"
FG = "#cdd6f4"
FG_DIM = "#6c7086"
ACCENT_FIRE = "#f38ba8"
ACCENT_WARN = "#fab387"
ACCENT_OK = "#a6e3a1"
ACCENT_BLUE = "#89b4fa"
BTN_ACTIVE = "#313244"
BORDER = "#45475a"

class SimGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Fire Detection - Sim Control")
        self.root.configure(bg=BG)
        self.root.resizable(False, False)

        # Fonts
        self.font_title = tkfont.Font(family="Helvetica", size=13, weight="bold")
        self.font_label = tkfont.Font(family="Helvetica", size=11)
        self.font_btn = tkfont.Font(family="Helvetica", size=11, weight="bold")
        self.font_small = tkfont.Font(family="Courier",   size=10)
        self.font_status = tkfont.Font(family="Helvetica", size=14, weight="bold")

        # Track active scenario for button highlight
        self._active_scenario = tk.StringVar(value="clear")

        # Track manual override toggle states
        self._alarm_on = False
        self._lock_on = False
        self._unlock_on = False

        self._build_ui()
        self._poll_flags() # start live readout loop

    # UI construction
    def _build_ui(self):
        pad = {"padx": 16, "pady": 8}

        # Header
        header = tk.Frame(self.root, bg=BG)
        header.pack(fill="x", **pad)

        tk.Label(
            header, text="FIRE DETECTION",
            font=self.font_title, bg=BG, fg=ACCENT_FIRE
        ).pack(side="left")

        tk.Label(
            header, text="Simulation Control",
            font=self.font_label, bg=BG, fg=FG_DIM
        ).pack(side="left", padx=(8, 0))

        self._divider()

        # Scenario buttons
        self._section_label("SCENARIOS")

        scenario_frame = tk.Frame(self.root, bg=BG)
        scenario_frame.pack(fill="x", padx=16, pady=(0, 8))

        self._scenario_btn(scenario_frame, "Full Fire", "fire", ACCENT_FIRE, 0, 0)
        self._scenario_btn(scenario_frame, "Gas Only", "gas_only", ACCENT_WARN, 0, 1)
        self._scenario_btn(scenario_frame, "Temp Only", "temp_only", ACCENT_BLUE, 1, 0)
        self._scenario_btn(scenario_frame, "Clear", "clear", ACCENT_OK,   1, 1)

        self._divider()

        # Manual overrides
        self._section_label("MANUAL OVERRIDES")

        override_frame = tk.Frame(self.root, bg=BG)
        override_frame.pack(fill="x", padx=16, pady=(0, 8))

        self.btn_alarm  = self._toggle_btn(
            override_frame, "Force Alarm", self._toggle_alarm, ACCENT_FIRE, 0)
        self.btn_lock   = self._toggle_btn(
            override_frame, "Lock Door", self._toggle_lock, ACCENT_BLUE, 1)
        self.btn_unlock = self._toggle_btn(
            override_frame, "Unlock Door", self._toggle_unlock, ACCENT_OK, 2)

        self._divider()

        # Live status
        self._section_label("ACTIVE FLAGS  (live)")

        status_frame = tk.Frame(self.root, bg=BG_CARD, relief="flat")
        status_frame.pack(fill="x", padx=16, pady=(0, 8))

        self.flag_vars = {}
        for key in config.SIM_DEFAULT_FLAGS:
            row = tk.Frame(status_frame, bg=BG_CARD)
            row.pack(fill="x", padx=12, pady=2)

            tk.Label(
                row, text=f"{key}",
                font=self.font_small, bg=BG_CARD, fg=FG_DIM,
                width=22, anchor="w"
            ).pack(side="left")

            var = tk.StringVar(value="False")
            lbl = tk.Label(
                row, textvariable=var,
                font=self.font_small, bg=BG_CARD, fg=FG_DIM
            )
            lbl.pack(side="left")
            self.flag_vars[key] = (var, lbl)

        # Padding at bottom
        tk.Frame(self.root, bg=BG, height=8).pack()

    def _divider(self):
        tk.Frame(self.root, bg=BORDER, height=1).pack(fill="x", padx=16, pady=4)

    def _section_label(self, text):
        tk.Label(
            self.root, text=text,
            font=self.font_label, bg=BG, fg=FG_DIM,
            anchor="w"
        ).pack(fill="x", padx=16, pady=(6, 2))

    def _scenario_btn(self, parent, label, scenario, colour, row, col):
        """Scenario button - highlights when active, clears others"""
        btn = tk.Button(
            parent,
            text=label,
            font=self.font_btn,
            bg=BG_CARD, fg=colour,
            activebackground=BTN_ACTIVE,
            activeforeground=colour,
            relief="flat",
            bd=0,
            padx=12, pady=8,
            cursor="hand2",
            command=lambda s=scenario: self._activate_scenario(s)
        )
        btn.grid(row=row, column=col, padx=6, pady=4, sticky="ew")
        parent.grid_columnconfigure(col, weight=1)

    def _toggle_btn(self, parent, label, command, colour, col):
        """Toggle button for manual overrides - shows ON/OFF state"""
        btn = tk.Button(
            parent,
            text=label,
            font=self.font_btn,
            bg=BG_CARD, fg=colour,
            activebackground=BTN_ACTIVE,
            activeforeground=colour,
            relief="flat",
            bd=0,
            padx=10, pady=8,
            cursor="hand2",
            command=command
        )
        btn.grid(row=0, column=col, padx=6, pady=4, sticky="ew")
        parent.grid_columnconfigure(col, weight=1)
        return btn

    # Button handlers
    def _activate_scenario(self, scenario: str):
        set_scenario(scenario)
        self._active_scenario.set(scenario)
        print(f"[SimGUI] Scenario: {scenario}")

    def _toggle_alarm(self):
        self._alarm_on = not self._alarm_on
        set_flag("manual_alarm", self._alarm_on)
        self._update_toggle_btn(
            self.btn_alarm, self._alarm_on,
            "Force Alarm  [ON]", "Force Alarm",
            ACCENT_FIRE
        )

    def _toggle_lock(self):
        # Mutex with unlock
        if not self._lock_on and self._unlock_on:
            self._unlock_on = False
            set_flag("manual_unlock", False)
            self._update_toggle_btn(
                self.btn_unlock, False,
                "", "Unlock Door", ACCENT_OK
            )
        self._lock_on = not self._lock_on
        set_flag("manual_lock", self._lock_on)
        self._update_toggle_btn(
            self.btn_lock, self._lock_on,
            "Lock Door  [ON]", "Lock Door",
            ACCENT_BLUE
        )

    def _toggle_unlock(self):
        # Mutex with lock
        if not self._unlock_on and self._lock_on:
            self._lock_on = False
            set_flag("manual_lock", False)
            self._update_toggle_btn(
                self.btn_lock, False,
                "", "Lock Door", ACCENT_BLUE
            )
        self._unlock_on = not self._unlock_on
        set_flag("manual_unlock", self._unlock_on)
        self._update_toggle_btn(
            self.btn_unlock, self._unlock_on,
            "Unlock Door  [ON]", "Unlock Door",
            ACCENT_OK
        )

    def _update_toggle_btn(self, btn, is_on, label_on, label_off, colour):
        """Update toggle button text and background to reflect state"""
        btn.config(
            text=label_on if is_on else label_off,
            bg=BTN_ACTIVE if is_on else BG_CARD,
        )

    # Live flag readout
    def _poll_flags(self):
        """Read flag file every 500ms and update the status display"""
        try:
            flags = get_all()
            for key, (var, lbl) in self.flag_vars.items():
                val = flags.get(key, False)
                var.set(str(val))
                lbl.config(fg=ACCENT_FIRE if val else FG_DIM)
        except Exception:
            pass

        # Schedule next poll
        self.root.after(500, self._poll_flags)


# Entry point
if __name__ == "__main__":
    # Reset all flags to clean state on launch
    reset_all()

    root = tk.Tk()

    # Centre window on screen
    root.update_idletasks()
    w, h = 420, 520
    x = (root.winfo_screenwidth() // 2) - (w // 2)
    y = (root.winfo_screenheight() // 2) - (h // 2)
    root.geometry(f"{w}x{h}+{x}+{y}")

    app = SimGUI(root)
    root.mainloop()

    # Clean up flags when window closes
    reset_all()
    print("[SimGUI] Closed - all flags reset.")
