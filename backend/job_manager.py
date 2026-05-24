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
            # per-stream progress (video+audio separate downloads)
            '_current_stream': None,      # 'video' | 'audio' | None
            'video_size_bytes': None,
            'video_size_mb': None,
            'audio_size_bytes': None,
            'audio_size_mb': None,
            'video_downloaded_bytes': None,
            'video_downloaded_mb': None,
            'audio_downloaded_bytes': None,
            'audio_downloaded_mb': None,
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
                        # Derive the displayed format label from what was actually requested,
                        # not from info['ext'] which reflects the raw stream ext before merging/post-processing.
                        fmt = opts.get('format', 'best')
                        if fmt == 'mp3':
                            job['format'] = 'mp3'
                        elif ydl_opts.get('merge_output_format'):
                            # Merged video+audio: use the container the user chose (mp4/mkv)
                            job['format'] = ydl_opts['merge_output_format']
                        else:
                            # Single-file download: info['ext'] is reliable here
                            job['format'] = info.get('ext') or fmt or job.get('format')
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

                                # (format label already set correctly above from merge_output_format)

                                # Compute sizes (prefer explicit filesize, fall back to approx)
                                def _size_of(r):
                                    if not r:
                                        return 0
                                    return r.get('filesize') or r.get('filesize_approx') or 0

                                vbytes = _size_of(video_rf)
                                abytes = _size_of(audio_rf)
                                # Prefer hook-tracked downloaded bytes (more accurate)
                                vbytes = job.get('video_downloaded_bytes') or vbytes
                                abytes = job.get('audio_downloaded_bytes') or abytes
                                total = (vbytes or 0) + (abytes or 0)
                                if total:
                                    job['video_size_bytes'] = vbytes or None
                                    job['audio_size_bytes'] = abytes or None
                                    job['video_downloaded_bytes'] = vbytes or None
                                    job['audio_downloaded_bytes'] = abytes or None
                                    job['video_size_mb'] = f"{(vbytes or 0)/1024/1024:.2f} MB" if vbytes else None
                                    job['audio_size_mb'] = f"{(abytes or 0)/1024/1024:.2f} MB" if abytes else None
                                    job['video_downloaded_mb'] = job['video_size_mb']
                                    job['audio_downloaded_mb'] = job['audio_size_mb']
                                    # Only set combined size_mb if hooks didn't already set a
                                    # larger/more accurate value (hooks sum actual downloaded bytes)
                                    existing = job.get('size_bytes') or 0
                                    if total > existing:
                                        job['size_bytes'] = total
                                        job['downloaded_bytes'] = total
                                        job['size_mb'] = f"{total/1024/1024:.2f} MB"
                                        job['downloaded_mb'] = job['size_mb']
                                        job['size'] = self._human_size(total)
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

        # ── helpers ────────────────────────────────────────────────────────────
        def _size_of(r):
            if not r:
                return 0
            return r.get('filesize') or r.get('filesize_approx') or 0

        def _identify_streams(info):
            """Return (video_rf, audio_rf) from requested_formats, or (None, None)."""
            rfs = info.get('requested_formats') or info.get('formats')
            if not isinstance(rfs, list) or len(rfs) < 2:
                return None, None
            video_rf = None
            audio_rf = None
            for rf in rfs:
                vcodec = rf.get('vcodec') or 'none'
                acodec = rf.get('acodec') or 'none'
                has_video = vcodec != 'none' or bool(rf.get('height'))
                has_audio = acodec != 'none'
                if has_video and not audio_rf and not (has_audio and not has_video):
                    if not video_rf:
                        video_rf = rf
                elif has_audio and not has_video:
                    if not audio_rf:
                        audio_rf = rf
            # fallbacks
            if not video_rf:
                for rf in rfs:
                    if rf.get('height') or (rf.get('vcodec') and rf.get('vcodec') != 'none'):
                        video_rf = rf
                        break
            if not audio_rf:
                for rf in rfs:
                    if rf.get('acodec') and rf.get('acodec') != 'none' and rf is not video_rf:
                        audio_rf = rf
                        break
            return video_rf, audio_rf

        # ── determine if this is a multi-stream (video+audio) download ─────────
        info = d.get('info_dict') or {}
        video_rf, audio_rf = _identify_streams(info)
        is_multi_stream = video_rf is not None and audio_rf is not None

        if d.get('status') == 'downloading':
            stream_total     = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            stream_downloaded = d.get('downloaded_bytes') or 0
            speed = d.get('speed') or 0
            job['speed'] = f"{speed/1024/1024:.2f} MB/s" if speed else None
            job['eta']   = f"{int(d.get('eta') or 0)}s" if d.get('eta') else None
            job['title'] = d.get('_filename') or d.get('filename') or job['title']

            if is_multi_stream:
                vbytes = _size_of(video_rf)
                abytes = _size_of(audio_rf)

                # Store individual stream sizes once we know them
                if vbytes:
                    job['video_size_bytes'] = vbytes
                    job['video_size_mb']    = f"{vbytes/1024/1024:.2f} MB"
                if abytes:
                    job['audio_size_bytes'] = abytes
                    job['audio_size_mb']    = f"{abytes/1024/1024:.2f} MB"

                # Detect which stream is currently being downloaded.
                # yt-dlp downloads video first, then audio.
                # We use the stream's total size vs what yt-dlp reports for
                # this hook call to figure out which stream is active.
                current_stream = job.get('_current_stream')

                if current_stream is None:
                    # First hook call — must be video (yt-dlp downloads video first)
                    current_stream = 'video'
                    job['_current_stream'] = 'video'
                # Stream switching is done exclusively in the 'finished' handler
                # to avoid false positives from size comparisons mid-download.

                if current_stream == 'video':
                    # Show: video_downloaded / video_total
                    job['video_downloaded_bytes'] = stream_downloaded
                    job['video_downloaded_mb']    = f"{stream_downloaded/1024/1024:.2f} MB"
                    # Use stream_total (from yt-dlp progress dict) as the authoritative video size
                    ref = stream_total or vbytes or 0
                    if ref:
                        job['video_size_bytes'] = ref
                        job['video_size_mb']    = f"{ref/1024/1024:.2f} MB"
                        job['size_bytes'] = ref
                        job['size_mb']    = f"{ref/1024/1024:.2f} MB"
                        job['size']       = self._human_size(ref)
                    # Audio not started yet — clear audio downloaded
                    job['audio_downloaded_bytes'] = None
                    job['audio_downloaded_mb']    = None
                    denom = ref or 1
                    job['progress'] = min(99.0, stream_downloaded / denom * 100) if denom else 0.0
                    job['downloaded_bytes'] = stream_downloaded
                    job['downloaded_mb']    = f"{stream_downloaded/1024/1024:.2f} MB"

                else:  # audio stream
                    # Video is fully downloaded; mark it complete
                    if vbytes:
                        job['video_downloaded_bytes'] = vbytes
                        job['video_downloaded_mb']    = f"{vbytes/1024/1024:.2f} MB"
                    job['audio_downloaded_bytes'] = stream_downloaded
                    job['audio_downloaded_mb']    = f"{stream_downloaded/1024/1024:.2f} MB"
                    # Use stream_total as authoritative audio size
                    ref = stream_total or abytes or 0
                    if ref:
                        job['audio_size_bytes'] = ref
                        job['audio_size_mb']    = f"{ref/1024/1024:.2f} MB"
                        job['size_bytes'] = ref
                        job['size_mb']    = f"{ref/1024/1024:.2f} MB"
                        job['size']       = self._human_size(ref)
                    denom = ref or 1
                    job['progress'] = min(99.0, stream_downloaded / denom * 100) if denom else 0.0
                    job['downloaded_bytes'] = stream_downloaded
                    job['downloaded_mb']    = f"{stream_downloaded/1024/1024:.2f} MB"

            else:
                # Single-stream download — straightforward
                job['_current_stream'] = None
                if stream_total:
                    job['size']       = self._human_size(stream_total)
                    job['size_bytes'] = stream_total
                    job['size_mb']    = f"{stream_total/1024/1024:.2f} MB"
                job['downloaded_bytes'] = stream_downloaded
                job['downloaded_mb']    = f"{stream_downloaded/1024/1024:.2f} MB"
                job['progress'] = (stream_downloaded / stream_total * 100) if stream_total else 0.0

            # format / resolution
            try:
                if info:
                    if info.get('ext'):
                        job['format'] = info.get('ext')
                    if info.get('height'):
                        job['resolution'] = f"{info.get('height')}p"
                    elif is_multi_stream and video_rf and video_rf.get('height'):
                        job['resolution'] = f"{video_rf.get('height')}p"
            except Exception:
                pass

            self._emit('job_update', self._serialize(job))

        elif d.get('status') == 'finished':
            # A single stream just finished downloading.
            # If multi-stream, wait for the hook that transitions to 'audio'
            # and then for the final 'finished' on the audio stream.
            # The safest approach: on every 'finished', check which stream
            # just completed, accumulate, and only mark job done in _run_job.

            finished_bytes = d.get('total_bytes') or d.get('downloaded_bytes') or 0

            if is_multi_stream:
                vbytes = _size_of(video_rf)
                abytes = _size_of(audio_rf)

                # Store stream sizes
                if vbytes:
                    job['video_size_bytes'] = vbytes
                    job['video_size_mb']    = f"{vbytes/1024/1024:.2f} MB"
                if abytes:
                    job['audio_size_bytes'] = abytes
                    job['audio_size_mb']    = f"{abytes/1024/1024:.2f} MB"

                current_stream = job.get('_current_stream')

                if current_stream == 'video' or current_stream is None:
                    # Video finished — mark it complete, switch to audio
                    ref = finished_bytes or vbytes or 0
                    job['video_downloaded_bytes'] = ref
                    job['video_downloaded_mb']    = f"{ref/1024/1024:.2f} MB"
                    if ref and not job.get('video_size_bytes'):
                        job['video_size_bytes'] = ref
                        job['video_size_mb']    = f"{ref/1024/1024:.2f} MB"
                    job['_current_stream'] = 'audio'
                    # Don't mark job progress 100 yet; audio still to come
                else:
                    # Audio finished — both streams done
                    ref = finished_bytes or abytes or 0
                    job['audio_downloaded_bytes'] = ref
                    job['audio_downloaded_mb']    = f"{ref/1024/1024:.2f} MB"
                    if ref and not job.get('audio_size_bytes'):
                        job['audio_size_bytes'] = ref
                        job['audio_size_mb']    = f"{ref/1024/1024:.2f} MB"

                    # Now set combined total size
                    vd = job.get('video_downloaded_bytes') or job.get('video_size_bytes') or 0
                    ad = job.get('audio_downloaded_bytes') or job.get('audio_size_bytes') or 0
                    combined = vd + ad
                    if combined:
                        job['size_bytes'] = combined
                        job['size_mb']    = f"{combined/1024/1024:.2f} MB"
                        job['size']       = self._human_size(combined)
                        job['downloaded_bytes'] = combined
                        job['downloaded_mb']    = f"{combined/1024/1024:.2f} MB"
                    job['progress'] = 100.0
            else:
                # Single stream finished
                job['progress'] = 100.0
                if finished_bytes:
                    job['size']       = self._human_size(finished_bytes)
                    job['size_bytes'] = finished_bytes
                    job['size_mb']    = f"{finished_bytes/1024/1024:.2f} MB"
                    job['downloaded_bytes'] = finished_bytes
                    job['downloaded_mb']    = f"{finished_bytes/1024/1024:.2f} MB"

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
            'ytdlp': self._get_ytdlp_version() if (ytdlp_path or _HAS_YTDLP_PY) else None,
            'ffmpeg': self._get_ffmpeg_version() if ffmpeg_path else None,
            'python': platform.python_version(),
        }

    def _get_ytdlp_version(self):
        try:
            if _HAS_YTDLP_PY:
                import yt_dlp.version as _v
                return _v.__version__
            result = subprocess.run(['yt-dlp', '--version'], capture_output=True, text=True)
            return result.stdout.strip()
        except Exception:
            try:
                import yt_dlp
                return getattr(yt_dlp, '__version__', None) or 'unknown'
            except Exception:
                return 'unknown'

    def _get_ffmpeg_version(self):
        try:
            result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
            first = result.stdout.splitlines()[0] if result.stdout else ''
            # "ffmpeg version 6.1.1 Copyright ..."
            parts = first.split()
            if len(parts) >= 3 and parts[1] == 'version':
                return parts[2]
            return 'installed'
        except Exception:
            return 'installed'
