import sys
import os
import subprocess
import webbrowser
import urllib.request
import tkinter as tk
from tkinter import ttk

SERVER_PROCESS = None
PORT = 8787

class ZipStreamControlPanel(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("ZipStream Hub — Control Panel")
        self.geometry("480x420")
        self.resizable(False, False)
        self.configure(bg="#0f172a")

        self.style = ttk.Style(self)
        self.style.theme_use("clam")

        self._create_widgets()
        self.check_server_status()

    def _create_widgets(self):
        header_frame = tk.Frame(self, bg="#1e293b", height=80, padx=20, pady=15)
        header_frame.pack(fill="x")

        title_lbl = tk.Label(
            header_frame,
            text="⚡ ZipStream Control Panel",
            font=("Segoe UI", 14, "bold"),
            fg="#f8fafc",
            bg="#1e293b"
        )
        title_lbl.pack(anchor="w")

        sub_lbl = tk.Label(
            header_frame,
            text="Remote ZIP streaming & direct episode extraction engine",
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#1e293b"
        )
        sub_lbl.pack(anchor="w", pady=(2, 0))

        content_frame = tk.Frame(self, bg="#0f172a", padx=25, pady=20)
        content_frame.pack(fill="both", expand=True)

        status_box = tk.LabelFrame(
            content_frame,
            text=" Service Status ",
            font=("Segoe UI", 9, "bold"),
            fg="#cbd5e1",
            bg="#1e293b",
            padx=15,
            pady=12
        )
        status_box.pack(fill="x", pady=(0, 20))

        self.status_dot = tk.Label(status_box, text="●", font=("Segoe UI", 16), fg="#ef4444", bg="#1e293b")
        self.status_dot.pack(side="left", padx=(0, 8))

        self.status_text = tk.Label(
            status_box,
            text="Service Stopped",
            font=("Segoe UI", 10, "bold"),
            fg="#f8fafc",
            bg="#1e293b"
        )
        self.status_text.pack(side="left")

        self.port_label = tk.Label(
            status_box,
            text=f"Port: {PORT}",
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#1e293b"
        )
        self.port_label.pack(side="right")

        btn_frame = tk.Frame(content_frame, bg="#0f172a")
        btn_frame.pack(fill="x", pady=5)

        self.btn_toggle = tk.Button(
            btn_frame,
            text="▶ Start Server",
            font=("Segoe UI", 10, "bold"),
            fg="#ffffff",
            bg="#10b981",
            activebackground="#059669",
            activeforeground="#ffffff",
            relief="flat",
            height=2,
            cursor="hand2",
            command=self.toggle_server
        )
        self.btn_toggle.pack(fill="x", pady=(0, 10))

        self.btn_open_gui = tk.Button(
            btn_frame,
            text="🌐 Open Web GUI Dashboard",
            font=("Segoe UI", 10, "bold"),
            fg="#ffffff",
            bg="#6366f1",
            activebackground="#4f46e5",
            activeforeground="#ffffff",
            relief="flat",
            height=2,
            cursor="hand2",
            command=self.open_web_gui
        )
        self.btn_open_gui.pack(fill="x", pady=(0, 10))

        footer_lbl = tk.Label(
            self,
            text="Tip: Start service and click 'Open Web GUI' to paste remote ZIP links.",
            font=("Segoe UI", 8),
            fg="#64748b",
            bg="#0f172a",
            pady=10
        )
        footer_lbl.pack(side="bottom")

    def toggle_server(self):
        global SERVER_PROCESS
        if SERVER_PROCESS is None or SERVER_PROCESS.poll() is not None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            backend_script = os.path.join(base_dir, "server.py")
            python_exe = sys.executable
            SERVER_PROCESS = subprocess.Popen([python_exe, backend_script], cwd=base_dir)
            self.set_running_state(True)
            self.after(500, self.open_web_gui)
        else:
            SERVER_PROCESS.terminate()
            SERVER_PROCESS = None
            self.set_running_state(False)

    def set_running_state(self, is_running):
        if is_running:
            self.status_dot.config(fg="#10b981")
            self.status_text.config(text="Service Running (Active)")
            self.btn_toggle.config(
                text="⏹ Stop Server",
                bg="#ef4444",
                activebackground="#dc2626"
            )
        else:
            self.status_dot.config(fg="#ef4444")
            self.status_text.config(text="Service Stopped")
            self.btn_toggle.config(
                text="▶ Start Server",
                bg="#10b981",
                activebackground="#059669"
            )

    def open_web_gui(self):
        webbrowser.open(f"http://127.0.0.1:{PORT}")

    def check_server_status(self):
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{PORT}", method="HEAD")
            with urllib.request.urlopen(req, timeout=0.5) as resp:
                self.set_running_state(True)
        except Exception:
            self.set_running_state(False)

if __name__ == "__main__":
    app = ZipStreamControlPanel()
    app.mainloop()
