import threading
import uuid
import shutil
import platform
import subprocess
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

try:
    from yt_dlp import YoutubeDL
    _HAS_YTDLP_PY = True
except Exception:
    _HAS_YTDLP_PY = False


class JobManager:
    def __init__(self):
        self.jobs = {}
        self.lock = threading.Lock()
        self.listeners = []
        self.executor = ThreadPoolExecutor(max_workers=4)
        self.settings = {
            'download_dir': '',
            'filename_template': '%(title)s [%(id)s].%(ext)s',
            'overwrite': False,
            'max_rate': 0,
            'concurrent': 2,
            'cookies_file': '',
            'embed_metadata': False,
            'write_subtitles': False,
            'embed_thumbnail': False,
            'recode_video': False,
        }
        # Persisted settings path in the user's home directory so the
        # selected download directory survives app restarts (works for
        # frozen executables as well).
        try:
            self._config_path = Path.home() / '.dlputility_settings.json'
            if self._config_path.exists():
                with self._config_path.open('r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.settings.update(data)
        except Exception:
            pass

    def _emit(self, event_name, data):
        payload = f"event: {event_name}\n"
        payload += f"data: {data}\n\n"
        with self.lock:
            for q in list(self.listeners):
                try:
                    q.put(payload)
                except Exception:
                    pass

    def subscribe(self, queue):
        with self.lock:
            self.listeners.append(queue)
            for job in self.jobs.values():
                try:
                    payload = f"event: job_update\n"
                    payload += f"data: {self._serialize(job)}\n\n"
                    queue.put(payload)
                except Exception:
                    pass

    def unsubscribe(self, queue):
        with self.lock:
            if queue in self.listeners:
                self.listeners.remove(queue)

    def add_job(self, url, opts):
        job_id = str(uuid.uuid4())
        job = {
            'id': job_id,
            'url': url,
            'title': url,
            'status': 'pending',
            'progress': 0.0,
            'speed': None,
            'eta': None,
            'size': None,
            'size_bytes': None,
            'size_mb': None,
            'downloaded_bytes': 0,
            'downloaded_mb': None,
            'format': None,
            'resolution': None,
            'error': None,
        }
        with self.lock:
            self.jobs[job_id] = job
        self._emit('job_update', self._serialize(job))
        # schedule
        self.executor.submit(self._run_job, job_id, url, opts)
        return job

    def _serialize(self, job):
        return json.dumps(job)

    def _build_ydl_opts(self, url, opts):
        """Build yt-dlp options from user selections."""
        outtmpl = opts.get('output_dir') or self.settings.get('download_dir') or '.'
        filename_template = opts.get('filename_template') or self.settings.get('filename_template')
        
        # Create output directory if it doesn't exist
        Path(outtmpl).mkdir(parents=True, exist_ok=True)
        
        ydl_opts = {
            'outtmpl': f"{outtmpl}/{filename_template}",
            'noplaylist': False,
            'quiet': False,
            'no_warnings': False,
        }
        
        fmt = opts.get('format', 'best')
        quality = opts.get('quality', 'best')
        ffmpeg_available = shutil.which('ffmpeg') is not None
        
        # Build format string based on selection
        if fmt == 'best':
            # Video + Audio merge - prefer MP4 container for merged output
            if quality == 'best':
                ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best'
            elif quality == '2160':
                ydl_opts['format'] = 'bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=2160]+bestaudio/best'
            elif quality == '1080':
                ydl_opts['format'] = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best'
            elif quality == '720':
                ydl_opts['format'] = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best'
            else:
                ydl_opts['format'] = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best'
            if ffmpeg_available:
                ydl_opts['merge_output_format'] = 'mp4'
        elif fmt == 'mp4':
            if not ffmpeg_available:
                # Without ffmpeg, prefer a single-file MP4 to avoid merge failures.
                ydl_opts['format'] = 'best[ext=mp4]/best'
            else:
                if quality == 'best':
                    ydl_opts['format'] = 'best[ext=mp4]/bestvideo+bestaudio/best'
                elif quality == '2160':
                    ydl_opts['format'] = 'bestvideo[height<=2160][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=2160]+bestaudio/best'
                elif quality == '1080':
                    ydl_opts['format'] = 'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=1080]+bestaudio/best'
                elif quality == '720':
                    ydl_opts['format'] = 'bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/bestvideo[height<=720]+bestaudio/best'
                else:
                    ydl_opts['format'] = 'best[ext=mp4]/bestvideo+bestaudio/best'
                # Prefer MP4 container when merging/remuxing
                ydl_opts['merge_output_format'] = 'mp4'
        elif fmt == 'mkv':
            if not ffmpeg_available:
                ydl_opts['format'] = 'best'
            else:
                if quality == 'best':
                    ydl_opts['format'] = 'bestvideo+bestaudio/best'
                elif quality == '2160':
                    ydl_opts['format'] = 'bestvideo[height<=2160]+bestaudio/best'
                elif quality == '1080':
                    ydl_opts['format'] = 'bestvideo[height<=1080]+bestaudio/best'
                elif quality == '720':
                    ydl_opts['format'] = 'bestvideo[height<=720]+bestaudio/best'
                else:
                    ydl_opts['format'] = 'bestvideo+bestaudio/best'
                # Prefer MKV container when merging/remuxing
                ydl_opts['merge_output_format'] = 'mkv'
        elif fmt == 'mp3':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [
                {
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }
            ]
        
        # Apply settings
        if self.settings.get('embed_metadata'):
            if 'postprocessors' not in ydl_opts:
                ydl_opts['postprocessors'] = []
            ydl_opts['postprocessors'].append({'key': 'FFmpegMetadata'})
        
        if self.settings.get('write_subtitles'):
            ydl_opts['writesubtitles'] = True
            ydl_opts['subtitlesformat'] = 'vtt'
        
        if self.settings.get('embed_thumbnail'):
            ydl_opts['writethumbnail'] = True
            if 'postprocessors' not in ydl_opts:
                ydl_opts['postprocessors'] = []
            ydl_opts['postprocessors'].append({'key': 'EmbedThumbnail'})
        
        if self.settings.get('recode_video'):
            if 'postprocessors' not in ydl_opts:
                ydl_opts['postprocessors'] = []
            ydl_opts['postprocessors'].append({
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            })
        
        # Proxy support
        if self.settings.get('proxy'):
            ydl_opts['proxy'] = self.settings.get('proxy')
        
        # Rate limiting
        if self.settings.get('max_rate') and self.settings.get('max_rate') > 0:
            ydl_opts['ratelimit'] = int(self.settings.get('max_rate') * 1024 * 1024)
        
        return ydl_opts

    def _run_job(self, job_id, url, opts):
        job = self.jobs[job_id]
        job['status'] = 'downloading'
        self._emit('job_update', self._serialize(job))

        try:
            ydl_opts = self._build_ydl_opts(url, opts)
            ydl_opts['progress_hooks'] = [lambda d: self._progress_hook(job_id, d)]
            
            if _HAS_YTDLP_PY:
                with YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    job['title'] = info.get('title') or job['title']
                    # Populate final metadata if available
                    try:
                        job['format'] = info.get('format') or job.get('format')
                        if info.get('height'):
                            job['resolution'] = f"{info.get('height')}p"
                        else:
                            rfs = info.get('requested_formats') or info.get('formats')
                            if isinstance(rfs, list) and len(rfs) > 0:
                                for rf in rfs:
                                    if rf.get('height'):
                                        job['resolution'] = f"{rf.get('height')}p"
                                        break
                        # If extraction produced multiple requested formats (video+audio)
                        # and the final container is MKV, prefer showing the video stream
                        # as the job format and compute combined sizes for display.
                        try:
                            rfs = info.get('requested_formats') or info.get('formats')
                            # Treat any multiple requested formats as a merged video+audio
                            if isinstance(rfs, list) and len(rfs) > 1:
                                video_rf = None
                                audio_rf = None
                                for rf in rfs:
                                    vcodec = rf.get('vcodec')
                                    acodec = rf.get('acodec')
                                    # Heuristic: video entries usually have a height or a vcodec
                                    if (vcodec and vcodec != 'none') or rf.get('height'):
                                        if not video_rf:
                                            video_rf = rf
                                    if acodec and acodec != 'none' and (not rf.get('height')):
                                        if not audio_rf:
                                            audio_rf = rf

                                # fallback heuristics
                                if not video_rf:
                                    for rf in rfs:
                                        if rf.get('height'):
                                            video_rf = rf
                                            break
                                if not audio_rf:
                                    for rf in rfs:
                                        if rf.get('acodec') and rf.get('acodec') != 'none':
                                            audio_rf = rf
                                            break

                                # Use video stream extension/format as the displayed format
                                if video_rf:
                                    job['format'] = video_rf.get('ext') or video_rf.get('format') or job.get('format')

                                # Compute sizes (prefer explicit filesize, fall back to approx)
                                def _size_of(r):
                                    if not r:
                                        return 0
                                    return r.get('filesize') or r.get('filesize_approx') or 0

                                vbytes = _size_of(video_rf)
                                abytes = _size_of(audio_rf)
                                total = (vbytes or 0) + (abytes or 0)
                                if total:
                                    job['video_size_bytes'] = vbytes
                                    job['audio_size_bytes'] = abytes
                                    job['size_bytes'] = total
                                    job['video_size_mb'] = f"{(vbytes or 0)/1024/1024:.2f} MB"
                                    job['audio_size_mb'] = f"{(abytes or 0)/1024/1024:.2f} MB"
                                    job['size_mb'] = f"{total/1024/1024:.2f} MB"
                        except Exception:
                            pass
                    except Exception:
                        pass
            else:
                # Fallback to subprocess
                cmd = ['yt-dlp', url, '-o', ydl_opts['outtmpl']]
                # format
                if 'format' in ydl_opts:
                    cmd.extend(['-f', ydl_opts['format']])
                # merge output format (container preference)
                if 'merge_output_format' in ydl_opts:
                    cmd.extend(['--merge-output-format', ydl_opts['merge_output_format']])
                # proxy
                if 'proxy' in ydl_opts:
                    cmd.extend(['--proxy', ydl_opts['proxy']])
                # cookies file
                if self.settings.get('cookies_file'):
                    cmd.extend(['--cookies', self.settings.get('cookies_file')])
                # write subtitles
                if ydl_opts.get('writesubtitles'):
                    cmd.append('--write-subs')
                # write thumbnail
                if ydl_opts.get('writethumbnail'):
                    cmd.append('--write-thumbnail')
                # rate limit (yt-dlp CLI uses --limit-rate)
                if ydl_opts.get('ratelimit'):
                    cmd.extend(['--limit-rate', str(ydl_opts.get('ratelimit'))])

                subprocess.check_call(cmd)
                job['title'] = url
            
            job['status'] = 'done'
            job['progress'] = 100.0
        except Exception as e:
            job['status'] = 'error'
            job['error'] = str(e)
        
        self._emit('job_update', self._serialize(job))

    def _progress_hook(self, job_id, d):
        job = self.jobs.get(job_id)
        if not job:
            return
        if d.get('status') == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or job.get('size_bytes') or 0
            downloaded = d.get('downloaded_bytes') or 0
            job['progress'] = (downloaded / total * 100) if total else 0.0
            speed = d.get('speed') or 0
            job['speed'] = f"{speed/1024/1024:.2f} MB/s" if speed else None
            job['eta'] = f"{int(d.get('eta') or 0)}s" if d.get('eta') else None
            job['title'] = d.get('_filename') or d.get('filename') or job['title']
            # human-friendly total size
            try:
                if total:
                    job['size'] = self._human_size(total)
                    job['size_bytes'] = total
                    job['size_mb'] = f"{total/1024/1024:.2f} MB"
                # current downloaded bytes
                job['downloaded_bytes'] = downloaded
                job['downloaded_mb'] = f"{downloaded/1024/1024:.2f} MB"
            except Exception:
                pass

            # If this is a requested_formats video+audio download,
            # compute and expose per-stream totals and current progress.
            try:
                info = d.get('info_dict') or {}
                rfs = info.get('requested_formats') or info.get('formats')
                if isinstance(rfs, list) and len(rfs) > 1:
                    def _size_of(r):
                        if not r:
                            return 0
                        return r.get('filesize') or r.get('filesize_approx') or 0

                    video_rf = None
                    audio_rf = None
                    for rf in rfs:
                        if rf.get('height') or (rf.get('vcodec') and rf.get('vcodec') != 'none'):
                            if not video_rf:
                                video_rf = rf
                        if rf.get('acodec') and rf.get('acodec') != 'none' and not rf.get('height'):
                            if not audio_rf:
                                audio_rf = rf

                    if not video_rf:
                        for rf in rfs:
                            if rf.get('height'):
                                video_rf = rf
                                break
                    if not audio_rf:
                        for rf in rfs:
                            if rf.get('acodec') and rf.get('acodec') != 'none':
                                audio_rf = rf
                                break

                    vbytes = _size_of(video_rf)
                    abytes = _size_of(audio_rf)
                    combined_est = (vbytes or 0) + (abytes or 0)

                    if vbytes or abytes:
                        job['video_size_bytes'] = vbytes or None
                        job['audio_size_bytes'] = abytes or None
                        job['video_size_mb'] = f"{(vbytes or 0)/1024/1024:.2f} MB" if vbytes else None
                        job['audio_size_mb'] = f"{(abytes or 0)/1024/1024:.2f} MB" if abytes else None

                    if not total and combined_est:
                        total = combined_est
                        job['size'] = self._human_size(total)
                        job['size_bytes'] = total
                        job['size_mb'] = f"{total/1024/1024:.2f} MB"
                        job['progress'] = (downloaded / total * 100) if total else job.get('progress', 0.0)

                    denom = total or combined_est or 0
                    if denom and combined_est and vbytes and abytes:
                        frac = downloaded / denom
                        vdown = min(vbytes, int(round(vbytes * frac)))
                        adown = min(abytes, int(round(abytes * frac)))
                        job['video_downloaded_bytes'] = vdown
                        job['audio_downloaded_bytes'] = adown
                        job['video_downloaded_mb'] = f"{vdown/1024/1024:.2f} MB"
                        job['audio_downloaded_mb'] = f"{adown/1024/1024:.2f} MB"
                    else:
                        job['video_downloaded_bytes'] = None
                        job['audio_downloaded_bytes'] = None
                        job['video_downloaded_mb'] = None
                        job['audio_downloaded_mb'] = None
            except Exception:
                pass

            # populate format and resolution from progress info if available
            info = d.get('info_dict') or {}
            try:
                if info:
                    if info.get('format'):
                        job['format'] = info.get('format')
                    if info.get('height'):
                        job['resolution'] = f"{info.get('height')}p"
                    else:
                        rfs = info.get('requested_formats') or info.get('formats')
                        if isinstance(rfs, list):
                            for rf in rfs:
                                if rf.get('height'):
                                    job['resolution'] = f"{rf.get('height')}p"
                                    break
            except Exception:
                pass

            self._emit('job_update', self._serialize(job))
        elif d.get('status') == 'finished':
            job['progress'] = 100.0
            # Ensure final sizes reflect completed download
            try:
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or job.get('size_bytes') or 0
                downloaded = d.get('downloaded_bytes') or total
                if total:
                    job['size'] = self._human_size(total)
                    job['size_bytes'] = total
                    job['size_mb'] = f"{total/1024/1024:.2f} MB"
                job['downloaded_bytes'] = downloaded
                job['downloaded_mb'] = f"{downloaded/1024/1024:.2f} MB"
            except Exception:
                pass

            try:
                # Populate requested_formats progress totals if available.
                info = d.get('info_dict') or {}
                rfs = info.get('requested_formats') or info.get('formats')
                if isinstance(rfs, list) and len(rfs) > 1:
                    def _size_of(r):
                        if not r:
                            return 0
                        return r.get('filesize') or r.get('filesize_approx') or 0

                    video_rf = None
                    audio_rf = None
                    for rf in rfs:
                        if rf.get('height') or (rf.get('vcodec') and rf.get('vcodec') != 'none'):
                            if not video_rf:
                                video_rf = rf
                        if rf.get('acodec') and rf.get('acodec') != 'none' and not rf.get('height'):
                            if not audio_rf:
                                audio_rf = rf

                    if not video_rf:
                        for rf in rfs:
                            if rf.get('height'):
                                video_rf = rf
                                break
                    if not audio_rf:
                        for rf in rfs:
                            if rf.get('acodec') and rf.get('acodec') != 'none':
                                audio_rf = rf
                                break

                    vbytes = _size_of(video_rf)
                    abytes = _size_of(audio_rf)
                    combined_est = (vbytes or 0) + (abytes or 0)

                    if vbytes or abytes:
                        job['video_size_bytes'] = vbytes or None
                        job['audio_size_bytes'] = abytes or None
                        job['video_size_mb'] = f"{(vbytes or 0)/1024/1024:.2f} MB" if vbytes else None
                        job['audio_size_mb'] = f"{(abytes or 0)/1024/1024:.2f} MB" if abytes else None

                    if not total and combined_est:
                        total = combined_est
                        job['size'] = self._human_size(total)
                        job['size_bytes'] = total
                        job['size_mb'] = f"{total/1024/1024:.2f} MB"

                    denom = total or combined_est or 0
                    if denom and combined_est and vbytes and abytes:
                        frac = downloaded / denom if denom else 0
                        vdown = min(vbytes, int(round(vbytes * frac)))
                        adown = min(abytes, int(round(abytes * frac)))
                        job['video_downloaded_bytes'] = vdown
                        job['audio_downloaded_bytes'] = adown
                        job['video_downloaded_mb'] = f"{(vdown or 0)/1024/1024:.2f} MB"
                        job['audio_downloaded_mb'] = f"{(adown or 0)/1024/1024:.2f} MB"
                    else:
                        job['video_downloaded_bytes'] = None
                        job['audio_downloaded_bytes'] = None
                        job['video_downloaded_mb'] = None
                        job['audio_downloaded_mb'] = None
            except Exception:
                pass
            self._emit('job_update', self._serialize(job))

    def _human_size(self, num, suffix="B"):
        try:
            for unit in ["","K","M","G","T","P"]:
                if abs(num) < 1024.0:
                    return f"{num:3.1f} {unit}{suffix}"
                num /= 1024.0
            return f"{num:.1f} P{suffix}"
        except Exception:
            return None

    def get_jobs(self):
        with self.lock:
            return list(self.jobs.values())

    def get_job(self, job_id):
        return self.jobs.get(job_id)

    def action_job(self, job_id, action):
        job = self.jobs.get(job_id)
        if not job:
            return False
        if action == 'pause':
            job['status'] = 'paused'
        elif action == 'resume':
            job['status'] = 'downloading'
        elif action == 'cancel':
            job['status'] = 'cancelled'
        self._emit('job_update', self._serialize(job))
        return True

    def pause_all(self):
        with self.lock:
            for j in self.jobs.values():
                if j['status'] == 'downloading':
                    j['status'] = 'paused'
                    self._emit('job_update', self._serialize(j))

    def cancel_all(self):
        with self.lock:
            for j in self.jobs.values():
                if j['status'] not in ('done','cancelled','error'):
                    j['status'] = 'cancelled'
                    self._emit('job_update', self._serialize(j))

    def get_settings(self):
        return self.settings

    def save_settings(self, s):
        self.settings.update(s)
        # persist to disk where possible
        try:
            if hasattr(self, '_config_path') and self._config_path:
                with self._config_path.open('w', encoding='utf-8') as f:
                    json.dump(self.settings, f, indent=2)
        except Exception:
            pass
        return True

    def check_deps(self):
        ytdlp_path = shutil.which('yt-dlp')
        ffmpeg_path = shutil.which('ffmpeg')
        return {
            'ytdlp': f"v{self._get_ytdlp_version()}" if (ytdlp_path or _HAS_YTDLP_PY) else None,
            'ffmpeg': 'found' if ffmpeg_path else None,
            'python': platform.python_version(),
        }

    def _get_ytdlp_version(self):
        try:
            if _HAS_YTDLP_PY:
                import yt_dlp
                return yt_dlp.__version__
            result = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True)
            return result.stdout.strip()
        except Exception:
            return 'unknown'
