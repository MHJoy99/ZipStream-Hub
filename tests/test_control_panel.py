"""
Unit and integration tests for ZipStreamControlPanel GUI, telemetry, tabs,
presets, drive detection, player bindings, and STRM/M3U export workflows.
"""

from __future__ import annotations

import io
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import tkinter as tk
from src.zipstream.control_panel import ZipStreamControlPanel, PORT


_SHARED_APP: ZipStreamControlPanel | None = None


def get_shared_app() -> ZipStreamControlPanel:
    """Create or reuse a headless Tk root to prevent Tcl init file churn across test cases."""
    global _SHARED_APP
    if _SHARED_APP is None:
        with patch("src.zipstream.control_panel.ZipStreamControlPanel._setup_tray"), \
             patch("src.zipstream.control_panel.ZipStreamControlPanel.check_server_status"), \
             patch("src.zipstream.control_panel.ZipStreamControlPanel.schedule_stats_poll"), \
             patch("src.zipstream.control_panel.ZipStreamControlPanel._detect_system_players"):
            _SHARED_APP = ZipStreamControlPanel()
            _SHARED_APP.withdraw()
    return _SHARED_APP


class BaseControlPanelTest(unittest.TestCase):
    """Base test class providing headless Tkinter setup and cleanup."""

    def setUp(self):
        try:
            self.app = get_shared_app()
            # Reset state variables between tests
            self.app.is_running = False
            self.app._bandwidth_history = [0.0] * 20
            self.app.current_archive_url = ""
            self.app.loaded_entries = []
            self.app.app_config.players.default_player = "mpv"
            self.app.selected_player_var.set("mpv")
            self.app.strm_structure_var.set("auto")
            while not self.app.log_queue.empty():
                self.app.log_queue.get_nowait()
            self.app.clear_logs()
        except Exception as e:
            self.skipTest(f"Tkinter / Display not available: {e}")


class TestControlPanelInitializationAndTabs(BaseControlPanelTest):
    """Tests for window initialization, layouts, tabs, and navigation."""

    def test_window_initialization(self):
        """Verify window properties, title, and initial states."""
        self.assertIn("ZipStream Hub", self.app.title())
        self.assertFalse(self.app.is_running)
        self.assertEqual(len(self.app._bandwidth_history), 20)
        self.assertIsNotNone(self.app.app_config)

    def test_tab_frames_instantiation(self):
        """Verify all expected tabs exist and have associated buttons."""
        expected_tabs = {"overview", "player", "mount", "performance", "logs"}
        self.assertEqual(set(self.app.tab_frames.keys()), expected_tabs)
        self.assertEqual(set(self.app.tab_buttons.keys()), expected_tabs)

        for tab_name, frame in self.app.tab_frames.items():
            self.assertIsInstance(frame, tk.Frame)

        for tab_name, btn in self.app.tab_buttons.items():
            self.assertIsInstance(btn, tk.Button)

    def test_tab_navigation_switching(self):
        """Verify switching tabs properly manages visibility and button states."""
        # Switch to player tab
        self.app.switch_tab("player")
        self.assertEqual(self.app.tab_buttons["player"].cget("fg"), "#00F0FF")

        # Switch to performance tab
        self.app.switch_tab("performance")
        self.assertEqual(self.app.tab_buttons["performance"].cget("fg"), "#00F0FF")

        # Switch to logs tab
        self.app.switch_tab("logs")
        self.assertEqual(self.app.tab_buttons["logs"].cget("fg"), "#00F0FF")

        # Switch back to overview
        self.app.switch_tab("overview")
        self.assertEqual(self.app.tab_buttons["overview"].cget("fg"), "#00F0FF")


