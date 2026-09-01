"""
ZipStream Hub — Modern Desktop Control Panel (Jellyfin/Plex Aesthetic).

Features:
- Sleek 780x620 modern dark theme:
  Deep Space (#080C14), Cards (#0F172A), Slate Borders (#1E293B),
  Electric Indigo (#6366F1), Cyber Cyan (#00F0FF), Emerald Green (#10B981).
- Custom Pill Tab Navigation:
  1. ⚡ Overview & Server Control (Service toggle, real-time live speed metrics + canvas sparkline, active connections, Web GUI launch).
  2. 🎬 Archive Quick-Player (URL input, instant scan, episode list with 1-click play & badges).
  3. 🖧 Mount & Virtual Drive (Windows WebDAV drive letter mapper Z:, Y:, etc., STRM exporter).
  4. ⚙️ Performance & Buffer (Live 32MB - 5GB buffer slider, socket slice tuner, player default selector).
  5. 📊 Diagnostics & Logs (Real-time HTTP 206 streaming logs and server output console).
- Full compatibility with backend API, system tray, and clean standalone proxy execution.
"""

from __future__ import annotations

import os
import sys
import time
import json
import socket
import threading
import subprocess
import webbrowser
import queue
from typing import Optional, Dict, Any, List
import urllib.request
import urllib.parse
import urllib.error

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext

try:
    import pystray
    from PIL import Image
    HAS_PYSTRAY = True
except ImportError:
    HAS_PYSTRAY = False

# Import internal modules with clean fallbacks
try:
    from .config import load_config, AppConfig, StreamingConfig
    from .player_detector import get_installed_players, launch_stream
    from .strm_generator import generate_strm_zip_bundle
    from .engine import RemoteZipReader
except ImportError:
    from config import load_config, AppConfig, StreamingConfig
    from player_detector import get_installed_players, launch_stream
    from strm_generator import generate_strm_zip_bundle
    from engine import RemoteZipReader

PORT = 8787
SERVER_PROCESS: Optional[subprocess.Popen] = None

# Styling constants
COLOR_BG = "#080C14"
COLOR_CARD = "#0F172A"
COLOR_CARD_ALT = "#131E32"
COLOR_BORDER = "#1E293B"
COLOR_BORDER_FOCUS = "#334155"
COLOR_TEXT_PRIMARY = "#F8FAFC"
COLOR_TEXT_MUTED = "#94A3B8"
COLOR_TEXT_DIM = "#64748B"
COLOR_ACCENT_INDIGO = "#6366F1"
COLOR_ACCENT_CYAN = "#00F0FF"
COLOR_SUCCESS = "#10B981"
COLOR_DANGER = "#EF4444"
COLOR_WARNING = "#F59E0B"
COLOR_TAB_ACTIVE_BG = "#1E293B"
COLOR_TAB_INACTIVE_BG = "#0B1120"


