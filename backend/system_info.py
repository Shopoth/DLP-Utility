import psutil
import os


def get_disk_info(path=None):
    """Get disk usage info."""
    if not path or not os.path.exists(path):
        path = os.path.expanduser('~')
    try:
        usage = psutil.disk_usage(path)
        return {
            'total': usage.total,
            'used': usage.used,
            'free': usage.free,
            'percent': usage.percent,
        }
    except Exception:
        return {'total': 0, 'used': 0, 'free': 0, 'percent': 0}


def get_cpu_info():
    """Get CPU usage percentage."""
    try:
        return psutil.cpu_percent(interval=0.1)
    except Exception:
        return 0


def get_memory_info():
    """Get memory usage info."""
    try:
        mem = psutil.virtual_memory()
        return {
            'total': mem.total,
            'available': mem.available,
            'used': mem.used,
            'percent': mem.percent,
        }
    except Exception:
        return {'total': 0, 'available': 0, 'used': 0, 'percent': 0}


def get_system_stats(download_dir=None):
    """Get all system stats."""
    return {
        'disk': get_disk_info(download_dir),
        'cpu': get_cpu_info(),
        'memory': get_memory_info(),
    }
