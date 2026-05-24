# DLP-Utility (yt-dlp Desktop UI)

This project wraps your existing HTML UI with a small FastAPI backend and a PyWebView launcher so you can build a native Windows exe without Electron.

Quick start (dev):

1. Create a virtualenv and install dependencies:

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

2. Run the app:

```bash
python launcher.py
```


Packaging to single EXE (Windows):

Two options:

- Browser-based (recommended, minimal): the launcher will open the default browser if `pywebview` is not available. Bundle the backend and HTML and the user will get a native-feeling app that opens the browser on launch.

```bash
pip install pyinstaller
python -m PyInstaller --noconfirm --onefile \
  --add-data "dashboard.html;." \
  --add-data "queue.html;." \
  --add-data "settings.html;." \
  --add-data "backend;backend" \
  launcher.py
```

If your system `py` launcher points to Python 3.14, use `python` instead, or activate the project virtual environment first.

A convenient build helper script is also included: `build_exe.bat`.

- Native window (pywebview): requires `pywebview` and on Windows the `pythonnet` binary dependency. Installing `pythonnet` may require Visual Studio build tools unless a matching wheel is available. If you can install `pywebview` successfully, the same `python -m PyInstaller` command above will create an EXE that uses a native window.

Notes:
- The backend serves the HTML files and provides the `/api/*` endpoints the UI expects.
- `yt-dlp` will be used either via the `yt_dlp` Python package or the `yt-dlp` executable if the package is not available.
- The browse dialogs use `tkinter` so packaging should include the standard library GUI support.
