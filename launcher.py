import inspect
import threading
import time
import sys
import os
import multiprocessing

def wait_for_server(url='http://127.0.0.1:8000/api/check', timeout=15.0):
    """Wait for the FastAPI server to be ready."""
    try:
        import requests
    except ModuleNotFoundError:
        print('ERROR: Missing dependency: requests')
        print('Install dependencies with `py -m pip install -r requirements.txt`.')
        return False

    start = time.time()
    while time.time() - start < timeout:
        try:
            r = requests.get(url, timeout=2.0)
            if r.status_code == 200:
                return True
        except Exception:
            pass
        time.sleep(0.2)
    return False


def start_server():
    """Start the FastAPI backend server."""
    log_file = os.path.join(os.path.expanduser('~'), 'DLP-Utility-error.log')

    try:
        import uvicorn
    except ModuleNotFoundError:
        msg = 'ERROR: Missing dependency: uvicorn'
        print(msg)
        print('Install dependencies with `py -m pip install -r requirements.txt`.')
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(msg + '\n')
        return

    try:
        # Ensure base path is in sys.path for module imports to work in frozen exe
        base_path = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(__file__)))
        if base_path not in sys.path:
            sys.path.insert(0, base_path)
        
        # Import the FastAPI app from the embedded backend package
        # This works in both development and frozen (exe) environments
        from backend import app as backend_app
    except ImportError as e:
        msg = f'ERROR: Failed to import backend app: {e}'
        print(msg)
        print(f'Searched in: {sys.path}')
        import traceback
        traceback.print_exc()
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(msg + '\n')
            traceback.print_exc(file=f)
        return
    except Exception as e:
        msg = f'ERROR: Failed to import backend app: {e}'
        print(msg)
        import traceback
        traceback.print_exc()
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(msg + '\n')
            traceback.print_exc(file=f)
        return

    try:
        print('Backend app loaded successfully, starting uvicorn server...')
        uvicorn.run(backend_app, host='127.0.0.1', port=8000, log_level='error')
    except Exception as e:
        msg = f'ERROR: Failed to start server: {e}'
        print(msg)
        import traceback
        traceback.print_exc()
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(msg + '\n')
            traceback.print_exc(file=f)


def resource_path(relative_path):
    base_path = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(__file__)))
    return os.path.join(base_path, relative_path)


def open_in_pywebview():
    """Try to open in pywebview native window."""
    try:
        import webview
        icon_path = resource_path('app_icon.ico')
        kwargs = {'width': 1200, 'height': 600}

        try:
            sig = inspect.signature(webview.create_window)
            if 'icon' in sig.parameters and os.path.exists(icon_path):
                kwargs['icon'] = icon_path
        except Exception:
            if os.path.exists(icon_path):
                kwargs['icon'] = icon_path

        webview.create_window('DLP-Utility', 'http://127.0.0.1:8000/', **kwargs)
        webview.start(debug=False)
        return True
    except TypeError as e:
        if 'unexpected keyword argument' in str(e) and 'icon' in str(e):
            try:
                webview.create_window('DLP-Utility', 'http://127.0.0.1:8000/', width=1200, height=600)
                webview.start(debug=False)
                return True
            except Exception as inner:
                print(f'PyWebView failed: {inner}')
                return False
        print(f'PyWebView failed: {e}')
        return False
    except Exception as e:
        print(f'PyWebView failed: {e}')
        return False


def open_in_browser():
    """Fallback: open in default browser."""
    import webbrowser
    try:
        webbrowser.open('http://127.0.0.1:8000/')
        print('Opening DLP-Utility in your default browser...')
        print('Keep this terminal window open while using the app.')
        # Keep the server running
        while True:
            time.sleep(1)
    except Exception as e:
        print(f'Failed to open browser: {e}')


def main():
    """Main entry point: start server, then open UI."""
    # Setup error logging
    log_file = os.path.join(os.path.expanduser('~'), 'DLP-Utility-error.log')
    
    try:
        print('Starting DLP-Utility...')
        
        # Start server in background
        server_thread = threading.Thread(target=start_server, daemon=True)
        server_thread.start()
        
        # Wait for server to be ready
        print('Waiting for backend to start...')
        if not wait_for_server():
            error_msg = 'ERROR: Backend failed to start. Check your Python environment and dependencies.'
            print(error_msg)
            with open(log_file, 'w') as f:
                f.write(error_msg + '\n')
                f.write('Check requirements.txt: fastapi, uvicorn[standard], yt-dlp, pywebview, requests, psutil\n')
            
            # Try to show error dialog
            try:
                import tkinter as tk
                from tkinter import messagebox
                root = tk.Tk()
                root.withdraw()
                messagebox.showerror('DLP-Utility Error', 'Backend failed to start.\n\nCheck ' + log_file + ' for details.')
                root.destroy()
            except:
                pass
            
            sys.exit(1)
        
        print('Backend ready. Opening DLP-Utility UI...')
        time.sleep(0.5)
        
        # Try pywebview first, fallback to browser
        if not open_in_pywebview():
            open_in_browser()
    
    except Exception as e:
        error_msg = f'ERROR: {e}'
        print(error_msg)
        import traceback
        with open(log_file, 'w') as f:
            f.write(error_msg + '\n')
            traceback.print_exc(file=f)
        sys.exit(1)


if __name__ == '__main__':
    try:
        multiprocessing.freeze_support()
    except Exception:
        pass
    
    # Wrap main in try-except to catch all errors
    try:
        main()
    except Exception as e:
        log_file = os.path.join(os.path.expanduser('~'), 'DLP-Utility-error.log')
        error_msg = f'FATAL ERROR: {e}'
        print(error_msg)
        import traceback
        with open(log_file, 'w') as f:
            f.write(error_msg + '\n\n')
            traceback.print_exc(file=f)
        
        # Try to show error dialog
        try:
            import tkinter as tk
            from tkinter import messagebox
            root = tk.Tk()
            root.withdraw()
            messagebox.showerror('DLP-Utility Fatal Error', 
                                f'An unexpected error occurred.\n\nSee {log_file} for details.')
            root.destroy()
        except:
            pass
        
        sys.exit(1)