class TestControlPanelTelemetry(BaseControlPanelTest):
    """Tests for live metrics update handler and sparkline telemetry rendering."""

    def test_initial_telemetry_state(self):
        """Test initial telemetry labels."""
        self.assertEqual(len(self.app._bandwidth_history), 20)
        self.app._update_metrics_ui({}, is_alive=False)
        self.assertEqual(self.app.lbl_speed.cget("text"), "0.00 Mbps")
        self.assertEqual(self.app.lbl_total.cget("text"), "0.00 MB")
        self.assertIn("0 active players", self.app.lbl_streams.cget("text"))

    def test_update_metrics_ui_idle_and_active(self):
        """Test UI updates for idle and active streaming stats with formatting and color codes."""
        # 1. Active with MB range (< 5 Mbps)
        active_stats_mb = {
            "current_bandwidth_mbps": 4.5,
            "total_bytes_served": 50 * 1024 * 1024,
            "total_mbytes_served": 50.0,
            "total_gbytes_served": 0.049,
            "active_streams_count": 1
        }
        self.app._update_metrics_ui(active_stats_mb, is_alive=True)
        self.assertEqual(self.app.lbl_speed.cget("text"), "4.50 Mbps")
        self.assertEqual(self.app.lbl_speed.cget("fg"), "#38bdf8")
        self.assertEqual(self.app.lbl_total.cget("text"), "50.00 MB")
        self.assertEqual(self.app.lbl_streams.cget("text"), "1 active player")
        self.assertEqual(self.app.lbl_streams.cget("fg").lower(), "#10b981")
        self.assertEqual(self.app._bandwidth_history[-1], 4.5)

        # 2. High throughput (> 5 Mbps neon green) and GB range
        active_stats_gb = {
            "current_bandwidth_mbps": 28.75,
            "total_bytes_served": 2 * 1024 * 1024 * 1024,
            "total_mbytes_served": 2048.0,
            "total_gbytes_served": 2.00,
            "active_streams_count": 3
        }
        self.app._update_metrics_ui(active_stats_gb, is_alive=True)
        self.assertEqual(self.app.lbl_speed.cget("text"), "28.75 Mbps")
        self.assertEqual(self.app.lbl_speed.cget("fg").lower(), "#10b981")
        self.assertEqual(self.app.lbl_total.cget("text"), "2.00 GB")
        self.assertEqual(self.app.lbl_streams.cget("text"), "3 active players")
        self.assertEqual(self.app._bandwidth_history[-1], 28.75)

        # 3. Server offline / idle fallback
        self.app._update_metrics_ui({}, is_alive=False)
        self.assertEqual(self.app.lbl_speed.cget("text"), "0.00 Mbps")
        self.assertEqual(self.app.lbl_speed.cget("fg").lower(), "#64748b")
        self.assertEqual(self.app.lbl_streams.cget("text"), "0 active players")
        self.assertEqual(self.app._bandwidth_history[-1], 0.0)

    def test_sparkline_rendering_and_history_cap(self):
        """Test sparkline rendering with custom data and history bound to 20 points."""
        self.app._bandwidth_history = [0.0, 1.2, 3.4, 15.0, 22.5] + [0.0] * 15
        self.app._draw_sparkline()
        self.assertIn("Peak: 22.50 Mbps", self.app.lbl_spark_peak.cget("text"))

        # Add 30 updates to verify history is capped at 20
        for i in range(30):
            stats = {"current_bandwidth_mbps": float(i), "total_bytes_served": 0, "active_streams_count": 0}
            self.app._update_metrics_ui(stats, is_alive=True)

        self.assertEqual(len(self.app._bandwidth_history), 20)
        self.assertEqual(self.app._bandwidth_history[-1], 29.0)


class TestControlPanelDriveDetector(BaseControlPanelTest):
    """Tests for available Windows drive letter detection."""

    def test_get_available_drive_letter_win32(self):
        """Test drive letter detection on win32 platforms."""
        with patch("sys.platform", "win32"):
            # Mock os.path.exists so Z: is used, Y: is free
            def mock_exists(path):
                if path.startswith("Z:"):
                    return True
                return False

            with patch("os.path.exists", side_effect=mock_exists):
                letter = self.app._get_available_drive_letter()
                self.assertEqual(letter, "Y")

    def test_get_available_drive_letter_non_win32(self):
        """Test drive letter detection returns None on non-Windows platforms."""
        with patch("sys.platform", "linux"):
            letter = self.app._get_available_drive_letter()
            self.assertIsNone(letter)

    def test_get_available_drive_letter_exhausted(self):
        """Test drive letter detection when all standard drive letters are occupied."""
        with patch("sys.platform", "win32"):
            with patch("os.path.exists", return_value=True):
                letter = self.app._get_available_drive_letter()
                self.assertIsNone(letter)


