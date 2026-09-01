"""
Global pytest fixtures and configuration for ZipStreamHub tests.
Ensures webbrowser.open, subprocess.Popen, os.startfile, and GUI popups
are universally mocked during test execution to prevent browser tabs,
external players, or OS dialogs from opening on developer machines.
"""

from unittest.mock import MagicMock, patch
import pytest


@pytest.fixture(autouse=True)
def guard_system_launchers(monkeypatch):
    """
    Auto-used fixture across all test suites ensuring no real processes
    or browser tabs spawn during test runs.
    """
    mock_browser = MagicMock(return_value=True)
    mock_popen = MagicMock()
    mock_startfile = MagicMock()

    monkeypatch.setattr("webbrowser.open", mock_browser, raising=False)
    monkeypatch.setattr("os.startfile", mock_startfile, raising=False)
