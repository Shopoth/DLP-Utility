from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import os
import sys
import json
from queue import Queue
from .job_manager import JobManager
from .system_info import get_system_stats


def resource_path(relative_path):
    base_path = getattr(sys, '_MEIPASS', os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
    return os.path.join(base_path, relative_path)


app = FastAPI()
STATIC_DIR = resource_path('')

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

mgr = JobManager()


@app.get('/')
def index():
    return FileResponse(resource_path('dashboard.html'))


@app.get('/queue')
def queue_page():
    return FileResponse(resource_path('queue.html'))


@app.get('/settings')
def settings_page():
    return FileResponse(resource_path('settings.html'))


@app.post('/api/download')
async def api_download(request: Request):
    body = await request.json()
    url = body.get('url')
    if not url:
        return JSONResponse({'error': 'missing url'}, status_code=400)
    job = mgr.add_job(url, body)
    return JSONResponse(job)


@app.get('/api/jobs')
def api_jobs():
    return JSONResponse({'jobs': mgr.get_jobs()})


@app.post('/api/jobs/{job_id}/{action}')
def api_job_action(job_id: str, action: str):
    ok = mgr.action_job(job_id, action)
    return JSONResponse({'ok': ok})


@app.post('/api/jobs/pause-all')
def api_pause_all():
    mgr.pause_all()
    return JSONResponse({'ok': True})


@app.post('/api/jobs/cancel-all')
def api_cancel_all():
    mgr.cancel_all()
    return JSONResponse({'ok': True})


@app.get('/api/system')
def api_system_stats():
    """Get system stats: CPU, memory, disk."""
    download_dir = mgr.settings.get('download_dir') or os.path.expanduser('~')
    stats = get_system_stats(download_dir)
    return JSONResponse(stats)


@app.api_route('/api/browse', methods=['GET', 'POST'])
def api_browse():
    """Open folder browser dialog for selecting download directory."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        
        # Create a minimal Tk window
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        
        # Open directory chooser dialog
        path = filedialog.askdirectory(
            title='Select Download Directory',
            mustexist=False
        )
        
        root.destroy()
        
        if path:
            return JSONResponse({'path': path})
        else:
            return JSONResponse({'path': ''})
    except Exception as e:
        # Return error details so the frontend can surface a helpful message
        print(f'Browse dialog error: {e}')
        return JSONResponse({'path': '', 'error': str(e)})


@app.api_route('/api/browse-file', methods=['GET', 'POST'])
def api_browse_file():
    """Open file browser dialog for cookies file."""
    try:
        import tkinter as tk
        from tkinter import filedialog
        root = tk.Tk()
        root.withdraw()
        path = filedialog.askopenfilename(
            title='Select Cookies File',
            filetypes=[('All Files', '*.*'), ('Text Files', '*.txt')]
        )
        root.destroy()
        if path:
            return JSONResponse({'path': path})
    except Exception as e:
        print(f'Browse file dialog error: {e}')
        return JSONResponse({'path': '', 'error': str(e)})
    
    return JSONResponse({'path': ''})


@app.get('/api/settings')
def api_get_settings():
    return JSONResponse(mgr.get_settings())


@app.post('/api/settings')
async def api_post_settings(request: Request):
    body = await request.json()
    mgr.save_settings(body)
    return JSONResponse({'ok': True})


@app.get('/api/check')
def api_check():
    return JSONResponse(mgr.check_deps())


@app.get('/app_icon.ico')
def app_icon():
    return FileResponse(resource_path('app_icon.ico'))


@app.get('/favicon.ico')
def favicon():
    return FileResponse(resource_path('app_icon.ico'))


def event_stream(q: Queue):
    try:
        while True:
            payload = q.get()
            if payload is None:
                break
            yield payload.encode()
    finally:
        mgr.unsubscribe(q)


@app.get('/api/events')
def sse_events():
    q = Queue()
    mgr.subscribe(q)
    return StreamingResponse(event_stream(q), media_type='text/event-stream')


if __name__ == '__main__':
    import uvicorn
    uvicorn.run('backend.main:app', host='127.0.0.1', port=8000, reload=False)
