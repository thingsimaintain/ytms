from flask import Flask, render_template, request, redirect, url_for, jsonify, send_file, abort, session
from threading import Thread, Lock
import time
import uuid
import os
import logging
import tempfile
import shutil
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re

# Optional: Flask-Limiter for rate limiting
try:
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
except Exception:
    Limiter = None
    get_remote_address = None

from ytms.core import MusicDownloader

# Application setup
app = Flask(__name__)
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB (safety)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SECURE"] = os.environ.get("USE_HTTPS", "False").lower() in ("1","true","yes")
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY") or os.urandom(24)

# Rate limiter (optional if Flask-Limiter is installed)
if Limiter and get_remote_address:
    # Create limiter in a way that's compatible with different Flask-Limiter versions
    try:
        limiter = Limiter(key_func=get_remote_address, default_limits=["200 per hour"])
        # Preferred: use init_app if available
        limiter.init_app(app)
    except Exception:
        # Fallback to older constructor signature if necessary
        limiter = Limiter(app, key_func=get_remote_address, default_limits=["200 per hour"])
else:
    limiter = None

# In-memory stores (simple, not persistent)
results_cache = {}  # id -> result dict
queue = []  # list of result dicts
queue_lock = Lock()

# Job management (per-download job for packaging & user download)
job_store = {}  # job_id -> {created_at, dir, status, file_path, logs: []}
job_lock = Lock()
JOB_RETENTION = timedelta(hours=2)

status = {
    "running": False,
    "current": None,
    "message": "Idle",
    "active_job_id": None,  # Track currently active job for log filtering
}

# Allow overriding download path via UI (not used for job dirs in production)
download_path = None

logger = logging.getLogger("webapp")
logging.basicConfig(level=logging.INFO)
logger.setLevel(logging.INFO)
# Ensure root logger is at INFO level so our ListHandler receives messages
logging.getLogger().setLevel(logging.INFO)

# In-memory logs for UI (thread-safe ring buffer) - kept for backward compat
log_lines = []
log_lock = Lock()
MAX_LOG_LINES = 500
MAX_JOB_LOG_LINES = 200

class ListHandler(logging.Handler):
    def emit(self, record):
        try:
            msg = self.format(record)
            with log_lock:
                log_lines.append(msg)
                # Trim oldest lines if exceeded
                if len(log_lines) > MAX_LOG_LINES:
                    del log_lines[0: len(log_lines) - MAX_LOG_LINES]
            
            # Also store in active job's log buffer if available
            active_job = status.get("active_job_id")
            if active_job:
                with job_lock:
                    job = job_store.get(active_job)
                    if job and "logs" in job:
                        job["logs"].append(msg)
                        if len(job["logs"]) > MAX_JOB_LOG_LINES:
                            job["logs"].pop(0)
        except Exception:
            pass

list_handler = ListHandler()
formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
list_handler.setFormatter(formatter)
# Ensure handler captures INFO and above
list_handler.setLevel(logging.INFO)
# Attach handler to both the webapp logger and the ytms package logger and root logger
logging.getLogger('webapp').addHandler(list_handler)
logging.getLogger('ytms').addHandler(list_handler)
logging.getLogger().addHandler(list_handler)

md = MusicDownloader()

ALLOWED_QUERY_RE = re.compile(r'^[\w\d\s\-\.,!\'"()]{1,200}$')
ALLOWED_EXT = {'.mp3', '.m4a', '.flac', '.wav', '.ogg', '.aac'}


def safe_query(q: str) -> bool:
    if not q or len(q) > 200:
        return False
    # Basic whitelist
    return bool(ALLOWED_QUERY_RE.match(q))


def list_music_files(directory: str):
    p = Path(directory)
    files = [str(f) for f in p.iterdir() if f.is_file() and f.suffix.lower() in ALLOWED_EXT]
    logger.info("Found %d music files in %s: %s", len(files), directory, files)
    return files


def find_downloaded_files(job_dir: str, search_parent: bool = True):
    """Recursively search for audio files in job_dir and subdirectories."""
    p = Path(job_dir)
    found = []
    
    # First check job_dir itself
    for item in p.rglob("*"):
        if item.is_file() and item.suffix.lower() in ALLOWED_EXT:
            found.append(str(item))
    
    logger.info("Recursive search in %s found %d files: %s", job_dir, len(found), found)
    
    # If still nothing, check parent and common music dirs as fallback
    if not found and search_parent:
        # Check if ytms created files in parent temp or home directories
        home = Path.home()
        music_dir = home / "Music"
        if music_dir.exists():
            logger.info("Checking fallback music directory: %s", music_dir)
            for item in music_dir.rglob("*"):
                if item.is_file() and item.suffix.lower() in ALLOWED_EXT:
                    # Check if file was modified recently (within last 60 seconds)
                    if time.time() - item.stat().st_mtime < 60:
                        found.append(str(item))
                        logger.info("Found recent file in Music: %s", item)
    
    return found


