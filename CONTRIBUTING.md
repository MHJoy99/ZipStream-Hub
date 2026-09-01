# Contributing to ZipStreamHub

Thank you for your interest in contributing to **ZipStreamHub**! We welcome contributions of all kinds: bug fixes, performance optimizations, new features, media player presets, documentation improvements, and tests.

---

## 🧭 Code of Conduct

By participating in this project, you agree to abide by the [Code of Conduct](CODE_OF_CONDUCT.md).

---

## 🛠️ Getting Started & Local Development

### 1. Fork and Clone
```bash
git clone https://github.com/ZipStreamHub/ZipStreamHub.git
cd ZipStreamHub
```

### 2. Create a Virtual Environment
```bash
# Python 3.9+ recommended
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate

# On Windows:
.venv\Scripts\activate
```

### 3. Install in Editable Mode with Dev Dependencies
```bash
pip install -e ".[dev]"
```

---

## 🧪 Running Tests & Quality Checks

Ensure all tests pass before submitting a pull request:

```bash
# Run test suite
pytest

# Run tests with code coverage report
pytest --cov=. --cov-report=term-missing

# Lint and check style
flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics
```

---

## 🚀 Branching & Commit Guidelines

- **Branch Naming**: Use descriptive prefixes:
  - `feat/feature-name`
  - `fix/bug-description`
  - `perf/optimization`
  - `docs/update-guide`
- **Commit Messages**: Write clear, concise, imperative commit messages:
  - `feat: add IINA media player auto-detection for macOS`
  - `fix: handle 64-bit ZIP data descriptor edge case`
  - `perf: expand sliding-window prefetcher memory pool`

---

## 📦 Pull Request Process

1. Ensure the test suite passes locally on your environment.
2. Update the `README.md` or `CHANGELOG.md` if your change introduces new features or alters user behavior.
3. Open a Pull Request referencing any related issues (e.g. `Fixes #12`).
4. Follow review discussions and make adjustments as requested.

Thank you for helping make ZipStreamHub the fastest remote archive streaming engine!