class ZipStreamControlPanel(tk.Tk):
    """
    Modular modern desktop control panel for ZipStream Hub.
    """

    def __init__(self, headless: bool = False):
        super().__init__()

        self.title("ZipStream Hub — Desktop Gateway")
        self.geometry("780x620")
        self.minsize(740, 580)
        self.resizable(True, True)
        self.configure(bg=COLOR_BG)

        # Window icon if available
        base_dir = os.path.dirname(os.path.abspath(__file__))
        static_icon = os.path.join(base_dir, "static", "zipstream_icon.ico")
        local_icon = os.path.join(base_dir, "zipstream_icon.ico")
        self.icon_path = static_icon if os.path.exists(static_icon) else local_icon
        if os.path.exists(self.icon_path):
            try:
                self.iconbitmap(self.icon_path)
            except Exception:
                pass

        # State & Telemetry tracking
        self.is_running = False
        self.tray_icon = None
        self._stats_poll_job = None
        self._is_closing = False
        self._bandwidth_history: List[float] = [0.0] * 20
        self.log_queue: queue.Queue[str] = queue.Queue()
        self._last_active_streams: int = 0
        self._last_total_bytes: int = 0
        self.loaded_entries: List[Dict[str, Any]] = []
        self.current_archive_url: str = ""
        self.available_players: List[Dict[str, Any]] = []
        self.selected_player_var = tk.StringVar(value="mpv")

        # Config management
        self.app_config: AppConfig = load_config()

        # Auto-start variable
        self.auto_start_var = tk.BooleanVar(value=self.is_auto_start_enabled())

        # UI Build
        self._init_styles()
        self._create_header()
        self._create_pill_nav()
        self._create_tab_container()
        self._create_footer()
        self._setup_tray()

        # Build individual tabs
        self._build_tab_overview()
        self._build_tab_player()
        self._build_tab_mount()
        self._build_tab_performance()
        self._build_tab_logs()

        # Switch to first tab initially
        self.switch_tab("overview")

        # Window close protocol
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Initial background workers
        self._poll_log_queue()
        self._detect_system_players()
        self.check_server_status()
        self.schedule_stats_poll()

    # -------------------------------------------------------------------------
    # Styles & Architecture
    # -------------------------------------------------------------------------

    def _init_styles(self):
        self.style = ttk.Style(self)
        self.style.theme_use("clam")

        self.style.configure(".", background=COLOR_BG, foreground=COLOR_TEXT_PRIMARY)
        self.style.configure("Dark.TFrame", background=COLOR_BG)
        self.style.configure("Card.TFrame", background=COLOR_CARD)

        # Scrollbar styling
        self.style.configure(
            "Vertical.TScrollbar",
            background=COLOR_CARD,
            troughcolor=COLOR_BG,
            bordercolor=COLOR_BORDER,
            arrowcolor=COLOR_TEXT_MUTED,
            relief="flat"
        )
        self.style.map(
            "Vertical.TScrollbar",
            background=[("active", COLOR_BORDER), ("!disabled", COLOR_CARD_ALT)]
        )

        # Scale / Slider styling
        self.style.configure(
            "Horizontal.TScale",
            background=COLOR_CARD,
            troughcolor=COLOR_BORDER,
            sliderlength=16,
            sliderrelief="flat"
        )

        # Combobox styling
        self.style.configure(
            "Dark.TCombobox",
            fieldbackground=COLOR_CARD_ALT,
            background=COLOR_BORDER,
            foreground=COLOR_TEXT_PRIMARY,
            darkcolor=COLOR_BORDER,
            lightcolor=COLOR_BORDER,
            arrowcolor=COLOR_ACCENT_CYAN,
            relief="flat"
        )
        self.style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", COLOR_CARD_ALT)],
            foreground=[("readonly", COLOR_TEXT_PRIMARY)]
        )

        # Treeview styling for Archive Quick-Player
        self.style.configure(
            "Treeview",
            background=COLOR_CARD,
            fieldbackground=COLOR_CARD,
            foreground=COLOR_TEXT_PRIMARY,
            borderwidth=0,
            rowheight=26,
            font=("Segoe UI", 9)
        )
        self.style.configure(
            "Treeview.Heading",
            background=COLOR_CARD_ALT,
            foreground=COLOR_TEXT_MUTED,
            borderwidth=1,
            relief="flat",
            font=("Segoe UI", 8, "bold")
        )
        self.style.map(
            "Treeview",
            background=[("selected", COLOR_ACCENT_INDIGO)],
            foreground=[("selected", "#ffffff")]
        )
        self.style.map(
            "Treeview.Heading",
            background=[("active", COLOR_BORDER)]
        )

    # -------------------------------------------------------------------------
    # UI Layout: Header & Pill Navigation
    # -------------------------------------------------------------------------

    def _create_header(self):
        header_frame = tk.Frame(self, bg=COLOR_CARD, highlightthickness=1, highlightbackground=COLOR_BORDER, padx=20, pady=10)
        header_frame.pack(fill="x")

        left_hdr = tk.Frame(header_frame, bg=COLOR_CARD)
        left_hdr.pack(side="left", fill="y")

        title_box = tk.Frame(left_hdr, bg=COLOR_CARD)
        title_box.pack(anchor="w")

        title_lbl = tk.Label(
            title_box,
            text="⚡ ZipStream Hub",
            font=("Segoe UI", 13, "bold"),
            fg=COLOR_TEXT_PRIMARY,
            bg=COLOR_CARD
        )
        title_lbl.pack(side="left")

        ver_lbl = tk.Label(
            title_box,
            text="PRO v2.2",
            font=("Segoe UI", 7, "bold"),
            fg=COLOR_ACCENT_CYAN,
            bg="#0B2138",
            padx=6,
            pady=1
        )
        ver_lbl.pack(side="left", padx=(8, 0))

        sub_lbl = tk.Label(
            left_hdr,
            text="High-Speed Remote ZIP Streaming & Virtual Media Gateway",
            font=("Segoe UI", 8),
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD
        )
        sub_lbl.pack(anchor="w", pady=(2, 0))

        # Right Header: Server Status pill + Quick Toggle
        right_hdr = tk.Frame(header_frame, bg=COLOR_CARD)
        right_hdr.pack(side="right", fill="y")

        self.hdr_status_dot = tk.Label(right_hdr, text="●", font=("Segoe UI", 12), fg=COLOR_DANGER, bg=COLOR_CARD)
        self.hdr_status_dot.pack(side="left", padx=(0, 4))

        self.hdr_status_text = tk.Label(
            right_hdr,
            text="Stopped",
            font=("Segoe UI", 9, "bold"),
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD
        )
        self.hdr_status_text.pack(side="left", padx=(0, 10))

        self.hdr_btn_toggle = tk.Button(
            right_hdr,
            text="▶ Start Server",
            font=("Segoe UI", 8, "bold"),
            fg="#FFFFFF",
            bg=COLOR_SUCCESS,
            activebackground="#059669",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=10,
            pady=4,
            cursor="hand2",
            command=self.toggle_server
        )
        self.hdr_btn_toggle.pack(side="left")

    def _create_pill_nav(self):
        nav_container = tk.Frame(self, bg=COLOR_BG, padx=16, pady=8)
        nav_container.pack(fill="x")

        pill_frame = tk.Frame(nav_container, bg=COLOR_TAB_INACTIVE_BG, highlightthickness=1, highlightbackground=COLOR_BORDER)
        pill_frame.pack(fill="x")

        self.tab_buttons: Dict[str, tk.Button] = {}
        tabs = [
            ("overview", "⚡ Overview"),
            ("player", "🎬 Quick-Player"),
            ("mount", "🖧 Mount & Drive"),
            ("performance", "⚙️ Performance"),
            ("logs", "📊 Logs"),
        ]

        for idx, (tab_id, label) in enumerate(tabs):
            pill_frame.columnconfigure(idx, weight=1)
            btn = tk.Button(
                pill_frame,
                text=label,
                font=("Segoe UI", 9, "bold"),
                fg=COLOR_TEXT_MUTED,
                bg=COLOR_TAB_INACTIVE_BG,
                activebackground=COLOR_TAB_ACTIVE_BG,
                activeforeground=COLOR_TEXT_PRIMARY,
                relief="flat",
                bd=0,
                pady=7,
                cursor="hand2",
                command=lambda tid=tab_id: self.switch_tab(tid)
            )
            btn.grid(row=0, column=idx, sticky="nsew", padx=1, pady=1)
            self.tab_buttons[tab_id] = btn

    def switch_tab(self, target_tab_id: str):
        for tab_id, frame in self.tab_frames.items():
            if tab_id == target_tab_id:
                frame.pack(fill="both", expand=True)
                self.tab_buttons[tab_id].config(
                    bg=COLOR_TAB_ACTIVE_BG,
                    fg=COLOR_ACCENT_CYAN,
                    font=("Segoe UI", 9, "bold")
                )
            else:
                frame.pack_forget()
                self.tab_buttons[tab_id].config(
                    bg=COLOR_TAB_INACTIVE_BG,
                    fg=COLOR_TEXT_MUTED,
                    font=("Segoe UI", 9)
                )

    def _create_tab_container(self):
        self.content_area = tk.Frame(self, bg=COLOR_BG, padx=16, pady=4)
        self.content_area.pack(fill="both", expand=True)

        self.tab_frames: Dict[str, tk.Frame] = {
            "overview": tk.Frame(self.content_area, bg=COLOR_BG),
            "player": tk.Frame(self.content_area, bg=COLOR_BG),
            "mount": tk.Frame(self.content_area, bg=COLOR_BG),
            "performance": tk.Frame(self.content_area, bg=COLOR_BG),
            "logs": tk.Frame(self.content_area, bg=COLOR_BG),
        }

    def _create_footer(self):
        footer = tk.Frame(self, bg=COLOR_CARD, highlightthickness=1, highlightbackground=COLOR_BORDER, padx=16, pady=6)
        footer.pack(fill="x", side="bottom")

        self.footer_lbl = tk.Label(
            footer,
            text="Ready • WebDAV endpoint at http://127.0.0.1:8787/webdav/",
            font=("Segoe UI", 8),
            fg=COLOR_TEXT_DIM,
            bg=COLOR_CARD
        )
        self.footer_lbl.pack(side="left")

        min_tray_btn = tk.Button(
            footer,
            text="📥 Minimize to Tray",
            font=("Segoe UI", 8),
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD_ALT,
            activebackground=COLOR_BORDER,
            activeforeground=COLOR_TEXT_PRIMARY,
            relief="flat",
            padx=8,
            pady=2,
            cursor="hand2",
            command=self.minimize_to_tray
        )
        min_tray_btn.pack(side="right")

    # -------------------------------------------------------------------------
    # TAB 1: ⚡ Overview & Server Control (with Sparkline Telemetry)
    # -------------------------------------------------------------------------

    def _build_tab_overview(self):
        frame = self.tab_frames["overview"]

        # Grid of 3 live metrics cards
        metrics_grid = tk.Frame(frame, bg=COLOR_BG)
        metrics_grid.pack(fill="x", pady=(4, 10))
        metrics_grid.columnconfigure(0, weight=1)
        metrics_grid.columnconfigure(1, weight=1)
        metrics_grid.columnconfigure(2, weight=1)

        # Card 1: Speed
        c1 = tk.Frame(metrics_grid, bg=COLOR_CARD, highlightthickness=1, highlightbackground=COLOR_BORDER, padx=12, pady=10)
        c1.grid(row=0, column=0, padx=(0, 6), sticky="nsew")
        tk.Label(c1, text="CURRENT SPEED", font=("Segoe UI", 7, "bold"), fg=COLOR_TEXT_MUTED, bg=COLOR_CARD).pack(anchor="w")
        self.lbl_speed = tk.Label(c1, text="0.00 Mbps", font=("JetBrains Mono", 14, "bold"), fg=COLOR_TEXT_DIM, bg=COLOR_CARD)
        self.lbl_speed.pack(anchor="w", pady=(4, 0))

        # Card 2: Total Served
        c2 = tk.Frame(metrics_grid, bg=COLOR_CARD, highlightthickness=1, highlightbackground=COLOR_BORDER, padx=12, pady=10)
        c2.grid(row=0, column=1, padx=3, sticky="nsew")
        tk.Label(c2, text="TOTAL SERVED", font=("Segoe UI", 7, "bold"), fg=COLOR_TEXT_MUTED, bg=COLOR_CARD).pack(anchor="w")
        self.lbl_total = tk.Label(c2, text="0.00 MB", font=("JetBrains Mono", 14, "bold"), fg="#A78BFA", bg=COLOR_CARD)
        self.lbl_total.pack(anchor="w", pady=(4, 0))

        # Card 3: Active Streams
        c3 = tk.Frame(metrics_grid, bg=COLOR_CARD, highlightthickness=1, highlightbackground=COLOR_BORDER, padx=12, pady=10)
        c3.grid(row=0, column=2, padx=(6, 0), sticky="nsew")
        tk.Label(c3, text="ACTIVE STREAMS", font=("Segoe UI", 7, "bold"), fg=COLOR_TEXT_MUTED, bg=COLOR_CARD).pack(anchor="w")
        self.lbl_streams = tk.Label(c3, text="0 active players", font=("JetBrains Mono", 12, "bold"), fg=COLOR_TEXT_DIM, bg=COLOR_CARD)
        self.lbl_streams.pack(anchor="w", pady=(4, 0))

        # Sparkline Live Throughput Canvas Card
        spark_card = tk.Frame(frame, bg=COLOR_CARD, highlightthickness=1, highlightbackground=COLOR_BORDER, padx=12, pady=8)
        spark_card.pack(fill="x", pady=(0, 10))

        spark_hdr = tk.Frame(spark_card, bg=COLOR_CARD)
        spark_hdr.pack(fill="x", pady=(0, 4))

        tk.Label(spark_hdr, text="THROUGHPUT TELEMETRY", font=("Segoe UI", 7, "bold"), fg=COLOR_TEXT_MUTED, bg=COLOR_CARD).pack(side="left")
        self.lbl_spark_peak = tk.Label(spark_hdr, text="Peak: 0.00 Mbps", font=("JetBrains Mono", 7, "bold"), fg=COLOR_ACCENT_CYAN, bg=COLOR_CARD)
        self.lbl_spark_peak.pack(side="right")

        self.spark_canvas = tk.Canvas(spark_card, height=42, bg=COLOR_CARD_ALT, highlightthickness=0)
        self.spark_canvas.pack(fill="x")
        self._draw_sparkline()

        # Main Server Actions Card
        actions_card = tk.LabelFrame(
            frame,
            text=" Server Orchestration & Gateway ",
            font=("Segoe UI", 9, "bold"),
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD,
            padx=14,
            pady=10,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1
        )
        actions_card.pack(fill="x", pady=(0, 10))

        act_grid = tk.Frame(actions_card, bg=COLOR_CARD)
        act_grid.pack(fill="x")
        act_grid.columnconfigure(0, weight=1)
        act_grid.columnconfigure(1, weight=1)

        self.btn_main_toggle = tk.Button(
            act_grid,
            text="▶ Start ZipStream Service",
            font=("Segoe UI", 9, "bold"),
            fg="#FFFFFF",
            bg=COLOR_SUCCESS,
            activebackground="#059669",
            activeforeground="#FFFFFF",
            relief="flat",
            pady=8,
            cursor="hand2",
            command=self.toggle_server
        )
        self.btn_main_toggle.grid(row=0, column=0, padx=(0, 5), sticky="nsew")

        self.btn_open_gui = tk.Button(
            act_grid,
            text="🌐 Open Web GUI Dashboard",
            font=("Segoe UI", 9, "bold"),
            fg="#FFFFFF",
            bg=COLOR_ACCENT_INDIGO,
            activebackground="#4F46E5",
            activeforeground="#FFFFFF",
            relief="flat",
            pady=8,
            cursor="hand2",
            command=self.open_web_gui
        )
        self.btn_open_gui.grid(row=0, column=1, padx=(5, 0), sticky="nsew")

        # Endpoint Information Subcard
        info_card = tk.Frame(frame, bg=COLOR_CARD_ALT, highlightthickness=1, highlightbackground=COLOR_BORDER, padx=12, pady=8)
        info_card.pack(fill="both", expand=True)

        tk.Label(info_card, text="LOCAL NETWORK ENDPOINTS", font=("Segoe UI", 7, "bold"), fg=COLOR_ACCENT_CYAN, bg=COLOR_CARD_ALT).pack(anchor="w")

        endpoint_text = (
            f"• Web UI & REST API:   http://127.0.0.1:{PORT}/\n"
            f"• Native WebDAV Gateway: http://127.0.0.1:{PORT}/webdav/\n"
            f"• Master M3U Playlist:  http://127.0.0.1:{PORT}/api/playlist.m3u\n"
            f"• Jellyfin / Kodi STRM: http://127.0.0.1:{PORT}/api/strm.zip"
        )
        self.lbl_endpoints = tk.Label(
            info_card,
            text=endpoint_text,
            font=("JetBrains Mono", 8),
            fg=COLOR_TEXT_PRIMARY,
            bg=COLOR_CARD_ALT,
            justify="left"
        )
        self.lbl_endpoints.pack(anchor="w", pady=(4, 0))

    def _draw_sparkline(self):
        """Renders live anti-aliased throughput sparkline polygon on canvas."""
        if not hasattr(self, "spark_canvas"):
            return

        c = self.spark_canvas
        c.delete("all")
        w = c.winfo_width()
        h = c.winfo_height()
        if w <= 1:
            w = 700
        if h <= 1:
            h = 42

        data = self._bandwidth_history or [0.0] * 20
        max_val = max(max(data), 1.0)
        peak_val = max(data)

        if hasattr(self, "lbl_spark_peak"):
            self.lbl_spark_peak.config(text=f"Peak: {peak_val:.2f} Mbps")

        points = []
        n = len(data)
        step = w / max(n - 1, 1)

        for i, val in enumerate(data):
            x = i * step
            norm = val / max_val
            y = (h - 6) - (norm * (h - 12))
            points.extend([x, y])

        # Fill area under graph
        if len(points) >= 4:
            poly_points = [0, h] + points + [w, h]
            c.create_polygon(poly_points, fill="#0B253D", outline="")
            c.create_line(points, fill=COLOR_ACCENT_CYAN, width=2, smooth=True)

    # -------------------------------------------------------------------------
    # TAB 2: 🎬 Archive Quick-Player
    # -------------------------------------------------------------------------

    def _build_tab_player(self):
        frame = self.tab_frames["player"]

        # URL Input Bar Card
        url_card = tk.Frame(frame, bg=COLOR_CARD, highlightthickness=1, highlightbackground=COLOR_BORDER, padx=12, pady=10)
        url_card.pack(fill="x", pady=(0, 10))

        tk.Label(url_card, text="REMOTE ZIP ARCHIVE URL:", font=("Segoe UI", 8, "bold"), fg=COLOR_TEXT_MUTED, bg=COLOR_CARD).pack(anchor="w")

        input_row = tk.Frame(url_card, bg=COLOR_CARD)
        input_row.pack(fill="x", pady=(4, 0))

        self.entry_archive_url = tk.Entry(
            input_row,
            font=("Segoe UI", 9),
            bg=COLOR_CARD_ALT,
            fg=COLOR_TEXT_PRIMARY,
            insertbackground=COLOR_ACCENT_CYAN,
            relief="flat",
            highlightthickness=1,
            highlightbackground=COLOR_BORDER
        )
        self.entry_archive_url.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 8))
        self.entry_archive_url.bind("<Return>", lambda e: self.scan_archive_url())

        self.btn_scan = tk.Button(
            input_row,
            text="🔍 Instant Scan",
            font=("Segoe UI", 9, "bold"),
            fg="#FFFFFF",
            bg=COLOR_ACCENT_INDIGO,
            activebackground="#4F46E5",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=12,
            pady=4,
            cursor="hand2",
            command=self.scan_archive_url
        )
        self.btn_scan.pack(side="right")

        # Episode List Table
        list_card = tk.Frame(frame, bg=COLOR_CARD, highlightthickness=1, highlightbackground=COLOR_BORDER, padx=8, pady=8)
        list_card.pack(fill="both", expand=True)

        hdr_row = tk.Frame(list_card, bg=COLOR_CARD)
        hdr_row.pack(fill="x", padx=4, pady=(0, 4))
        self.lbl_scan_status = tk.Label(
            hdr_row,
            text="Paste a remote ZIP URL and click 'Instant Scan' to preview episodes.",
            font=("Segoe UI", 8),
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD
        )
        self.lbl_scan_status.pack(side="left")

        # Treeview + Scrollbar
        tree_frame = tk.Frame(list_card, bg=COLOR_CARD)
        tree_frame.pack(fill="both", expand=True)

        columns = ("id", "filename", "size", "codec")
        self.player_tree = ttk.Treeview(
            tree_frame,
            columns=columns,
            show="headings",
            selectmode="browse"
        )
        self.player_tree.heading("id", text="#", anchor="center")
        self.player_tree.heading("filename", text="File / Episode Name", anchor="w")
        self.player_tree.heading("size", text="Size", anchor="center")
        self.player_tree.heading("codec", text="Codec / Badges", anchor="center")

        self.player_tree.column("id", width=40, minwidth=35, anchor="center")
        self.player_tree.column("filename", width=420, minwidth=250, anchor="w")
        self.player_tree.column("size", width=80, minwidth=70, anchor="center")
        self.player_tree.column("codec", width=120, minwidth=90, anchor="center")

        tree_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.player_tree.yview, style="Vertical.TScrollbar")
        self.player_tree.configure(yscrollcommand=tree_scroll.set)

        self.player_tree.pack(side="left", fill="both", expand=True)
        tree_scroll.pack(side="right", fill="y")

        self.player_tree.bind("<Double-1>", lambda e: self.play_selected_entry())

        # Action bar underneath tree
        bot_row = tk.Frame(list_card, bg=COLOR_CARD)
        bot_row.pack(fill="x", padx=4, pady=(8, 0))

        self.btn_play_selected = tk.Button(
            bot_row,
            text="▶ Play Selected Episode",
            font=("Segoe UI", 9, "bold"),
            fg="#080C14",
            bg=COLOR_ACCENT_CYAN,
            activebackground="#00B4D8",
            activeforeground="#000000",
            relief="flat",
            padx=14,
            pady=5,
            cursor="hand2",
            command=self.play_selected_entry
        )
        self.btn_play_selected.pack(side="left")

        # Player selector dropdown
        player_sel_frame = tk.Frame(bot_row, bg=COLOR_CARD)
        player_sel_frame.pack(side="right")

        tk.Label(player_sel_frame, text="Player:", font=("Segoe UI", 8), fg=COLOR_TEXT_MUTED, bg=COLOR_CARD).pack(side="left", padx=(0, 4))
        self.cmb_player_quick = ttk.Combobox(
            player_sel_frame,
            textvariable=self.selected_player_var,
            state="readonly",
            width=14,
            style="Dark.TCombobox"
        )
        self.cmb_player_quick.pack(side="left")

    def scan_archive_url(self):
        url = self.entry_archive_url.get().strip()
        if not url:
            messagebox.showwarning("Missing URL", "Please enter a valid remote ZIP file URL.")
            return

        self.lbl_scan_status.config(text="Scanning remote archive central directory...", fg=COLOR_ACCENT_CYAN)
        self.btn_scan.config(state="disabled")

        def _do_scan():
            try:
                reader = RemoteZipReader(url)
                entries = reader.entries
                self.after(0, lambda: self._on_scan_success(url, entries))
            except Exception as e:
                err_msg = str(e)
                self.after(0, lambda: self._on_scan_error(err_msg))

        threading.Thread(target=_do_scan, daemon=True).start()

    def _on_scan_success(self, url: str, entries: List[Dict[str, Any]]):
        self.current_archive_url = url
        self.loaded_entries = entries
        self.btn_scan.config(state="normal")
        self.lbl_scan_status.config(text=f"Loaded {len(entries)} files from archive.", fg=COLOR_SUCCESS)

        # Clear existing items
        for item in self.player_tree.get_children():
            self.player_tree.delete(item)

        for entry in entries:
            eid = entry.get("id", 1)
            filename = entry.get("filename", "")
            size_bytes = entry.get("file_size", 0)
            size_mb = f"{size_bytes / (1024 * 1024):.1f} MB" if size_bytes > 0 else "0 MB"

            # Check badges
            ext = os.path.splitext(filename)[1].lower()
            badges = []
            if ext in (".mp4", ".m4v"):
                badges.append("MP4/H.264")
            elif ext in (".mkv",):
                badges.append("MKV/HEVC")
            elif ext in (".webm",):
                badges.append("WebM/VP9")
            elif ext in (".srt", ".vtt", ".ass"):
                badges.append("SUBTITLE")
            else:
                badges.append(ext.replace(".", "").upper() or "DATA")

            badge_str = " | ".join(badges)
            self.player_tree.insert("", "end", iid=str(eid), values=(eid, filename, size_mb, badge_str))

        if entries:
            first_iid = str(entries[0].get("id", 1))
            self.player_tree.selection_set(first_iid)

    def _on_scan_error(self, error_msg: str):
        self.btn_scan.config(state="normal")
        self.lbl_scan_status.config(text="Scan failed.", fg=COLOR_DANGER)
        messagebox.showerror("Scan Failed", f"Could not inspect remote archive:\n{error_msg}")

    def play_selected_entry(self):
        selected = self.player_tree.selection()
        if not selected:
            messagebox.showinfo("No Selection", "Please select an episode or media file from the list.")
            return

        eid = int(selected[0])
        player_key = self.selected_player_var.get()

        # Ensure server is running
        if not self.check_live_status():
            ans = messagebox.askyesno(
                "Server Offline",
                "ZipStream server must be running to stream media.\nWould you like to start it now?"
            )
            if ans:
                self.toggle_server()
                time.sleep(0.5)
            else:
                return

        stream_url = f"http://127.0.0.1:{PORT}/stream/{eid}"
        self.log(f"Launching stream {stream_url} with player '{player_key}'...")

        try:
            success = launch_stream(stream_url, player_key=player_key)
            if not success:
                webbrowser.open(stream_url)
        except Exception as e:
            webbrowser.open(stream_url)
            self.log(f"Fallback to browser stream for {stream_url}: {e}")

    # -------------------------------------------------------------------------
    # TAB 3: 🖧 Mount & Virtual Drive
    # -------------------------------------------------------------------------

    def _build_tab_mount(self):
        frame = self.tab_frames["mount"]

        # Windows WebDAV Mount Card
        mount_card = tk.LabelFrame(
            frame,
            text=" 🖧 Windows WebDAV Virtual Drive Mapper ",
            font=("Segoe UI", 9, "bold"),
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD,
            padx=16,
            pady=12,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1
        )
        mount_card.pack(fill="x", pady=(0, 12))

        desc_lbl = tk.Label(
            mount_card,
            text="Map the ZipStream WebDAV repository to an unused Windows drive letter (Z:, Y:, X:) for zero-copy file explorer access.",
            font=("Segoe UI", 8),
            fg=COLOR_TEXT_PRIMARY,
            bg=COLOR_CARD,
            wraplength=660,
            justify="left"
        )
        desc_lbl.pack(anchor="w", pady=(0, 10))

        drive_row = tk.Frame(mount_card, bg=COLOR_CARD)
        drive_row.pack(fill="x")

        tk.Label(drive_row, text="Target Drive Letter:", font=("Segoe UI", 9), fg=COLOR_TEXT_MUTED, bg=COLOR_CARD).pack(side="left", padx=(0, 6))

        self.cmb_drive_letter = ttk.Combobox(
            drive_row,
            values=["Auto (First Free)", "Z:", "Y:", "X:", "W:", "V:", "U:", "T:", "S:"],
            state="readonly",
            width=16,
            style="Dark.TCombobox"
        )
        self.cmb_drive_letter.current(0)
        self.cmb_drive_letter.pack(side="left", padx=(0, 12))

        self.btn_mount = tk.Button(
            drive_row,
            text="🚀 Map Network Drive",
            font=("Segoe UI", 9, "bold"),
            fg="#FFFFFF",
            bg=COLOR_ACCENT_INDIGO,
            activebackground="#4F46E5",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=12,
            pady=4,
            cursor="hand2",
            command=self.mount_webdav_drive
        )
        self.btn_mount.pack(side="left", padx=(0, 8))

        self.btn_unmount = tk.Button(
            drive_row,
            text="Unmount",
            font=("Segoe UI", 9),
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD_ALT,
            activebackground=COLOR_BORDER,
            activeforeground=COLOR_TEXT_PRIMARY,
            relief="flat",
            padx=10,
            pady=4,
            cursor="hand2",
            command=self.unmount_webdav_drive
        )
        self.btn_unmount.pack(side="left")

        # STRM Exporter Card
        strm_card = tk.LabelFrame(
            frame,
            text=" 📦 Jellyfin / Emby / Kodi STRM Exporter ",
            font=("Segoe UI", 9, "bold"),
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD,
            padx=16,
            pady=12,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1
        )
        strm_card.pack(fill="both", expand=True)

        strm_desc = tk.Label(
            strm_card,
            text="Generate structured .strm pointers and multi-episode directory bundles ready for instant Jellyfin / Emby library indexing without downloading gigabytes of video.",
            font=("Segoe UI", 8),
            fg=COLOR_TEXT_PRIMARY,
            bg=COLOR_CARD,
            wraplength=660,
            justify="left"
        )
        strm_desc.pack(anchor="w", pady=(0, 10))

        strm_opts = tk.Frame(strm_card, bg=COLOR_CARD)
        strm_opts.pack(fill="x", pady=(0, 12))

        tk.Label(strm_opts, text="Structure Format:", font=("Segoe UI", 8), fg=COLOR_TEXT_MUTED, bg=COLOR_CARD).pack(side="left", padx=(0, 6))

        self.strm_structure_var = tk.StringVar(value="auto")
        r1 = tk.Radiobutton(strm_opts, text="Auto Detect", variable=self.strm_structure_var, value="auto", fg=COLOR_TEXT_PRIMARY, bg=COLOR_CARD, selectcolor=COLOR_CARD_ALT)
        r2 = tk.Radiobutton(strm_opts, text="TV Shows (Season Folders)", variable=self.strm_structure_var, value="tv", fg=COLOR_TEXT_PRIMARY, bg=COLOR_CARD, selectcolor=COLOR_CARD_ALT)
        r3 = tk.Radiobutton(strm_opts, text="Movies (Flat)", variable=self.strm_structure_var, value="movie", fg=COLOR_TEXT_PRIMARY, bg=COLOR_CARD, selectcolor=COLOR_CARD_ALT)
        r1.pack(side="left", padx=(0, 8))
        r2.pack(side="left", padx=(0, 8))
        r3.pack(side="left")

        self.btn_export_strm = tk.Button(
            strm_card,
            text="📦 Export STRM Bundle ZIP",
            font=("Segoe UI", 9, "bold"),
            fg="#080C14",
            bg=COLOR_ACCENT_CYAN,
            activebackground="#00B4D8",
            activeforeground="#000000",
            relief="flat",
            padx=16,
            pady=7,
            cursor="hand2",
            command=self.export_strm_bundle
        )
        self.btn_export_strm.pack(anchor="w")

    def unmount_webdav_drive(self):
        choice = self.cmb_drive_letter.get()
        letter = choice if ":" in choice else "Z:"
        cmd = f"net use {letter} /delete /y"
        res = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if res.returncode == 0:
            messagebox.showinfo("Drive Unmounted", f"Successfully disconnected network drive {letter}.")
        else:
            messagebox.showwarning("Unmount Result", res.stdout or res.stderr or "Drive was not connected.")

    # -------------------------------------------------------------------------
    # TAB 4: ⚙️ Performance & Buffer
    # -------------------------------------------------------------------------

    def _build_tab_performance(self):
        frame = self.tab_frames["performance"]

        perf_card = tk.LabelFrame(
            frame,
            text=" ⚙️ Streaming Engine Tuning & Cache Buffer ",
            font=("Segoe UI", 9, "bold"),
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD,
            padx=16,
            pady=14,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1
        )
        perf_card.pack(fill="x", pady=(0, 12))

        # Header & Subtitle
        tk.Label(
            perf_card,
            text="Prefetch Ring Buffer Capacity (Memory):",
            font=("Segoe UI", 9, "bold"),
            fg=COLOR_TEXT_PRIMARY,
            bg=COLOR_CARD
        ).pack(anchor="w")

        tk.Label(
            perf_card,
            text="Controls the sliding-window RAM buffer. Higher values saturate gigabit connections.",
            font=("Segoe UI", 8),
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD
        ).pack(anchor="w", pady=(1, 6))

        # Preset Buttons Row
        preset_row = tk.Frame(perf_card, bg=COLOR_CARD)
        preset_row.pack(fill="x", pady=(0, 8))

        presets = [
            ("32 MB (Light)", 32),
            ("512 MB (Balanced)", 512),
            ("1 GB (Fast)", 1024),
            ("2 GB (4K Ultra)", 2048),
            ("5 GB (Maximum Cache)", 5120),
        ]
        for label, mb_val in presets:
            btn = tk.Button(
                preset_row,
                text=label,
                font=("Segoe UI", 7, "bold"),
                fg=COLOR_TEXT_PRIMARY,
                bg=COLOR_CARD_ALT,
                activebackground=COLOR_BORDER,
                activeforeground=COLOR_ACCENT_CYAN,
                relief="flat",
                padx=8,
                pady=3,
                cursor="hand2",
                command=lambda val=mb_val: self._set_buffer_preset(val)
            )
            btn.pack(side="left", padx=(0, 6))

        # Continuous Buffer Slider Row (32 MB to 5120 MB)
        slider_row1 = tk.Frame(perf_card, bg=COLOR_CARD)
        slider_row1.pack(fill="x", pady=(4, 12))

        self.buffer_mb_var = tk.IntVar(value=self.app_config.streaming.prefetch_buffer_size_mb)
        self.scale_buffer = ttk.Scale(
            slider_row1,
            from_=32,
            to=5120,
            orient="horizontal",
            variable=self.buffer_mb_var,
            command=self._on_buffer_slider_change,
            style="Horizontal.TScale"
        )
        self.scale_buffer.pack(side="left", fill="x", expand=True, padx=(0, 12))

        init_mb = self.buffer_mb_var.get()
        init_gb = init_mb / 1024.0
        init_text = f"{init_mb} MB ({init_gb:.2f} GB)" if init_mb >= 1024 else f"{init_mb} MB"

        self.lbl_buffer_val = tk.Label(
            slider_row1,
            text=init_text,
            font=("JetBrains Mono", 9, "bold"),
            fg=COLOR_ACCENT_CYAN,
            bg=COLOR_CARD,
            width=18,
            anchor="e"
        )
        self.lbl_buffer_val.pack(side="right")

        # Network & Socket Tuning Row
        net_row = tk.Frame(perf_card, bg=COLOR_CARD)
        net_row.pack(fill="x", pady=(4, 12))

        # Socket Slice Size Dropdown
        slice_col = tk.Frame(net_row, bg=COLOR_CARD)
        slice_col.pack(side="left", fill="x", expand=True, padx=(0, 10))

        tk.Label(
            slice_col,
            text="Socket Slice Size:",
            font=("Segoe UI", 8, "bold"),
            fg=COLOR_TEXT_PRIMARY,
            bg=COLOR_CARD
        ).pack(anchor="w", pady=(0, 4))

        self.slice_kb_var = tk.IntVar(value=self.app_config.streaming.slice_size_kb)
        self.slice_display_var = tk.StringVar()
        slice_options = ["64 KB", "128 KB", "256 KB", "512 KB", "1024 KB"]
        curr_slice = self.slice_kb_var.get()
        if f"{curr_slice} KB" in slice_options:
            self.slice_display_var.set(f"{curr_slice} KB")
        else:
            self.slice_display_var.set("128 KB")

        self.cmb_slice_size = ttk.Combobox(
            slice_col,
            textvariable=self.slice_display_var,
            values=slice_options,
            state="readonly",
            style="Dark.TCombobox"
        )
        self.cmb_slice_size.pack(fill="x")
        self.cmb_slice_size.bind("<<ComboboxSelected>>", self._on_slice_combo_change)

        # Connection Timeout Selector
        timeout_col = tk.Frame(net_row, bg=COLOR_CARD)
        timeout_col.pack(side="left", fill="x", expand=True, padx=(10, 0))

        tk.Label(
            timeout_col,
            text="Connection Timeout:",
            font=("Segoe UI", 8, "bold"),
            fg=COLOR_TEXT_PRIMARY,
            bg=COLOR_CARD
        ).pack(anchor="w", pady=(0, 4))

        self.timeout_sec_var = tk.IntVar(value=getattr(self.app_config.streaming, "chunk_timeout_seconds", 30))
        self.timeout_display_var = tk.StringVar()
        timeout_options = ["15s", "30s", "45s", "60s"]
        curr_timeout = self.timeout_sec_var.get()
        if f"{curr_timeout}s" in timeout_options:
            self.timeout_display_var.set(f"{curr_timeout}s")
        else:
            self.timeout_display_var.set("30s")

        self.cmb_timeout = ttk.Combobox(
            timeout_col,
            textvariable=self.timeout_display_var,
            values=timeout_options,
            state="readonly",
            style="Dark.TCombobox"
        )
        self.cmb_timeout.pack(fill="x")
        self.cmb_timeout.bind("<<ComboboxSelected>>", self._on_timeout_combo_change)

        # Global Player Default Selector
        player_card = tk.LabelFrame(
            frame,
            text=" 🎯 Default External Media Player ",
            font=("Segoe UI", 9, "bold"),
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD,
            padx=16,
            pady=12,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1
        )
        player_card.pack(fill="x", pady=(0, 12))

        p_row = tk.Frame(player_card, bg=COLOR_CARD)
        p_row.pack(fill="x")

        tk.Label(p_row, text="Active Desktop Player:", font=("Segoe UI", 8), fg=COLOR_TEXT_PRIMARY, bg=COLOR_CARD).pack(side="left", padx=(0, 8))

        self.cmb_player_default = ttk.Combobox(
            p_row,
            textvariable=self.selected_player_var,
            state="readonly",
            width=20,
            style="Dark.TCombobox"
        )
        self.cmb_player_default.pack(side="left", padx=(0, 12))

        # Windows System Integration Card
        win_card = tk.LabelFrame(
            frame,
            text=" 🪟 Windows Desktop Integration ",
            font=("Segoe UI", 9, "bold"),
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD,
            padx=16,
            pady=12,
            highlightbackground=COLOR_BORDER,
            highlightthickness=1
        )
        win_card.pack(fill="x", pady=(0, 12))

        chk_autostart = tk.Checkbutton(
            win_card,
            text="Launch ZipStream Hub automatically on Windows login (Startup Folder)",
            variable=self.auto_start_var,
            font=("Segoe UI", 9),
            fg=COLOR_TEXT_PRIMARY,
            bg=COLOR_CARD,
            activebackground=COLOR_CARD,
            activeforeground=COLOR_ACCENT_CYAN,
            selectcolor=COLOR_CARD_ALT,
            command=self.toggle_auto_start
        )
        chk_autostart.pack(anchor="w")

        # Save & Apply Live Settings Button
        self.btn_save_config = tk.Button(
            perf_card,
            text="💾 Save & Apply Live Settings",
            font=("Segoe UI", 9, "bold"),
            fg="#FFFFFF",
            bg=COLOR_ACCENT_INDIGO,
            activebackground="#4F46E5",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=14,
            pady=6,
            cursor="hand2",
            command=self.save_engine_config
        )
        self.btn_save_config.pack(anchor="w")

    def _set_buffer_preset(self, mb_val: int):
        self.buffer_mb_var.set(mb_val)
        self._on_buffer_slider_change(str(mb_val))

    def _on_buffer_slider_change(self, val):
        v = int(float(val))
        if v >= 1024:
            gb = v / 1024.0
            self.lbl_buffer_val.config(text=f"{v} MB ({gb:.2f} GB)")
        else:
            self.lbl_buffer_val.config(text=f"{v} MB")

    def _on_slice_combo_change(self, event=None):
        val_str = self.slice_display_var.get().replace(" KB", "").strip()
        try:
            self.slice_kb_var.set(int(val_str))
        except ValueError:
            pass

    def _on_timeout_combo_change(self, event=None):
        val_str = self.timeout_display_var.get().replace("s", "").strip()
        try:
            self.timeout_sec_var.set(int(val_str))
        except ValueError:
            pass

    def save_engine_config(self):
        # Update local dataclass config
        self.app_config.streaming.prefetch_buffer_size_mb = self.buffer_mb_var.get()
        self.app_config.streaming.slice_size_kb = self.slice_kb_var.get()
        self.app_config.streaming.chunk_timeout_seconds = self.timeout_sec_var.get()
        self.app_config.players.default_player = self.selected_player_var.get()

        # Send POST /api/config to update running server dynamically
        live_updated = False
        payload = {
            "streaming": {
                "prefetch_buffer_size_mb": self.buffer_mb_var.get(),
                "slice_size_kb": self.slice_kb_var.get(),
                "chunk_timeout_seconds": self.timeout_sec_var.get()
            }
        }

        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{PORT}/api/config",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=1.5) as resp:
                if resp.status == 200:
                    live_updated = True
        except Exception:
            live_updated = False

        try:
            self.app_config.save()
            log_msg = (
                f"Saved config: Buffer={self.buffer_mb_var.get()}MB, "
                f"Slice={self.slice_kb_var.get()}KB, "
                f"Timeout={self.timeout_sec_var.get()}s, "
                f"Player={self.selected_player_var.get()}"
            )
            if live_updated:
                log_msg += " (Live Server Synced via POST /api/config)"
            self.log(log_msg)

            success_msg = (
                "Streaming engine configuration successfully saved to config.json.\n\n"
                + ("• Live Server: Applied instantly via POST /api/config" if live_updated else "• Live Server: Offline (settings saved for next launch)")
            )
            messagebox.showinfo("Config Saved", success_msg)
        except Exception as e:
            messagebox.showerror("Save Error", f"Failed to persist config:\n{e}")

    # -------------------------------------------------------------------------
    # TAB 5: 📊 Diagnostics & Real-time Logs
    # -------------------------------------------------------------------------

    def _build_tab_logs(self):
        frame = self.tab_frames["logs"]

        log_card = tk.Frame(frame, bg=COLOR_CARD, highlightthickness=1, highlightbackground=COLOR_BORDER, padx=10, pady=10)
        log_card.pack(fill="both", expand=True)

        hdr_row = tk.Frame(log_card, bg=COLOR_CARD)
        hdr_row.pack(fill="x", pady=(0, 6))

        tk.Label(hdr_row, text="REAL-TIME HTTP 206 / ENGINE LOGS", font=("Segoe UI", 8, "bold"), fg=COLOR_ACCENT_CYAN, bg=COLOR_CARD).pack(side="left")

        # Action Buttons row
        btn_bar = tk.Frame(hdr_row, bg=COLOR_CARD)
        btn_bar.pack(side="right")

        self.btn_ping_health = tk.Button(
            btn_bar,
            text="🏥 Check Health",
            font=("Segoe UI", 8, "bold"),
            fg="#FFFFFF",
            bg=COLOR_CARD_ALT,
            activebackground=COLOR_BORDER,
            activeforeground=COLOR_ACCENT_CYAN,
            relief="flat",
            padx=8,
            pady=2,
            cursor="hand2",
            command=self.check_server_health
        )
        self.btn_ping_health.pack(side="left", padx=(0, 4))

        self.btn_export_diag = tk.Button(
            btn_bar,
            text="📑 Export Diagnostics",
            font=("Segoe UI", 8),
            fg=COLOR_TEXT_PRIMARY,
            bg=COLOR_CARD_ALT,
            activebackground=COLOR_BORDER,
            activeforeground=COLOR_TEXT_PRIMARY,
            relief="flat",
            padx=8,
            pady=2,
            cursor="hand2",
            command=self.export_diagnostics_report
        )
        self.btn_export_diag.pack(side="left", padx=(0, 4))

        self.btn_copy_logs = tk.Button(
            btn_bar,
            text="📋 Copy Logs",
            font=("Segoe UI", 8),
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD_ALT,
            activebackground=COLOR_BORDER,
            activeforeground=COLOR_TEXT_PRIMARY,
            relief="flat",
            padx=8,
            pady=2,
            cursor="hand2",
            command=self.copy_log_output
        )
        self.btn_copy_logs.pack(side="left", padx=(0, 4))

        btn_clear = tk.Button(
            btn_bar,
            text="🗑️ Clear",
            font=("Segoe UI", 8),
            fg=COLOR_TEXT_MUTED,
            bg=COLOR_CARD_ALT,
            activebackground=COLOR_BORDER,
            activeforeground=COLOR_TEXT_PRIMARY,
            relief="flat",
            padx=8,
            pady=2,
            cursor="hand2",
            command=self.clear_logs
        )
        btn_clear.pack(side="left")

        # Real-time Scrolling Log Console with ScrolledText & dark monospaced styling
        text_frame = tk.Frame(log_card, bg=COLOR_BG)
        text_frame.pack(fill="both", expand=True)

        self.txt_logs = scrolledtext.ScrolledText(
            text_frame,
            font=("JetBrains Mono", 8),
            bg="#05080E",
            fg="#94A3B8",
            insertbackground=COLOR_ACCENT_CYAN,
            relief="flat",
            wrap="word",
            state="disabled",
            highlightthickness=1,
            highlightbackground=COLOR_BORDER
        )
        self.txt_logs.tag_config("info", foreground="#94A3B8")
        self.txt_logs.tag_config("stream", foreground=COLOR_ACCENT_CYAN)
        self.txt_logs.tag_config("warn", foreground=COLOR_WARNING)
        self.txt_logs.tag_config("error", foreground=COLOR_DANGER)
        self.txt_logs.tag_config("success", foreground=COLOR_SUCCESS)
        self.txt_logs.tag_config("highlight", foreground="#F8FAFC", background="#1E293B")

        self.txt_logs.pack(fill="both", expand=True)

    def log(self, message: str, tag: str = "info"):
        timestamp = time.strftime("%H:%M:%S")
        self.log_queue.put(f"[{timestamp}] {message}")

    def _poll_log_queue(self):
        while not self.log_queue.empty():
            msg = self.log_queue.get_nowait()
            self.txt_logs.config(state="normal")
            tag = "info"
            if "206" in msg or "stream" in msg.lower() or "range:" in msg.lower() or "partial content" in msg.lower():
                tag = "stream"
            elif "error" in msg.lower() or "fail" in msg.lower() or "offline" in msg.lower():
                tag = "error"
            elif "start" in msg.lower() or "success" in msg.lower() or "healthy" in msg.lower() or "ok" in msg.lower():
                tag = "success"
            elif "warn" in msg.lower() or "warning" in msg.lower() or "buffer" in msg.lower():
                tag = "warn"
            self.txt_logs.insert("end", msg + "\n", tag)
            self.txt_logs.see("end")
            self.txt_logs.config(state="disabled")

        if not self._is_closing:
            self.after(200, self._poll_log_queue)

    def clear_logs(self):
        self.txt_logs.config(state="normal")
        self.txt_logs.delete("1.0", "end")
        self.txt_logs.config(state="disabled")

    def copy_log_output(self):
        """Copies entire log output console content to system clipboard."""
        content = self.txt_logs.get("1.0", "end-1c")
        if not content.strip():
            messagebox.showinfo("Clipboard", "Log output console is empty.")
            return
        self.clipboard_clear()
        self.clipboard_append(content)
        self.update()
        self.log("Log output copied to clipboard.", "info")
        messagebox.showinfo("Clipboard", "Log output copied to clipboard!")

    def check_server_health(self):
        """Pings server on port 8787 via /api/stats to check latency and connectivity."""
        self.log(f"Pinging server health on http://127.0.0.1:{PORT}/api/stats...", "info")

        def _do_ping():
            t0 = time.perf_counter()
            try:
                req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/stats", method="GET")
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    elapsed_ms = (time.perf_counter() - t0) * 1000.0
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        stats = data.get("stats", {})
                        active = stats.get("active_streams_count", 0)
                        bw = stats.get("current_bandwidth_mbps", 0.0)
                        msg = (
                            f"Server Healthy (HTTP 200 OK) — Latency: {elapsed_ms:.1f}ms | "
                            f"Active Streams: {active} | Speed: {bw:.2f} Mbps"
                        )
                        self.after(0, lambda: self._on_health_check_result(True, msg))
                        return
                    else:
                        msg = f"Server returned unexpected HTTP {resp.status} in {elapsed_ms:.1f}ms"
                        self.after(0, lambda: self._on_health_check_result(False, msg))
                        return
            except Exception as e:
                elapsed_ms = (time.perf_counter() - t0) * 1000.0
                msg = f"Server Ping Failed ({elapsed_ms:.1f}ms): {e}"
                self.after(0, lambda: self._on_health_check_result(False, msg))

        threading.Thread(target=_do_ping, daemon=True).start()

    def _on_health_check_result(self, is_healthy: bool, details: str):
        if is_healthy:
            self.log(f"✓ {details}", "success")
            messagebox.showinfo(
                "Server Health: Online",
                f"ZipStream Server is ONLINE & HEALTHY on Port {PORT}!\n\n{details}"
            )
        else:
            self.log(f"✗ {details}", "error")
            messagebox.showwarning(
                "Server Health: Offline / Error",
                f"ZipStream Server health check failed on Port {PORT}:\n\n{details}\n\nTip: Click 'Start Server' to launch the backend."
            )

    def export_diagnostics_report(self):
        """Generates a comprehensive diagnostic report and exports it to a .txt file."""
        default_filename = f"zipstream_diagnostics_{int(time.time())}.txt"
        save_path = filedialog.asksaveasfilename(
            title="Export Diagnostics Report (.txt)",
            defaultextension=".txt",
            initialfile=default_filename,
            filetypes=[("Text File", "*.txt"), ("All Files", "*.*")]
        )
        if not save_path:
            return

        try:
            report_lines = [
                "==================================================================",
                "               ZIPSTREAM HUB - SYSTEM DIAGNOSTICS REPORT         ",
                "==================================================================",
                f"Timestamp:          {time.strftime('%Y-%m-%d %H:%M:%S')}",
                f"Platform:           {sys.platform} ({os.name})",
                f"Python Version:     {sys.version}",
                f"Server Port:        {PORT}",
                f"Server Status:      {'ONLINE / ACTIVE' if self.is_running else 'STOPPED / OFFLINE'}",
                f"Active Archive URL: {self.current_archive_url or 'None loaded'}",
                f"Loaded Entries:     {len(self.loaded_entries)} files",
                f"Default Player:     {self.selected_player_var.get()}",
                f"Prefetch Buffer:    {self.buffer_mb_var.get()} MB",
                f"Socket Slice Size:  {self.slice_kb_var.get()} KB",
                f"Chunk Timeout:      {self.timeout_sec_var.get()}s",
                f"Windows Auto-Start: {'Enabled' if self.auto_start_var.get() else 'Disabled'}",
                "",
                "------------------------------------------------------------------",
                "                       TELEMETRY METRICS                          ",
                "------------------------------------------------------------------",
                f"Speed Display:      {self.lbl_speed.cget('text')}",
                f"Total Served:       {self.lbl_total.cget('text')}",
                f"Active Streams:     {self.lbl_streams.cget('text')}",
                f"Peak Bandwidth:     {getattr(self, 'lbl_spark_peak', tk.Label()).cget('text')}",
                f"Throughput History: {self._bandwidth_history}",
                "",
                "------------------------------------------------------------------",
                "                       DETECTED PLAYERS                           ",
                "------------------------------------------------------------------",
            ]

            if self.available_players:
                for p in self.available_players:
                    report_lines.append(f"• {p.get('name', 'Unknown')} ({p.get('key', '')}) -> {p.get('path', 'N/A')}")
            else:
                report_lines.append("• Default / System browser fallback")

            report_lines.extend([
                "",
                "------------------------------------------------------------------",
                "                       CONSOLE LOG OUTPUT                         ",
                "------------------------------------------------------------------",
            ])

            log_text = self.txt_logs.get("1.0", "end-1c")
            if log_text.strip():
                report_lines.append(log_text)
            else:
                report_lines.append("(No logs recorded yet)")

            report_lines.extend([
                "",
                "==================================================================",
                "                       END OF DIAGNOSTICS                         ",
                "==================================================================",
            ])

            with open(save_path, "w", encoding="utf-8") as f:
                f.write("\n".join(report_lines) + "\n")

            self.log(f"Exported diagnostics report to: {save_path}", "success")
            messagebox.showinfo(
                "Report Exported",
                f"Diagnostics report successfully exported to:\n{save_path}"
            )
        except Exception as e:
            self.log(f"Failed to export diagnostics report: {e}", "error")
            messagebox.showerror("Export Error", f"Could not write diagnostics report:\n{e}")

    # -------------------------------------------------------------------------
    # Server Process Control & System Integrations
    # -------------------------------------------------------------------------

    def toggle_server(self):
        global SERVER_PROCESS
        if SERVER_PROCESS is None or SERVER_PROCESS.poll() is not None:
            if self.is_port_in_use(PORT):
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
                creation_flags = 0
                if sys.platform == "win32":
                    creation_flags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0x08000000

                SERVER_PROCESS = subprocess.Popen(
                    [python_exe, backend_script],
                    cwd=base_dir,
                    creationflags=creation_flags
                )
                self.set_running_state(True)
                self.log(f"ZipStream server process spawned (PID: {SERVER_PROCESS.pid})", "success")
                self.footer_lbl.config(text="Server starting up...")
                self.after(600, self.open_web_gui)
            except Exception as e:
                self.log(f"Failed to start backend server: {e}", "error")
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
            self.log("ZipStream server stopped.", "warn")
            self.footer_lbl.config(text="Server stopped.")

    def set_running_state(self, is_running: bool):
        self.is_running = is_running
        if is_running:
            self.hdr_status_dot.config(fg=COLOR_SUCCESS)
            self.hdr_status_text.config(text="Active", fg=COLOR_SUCCESS)
            self.hdr_btn_toggle.config(text="⏹ Stop Server", bg=COLOR_DANGER, activebackground="#DC2626")
            self.btn_main_toggle.config(text="⏹ Stop ZipStream Service", bg=COLOR_DANGER, activebackground="#DC2626")
            self.footer_lbl.config(text="● Online • WebDAV: http://127.0.0.1:8787/webdav/")
        else:
            self.hdr_status_dot.config(fg=COLOR_DANGER)
            self.hdr_status_text.config(text="Stopped", fg=COLOR_TEXT_MUTED)
            self.hdr_btn_toggle.config(text="▶ Start Server", bg=COLOR_SUCCESS, activebackground="#059669")
            self.btn_main_toggle.config(text="▶ Start ZipStream Service", bg=COLOR_SUCCESS, activebackground="#059669")
            self.footer_lbl.config(text="Service Stopped • Click 'Start Server' to begin.")

    def open_web_gui(self):
        url = f"http://127.0.0.1:{PORT}"
        self.log(f"Opening Web Dashboard in default browser: {url}")
        webbrowser.open(url)

    def mount_webdav_drive(self):
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
            try:
                choice = self.cmb_drive_letter.get()
                if "Auto" in choice:
                    available_drive = self._get_available_drive_letter()
                else:
                    available_drive = choice.replace(":", "").strip()

                drive_target = f"{available_drive}:" if available_drive else "*"
                cmd = f'net use {drive_target} "{webdav_url}" /persistent:no'
                self.log(f"Executing: {cmd}")
                res = subprocess.run(cmd, shell=True, capture_output=True, text=True)

                if res.returncode == 0:
                    drive_assigned = available_drive or "Assigned"
                    self.log(f"WebDAV drive mapped to {drive_assigned}:", "success")
                    messagebox.showinfo(
                        "WebDAV Mounted",
                        f"Successfully mounted WebDAV endpoint as Drive {drive_assigned}:\n{webdav_url}\n\nOpening File Explorer..."
                    )
                    if available_drive:
                        os.startfile(f"{available_drive}:\\")
                    else:
                        os.startfile(webdav_url)
                else:
                    err_msg = res.stderr.strip() or res.stdout.strip()
                    self.log(f"Net use notice: {err_msg}", "warn")
                    webbrowser.open(f"{webdav_url}/")
                    messagebox.showinfo(
                        "WebDAV Explorer",
                        f"Opened WebDAV HTTP directory in browser/explorer.\n\nTip: You can manually map network drive in Windows Explorer to:\n{webdav_url}\n\n(Info: {err_msg})"
                    )
            except Exception as e:
                webbrowser.open(webdav_url)
                messagebox.showinfo("WebDAV Directory", f"Opened WebDAV Directory:\n{webdav_url}\n({e})")
        else:
            webbrowser.open(webdav_url)

    def _get_available_drive_letter(self) -> Optional[str]:
        if sys.platform != "win32":
            return None
        import string
        used_drives = set()
        for letter in string.ascii_uppercase:
            if os.path.exists(f"{letter}:\\"):
                used_drives.add(letter)
        for letter in reversed(string.ascii_uppercase[:26]):
            if letter not in ("A", "B", "C") and letter not in used_drives:
                return letter
        return None

    def export_strm_bundle(self):
        if not self.check_live_status():
            messagebox.showwarning(
                "Server Offline",
                "Please start the server and scan an archive first to export a STRM bundle."
            )
            return

        try:
            history_url = f"http://127.0.0.1:{PORT}/api/history"
            req = urllib.request.Request(history_url)
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                history_items = data.get("history", [])

            target_url = self.current_archive_url or (history_items[0].get("url") if history_items else "")
            if not target_url:
                messagebox.showinfo(
                    "No Archive Loaded",
                    "No archive loaded.\n\nPaste a remote ZIP link into Quick-Player or scan one on the Web Dashboard first!"
                )
                return

            default_filename = f"strm_bundle_{int(time.time())}.zip"
            save_path = filedialog.asksaveasfilename(
                title="Save Jellyfin / Kodi STRM ZIP Bundle",
                defaultextension=".zip",
                initialfile=default_filename,
                filetypes=[("ZIP Archive", "*.zip"), ("All Files", "*.*")]
            )

            if not save_path:
                return

            reader = RemoteZipReader(target_url)
            base_url = f"http://127.0.0.1:{PORT}"
            struct_choice = self.strm_structure_var.get()
            zip_bytes = generate_strm_zip_bundle(reader.entries, base_url, structure_type=struct_choice)

            with open(save_path, "wb") as f:
                f.write(zip_bytes)

            self.log(f"Exported STRM Bundle ({len(reader.entries)} entries) -> {save_path}", "success")
            messagebox.showinfo(
                "Export Complete",
                f"Exported {len(reader.entries)} entries to STRM Bundle:\n{save_path}\n\nExtract this into your Jellyfin, Emby, or Kodi media folder!"
            )
        except Exception as e:
            self.log(f"Export failed: {e}", "error")
            messagebox.showerror("Export Failed", f"Could not generate STRM bundle:\n{e}")

    def is_port_in_use(self, port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.3)
            return s.connect_ex(("127.0.0.1", port)) == 0

    def check_live_status(self) -> bool:
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{PORT}/api/stats", method="GET")
            with urllib.request.urlopen(req, timeout=0.6) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        return False

    def check_server_status(self):
        is_alive = self.check_live_status()
        self.set_running_state(is_alive)

    def schedule_stats_poll(self):
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
            self.lbl_speed.config(text="0.00 Mbps", fg="#64748b")
            self.lbl_streams.config(text="0 active players", fg=COLOR_TEXT_DIM)
            self._bandwidth_history.append(0.0)
            if len(self._bandwidth_history) > 20:
                self._bandwidth_history.pop(0)
            self._draw_sparkline()
            return

        if not self.is_running:
            self.set_running_state(True)

        speed_mbps = float(stats.get("current_bandwidth_mbps", 0.0))
        total_bytes = stats.get("total_bytes_served", 0)
        total_mb = stats.get("total_mbytes_served", total_bytes / (1024 * 1024))
        total_gb = stats.get("total_gbytes_served", total_bytes / (1024 * 1024 * 1024))
        active_streams = int(stats.get("active_streams_count", 0))

        # Check server streaming activity deltas and capture live request log events
        if active_streams > self._last_active_streams:
            new_sessions = active_streams - self._last_active_streams
            self.log(
                f"GET /stream/... [Incoming Stream Client Connected] • Range: bytes=0- | Active Sessions: {active_streams} | 206 Partial Content",
                "stream"
            )
        elif active_streams < self._last_active_streams and self._last_active_streams > 0:
            self.log(
                f"Stream Session Completed • Active Sessions Remaining: {active_streams} | Buffer Status: Flushed",
                "info"
            )

        if total_bytes > self._last_total_bytes and self._last_total_bytes > 0:
            delta_mb = (total_bytes - self._last_total_bytes) / (1024 * 1024)
            if speed_mbps > 0.05:
                self.log(
                    f"HTTP 206 Partial Content • Stream Throughput: {speed_mbps:.2f} Mbps (+{delta_mb:.2f} MB served) | Buffer Status: Nominal",
                    "stream"
                )

        self._last_active_streams = active_streams
        self._last_total_bytes = total_bytes

        # Speed formatting & color coding
        self.lbl_speed.config(text=f"{speed_mbps:.2f} Mbps")
        if speed_mbps > 5.0:
            self.lbl_speed.config(fg="#10b981")  # Glowing neon green for high throughput
        elif speed_mbps > 0:
            self.lbl_speed.config(fg="#38bdf8")  # Sky blue for active
        else:
            self.lbl_speed.config(fg="#64748b" if active_streams == 0 else "#38bdf8")

        # Total served formatting
        if total_gb >= 1.0:
            self.lbl_total.config(text=f"{total_gb:.2f} GB")
        else:
            self.lbl_total.config(text=f"{total_mb:.2f} MB")

        # Active streams wording
        stream_suffix = "active player" if active_streams == 1 else "active players"
        self.lbl_streams.config(text=f"{active_streams} {stream_suffix}")

        if active_streams > 0:
            self.lbl_streams.config(fg="#10b981")
        else:
            self.lbl_streams.config(fg=COLOR_TEXT_DIM)

        # Update sparkline history
        self._bandwidth_history.append(speed_mbps)
        if len(self._bandwidth_history) > 20:
            self._bandwidth_history.pop(0)
        self._draw_sparkline()

    def _detect_system_players(self):
        def _detect():
            try:
                players = get_installed_players()
                self.after(0, lambda: self._on_players_detected(players))
            except Exception:
                pass

        threading.Thread(target=_detect, daemon=True).start()

    def _on_players_detected(self, players: List[Dict[str, Any]]):
        self.available_players = players
        player_keys = [p.get("key", "mpv") for p in players]
        if not player_keys:
            player_keys = ["mpv", "vlc", "potplayer", "browser"]

        self.cmb_player_quick["values"] = player_keys
        self.cmb_player_default["values"] = player_keys

        default_choice = self.app_config.players.default_player
        if default_choice in player_keys:
            self.selected_player_var.set(default_choice)
        elif player_keys:
            self.selected_player_var.set(player_keys[0])

    # -------------------------------------------------------------------------
    # System Tray Integration & Windows Desktop Integration
    # -------------------------------------------------------------------------

    def _get_startup_shortcut_path(self) -> str:
        """Returns the path to the startup shortcut in APPDATA."""
        appdata = os.environ.get("APPDATA")
        if not appdata:
            appdata = os.path.expanduser(r"~\AppData\Roaming")
        startup_folder = os.path.join(
            appdata, r"Microsoft\Windows\Start Menu\Programs\Startup"
        )
        return os.path.join(startup_folder, "ZipStreamHub.vbs")

    def is_auto_start_enabled(self) -> bool:
        """Check if Windows auto-start entry exists."""
        try:
            target = self._get_startup_shortcut_path()
            return os.path.exists(target)
        except Exception:
            return False

    def set_auto_start(self, enabled: bool) -> bool:
        """Create or remove Windows auto-start launcher in Startup folder."""
        try:
            shortcut_path = self._get_startup_shortcut_path()
            if enabled:
                os.makedirs(os.path.dirname(shortcut_path), exist_ok=True)
                python_exe = sys.executable
                if python_exe.endswith("python.exe"):
                    pythonw = python_exe[:-10] + "pythonw.exe"
                    if os.path.exists(pythonw):
                        python_exe = pythonw

                base_dir = os.path.dirname(os.path.abspath(__file__))
                main_script = os.path.join(base_dir, "control_panel.py")

                # Create non-flashing Windows Script Host runner
                vbs_content = (
                    f'Set WshShell = CreateObject("WScript.Shell")\r\n'
                    f'WshShell.CurrentDirectory = "{base_dir}"\r\n'
                    f'WshShell.Run """{python_exe}"" ""{main_script}""", 0, False\r\n'
                )
                with open(shortcut_path, "w", encoding="utf-8") as f:
                    f.write(vbs_content)
                self.log(f"Created auto-start launcher at {shortcut_path}", "success")
                return True
            else:
                if os.path.exists(shortcut_path):
                    os.remove(shortcut_path)
                    self.log(f"Removed auto-start launcher at {shortcut_path}", "info")
                return True
        except Exception as e:
            self.log(f"Failed to update auto-start: {e}", "error")
            return False

    def toggle_auto_start(self):
        enabled = self.auto_start_var.get()
        success = self.set_auto_start(enabled)
        if success:
            state_str = "enabled" if enabled else "disabled"
            messagebox.showinfo(
                "Windows Auto-Start",
                f"ZipStream Hub auto-start on Windows login has been {state_str}."
            )
        else:
            self.auto_start_var.set(not enabled)
            messagebox.showerror(
                "Windows Auto-Start Error",
                "Could not modify Windows Startup directory."
            )

    def _setup_tray(self):
        if not HAS_PYSTRAY:
            return

        try:
            if os.path.exists(self.icon_path):
                image = Image.open(self.icon_path)
            else:
                image = Image.new("RGB", (64, 64), color="#6366F1")

            def _toggle_server_action(icon, item):
                self.after(0, self.toggle_server)

            def _open_gui_action(icon, item):
                self.after(0, self.open_web_gui)

            def _mount_action(icon, item):
                self.after(0, self.mount_webdav_drive)

            def _show_cp_action(icon, item):
                self.after(0, self._show_window)

            def _quit_action(icon, item):
                self.after(0, self.quit_application)

            menu = pystray.Menu(
                pystray.MenuItem("⚡ Show Control Panel", _show_cp_action, default=True),
                pystray.MenuItem("🌐 Open Web GUI Dashboard", _open_gui_action),
                pystray.MenuItem("🖧 Mount Virtual Drive (Z:)", _mount_action),
                pystray.MenuItem("⏸ Toggle Streaming Server", _toggle_server_action),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("❌ Exit", _quit_action)
            )

            self.tray_icon = pystray.Icon("ZipStreamHub", image, "ZipStream Hub", menu)
        except Exception:
            self.tray_icon = None

    def minimize_to_tray(self):
        if HAS_PYSTRAY and self.tray_icon:
            self.withdraw()
            if not getattr(self.tray_icon, "_running", False):
                threading.Thread(target=self.tray_icon.run, daemon=True).start()
            self._notify_minimized()
        else:
            self.iconify()

    def _notify_minimized(self):
        try:
            if self.tray_icon and hasattr(self.tray_icon, "notify"):
                status_text = "Running" if self.is_running else "Stopped"
                self.tray_icon.notify(
                    f"ZipStream Hub is running in the background (Server: {status_text}).\nDouble-click the tray icon to restore.",
                    title="ZipStream Hub Minimized"
                )
        except Exception:
            pass

    def restore_from_tray(self, icon=None, item=None):
        self.after(0, self._show_window)

    def _show_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()

    def on_close(self):
        if HAS_PYSTRAY and self.tray_icon:
            self.minimize_to_tray()
        else:
            self.quit_application()

    def quit_application(self, icon=None, item=None):
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


def main():
    app = ZipStreamControlPanel()
    app.mainloop()


if __name__ == "__main__":
    main()
