"""
FrameSight Setup Wizard — double-click 'Setup FrameSight.bat' to run.
"""
from __future__ import annotations

import subprocess
import sys
import threading
import webbrowser
from pathlib import Path
import tkinter as tk
from tkinter import ttk

ROOT   = Path(__file__).parent
VENV   = ROOT / ".venv"
PYTHON = VENV / "Scripts" / "python.exe"

# ── palette ────────────────────────────────────────────────────────────────────
BG     = "#0d0d0d"
CARD   = "#111111"
BORDER = "#1e1e1e"
FG     = "#e0e0e0"
FG2    = "#555555"
GREEN  = "#00ff88"
BLUE   = "#00aaff"
RED    = "#ff4444"
YELLOW = "#ffdd00"


# ── custom button ──────────────────────────────────────────────────────────────
class Btn(tk.Frame):
    def __init__(self, parent, text, command=None, color=GREEN, **kw):
        super().__init__(parent, bg=BORDER, padx=1, pady=1, **kw)
        self._bg  = tk.Frame(self, bg=CARD, padx=22, pady=9)
        self._bg.pack(fill="both", expand=True)
        self._lbl = tk.Label(self._bg, text=text, fg=color, bg=CARD,
                             font=("Consolas", 10, "bold"), cursor="hand2")
        self._lbl.pack()
        self._cmd   = command
        self._color = color
        for w in (self, self._bg, self._lbl):
            w.bind("<Button-1>", self._on_click)
            w.bind("<Enter>",    self._on_enter)
            w.bind("<Leave>",    self._on_leave)

    def _on_click(self, _=None):
        if self._cmd:
            self._cmd()

    def _on_enter(self, _=None):
        self._bg.configure(bg="#1a1a1a")
        self._lbl.configure(bg="#1a1a1a")

    def _on_leave(self, _=None):
        self._bg.configure(bg=CARD)
        self._lbl.configure(bg=CARD)

    def set_text(self, t):
        self._lbl.configure(text=t)

    def set_color(self, c):
        self._lbl.configure(fg=c)

    def disable(self):
        self._cmd = None
        self._lbl.configure(fg=FG2, cursor="")

    def enable(self, command=None):
        if command:
            self._cmd = command
        self._lbl.configure(fg=self._color, cursor="hand2")


