# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [1.0.0] - 2026-09-02

### Added
- **Core Engine**: High-performance remote ZIP and ZIP64 binary parser with sub-2-second Central Directory inspection.
- **Sliding-Window Prefetcher**: Configurable 32MB read-ahead prefetching buffer with socket chunk slicing for zero-stall playback.
- **Streaming Server**: Multi-threaded HTTP 1.1 server supporting full RFC 7233 HTTP 206 byte-range negotiation, `Accept-Ranges: bytes`, and instant player seeks.
- **Media Player Integration**: Auto-detection and launch support for PotPlayer, MPV, VLC, and IINA across Windows, macOS, and Linux.
- **Modern Web Dashboard**: Responsive dark-mode web control panel with glassmorphism UI for stream monitoring and archive inspection.
- **Interactive CLI & Launcher**: Colorful terminal client (`cli.py` / `zipstream` command) and one-click batch launcher.
- **Docker Support**: Multi-stage lightweight headless container and `docker-compose.yml` for NAS and homelab deployment.
- **Standard Packaging**: Full PEP 517/621 `pyproject.toml` support and cross-platform GitHub Actions CI workflows.