def package_job_files(job_id: str, job_dir: str):
    # Try recursive search first
    files = find_downloaded_files(job_dir, search_parent=True)
    
    if not files:
        logger.warning("No music files found anywhere for job %s (searched: %s)", job_id, job_dir)
        # Try listing ALL files in temp dir recursively for debugging
        p = Path(job_dir)
        all_items = list(p.rglob("*"))
        logger.info("ALL items (recursive) in %s: %s", job_dir, [str(x) for x in all_items[:50]])
        return None
    
    # If files are outside job_dir, copy them in
    job_path = Path(job_dir)
    local_files = []
    for f in files:
        f_path = Path(f)
        if not f_path.is_relative_to(job_path):
            # File is outside our job dir, copy it in
            dest = job_path / f_path.name
            logger.info("Copying external file %s to %s", f, dest)
            shutil.copy2(f, dest)
            local_files.append(str(dest))
        else:
            local_files.append(f)
    
    if len(local_files) == 1:
        logger.info("Single file download for job %s: %s", job_id, local_files[0])
        return local_files[0]
    
    # Create zip for multiple files
    zip_path = os.path.join(job_dir, f"{job_id}.zip")
    logger.info("Creating zip for job %s with %d files", job_id, len(local_files))
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for f in local_files:
            zf.write(f, arcname=os.path.basename(f))
    return zip_path


def download_worker(items, job_id=None, target_path=None):
    """Background worker: downloads queued items sequentially into a job dir."""
    global status, job_store

    logger.info("Worker invoked for job %s", job_id)
    with job_lock:
        job = job_store.get(job_id)
        if job is None:
            logger.error("Job not found: %s", job_id)
            return
        job["status"] = "running"
        if "logs" not in job:
            job["logs"] = []

    status["running"] = True
    status["message"] = "Starting downloads..."
    status["active_job_id"] = job_id

    def status_cb(msg):
        status["message"] = msg
        logger.info("Status update for job %s: %s", job_id, msg)

    logger.info("Starting job %s with %d items into %s", job_id, len(items), target_path)

    for idx, item in enumerate(items):
        try:
            status["current"] = item.get("title", item.get("artist"))
            status["message"] = f"Downloading ({idx+1}/{len(items)})"
            logger.info("Job %s: downloading item %s", job_id, status["current"])

            # Ensure target directory exists
            try:
                os.makedirs(target_path, exist_ok=True)
            except Exception as e:
                logger.exception("Could not create target path %s for job %s: %s", target_path, job_id, e)
                status["message"] = f"Path error: {e}"
                with job_lock:
                    job_store.get(job_id, {})["status"] = "error"
                return

            md.download_item(item, download_path=target_path, logger=logger, status_callback=status_cb)

            # small delay to let UI catch up
            time.sleep(0.5)
        except Exception as e:
            logger.exception("Download error in job %s: %s", job_id, e)
            status["message"] = f"Error: {e}"
            with job_lock:
                job_store.get(job_id, {})["status"] = "error"
            time.sleep(2)

    # package files and mark job ready
    file_path = package_job_files(job_id, target_path)
    with job_lock:
        job = job_store.get(job_id)
        if job is not None:
            job["status"] = "done"
            job["file_path"] = file_path
            job["ready_at"] = datetime.now(timezone.utc)

    logger.info("Job %s completed; packaged file: %s", job_id, file_path)

    status["running"] = False
    status["current"] = None
    status["message"] = "Done"
    status["active_job_id"] = None


# Security headers
@app.after_request
def set_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    # Basic CSP: allow inline scripts for our polling code
    response.headers["Content-Security-Policy"] = "default-src 'self' https:; script-src 'self' https: 'unsafe-inline'; style-src 'self' https: 'unsafe-inline'"
    return response


@app.route("/")
def index():
    # Show main UI
    with queue_lock:
        q = list(queue)
    download_mode = session.get('download_mode', 'device')
    return render_template("index.html", results=None, queue=q, download_path=download_path, download_mode=download_mode)