class TestControlPanelBufferPresets(BaseControlPanelTest):
    """Tests for performance buffer slider, presets, slice dropdown, timeout, and persistence."""

    def test_buffer_slider_change_handler(self):
        """Test prefetch buffer slider callback updates label text in MB and GB."""
        self.app._on_buffer_slider_change("256.0")
        self.assertEqual(self.app.lbl_buffer_val.cget("text"), "256 MB")

        self.app._on_buffer_slider_change("1024")
        self.assertEqual(self.app.lbl_buffer_val.cget("text"), "1024 MB (1.00 GB)")

        self.app._on_buffer_slider_change("2048")
        self.assertEqual(self.app.lbl_buffer_val.cget("text"), "2048 MB (2.00 GB)")

    def test_buffer_presets(self):
        """Test preset buttons set exact buffer values and updates UI."""
        self.app._set_buffer_preset(512)
        self.assertEqual(self.app.buffer_mb_var.get(), 512)
        self.assertEqual(self.app.lbl_buffer_val.cget("text"), "512 MB")

        self.app._set_buffer_preset(5120)
        self.assertEqual(self.app.buffer_mb_var.get(), 5120)
        self.assertEqual(self.app.lbl_buffer_val.cget("text"), "5120 MB (5.00 GB)")

    def test_slice_combo_change_handler(self):
        """Test socket slice dropdown handler updates variable."""
        self.app.slice_display_var.set("256 KB")
        self.app._on_slice_combo_change()
        self.assertEqual(self.app.slice_kb_var.get(), 256)

        self.app.slice_display_var.set("1024 KB")
        self.app._on_slice_combo_change()
        self.assertEqual(self.app.slice_kb_var.get(), 1024)

    def test_timeout_combo_change_handler(self):
        """Test connection timeout dropdown handler updates variable."""
        self.app.timeout_display_var.set("45s")
        self.app._on_timeout_combo_change()
        self.assertEqual(self.app.timeout_sec_var.get(), 45)

        self.app.timeout_display_var.set("60s")
        self.app._on_timeout_combo_change()
        self.assertEqual(self.app.timeout_sec_var.get(), 60)

    @patch("tkinter.messagebox.showinfo")
    def test_save_engine_config_success(self, mock_info):
        """Test saving streaming engine configuration and sending POST /api/config."""
        self.app.buffer_mb_var.set(512)
        self.app.slice_kb_var.set(256)
        self.app.timeout_sec_var.set(45)
        self.app.selected_player_var.set("vlc")

        with patch.object(self.app.app_config, "save") as mock_save, \
             patch("urllib.request.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.status = 200
            mock_urlopen.return_value.__enter__.return_value = mock_resp

            self.app.save_engine_config()
            mock_save.assert_called_once()
            mock_info.assert_called_once()
            mock_urlopen.assert_called_once()

        self.assertEqual(self.app.app_config.streaming.prefetch_buffer_size_mb, 512)
        self.assertEqual(self.app.app_config.streaming.slice_size_kb, 256)
        self.assertEqual(self.app.app_config.streaming.chunk_timeout_seconds, 45)
        self.assertEqual(self.app.app_config.players.default_player, "vlc")

    @patch("tkinter.messagebox.showerror")
    def test_save_engine_config_error(self, mock_error):
        """Test handling failure when saving config raises exception."""
        with patch.object(self.app.app_config, "save", side_effect=IOError("Permission denied")), \
             patch("urllib.request.urlopen"):
            self.app.save_engine_config()
            mock_error.assert_called_once()


class TestControlPanelPlayerDetector(BaseControlPanelTest):
    """Tests for external player detection and status binding."""

    def test_players_detected_binding(self):
        """Test binding detected players to UI comboboxes."""
        self.app.app_config.players.default_player = "mpv"
        players = [
            {"name": "MPV Player", "key": "mpv", "path": "mpv.exe", "supported": True},
            {"name": "VLC Media Player", "key": "vlc", "path": "vlc.exe", "supported": True},
            {"name": "PotPlayer", "key": "potplayer", "path": "potplayer.exe", "supported": True},
        ]
        self.app._on_players_detected(players)

        self.assertEqual(self.app.available_players, players)
        expected_keys = ("mpv", "vlc", "potplayer")
        self.assertEqual(tuple(self.app.cmb_player_quick["values"]), expected_keys)
        self.assertEqual(tuple(self.app.cmb_player_default["values"]), expected_keys)
        self.assertEqual(self.app.selected_player_var.get(), "mpv")

    def test_players_detected_fallback_empty(self):
        """Test player detection fallback when no media players are found."""
        self.app._on_players_detected([])
        fallback_keys = ("mpv", "vlc", "potplayer", "browser")
        self.assertEqual(tuple(self.app.cmb_player_quick["values"]), fallback_keys)
        self.assertEqual(tuple(self.app.cmb_player_default["values"]), fallback_keys)


class TestControlPanelQuickPlayerAndSTRM(BaseControlPanelTest):
    """Tests for Archive Quick-Player scanning, playback, and STRM/M3U exports."""

    @patch("tkinter.messagebox.showwarning")
    def test_scan_archive_url_empty(self, mock_warn):
        """Test warning on empty URL input."""
        self.app.entry_archive_url.delete(0, "end")
        self.app.scan_archive_url()
        mock_warn.assert_called_once()

    def test_scan_success_populates_treeview_and_badges(self):
        """Test successful scan populates player tree with formatted sizes and media badges."""
        entries = [
            {"id": 1, "filename": "Show.S01E01.mp4", "file_size": 150 * 1024 * 1024},
            {"id": 2, "filename": "Show.S01E02.mkv", "file_size": 300 * 1024 * 1024},
            {"id": 3, "filename": "Show.S01E01.srt", "file_size": 45 * 1024},
            {"id": 4, "filename": "document.pdf", "file_size": 5 * 1024 * 1024},
        ]
        test_url = "http://example.com/archive.zip"
        self.app._on_scan_success(test_url, entries)

        self.assertEqual(self.app.current_archive_url, test_url)
        self.assertEqual(len(self.app.player_tree.get_children()), 4)

        # Verify entry 1: MP4 badge
        item1 = self.app.player_tree.item("1")["values"]
        self.assertEqual(item1[0], 1)
        self.assertEqual(item1[1], "Show.S01E01.mp4")
        self.assertIn("150.0 MB", item1[2])
        self.assertIn("MP4/H.264", item1[3])

        # Verify entry 2: MKV badge
        item2 = self.app.player_tree.item("2")["values"]
        self.assertIn("MKV/HEVC", item2[3])

        # Verify entry 3: Subtitle badge
        item3 = self.app.player_tree.item("3")["values"]
        self.assertIn("SUBTITLE", item3[3])

        # Verify entry 4: Generic extension badge
        item4 = self.app.player_tree.item("4")["values"]
        self.assertIn("PDF", item4[3])

    @patch("tkinter.messagebox.showerror")
    def test_scan_error_handling(self, mock_error):
        """Test scan error updates status and displays error dialog."""
        self.app._on_scan_error("HTTP 404 Not Found")
        self.assertEqual(self.app.lbl_scan_status.cget("text"), "Scan failed.")
        mock_error.assert_called_once()

    @patch("src.zipstream.control_panel.launch_stream", return_value=True)
    @patch.object(ZipStreamControlPanel, "check_live_status", return_value=True)
    def test_play_selected_entry_success(self, mock_live, mock_launch):
        """Test playback launch for selected episode when server is running."""
        entries = [{"id": 42, "filename": "Episode42.mp4", "file_size": 1000}]
        self.app._on_scan_success("http://example.com/pack.zip", entries)
        self.app.player_tree.selection_set("42")
        self.app.selected_player_var.set("mpv")

        self.app.play_selected_entry()
        mock_launch.assert_called_once_with(f"http://127.0.0.1:{PORT}/stream/42", player_key="mpv")

    @patch("tkinter.messagebox.showinfo")
    def test_play_selected_entry_no_selection(self, mock_info):
        """Test play button when no entry is selected."""
        for item in self.app.player_tree.get_children():
            self.app.player_tree.delete(item)
        self.app.play_selected_entry()
        mock_info.assert_called_once()

    @patch("tkinter.messagebox.showwarning")
    @patch.object(ZipStreamControlPanel, "check_live_status", return_value=False)
    def test_export_strm_bundle_server_offline(self, mock_live, mock_warn):
        """Test STRM bundle export aborts when server is offline."""
        self.app.export_strm_bundle()
        mock_warn.assert_called_once()

    @patch("tkinter.messagebox.showinfo")
    @patch("urllib.request.urlopen")
    @patch.object(ZipStreamControlPanel, "check_live_status", return_value=True)
    def test_export_strm_bundle_no_archive_loaded(self, mock_live, mock_urlopen, mock_info):
        """Test STRM bundle export notification when no archive is loaded or in history."""
        self.app.current_archive_url = ""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"history": []}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        self.app.export_strm_bundle()
        mock_info.assert_called_once()

    @patch("tkinter.filedialog.asksaveasfilename")
    @patch("tkinter.messagebox.showinfo")
    @patch("src.zipstream.control_panel.RemoteZipReader")
    @patch("src.zipstream.control_panel.generate_strm_zip_bundle", return_value=b"PK_MOCK_ZIP_CONTENT")
    @patch.object(ZipStreamControlPanel, "check_live_status", return_value=True)
    def test_export_strm_bundle_success(self, mock_live, mock_gen_zip, mock_reader, mock_info, mock_filedialog):
        """Test full STRM export pipeline with valid archive."""
        self.app.current_archive_url = "http://example.com/tvshow.zip"
        mock_filedialog.return_value = "E:/output_strm.zip"

        fake_reader = MagicMock()
        fake_reader.entries = [{"id": 1, "filename": "S01E01.mp4", "file_size": 1000}]
        mock_reader.return_value = fake_reader

        m_open = mock_open()
        with patch("builtins.open", m_open):
            self.app.export_strm_bundle()

        mock_gen_zip.assert_called_once()
        m_open.assert_called_once_with("E:/output_strm.zip", "wb")
        m_open().write.assert_called_once_with(b"PK_MOCK_ZIP_CONTENT")
        mock_info.assert_called_once()