# ── wizard ─────────────────────────────────────────────────────────────────────
class Wizard(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("FrameSight Setup")
        self.configure(bg=BG)
        self.resizable(False, False)
        W, H = 560, 520
        self.geometry(f"{W}x{H}")
        self.update_idletasks()
        x = (self.winfo_screenwidth()  - W) // 2
        y = (self.winfo_screenheight() - H) // 2
        self.geometry(f"{W}x{H}+{x}+{y}")

        self._page      = -1
        self._install_ok = False
        self._proc       = None

        self._build_chrome()
        self._show(0)

    # ── chrome ────────────────────────────────────────────────────────
    def _build_chrome(self):
        # Header
        hdr = tk.Frame(self, bg=BG)
        hdr.pack(fill="x", padx=30, pady=(22, 0))
        tk.Label(hdr, text="⬡ FRAMESIGHT", fg=GREEN, bg=BG,
                 font=("Consolas", 18, "bold")).pack(anchor="w")
        tk.Label(hdr, text="Real-time detection overlay  ·  Setup",
                 fg=FG2, bg=BG, font=("Consolas", 9)).pack(anchor="w", pady=(1, 0))

        # Step breadcrumb
        bc = tk.Frame(self, bg=BG)
        bc.pack(fill="x", padx=30, pady=(14, 0))
        self._crumbs = []
        for i, label in enumerate(("Welcome", "Install", "Done")):
            f = tk.Frame(bc, bg=BG)
            f.pack(side="left", padx=(0, 18))
            n = tk.Label(f, text=str(i + 1), fg=FG2, bg=BG,
                         font=("Consolas", 9, "bold"), width=2)
            n.pack(side="left")
            l = tk.Label(f, text=label, fg=FG2, bg=BG,
                         font=("Consolas", 9))
            l.pack(side="left")
            self._crumbs.append((n, l))

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=30, pady=(12, 0))

        # Content container
        self._body = tk.Frame(self, bg=BG)
        self._body.pack(fill="both", expand=True, padx=30, pady=12)

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", padx=30)

        # Footer buttons
        ftr = tk.Frame(self, bg=BG)
        ftr.pack(fill="x", padx=30, pady=12)
        self._btn_back = Btn(ftr, "← BACK",  self._go_back, color=FG2)
        self._btn_back.pack(side="left")
        self._btn_next = Btn(ftr, "NEXT →", self._go_next, color=GREEN)
        self._btn_next.pack(side="right")

    def _clear(self):
        for w in self._body.winfo_children():
            w.destroy()

    def _show(self, idx: int):
        self._page = idx
        self._clear()

        for i, (n, l) in enumerate(self._crumbs):
            if i < idx:
                n.configure(fg=GREEN); l.configure(fg=GREEN)
            elif i == idx:
                n.configure(fg=BLUE);  l.configure(fg=BLUE)
            else:
                n.configure(fg=FG2);   l.configure(fg=FG2)

        self._btn_back.pack_forget() if idx == 0 else self._btn_back.pack(side="left")

        [self._p_welcome, self._p_install, self._p_done][idx]()

    def _go_next(self):
        if self._page == 0:
            if sys.version_info < (3, 10):
                return
            self._show(1)
            self.after(200, self._run_install)
        elif self._page == 1:
            if self._install_ok:
                self._show(2)
        elif self._page == 2:
            self._launch()

    def _go_back(self):
        if self._page == 1 and not self._install_ok:
            return
        if self._page > 0:
            self._show(self._page - 1)

    # ── page 0: welcome ───────────────────────────────────────────────
    def _p_welcome(self):
        c = self._body
        self._btn_next.set_text("NEXT →")
        self._btn_next.set_color(GREEN)

        tk.Label(c, text="Welcome", fg=FG, bg=BG,
                 font=("Consolas", 13, "bold")).pack(anchor="w", pady=(2, 2))
        tk.Label(c, text="This wizard will install FrameSight's dependencies and create a launcher.",
                 fg=FG2, bg=BG, font=("Consolas", 9), wraplength=480,
                 justify="left").pack(anchor="w")

        tk.Frame(c, bg=BG, height=12).pack()

        # What-we-do card
        card = tk.Frame(c, bg=CARD, highlightbackground=BORDER,
                        highlightthickness=1)
        card.pack(fill="x")
        inner = tk.Frame(card, bg=CARD, padx=16, pady=14)
        inner.pack(fill="x")
        for tag, col, desc in (
            ("[CHECK]",   BLUE,  "Verify Python 3.10+ and locate model weights"),
            ("[INSTALL]", GREEN, "Create .venv and install Python packages"),
            ("[LAUNCH]",  GREEN, "Create a one-click launcher + open HUD panel"),
        ):
            row = tk.Frame(inner, bg=CARD)
            row.pack(anchor="w", pady=2)
            tk.Label(row, text=tag, fg=col, bg=CARD,
                     font=("Consolas", 9, "bold"), width=12,
                     anchor="w").pack(side="left")
            tk.Label(row, text=desc, fg=FG, bg=CARD,
                     font=("Consolas", 9)).pack(side="left")

        tk.Frame(c, bg=BG, height=14).pack()

        # Live checks
        pyver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        py_ok = sys.version_info >= (3, 10)

        weights = list((ROOT / "weights").glob("*.onnx"))
        w_ok    = len(weights) > 0
        wname   = weights[0].name if w_ok else "no .onnx found in weights/"

        venv_ok   = PYTHON.exists()
        venv_note = "already set up" if venv_ok else "will be created"

        for ok, line in (
            (py_ok,   f"Python {pyver}"),
            (w_ok,    f"Weights:  {wname}"),
            (venv_ok, f"Venv:     {venv_note}"),
        ):
            row = tk.Frame(c, bg=BG)
            row.pack(anchor="w", pady=2)
            tk.Label(row, text="✓" if ok else ("✗" if not w_ok and line.startswith("W") else "○"),
                     fg=GREEN if ok else (RED if not ok and line.startswith("P") else FG2),
                     bg=BG, font=("Consolas", 11, "bold"), width=3).pack(side="left")
            tk.Label(row, text=line,
                     fg=FG if ok else (RED if not ok and line.startswith("P") else FG2),
                     bg=BG, font=("Consolas", 9)).pack(side="left")

        if not py_ok:
            tk.Label(c, text="  Python 3.10+ is required — get it from python.org",
                     fg=RED, bg=BG, font=("Consolas", 9)).pack(anchor="w", pady=(6, 0))
            self._btn_next.set_text("PYTHON REQUIRED")
            self._btn_next.set_color(FG2)

    # ── page 1: install ───────────────────────────────────────────────
    def _p_install(self):
        c = self._body
        self._btn_next.set_text("Installing…")
        self._btn_next.set_color(FG2)
        self._btn_next.disable()

        tk.Label(c, text="Installing", fg=FG, bg=BG,
                 font=("Consolas", 13, "bold")).pack(anchor="w", pady=(2, 2))
        tk.Label(c, text="Setting up your virtual environment and packages.",
                 fg=FG2, bg=BG, font=("Consolas", 9)).pack(anchor="w")

        tk.Frame(c, bg=BG, height=10).pack()

        # Status rows
        self._status_rows = {}
        sf = tk.Frame(c, bg=BG)
        sf.pack(fill="x")
        for key, label in (
            ("venv", "Create virtual environment"),
            ("pip",  "Upgrade pip"),
            ("deps", "Install dependencies"),
            ("gpu",  "Detect GPU / DirectML"),
        ):
            row = tk.Frame(sf, bg=BG)
            row.pack(anchor="w", pady=3)
            icon = tk.Label(row, text="○", fg=FG2, bg=BG,
                            font=("Consolas", 11), width=3)
            icon.pack(side="left")
            lbl  = tk.Label(row, text=label, fg=FG2, bg=BG,
                            font=("Consolas", 9))
            lbl.pack(side="left")
            self._status_rows[key] = (icon, lbl)

        tk.Frame(c, bg=BG, height=8).pack()

        # Progress bar
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("fs.Horizontal.TProgressbar",
                        background=GREEN, troughcolor=CARD,
                        bordercolor=BORDER, lightcolor=GREEN, darkcolor=GREEN)
        self._pbar = ttk.Progressbar(c, mode="indeterminate", length=480,
                                     style="fs.Horizontal.TProgressbar")
        self._pbar.pack(pady=(0, 8))

        # Log box
        lf = tk.Frame(c, bg=CARD, highlightbackground=BORDER,
                      highlightthickness=1)
        lf.pack(fill="both", expand=True)
        sb = tk.Scrollbar(lf, bg=CARD, troughcolor=CARD, activebackground=BORDER,
                          relief="flat", bd=0)
        sb.pack(side="right", fill="y")
        self._log = tk.Text(lf, bg=CARD, fg="#444", font=("Consolas", 8),
                            relief="flat", bd=0, state="disabled", wrap="word",
                            yscrollcommand=sb.set)
        sb.configure(command=self._log.yview)
        self._log.pack(fill="both", expand=True, padx=10, pady=8)

    def _log_append(self, text: str):
        self._log.configure(state="normal")
        self._log.insert("end", text)
        self._log.see("end")
        self._log.configure(state="disabled")

    def _set_row(self, key: str, state: str):
        states = {
            "pending": ("○", FG2),
            "running": ("◌", BLUE),
            "ok":      ("✓", GREEN),
            "warn":    ("⚠", YELLOW),
            "error":   ("✗", RED),
        }
        icon_ch, color = states.get(state, ("○", FG2))
        icon, lbl = self._status_rows[key]
        self.after(0, lambda: (icon.configure(text=icon_ch, fg=color),
                               lbl.configure(fg=color)))

    def _log(self, text: str):
        self.after(0, lambda: self._log_append(text))

    def _run_install(self):
        threading.Thread(target=self._install_thread, daemon=True).start()

    def _install_thread(self):
        self._pbar.start(14)
        ok = True

        # ── venv ──────────────────────────────────────────────────────
        self._set_row("venv", "running")
        if not PYTHON.exists():
            self._log(f"Creating .venv…\n")
            r = subprocess.run(
                [sys.executable, "-m", "venv", str(VENV)],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                self._log(r.stderr)
                self._set_row("venv", "error")
                ok = False
            else:
                self._set_row("venv", "ok")
        else:
            self._log(f"Venv already exists at {VENV.name}\n")
            self._set_row("venv", "ok")

        # ── pip upgrade ───────────────────────────────────────────────
        if ok:
            self._set_row("pip", "running")
            self._log("Upgrading pip…\n")
            r = subprocess.run(
                [str(PYTHON), "-m", "pip", "install", "--upgrade", "pip", "-q"],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                self._log(r.stderr)
                self._set_row("pip", "error")
                ok = False
            else:
                self._set_row("pip", "ok")

        # ── requirements ──────────────────────────────────────────────
        if ok:
            self._set_row("deps", "running")
            req = ROOT / "requirements.txt"
            self._log(f"pip install -r {req.name}…\n")
            proc = subprocess.Popen(
                [str(PYTHON), "-m", "pip", "install", "-r", str(req)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, env={**__import__("os").environ,
                                           "ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS": "1"},
            )
            for line in proc.stdout:
                self._log(line)
            proc.wait()
            if proc.returncode != 0:
                self._set_row("deps", "error")
                ok = False
            else:
                self._set_row("deps", "ok")

        # ── GPU / DirectML ────────────────────────────────────────────
        if ok:
            self._set_row("gpu", "running")
            try:
                gpu_out = subprocess.run(
                    ["powershell", "-Command",
                     "Get-CimInstance Win32_VideoController | "
                     "Select-Object -ExpandProperty Name"],
                    capture_output=True, text=True, timeout=10,
                ).stdout
                gpus = [g.strip() for g in gpu_out.splitlines() if g.strip()]
                self._log("GPUs: " + ", ".join(gpus) + "\n" if gpus else "No GPU detected\n")
                is_amd_intel = any(
                    any(v in g for v in ("AMD", "Radeon", "Intel", "Arc"))
                    for g in gpus
                )
                if is_amd_intel:
                    self._log("AMD/Intel GPU — installing onnxruntime-directml…\n")
                    subprocess.run(
                        [str(PYTHON), "-m", "pip", "uninstall", "-y", "onnxruntime"],
                        capture_output=True,
                    )
                    r2 = subprocess.run(
                        [str(PYTHON), "-m", "pip", "install",
                         "onnxruntime-directml>=1.17.0"],
                        capture_output=True, text=True,
                    )
                    if r2.returncode != 0:
                        self._log(r2.stderr)
                        self._set_row("gpu", "warn")
                    else:
                        self._set_row("gpu", "ok")
                else:
                    self._set_row("gpu", "ok")
            except Exception as exc:
                self._log(f"GPU check skipped: {exc}\n")
                self._set_row("gpu", "warn")

        self._pbar.stop()
        self._install_ok = ok
        if ok:
            self.after(0, self._install_finished)
        else:
            self.after(0, lambda: (
                self._btn_next.set_text("INSTALL FAILED"),
                self._btn_next.set_color(RED),
            ))

    def _install_finished(self):
        self._btn_next.set_text("NEXT →")
        self._btn_next.set_color(GREEN)
        self._btn_next.enable(self._go_next)

    # ── page 2: done ──────────────────────────────────────────────────
    def _p_done(self):
        c = self._body
        self._btn_next.set_text("LAUNCH →")
        self._btn_next.set_color(GREEN)
        self._btn_next.enable(self._go_next)

        tk.Label(c, text="✓  Ready", fg=GREEN, bg=BG,
                 font=("Consolas", 13, "bold")).pack(anchor="w", pady=(2, 2))
        tk.Label(c, text="FrameSight is installed. Click LAUNCH to start.",
                 fg=FG2, bg=BG, font=("Consolas", 9)).pack(anchor="w")

        tk.Frame(c, bg=BG, height=16).pack()

        card = tk.Frame(c, bg=CARD, highlightbackground=BORDER,
                        highlightthickness=1)
        card.pack(fill="x")
        inner = tk.Frame(card, bg=CARD, padx=16, pady=16)
        inner.pack(fill="x")
        for tag, desc in (
            ("HUD:",     "http://localhost:5000  —  colors, magnifier, lines"),
            ("Config:",  "Edit config/local.yaml to override any setting"),
            ("Launcher:", "framesight_launcher.pyw — double-click anytime"),
        ):
            row = tk.Frame(inner, bg=CARD)
            row.pack(anchor="w", pady=3)
            tk.Label(row, text=tag, fg=BLUE, bg=CARD,
                     font=("Consolas", 9, "bold"), width=12,
                     anchor="w").pack(side="left")
            tk.Label(row, text=desc, fg=FG, bg=CARD,
                     font=("Consolas", 9)).pack(side="left")

        tk.Frame(c, bg=BG, height=16).pack()

        self._write_launcher()
        launcher = ROOT / "framesight_launcher.pyw"
        ok2 = launcher.exists()
        row = tk.Frame(c, bg=BG)
        row.pack(anchor="w")
        tk.Label(row, text="✓" if ok2 else "○", fg=GREEN if ok2 else FG2,
                 bg=BG, font=("Consolas", 10, "bold"), width=3).pack(side="left")
        tk.Label(row, text="Launcher ready", fg=FG2, bg=BG,
                 font=("Consolas", 9)).pack(side="left")

    def _write_launcher(self):
        launcher = ROOT / "framesight_launcher.pyw"
        if not launcher.exists():
            launcher.write_text(
                (ROOT / "framesight_launcher.pyw").read_text()
                if False else _LAUNCHER_SRC,
                encoding="utf-8",
            )

    def _launch(self):
        import os, subprocess
        env = {**os.environ, "ULTRALYTICS_SKIP_REQUIREMENTS_CHECKS": "1"}
        subprocess.Popen(
            [str(PYTHON), "-m", "src.main"],
            cwd=str(ROOT), env=env,
            creationflags=subprocess.CREATE_NEW_CONSOLE,
        )
        self.after(2800, lambda: webbrowser.open("http://localhost:5000"))
        self.destroy()


# ── launcher source (written out by wizard if .pyw missing) ───────────────────
_LAUNCHER_SRC = '''\
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

        tk.Label(self, text="\\u29c6 FRAMESIGHT", fg=GREEN, bg=BG,
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
'''


if __name__ == "__main__":
    Wizard().mainloop()
