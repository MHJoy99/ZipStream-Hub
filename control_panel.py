import os
import sys
import time
import json
import socket
import threading
import subprocess
import webbrowser
import urllib.request
import urllib.parse
from typing import Optional, Dict, Any

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

try:
    import pystray
    from PIL import Image
    HAS_PYSTRAY = True
except ImportError:
    HAS_PYSTRAY = False

PORT = 8787
SERVER_PROCESS: Optional[subprocess.Popen] = None


class ZipStreamControlPanel(tk.Tk):
    """
    Enhanced desktop control panel for ZipStream Hub.
    Features:
    - Live bandwidth monitor (speed, total served, active streams) polling /api/stats.
    - Quick actions: Open Web Dashboard, Mount WebDAV / Network Drive, Export STRM Bundle, Toggle Server.
    - System tray minimization (pystray integration with graceful fallback).
    - Modern Jellyfin/Plex dark theme styling (#07090e, #0f172a, #1e293b, indigo/violet/emerald accents).
    """

    def __init__(self):
        super().__init__()

        self.title("ZipStream Hub — Control Panel")
        self.geometry("540x620")
        self.minsize(500, 580)
        self.resizable(True, True)
        self.configure(bg="#07090e")

        # Window icon if available
        self.icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zipstream_icon.ico")
        if os.path.exists(self.icon_path):
            try:
                self.iconbitmap(self.icon_path)
            except Exception:
                pass

        # State tracking
        self.is_running = False
        self.tray_icon = None
        self._stats_poll_job = None
        self._is_closing = False

        self._init_styles()
        self._create_widgets()
        self._setup_tray()

        # Handle window close protocol
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Initial checks and polling
        self.check_server_status()
        self.schedule_stats_poll()

    def _init_styles(self):
        self.style = ttk.Style(self)
        self.style.theme_use("clam")

        # Configure dark aesthetic
        self.style.configure(".", background="#07090e", foreground="#f8fafc")
        self.style.configure("Dark.TFrame", background="#07090e")
        self.style.configure("Card.TFrame", background="#10172a", relief="flat")
        self.style.configure("Header.TFrame", background="#0f172a", relief="flat")

    def _create_widgets(self):
        # 1. Header Banner
        header = tk.Frame(self, bg="#0f172a", padx=24, pady=16, highlightthickness=1, highlightbackground="#1e293b")
        header.pack(fill="x")

        title_frame = tk.Frame(header, bg="#0f172a")
        title_frame.pack(fill="x")

        title_lbl = tk.Label(
            title_frame,
            text="⚡ ZipStream Hub",
            font=("Segoe UI", 15, "bold"),
            fg="#f8fafc",
            bg="#0f172a"
        )
        title_lbl.pack(side="left")

        ver_lbl = tk.Label(
            title_frame,
            text="v2.1 Pro",
            font=("Segoe UI", 8, "bold"),
            fg="#818cf8",
            bg="#1e1b4b",
            padx=6,
            pady=2
        )
        ver_lbl.pack(side="left", padx=(8, 0), pady=2)

        sub_lbl = tk.Label(
            header,
            text="High-Speed Remote ZIP Streaming & Virtual Media Gateway",
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#0f172a"
        )
        sub_lbl.pack(anchor="w", pady=(4, 0))

        # 2. Main Scrollable/Padded Content Area
        main_content = tk.Frame(self, bg="#07090e", padx=20, pady=16)
        main_content.pack(fill="both", expand=True)

        # --- Service Status Card ---
        status_card = tk.LabelFrame(
            main_content,
            text=" Service Status ",
            font=("Segoe UI", 9, "bold"),
            fg="#cbd5e1",
            bg="#0f172a",
            padx=16,
            pady=12,
            highlightbackground="#1e293b",
            highlightthickness=1
        )
        status_card.pack(fill="x", pady=(0, 14))

        status_top = tk.Frame(status_card, bg="#0f172a")
        status_top.pack(fill="x")

        self.status_dot = tk.Label(status_top, text="●", font=("Segoe UI", 16), fg="#ef4444", bg="#0f172a")
        self.status_dot.pack(side="left", padx=(0, 8))

        self.status_text = tk.Label(
            status_top,
            text="Service Stopped",
            font=("Segoe UI", 10, "bold"),
            fg="#f8fafc",
            bg="#0f172a"
        )
        self.status_text.pack(side="left")

        self.port_label = tk.Label(
            status_top,
            text=f"Port: {PORT}",
            font=("Segoe UI", 9),
            fg="#94a3b8",
            bg="#0f172a"
        )
        self.port_label.pack(side="right")

        # --- Live Bandwidth & Streaming Metrics Card ---
        metrics_card = tk.LabelFrame(
            main_content,
            text=" Live Performance & Bandwidth Monitor ",
            font=("Segoe UI", 9, "bold"),
            fg="#cbd5e1",
            bg="#0f172a",
            padx=16,
            pady=12,
            highlightbackground="#1e293b",
            highlightthickness=1
        )
        metrics_card.pack(fill="x", pady=(0, 14))

        # Metrics Grid (3 stats columns)
        metrics_grid = tk.Frame(metrics_card, bg="#0f172a")
        metrics_grid.pack(fill="x")
        metrics_grid.columnconfigure(0, weight=1)
        metrics_grid.columnconfigure(1, weight=1)
        metrics_grid.columnconfigure(2, weight=1)

        # Col 0: Current Speed
        box0 = tk.Frame(metrics_grid, bg="#1e293b", padx=10, pady=8, highlightthickness=1, highlightbackground="#334155")
        box0.grid(row=0, column=0, padx=(0, 6), sticky="nsew")
        tk.Label(box0, text="CURRENT SPEED", font=("Segoe UI", 7, "bold"), fg="#94a3b8", bg="#1e293b").pack(anchor="w")
        self.lbl_speed = tk.Label(box0, text="0.0 Mb/s", font=("JetBrains Mono", 12, "bold"), fg="#38bdf8", bg="#1e293b")
        self.lbl_speed.pack(anchor="w", pady=(3, 0))

        # Col 1: Total Served
        box1 = tk.Frame(metrics_grid, bg="#1e293b", padx=10, pady=8, highlightthickness=1, highlightbackground="#334155")
        box1.grid(row=0, column=1, padx=3, sticky="nsew")
        tk.Label(box1, text="TOTAL SERVED", font=("Segoe UI", 7, "bold"), fg="#94a3b8", bg="#1e293b").pack(anchor="w")
        self.lbl_total = tk.Label(box1, text="0.00 GB", font=("JetBrains Mono", 12, "bold"), fg="#a78bfa", bg="#1e293b")
        self.lbl_total.pack(anchor="w", pady=(3, 0))

        # Col 2: Active Streams
        box2 = tk.Frame(metrics_grid, bg="#1e293b", padx=10, pady=8, highlightthickness=1, highlightbackground="#334155")
        box2.grid(row=0, column=2, padx=(6, 0), sticky="nsew")
        tk.Label(box2, text="ACTIVE STREAMS", font=("Segoe UI", 7, "bold"), fg="#94a3b8", bg="#1e293b").pack(anchor="w")
        self.lbl_streams = tk.Label(box2, text="0", font=("JetBrains Mono", 12, "bold"), fg="#34d399", bg="#1e293b")
        self.lbl_streams.pack(anchor="w", pady=(3, 0))

        # --- Quick Action Controls Card ---
        actions_card = tk.LabelFrame(
            main_content,
            text=" Quick Actions & Integrations ",
            font=("Segoe UI", 9, "bold"),
            fg="#cbd5e1",
            bg="#0f172a",
            padx=16,
            pady=12,
            highlightbackground="#1e293b",
            highlightthickness=1
        )
        actions_card.pack(fill="both", expand=True, pady=(0, 10))

        # 1. Toggle Server Button
        self.btn_toggle = tk.Button(
            actions_card,
            text="▶ Start Server",
            font=("Segoe UI", 10, "bold"),
            fg="#ffffff",
            bg="#10b981",
            activebackground="#059669",
            activeforeground="#ffffff",
            relief="flat",
            pady=8,
            cursor="hand2",
            command=self.toggle_server
        )
        self.btn_toggle.pack(fill="x", pady=(0, 8))

        # 2. Open Web Dashboard Button
        self.btn_open_gui = tk.Button(
            actions_card,
            text="🌐 Open Web Dashboard",
            font=("Segoe UI", 10, "bold"),
            fg="#ffffff",
            bg="#6366f1",
            activebackground="#4f46e5",
            activeforeground="#ffffff",
            relief="flat",
            pady=7,
            cursor="hand2",
            command=self.open_web_gui
        )
        self.btn_open_gui.pack(fill="x", pady=(0, 8))

        # Row with WebDAV + STRM buttons
        btn_row = tk.Frame(actions_card, bg="#0f172a")
        btn_row.pack(fill="x")
        btn_row.columnconfigure(0, weight=1)
        btn_row.columnconfigure(1, weight=1)

        # 3. Mount as WebDAV / Network Drive
        self.btn_mount_webdav = tk.Button(
            btn_row,
            text="📁 Mount WebDAV Drive",
            font=("Segoe UI", 9, "bold"),
            fg="#f8fafc",
            bg="#1e293b",
            activebackground="#334155",
            activeforeground="#f8fafc",
            relief="flat",
            pady=7,
            cursor="hand2",
            command=self.mount_webdav_drive
        )
        self.btn_mount_webdav.grid(row=0, column=0, padx=(0, 4), sticky="nsew")

        # 4. Export Jellyfin/Kodi STRM Bundle
        self.btn_export_strm = tk.Button(
            btn_row,
            text="📦 Export STRM Bundle",
            font=("Segoe UI", 9, "bold"),
            fg="#f8fafc",
            bg="#1e293b",
            activebackground="#334155",
            activeforeground="#f8fafc",
            relief="flat",
            pady=7,
            cursor="hand2",
            command=self.export_strm_bundle
        )
        self.btn_export_strm.grid(row=0, column=1, padx=(4, 0), sticky="nsew")

        # Optional tray button / minimize to tray
        tray_row = tk.Frame(actions_card, bg="#0f172a")
        tray_row.pack(fill="x", pady=(8, 0))

        self.btn_min_tray = tk.Button(
            tray_row,
            text="📥 Minimize to Tray",
            font=("Segoe UI", 8),
            fg="#94a3b8",
            bg="#0f172a",
            activebackground="#1e293b",
            activeforeground="#cbd5e1",
            relief="groove",
            bd=1,
            pady=3,
            cursor="hand2",
            command=self.minimize_to_tray
        )
        self.btn_min_tray.pack(side="right")

        # Footer status bar
        self.footer_lbl = tk.Label(
            self,
            text="Ready • WebDAV endpoint at http://127.0.0.1:8787/webdav/",
            font=("Segoe UI", 8),
            fg="#64748b",
            bg="#07090e",
            pady=8
        )
        self.footer_lbl.pack(side="bottom", fill="x")

    def toggle_server(self):
        """Starts or stops the backend streaming server."""
        global SERVER_PROCESS
        if SERVER_PROCESS is None or SERVER_PROCESS.poll() is not None:
            # Check if another process is already listening on the port
            if self.is_port_in_use(PORT):
                # Verify if it is ZipStreamHub
                if self.check_live_status():
                    self.set_running_state(True)
                    messagebox.showinfo("Server Running", f"ZipStreamHub is already actively running on port {PORT}.")
                    return
                else:
                    messagebox.showwarning("Port Conflict", f"Port {PORT} is occupied by another application.")
                    return

            base_dir = os.path.dirname(os.path.abspath(__file__))
            backend_script = os.path.join(base_dir, "server.py")
            python_exe = sys.executable
            try:
                # Use CREATE_NO_WINDOW on Windows if available to run clean background process
                creation_flags = 0
                if sys.platform == "win32":
                    creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000

                SERVER_PROCESS = subprocess.Popen(
                    [python_exe, backend_script],
                    cwd=base_dir,
                    creationflags=creation_flags
                )
                self.set_running_state(True)
                self.footer_lbl.config(text="Server starting up...")
                self.after(600, self.open_web_gui)
            except Exception as e:
                messagebox.showerror("Launch Error", f"Failed to start backend server:\n{e}")
        else:
            try:
                SERVER_PROCESS.terminate()
                SERVER_PROCESS.wait(timeout=2)
            except Exception:
                try:
                    SERVER_PROCESS.kill()
                except Exception:
                    pass
            SERVER_PROCESS = None
            self.set_running_state(False)
            self.footer_lbl.config(text="Server stopped.")

    def set_running_state(self, is_running: bool):
        self.is_running = is_running
        if is_running:
            self.status_dot.config(fg="#10b981")
            self.status_text.config(text="Service Running (Active)")
            self.btn_toggle.config(
                text="⏹ Stop Server",
                bg="#ef4444",
                activebackground="#dc2626"
            )
            self.footer_lbl.config(text="● Online • WebDAV: http://127.0.0.1:8787/webdav/")
        else:
            self.status_dot.config(fg="#ef4444")
            self.status_text.config(text="Service Stopped")
            self.btn_toggle.config(
                text="▶ Start Server",
                bg="#10b981",
                activebackground="#059669"
            )
            self.lbl_speed.config(text="0.0 Mb/s")
            self.lbl_streams.config(text="0")
            self.footer_lbl.config(text="Service Stopped • Click 'Start Server' to begin.")

    def open_web_gui(self):
        """Opens web GUI dashboard in default browser."""
        url = f"http://127.0.0.1:{PORT}"
        webbrowser.open(url)

    def mount_webdav_drive(self):
        """
        Mounts the ZipStream WebDAV endpoint as a local Windows Network Drive (e.g. Z:).
        Uses 'net use * http://127.0.0.1:8787/webdav' or opens file explorer.
        """
        webdav_url = f"http://127.0.0.1:{PORT}/webdav"
        
        if not self.check_live_status():
            ans = messagebox.askyesno(
                "Server Offline",
                "ZipStreamHub server is not currently running.\nWould you like to start it now to mount WebDAV?"
            )
            if ans:
                self.toggle_server()
            else:
                return

        if sys.platform == "win32":
            # Attempt to mount via Windows net use command
            try:
                # Find an available drive letter starting from Z: down to M:
                available_drive = self._get_available_drive_letter()
                drive_target = f"{available_drive}:" if available_drive else "*"
                
                cmd = f'net use {drive_target} "{webdav_url}" /persistent:no'
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
                
                if res.returncode == 0:
                    drive_assigned = available_drive or "Assigned"
                    messagebox.showinfo(
                        "WebDAV Mounted",
                        f"Successfully mounted WebDAV endpoint as Drive {drive_assigned}:\n{webdav_url}\n\nOpening File Explorer..."
                    )
                    if available_drive:
                        os.startfile(f"{available_drive}:\\")
                    else:
                        os.startfile(webdav_url)
                else:
                    # If net use fails (e.g. WebClient service disabled or security constraint), open explorer directly
                    err_msg = res.stderr.strip() or res.stdout.strip()
                    webbrowser.open(f"{webdav_url}/")
                    messagebox.showinfo(
                        "WebDAV Explorer",
                        f"Opened WebDAV HTTP directory in your browser/explorer.\n\nTip: You can manually map network drive in Windows Explorer to:\n{webdav_url}\n\n(System info: {err_msg})"
                    )
            except Exception as e:
                webbrowser.open(webdav_url)
                messagebox.showinfo("WebDAV Directory", f"Opened WebDAV Directory:\n{webdav_url}\n({e})")
        else:
            webbrowser.open(webdav_url)

    def _get_available_drive_letter(self) -> Optional[str]:
        """Returns the first available unused drive letter (from Z down to D)."""
        if sys.platform != "win32":
            return None
        import string
        used_drives = set()
        for letter in string.ascii_uppercase:
            if os.path.exists(f"{letter}:\\"):
                used_drives.add(letter)
        for letter in reversed(string.ascii_uppercase[:26]):  # Z -> A
            if letter not in ("A", "B", "C") and letter not in used_drives:
                return letter
        return None

    def export_strm_bundle(self):
        """
        Exports an in-memory or generated .strm bundle for the current archive or opens
        the export helper dialog to save for Jellyfin/Emby/Kodi.
        """
        if not self.check_live_status():
            messagebox.showwarning(
                "Server Offline",
                "Please start the server and inspect an archive first to export a STRM bundle."
            )
            return

        try:
            # Query history or current readers to get current archive
            history_url = f"http://127.0.0.1:{PORT}/api/history"
            req = urllib.request.Request(history_url)
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                history_items = data.get("history", [])

            if not history_items:
                messagebox.showinfo(
                    "No Archive Loaded",
                    "No active or recent archives found in history.\n\nOpen the Web Dashboard, paste a remote ZIP link to inspect, and click Export STRM!"
                )
                return

            # Let user choose save path
            default_filename = f"strm_bundle_{int(time.time())}.zip"
            save_path = filedialog.asksaveasfilename(
                title="Save Jellyfin / Kodi STRM ZIP Bundle",
                defaultextension=".zip",
                initialfile=default_filename,
                filetypes=[("ZIP Archive", "*.zip"), ("All Files", "*.*")]
            )

            if not save_path:
                return

            # Import strm_generator to bundle
            from strm_generator import generate_strm_zip_bundle
            from engine import RemoteZipReader

            latest_url = history_items[0].get("url")
            if not latest_url:
                raise ValueError("No archive URL found in history.")

            # Create reader or fetch entries
            reader = RemoteZipReader(latest_url)
            base_url = f"http://127.0.0.1:{PORT}"
            zip_bytes = generate_strm_zip_bundle(reader.entries, base_url, structure_type="auto")

            with open(save_path, "wb") as f:
                f.write(zip_bytes)

            messagebox.showinfo(
                "Export Complete",
                f"Exported {len(reader.entries)} entries to STRM Bundle:\n{save_path}\n\nExtract this into your Jellyfin, Emby, or Kodi media folder!"
            )
        except Exception as e:
            messagebox.showerror("Export Failed", f"Could not generate STRM bundle:\n{e}")

    def is_port_in_use(self, port: int) -> bool:
        """Checks if a local TCP port is already open."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            return s.connect_ex(("127.0.0.1", port)) == 0

    def check_live_status(self) -> bool:
        """Fast check if ZipStream backend is alive."""
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/stats", method="GET")
            with urllib.request.urlopen(req, timeout=0.6) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        return False

    def check_server_status(self):
        """Polls server online/offline state and syncs UI buttons."""
        is_alive = self.check_live_status()
        self.set_running_state(is_alive)

    def schedule_stats_poll(self):
        """Periodic background polling loop for /api/stats (every 1.5s)."""
        if self._is_closing:
            return

        def _fetch_stats():
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/stats", method="GET")
                with urllib.request.urlopen(req, timeout=0.8) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        stats = data.get("stats", {})
                        self.after(0, lambda: self._update_metrics_ui(stats, True))
                        return
            except Exception:
                pass
            self.after(0, lambda: self._update_metrics_ui({}, False))

        threading.Thread(target=_fetch_stats, daemon=True).start()
        self._stats_poll_job = self.after(1500, self.schedule_stats_poll)

    def _update_metrics_ui(self, stats: Dict[str, Any], is_alive: bool):
        if not is_alive:
            if self.is_running:
                self.set_running_state(False)
            self.lbl_speed.config(text="0.0 Mb/s")
            self.lbl_streams.config(text="0")
            return

        if not self.is_running:
            self.set_running_state(True)

        speed_mbps = stats.get("current_bandwidth_mbps", 0.0)
        total_gb = stats.get("total_gbytes_served", 0.0)
        active_streams = stats.get("active_streams_count", 0)

        # Format display strings
        self.lbl_speed.config(text=f"{speed_mbps:.1f} Mb/s")
        self.lbl_total.config(text=f"{total_gb:.2f} GB")
        self.lbl_streams.config(text=str(active_streams))

        # Dynamic color highlights for active streaming
        if active_streams > 0:
            self.lbl_streams.config(fg="#10b981")
            self.lbl_speed.config(fg="#38bdf8")
        else:
            self.lbl_streams.config(fg="#94a3b8")
            self.lbl_speed.config(fg="#64748b" if speed_mbps == 0 else "#38bdf8")

    # --- System Tray Integration ---

    def _setup_tray(self):
        if not HAS_PYSTRAY:
            return

        try:
            # Create a simple icon image for tray
            if os.path.exists(self.icon_path):
                image = Image.open(self.icon_path)
            else:
                image = Image.new("RGB", (64, 64), color="#6366f1")

            menu = pystray.Menu(
                pystray.MenuItem("Open Control Panel", self.restore_from_tray, default=True),
                pystray.MenuItem("Open Web Dashboard", lambda: self.open_web_gui()),
                pystray.MenuItem("Mount WebDAV Drive", lambda: self.mount_webdav_drive()),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit ZipStream Hub", self.quit_application)
            )

            self.tray_icon = pystray.Icon("ZipStreamHub", image, "ZipStream Hub", menu)
        except Exception:
            self.tray_icon = None

    def minimize_to_tray(self):
        """Hides the tkinter window and activates the system tray icon."""
        if HAS_PYSTRAY and self.tray_icon:
            self.withdraw()
            if not self.tray_icon._running:
                threading.Thread(target=self.tray_icon.run, daemon=True).start()
        else:
            # Fallback: standard minimize (iconify)
            self.iconify()

    def restore_from_tray(self, icon=None, item=None):
        """Restores window from system tray."""
        self.after(0, self._show_window)

    def _show_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def on_close(self):
        """Handle window close: prompt to minimize or quit."""
        if HAS_PYSTRAY and self.tray_icon:
            self.minimize_to_tray()
        else:
            self.quit_application()

    def quit_application(self, icon=None, item=None):
        """Gracefully shuts down control panel, tray icon, and background server."""
        self._is_closing = True
        if self._stats_poll_job:
            try:
                self.after_cancel(self._stats_poll_job)
            except Exception:
                pass

        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass

        global SERVER_PROCESS
        if SERVER_PROCESS and SERVER_PROCESS.poll() is None:
            try:
                SERVER_PROCESS.terminate()
            except Exception:
                pass

        self.after(100, self.destroy)


if __name__ == "__main__":
    app = ZipStreamControlPanel()
    app.mainloop()