@app.route("/search", methods=["POST"])
def search():
    if limiter:
        limiter.limit("30/minute")(lambda: None)()

    q = request.form.get("query", "").strip()
    if not safe_query(q):
        return render_template("index.html", results=None, error="Invalid query", queue=list(queue), download_path=download_path, query=q)

    try:
        results = md.search(q)
    except Exception as e:
        logger.exception("Search failed")
        return render_template("index.html", results=[], error=str(e), queue=list(queue), download_path=download_path, query=q)

    filtered = [r for r in results if r.get("resultType") in ["song", "album"]]

    # Cache the result objects with ids
    wrapped = []
    for r in filtered[:20]:
        rid = str(uuid.uuid4())
        results_cache[rid] = r
        display = {
            "id": rid,
            "title": r.get("title", r.get("artist")),
            "type": r.get("resultType"),
            "artist": (r.get("artists") and r.get("artists")[0]["name"]) or r.get("artist"),
        }
        wrapped.append(display)

    # Preserve download mode
    download_mode = request.form.get('download_mode', session.get('download_mode', 'device'))
    session['download_mode'] = download_mode
    
    return render_template("index.html", results=wrapped, queue=list(queue), download_path=download_path, query=q, download_mode=download_mode)


@app.route("/queue/add", methods=["POST"])
def add_to_queue():
    rid = request.form.get("result_id")
    query = request.form.get("query", "")
    if not rid or rid not in results_cache:
        return ("Not found", 404)

    item = results_cache[rid]
    with queue_lock:
        queue.append(item)
    
    # Rebuild results display from cache for current session
    wrapped = []
    for cached_id, cached_item in results_cache.items():
        display = {
            "id": cached_id,
            "title": cached_item.get("title", cached_item.get("artist")),
            "type": cached_item.get("resultType"),
            "artist": (cached_item.get("artists") and cached_item.get("artists")[0]["name"]) or cached_item.get("artist"),
        }
        wrapped.append(display)
    
    # Preserve download mode
    download_mode = request.form.get('download_mode', session.get('download_mode', 'device'))
    session['download_mode'] = download_mode
    
    return render_template("index.html", results=wrapped, queue=list(queue), download_path=download_path, query=query, download_mode=download_mode)


@app.route("/queue/remove", methods=["POST"])
def remove_from_queue():
    video_id = request.form.get("result_id")
    query = request.form.get("query", "")
    if not video_id:
        return ("Bad Request", 400)

    with queue_lock:
        # Remove item by matching videoId
        for i, it in enumerate(queue):
            if it.get("videoId") == video_id:
                queue.pop(i)
                logger.info("Removed item %s from queue", video_id)
                break
    
    # Rebuild results display from cache
    wrapped = []
    for cached_id, cached_item in results_cache.items():
        display = {
            "id": cached_id,
            "title": cached_item.get("title", cached_item.get("artist")),
            "type": cached_item.get("resultType"),
            "artist": (cached_item.get("artists") and cached_item.get("artists")[0]["name"]) or cached_item.get("artist"),
        }
        wrapped.append(display)
    
    # Preserve download mode
    download_mode = request.form.get('download_mode', session.get('download_mode', 'device'))
    session['download_mode'] = download_mode
    
    return render_template("index.html", results=wrapped, queue=list(queue), download_path=download_path, query=query, download_mode=download_mode)


@app.route("/set_path", methods=["POST"])
def set_path():
    global download_path
    path = request.form.get("path")
    if not path:
        return redirect(url_for("index"))

    # Validate path: avoid directory traversal; create only under tempdir or approved directories
    try:
        p = Path(path).expanduser().resolve()
    except Exception as e:
        return render_template("index.html", results=None, error=f"Invalid path: {e}", queue=list(queue), download_path=download_path)

    try:
        p.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return render_template("index.html", results=None, error=f"Could not create path: {e}", queue=list(queue), download_path=download_path)

    # For security, restrict to user-writable locations; here we just assign but in production enforce a whitelist
    download_path = str(p)
    return redirect(url_for("index"))


@app.route("/start", methods=["POST"])
def start_downloads():
    if limiter:
        limiter.limit("10/minute")(lambda: None)()

    with queue_lock:
        if not queue:
            return redirect(url_for("index"))
        items = list(queue)
        queue.clear()

    # Check download mode from session
    download_mode = session.get('download_mode', 'device')
    
    # Create a job dir for this batch
    job_id = str(uuid.uuid4())
    
    # Determine target path based on download mode
    if download_mode == 'server' and download_path:
        # Use server path, but create a subdirectory for this job
        target_path = os.path.join(download_path, f"ytmdl_{job_id}")
        job_dir = tempfile.mkdtemp(prefix=f"ytmdl_{job_id}_")  # Still need for packaging
    else:
        # Use temp directory for device downloads
        job_dir = tempfile.mkdtemp(prefix=f"ytmdl_{job_id}_")
        target_path = job_dir
    
    with job_lock:
        job_store[job_id] = {"created_at": datetime.now(timezone.utc), "dir": job_dir, "status": "queued", "file_path": None, "logs": [], "mode": download_mode}

    logger.info("Created job %s (items=%d) mode=%s target=%s", job_id, len(items), download_mode, target_path)

    # Start background thread
    t = Thread(target=download_worker, args=(items, job_id, target_path), daemon=True)
    t.start()

    # Mark status immediately so UI reflects running state
    status["running"] = True
    status["message"] = f"Job {job_id} started"
    status["current"] = items[0].get("title", items[0].get("artist")) if items else None
    with job_lock:
        job_store[job_id]["status"] = "running"

    # Return job id so client can poll/download
    return redirect(url_for("index"))