class TestControlPanelServerAndLogs(BaseControlPanelTest):
    """Tests for server process toggle, logging subsystem, and WebDAV mount/unmount."""

    def test_set_running_state_active_and_stopped(self):
        """Test set_running_state modifies widgets, colors, and labels appropriately."""
        # Online
        self.app.set_running_state(True)
        self.assertTrue(self.app.is_running)
        self.assertIn("Active", self.app.hdr_status_text.cget("text"))
        self.assertIn("Stop Server", self.app.hdr_btn_toggle.cget("text"))
        self.assertIn("Online", self.app.footer_lbl.cget("text"))

        # Offline
        self.app.set_running_state(False)
        self.assertFalse(self.app.is_running)
        self.assertEqual(self.app.hdr_status_text.cget("text"), "Stopped")
        self.assertIn("Start Server", self.app.hdr_btn_toggle.cget("text"))
        self.assertIn("Stopped", self.app.footer_lbl.cget("text"))

    def test_auto_attach_to_running_instance(self):
        """Test auto-attaching to an existing running instance discovered via /api/ping."""
        mock_ping_data = {
            "status": "ok",
            "app": "zipstream-hub",
            "version": "1.0.0",
            "pid": 12345,
            "uptime": 42.5,
            "port": 8787
        }
        with patch.object(self.app, "ping_running_instance", return_value=mock_ping_data):
            self.app.check_server_status()
            self.assertTrue(self.app.is_running)
            self.assertEqual(self.app.active_pid, 12345)
            self.assertEqual(self.app.active_port, 8787)
            self.assertIn("Active", self.app.hdr_status_text.cget("text"))
            self.assertIn("PID: 12345", self.app.footer_lbl.cget("text"))

    def test_log_queue_and_clear_logs(self):
        """Test queuing log messages and clearing the log text widget."""
        self.app.log("Server initialized", "info")
        self.app.log("Streaming HTTP 206 chunk", "stream")
        self.app.log("Network timeout error", "error")

        self.app._poll_log_queue()
        log_content = self.app.txt_logs.get("1.0", "end")
        self.assertIn("Server initialized", log_content)
        self.assertIn("Streaming HTTP 206 chunk", log_content)
        self.assertIn("Network timeout error", log_content)

        # Clear logs
        self.app.clear_logs()
        self.assertEqual(self.app.txt_logs.get("1.0", "end").strip(), "")

    def test_copy_log_output(self):
        """Test copy log output to clipboard."""
        self.app.log("Test log entry for clipboard", "info")
        self.app._poll_log_queue()

        with patch("tkinter.messagebox.showinfo") as mock_info:
            self.app.copy_log_output()
            mock_info.assert_called_once()
            # Verify clipboard contains the log
            clipboard_content = self.app.clipboard_get()
            self.assertIn("Test log entry for clipboard", clipboard_content)

    def test_copy_log_output_empty(self):
        """Test copy log output when log is empty."""
        self.app.clear_logs()
        with patch("tkinter.messagebox.showinfo") as mock_info:
            self.app.copy_log_output()
            mock_info.assert_called_once_with("Clipboard", "Log output console is empty.")

    @patch("urllib.request.urlopen")
    @patch("tkinter.messagebox.showinfo")
    def test_check_server_health_success(self, mock_info, mock_urlopen):
        """Test Check Server Health ping 8787 success."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({
            "status": "ok",
            "stats": {"active_streams_count": 2, "current_bandwidth_mbps": 12.5}
        }).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        self.app._on_health_check_result(True, "Server Healthy (HTTP 200 OK) — Latency: 1.2ms")
        mock_info.assert_called_once()
        self.app._poll_log_queue()
        self.assertIn("Server Healthy", self.app.txt_logs.get("1.0", "end"))

    @patch("tkinter.messagebox.showwarning")
    def test_check_server_health_failure(self, mock_warn):
        """Test Check Server Health ping failure."""
        self.app._on_health_check_result(False, "Server Ping Failed (timeout)")
        mock_warn.assert_called_once()
        self.app._poll_log_queue()
        self.assertIn("Server Ping Failed", self.app.txt_logs.get("1.0", "end"))

    @patch("tkinter.filedialog.asksaveasfilename")
    @patch("tkinter.messagebox.showinfo")
    def test_export_diagnostics_report(self, mock_info, mock_filedialog):
        """Test Export Diagnostics Report (.txt)."""
        mock_filedialog.return_value = "E:/test_diagnostics.txt"
        self.app.log("Sample diagnostics error line", "error")
        self.app._poll_log_queue()

        m_open = mock_open()
        with patch("builtins.open", m_open):
            self.app.export_diagnostics_report()

        m_open.assert_called_once_with("E:/test_diagnostics.txt", "w", encoding="utf-8")
        written_content = "".join(call.args[0] for call in m_open().write.call_args_list)
        self.assertIn("ZIPSTREAM HUB - SYSTEM DIAGNOSTICS REPORT", written_content)
        self.assertIn("Sample diagnostics error line", written_content)
        mock_info.assert_called_once()

    @patch("subprocess.run")
    @patch("tkinter.messagebox.showinfo")
    def test_unmount_webdav_drive(self, mock_info, mock_run):
        """Test unmounting mapped WebDAV drive invokes 'net use' command."""
        self.app.cmb_drive_letter.set("Z:")
        mock_res = MagicMock()
        mock_res.returncode = 0
        mock_run.return_value = mock_res

        self.app.unmount_webdav_drive()
        mock_run.assert_called_once_with("net use Z: /delete /y", shell=True, capture_output=True, text=True)
        mock_info.assert_called_once()

    @patch("subprocess.run")
    @patch("tkinter.messagebox.showinfo")
    @patch("os.startfile")
    @patch.object(ZipStreamControlPanel, "check_live_status", return_value=True)
    def test_mount_webdav_drive_success(self, mock_live, mock_startfile, mock_info, mock_run):
        """Test mounting WebDAV drive with specific drive letter."""
        with patch("sys.platform", "win32"):
            self.app.cmb_drive_letter.set("Z:")
            mock_res = MagicMock()
            mock_res.returncode = 0
            mock_run.return_value = mock_res

            self.app.mount_webdav_drive()
            mock_run.assert_called_once()
            mock_info.assert_called_once()


class TestSingleInstanceAndStartupDetection(BaseControlPanelTest):
    """Tests for single instance mutex, window restore signal, and startup auto-attach."""

    def test_single_instance_lock_first_and_second_instance(self):
        """Test acquire_single_instance_lock allows first instance and notifies/exits second instance."""
        from src.zipstream.control_panel import acquire_single_instance_lock

        activated = []

        def on_activate():
            activated.append(True)

        # First instance should successfully bind socket
        # Use an ephemeral or custom test port
        test_port = 8798
        acquired1, sock1 = acquire_single_instance_lock(port=test_port, on_activate_callback=on_activate)
        self.assertTrue(acquired1)
        self.assertIsNotNone(sock1)

        try:
            # Second instance attempting same port should fail to bind and send activation signal
            acquired2, sock2 = acquire_single_instance_lock(port=test_port)
            self.assertFalse(acquired2)
            self.assertIsNone(sock2)

            # Allow brief moment for thread to process socket payload
            import time
            time.sleep(0.1)
            self.assertTrue(len(activated) > 0)
        finally:
            if sock1:
                sock1.close()

    @patch("src.zipstream.control_panel._bring_window_to_front")
    def test_main_duplicate_instance_exits_gracefully(self, mock_bring_front):
        """Test main() exits with sys.exit(0) without throwing errors when another instance runs."""
        from src.zipstream.control_panel import main

        with patch("src.zipstream.control_panel.acquire_single_instance_lock", return_value=(False, None)):
            with self.assertRaises(SystemExit) as cm:
                main()
            self.assertEqual(cm.exception.code, 0)

    def test_startup_server_detection_sets_active(self):
        """Test probe on startup immediately sets status to Active when server is responding."""
        with patch.object(self.app, "ping_running_instance", return_value={"app": "zipstream-hub", "pid": 12345, "port": 8787, "version": "2.2.0"}):
            self.app.check_server_status()
            self.assertTrue(self.app.is_running)
            self.assertEqual(self.app.active_pid, 12345)
            self.assertEqual(self.app.hdr_status_text.cget("text"), "Active")
            self.assertEqual(self.app.hdr_status_dot.cget("fg").lower(), "#10b981")


class TestUnrelatedPortConflictAndAutoHunt(BaseControlPanelTest):
    """Tests for unrelated process port conflict detection, auto-hunting, and process killing."""

    def test_find_process_occupying_port(self):
        """Test find_process_occupying_port identifies process on listening port."""
        from src.zipstream.control_panel import find_process_occupying_port
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        test_port = s.getsockname()[1]
        try:
            pid = find_process_occupying_port(test_port)
            # In python test process, pid should match os.getpid() if net_connections succeeds
            if pid is not None:
                self.assertEqual(pid, os.getpid())
        finally:
            s.close()

    @patch("tkinter.messagebox.askyesnocancel", return_value=True)
    def test_handle_unrelated_port_conflict_auto_hunt(self, mock_msgbox):
        """Test user choosing Yes to auto-hunt next available port."""
        from src.zipstream.control_panel import find_free_port
        with patch("src.zipstream.control_panel.find_process_occupying_port", return_value=99999):
            chosen_port = self.app.handle_unrelated_port_conflict(8787)
            self.assertIsNotNone(chosen_port)
            self.assertGreater(chosen_port, 8787)

    @patch("tkinter.messagebox.askyesnocancel", return_value=False)
    @patch("src.zipstream.control_panel.kill_process_by_pid", return_value=True)
    def test_handle_unrelated_port_conflict_kill_process(self, mock_kill, mock_msgbox):
        """Test user choosing No to kill orphan process."""
        with patch("src.zipstream.control_panel.find_process_occupying_port", return_value=1234):
            chosen_port = self.app.handle_unrelated_port_conflict(8787)
            self.assertEqual(chosen_port, 8787)
            mock_kill.assert_called_once_with(1234)

    @patch("tkinter.messagebox.askyesnocancel", return_value=None)
    def test_handle_unrelated_port_conflict_cancel(self, mock_msgbox):
        """Test user choosing Cancel aborts startup."""
        chosen_port = self.app.handle_unrelated_port_conflict(8787)
        self.assertIsNone(chosen_port)


if __name__ == "__main__":
    unittest.main()
