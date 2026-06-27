"""FrameSight launcher — no console window."""
from __future__ import annotations
import os, subprocess, sys, threading, webbrowser
from pathlib import Path
import tkinter as tk

ROOT   = Path(__file__).parent
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
if not PYTHON.exists():
    PYTHON = Path(sys.executable)

BG, GREEN, RED, BLUE, FG, FG2 = "#0d0d0d","#00ff88","#ff4444","#00aaff","#e0e0e0","#555"

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FrameSight")
        self.geometry("300x148")
        self.resizable(False, False)
        self.configure(bg=BG)
        self.attributes("-topmost", True)
        x = (self.winfo_screenwidth()  - 300) // 2
        y =  self.winfo_screenheight() - 200
        self.geometry(f"300x148+{x}+{y}")

        tk.Label(self, text="⧆ FRAMESIGHT", fg=GREEN, bg=BG,
                 font=("Consolas", 13, "bold")).pack(pady=(14, 3))
        self._st = tk.Label(self, text="Starting…", fg=FG2, bg=BG,
                            font=("Consolas", 9))
        self._st.pack()

        row = tk.Frame(self, bg=BG)
        row.pack(pady=14)
        for text, color, cb in (
            ("OPEN HUD", GREEN, lambda: webbrowser.open("http://localhost:5000")),
            ("STOP",     RED,   self._stop),
        ):
            lbl = tk.Label(row, text=text, fg=color, bg="#111",
                           font=("Consolas", 9, "bold"), padx=14, pady=7,
                           cursor="hand2")
            lbl.pack(side="left", padx=5)
            lbl.bind("<Button-1>", lambda _e, f=cb: f())

        self._proc = None
        self.protocol("WM_DELETE_WINDOW", self._stop)
        threading.Thread(target=self._start, daemon=True).start()

    def _start(self):
        env = {**os.environ, "ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS": "1"}
        self._proc = subprocess.Popen(
            [str(PYTHON), "-m", "src.main"],
            cwd=str(ROOT), env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        self.after(2800, lambda: webbrowser.open("http://localhost:5000"))
        self.after(0, lambda: self._st.configure(text="Running", fg=GREEN))
        for line in self._proc.stdout:
            if "capture" in line and "fps" in line:
                txt = line.strip()[:46]
                self.after(0, lambda t=txt: self._st.configure(text=t, fg=FG2))
        self._proc.wait()
        self.after(0, lambda: self._st.configure(text="Stopped", fg=FG2))

    def _stop(self, _=None):
        if self._proc:
            self._proc.terminate()
        self.destroy()

App().mainloop()