@app.route("/status")
def get_status():
    # Return simple JSON status for polling
    with job_lock:
        completed_jobs = [{"job_id": jid, "status": j.get("status"), "ready": bool(j.get("file_path")), "created_at": j.get("created_at").isoformat()} for jid, j in job_store.items()]

    result = {
        "running": status["running"],
        "current": status["current"],
        "message": status["message"],
        "queue_length": len(queue),
        "completed_jobs": completed_jobs,
        "logs_count": len(log_lines),
    }
    logger.debug("Status poll: running=%s, jobs=%d", result["running"], len(completed_jobs))
    return jsonify(result)


@app.route("/logs")
def get_logs():
    # Return logs for active job or most recent job only
    active_job = status.get("active_job_id")
    
    with job_lock:
        if active_job and active_job in job_store:
            # Return active job logs
            job = job_store[active_job]
            lines = job.get("logs", [])
        else:
            # Return most recent job logs
            if job_store:
                most_recent = max(job_store.items(), key=lambda x: x[1].get("created_at", datetime.min.replace(tzinfo=timezone.utc)))
                lines = most_recent[1].get("logs", [])
            else:
                lines = []
    
    return jsonify(lines[-200:])


@app.route("/quick", methods=["POST"])
def quick_download():
    if limiter:
        limiter.limit("5/minute")(lambda: None)()

    # Quick search and download first result
    q = request.form.get("query", "").strip()
    if not safe_query(q):
        return render_template("index.html", results=None, error="Invalid query", queue=list(queue), download_path=download_path)

    try:
        results = md.search(q)
    except Exception as e:
        logger.exception("Quick search failed")
        return render_template("index.html", results=None, error=str(e), queue=list(queue), download_path=download_path)

    valid = [r for r in results if r.get("resultType") in ["song", "album"]]
    if not valid:
        return render_template("index.html", results=None, error="No results found", queue=list(queue), download_path=download_path)

    selected = valid[0]

    # Create single-item job
    job_id = str(uuid.uuid4())
    job_dir = tempfile.mkdtemp(prefix=f"ytmdl_{job_id}_")
    with job_lock:
        job_store[job_id] = {"created_at": datetime.now(timezone.utc), "dir": job_dir, "status": "queued", "file_path": None, "logs": []}

    t = Thread(target=download_worker, args=([selected], job_id, job_dir), daemon=True)
    t.start()

    # Mark status immediately so UI reflects running state
    status["running"] = True
    status["message"] = f"Job {job_id} started"
    status["current"] = selected.get("title", selected.get("artist"))
    with job_lock:
        job_store[job_id]["status"] = "running"

    return redirect(url_for("index"))


@app.route('/download/<job_id>')
def download_job(job_id):
    # Provide the packaged file (single file or zip) for user download
    with job_lock:
        job = job_store.get(job_id)
        if not job:
            return ("Not found", 404)
        if job.get('status') != 'done' or not job.get('file_path'):
            return ("Not ready", 409)

        file_path = job.get('file_path')

    if not file_path or not os.path.exists(file_path):
        return ("File missing", 410)

    # Stream file as attachment
    filename = os.path.basename(file_path)
    return send_file(file_path, as_attachment=True, download_name=filename)


# Background cleanup thread to remove old job dirs
def cleanup_loop():
    while True:
        with job_lock:
            now = datetime.now(timezone.utc)
            to_delete = []
            for jid, job in list(job_store.items()):
                created = job.get('created_at')
                if created and now - created > JOB_RETENTION:
                    to_delete.append(jid)
            for jid in to_delete:
                job = job_store.pop(jid, None)
                if job:
                    try:
                        shutil.rmtree(job.get('dir', ''), ignore_errors=True)
                        logger.info("Cleaned up job %s", jid)
                    except Exception:
                        logger.exception("Error cleaning job %s", jid)
        time.sleep(600)  # run every 10 minutes


# Start cleanup thread on import
cleanup_thread = Thread(target=cleanup_loop, daemon=True)
cleanup_thread.start()


if __name__ == "__main__":
    debug_flag = os.environ.get("FLASK_DEBUG", "false").lower() in ("1","true","yes")
    app.run(host="0.0.0.0", debug=debug_flag)

