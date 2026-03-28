import os
# Force re-load workers
import io
import time
import uuid
import base64
import threading
from werkzeug.utils import secure_filename
from flask import Flask, request, jsonify, render_template, send_file
from crypto import (generate_key, encrypt_file, decrypt_file, encrypt_text, decrypt_text,
                    generate_puzzle, solve_puzzle_tracked, protect_base_key,
                    unprotect_base_key, generate_sha256)
from data.db import (init_db, insert_file_metadata, get_file_metadata, update_file_status,
                     update_solve_progress, update_execution_time, get_performance_stats)
from perf_tracker import (create_tracker, get_tracker, remove_tracker,
                           run_delay_benchmark)

app = Flask(__name__, template_folder='templates', static_folder='static')
app.config['SECRET_KEY'] = 'dev-secret-key-replace-in-prod'

# ── Graph output directory ────────────────────────────────────────────────────
# Override via CHRONOS_GRAPH_DIR environment variable if needed.
GRAPH_SAVE_DIR = os.environ.get(
    'CHRONOS_GRAPH_DIR', os.path.join('static', 'graphs'))

init_db()

# RAM cache for decrypted payloads awaiting download
TMP_DECRYPTED_CACHE: dict = {}

# Benchmark state: tracks whether a run is in progress and stores results
_BENCHMARK_LOCK    = threading.Lock()
_BENCHMARK_STATUS  = {"running": False, "graphs": {}, "error": ""}


# ─────────────────────────────────────────────────────────────────────────────
# Core routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/encrypt/file', methods=['POST'])
def encrypt_file_route():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file     = request.files['file']
    password = request.form.get('password', '').strip()
    try:
        delay_seconds = int(request.form.get('delay', 10))
    except ValueError:
        return jsonify({'error': 'Invalid delay parameter'}), 400

    original_filename = secure_filename(file.filename)
    file_data         = file.read()
    sha256_hash       = generate_sha256(file_data)

    aes_key                = generate_key()
    ciphertext, nonce, tag = encrypt_file(aes_key, file_data)

    key_payload, salt = protect_base_key(aes_key, password if password else None)
    puzzle            = generate_puzzle(key_payload, delay_seconds)

    file_id      = str(uuid.uuid4())
    enc_filename = f"{file_id}.enc"
    timestamp    = time.time()
    unlock_time  = timestamp + delay_seconds

    insert_file_metadata(
        file_id=file_id, filename=original_filename, payload_type='file',
        delay=delay_seconds, timestamp=timestamp, unlock_time=unlock_time,
        pzl=puzzle, nonce=nonce, tag=tag, password_salt=salt,
        sha256_hash=sha256_hash)

    return send_file(io.BytesIO(ciphertext), mimetype='application/octet-stream',
                     as_attachment=True, download_name=enc_filename)


@app.route('/encrypt/text', methods=['POST'])
def encrypt_text_route():
    data          = request.json
    text_message  = data.get('message', '')
    delay_seconds = int(data.get('delay', 10))
    password      = data.get('password', '').strip()

    if not text_message:
        return jsonify({'error': 'Empty message'}), 400

    sha256_hash            = generate_sha256(text_message.encode('utf-8'))
    aes_key                = generate_key()
    ciphertext, nonce, tag = encrypt_text(aes_key, text_message)
    key_payload, salt      = protect_base_key(aes_key, password if password else None)
    puzzle                 = generate_puzzle(key_payload, delay_seconds)

    file_id   = str(uuid.uuid4())
    timestamp = time.time()

    insert_file_metadata(
        file_id=file_id, filename='message.txt', payload_type='text',
        delay=delay_seconds, timestamp=timestamp,
        unlock_time=timestamp + delay_seconds,
        pzl=puzzle, nonce=nonce, tag=tag, password_salt=salt,
        sha256_hash=sha256_hash)

    b64_cipher = base64.b64encode(ciphertext).decode('utf-8')
    return jsonify({'success': True,
                    'filename': f"{file_id}.enc",
                    'ciphertext_b64': b64_cipher})


@app.route('/status/<file_name>', methods=['GET'])
def check_status(file_name):
    file_id = file_name.replace('.enc', '')
    meta    = get_file_metadata(file_id)
    if not meta:
        return jsonify({'error': 'Unknown file signature'}), 404

    return jsonify({
        'unlock_time':    meta['unlock_time'],
        'status':         meta['status'],
        'payload_type':   meta['payload_type'],
        'delay':          meta['delay'],
        'has_password':   meta['password_salt'] is not None,
        'solve_progress': meta['solve_progress'],
        'logs':           meta['logs'],
    })


# ─────────────────────────────────────────────────────────────────────────────
# Decryption
# ─────────────────────────────────────────────────────────────────────────────

def _measure_aes_baseline(aes_key: bytes, ciphertext: bytes,
                           nonce: bytes, tag: bytes,
                           payload_type: str) -> float:
    """
    Run a plain AES-EAX decrypt (no puzzle) and return elapsed milliseconds.
    Used to populate the comparison bar chart.  Non-fatal if it fails.
    """
    try:
        t0 = time.perf_counter()
        if payload_type == 'text':
            decrypt_text(aes_key, ciphertext, nonce, tag)
        else:
            decrypt_file(aes_key, ciphertext, nonce, tag)
        return (time.perf_counter() - t0) * 1000
    except Exception:
        return 0.0


def background_puzzle_solver(file_id: str, meta: dict,
                               ciphertext: bytes, password: str) -> None:
    """
    Isolated worker thread: solves the time-lock puzzle, verifies integrity,
    caches the plaintext, and fires off graph rendering.

    Performance telemetry is collected non-blockingly via PerfTracker:
    - A CPU-sampling daemon sub-thread ticks every 0.5 s.
    - The solver's on_progress callback also injects iteration-aligned points.
    - Graph rendering runs in a *third* daemon thread so this function
      returns quickly after the puzzle is solved.
    """
    tracker = create_tracker(
        file_id,
        total_iters=meta['t_squarings'],
        sample_interval=0.5)
    tracker.start()

    try:
        update_file_status(file_id, 'solving')
        update_solve_progress(file_id, 0.0, "Booting discrete hardware thread array...")

        # Running iteration counter shared with the callback closure
        _iter_counter = [0]

        def on_progress(percentage: float, log_msg: str) -> None:
            """
            Called by solve_puzzle_tracked every `update_interval` squarings.
            Forwards to SQLite (for /status polling) AND records a telemetry
            sample.  Kept intentionally lightweight — runs in the solver thread.
            """
            try:
                update_solve_progress(file_id, percentage, log_msg)
            except Exception:
                pass
            # Estimate current iteration from percentage
            est_iter = int((percentage / 100.0) * meta['t_squarings'])
            _iter_counter[0] = est_iter
            tracker.record_sample(est_iter, percentage)

        start_time = time.time()

        key_payload = solve_puzzle_tracked(
            meta['n_mod'], meta['a_base'], meta['t_squarings'], meta['c_k'],
            db_update_func=on_progress,
            update_interval=max(1, meta['t_squarings'] // 30))

        elapsed = time.time() - start_time
        update_execution_time(file_id, elapsed)

        # ── Security Boundary 1: password unwrap ──────────────────────────────
        salt_hex = meta['password_salt']
        if salt_hex is not None and not password:
            update_solve_progress(file_id, 100,
                "FATAL SECURITY HALT: Payload is password-protected "
                "but no password was supplied.")
            update_file_status(file_id, 'locked')
            return

        try:
            aes_key = unprotect_base_key(
                key_payload, password if salt_hex else None, salt_hex)
        except Exception:
            update_solve_progress(file_id, 100,
                "FATAL SECURITY HALT: Dual-Lock PBKDF2 Password Mismatch. "
                "Refusing to decouple payload.")
            update_file_status(file_id, 'locked')
            return

        nonce_b = bytes.fromhex(meta['nonce'])
        tag_b   = bytes.fromhex(meta['tag'])

        # ── AES baseline for comparison chart ─────────────────────────────────
        aes_ms = _measure_aes_baseline(
            aes_key, ciphertext, nonce_b, tag_b, meta['payload_type'])
        tracker.record_aes_baseline(aes_ms)

        # ── Security Boundary 2: AES-EAX + SHA-256 integrity ─────────────────
        if meta['payload_type'] == 'text':
            plaintext_str = decrypt_text(aes_key, ciphertext, nonce_b, tag_b)
            if generate_sha256(plaintext_str.encode('utf-8')) != meta['sha256_hash']:
                raise ValueError(
                    "Physical SHA256 integrity failure. Data corruption indicated.")
            TMP_DECRYPTED_CACHE[file_id] = {
                'type': 'text', 'content': plaintext_str}
        else:
            plaintext_bytes = decrypt_file(aes_key, ciphertext, nonce_b, tag_b)
            if generate_sha256(plaintext_bytes) != meta['sha256_hash']:
                raise ValueError(
                    "Physical SHA256 integrity failure. "
                    "Binary sector corruption indicated.")
            TMP_DECRYPTED_CACHE[file_id] = {
                'type': 'file', 'content': plaintext_bytes,
                'filename': meta['filename']}

        update_file_status(file_id, 'unlocked')
        update_solve_progress(file_id, 100.0,
            "DECRYPTION & FULL INTEGRITY SHA256 HASH VERIFIED. "
            "READY FOR TRANSMISSION.")

        # ── Stop CPU sampler, add final data point, render graphs async ───────
        tracker.stop()
        tracker.record_sample(meta['t_squarings'], 100.0)

        threading.Thread(
            target=_render_graphs_async,
            args=(file_id,),
            daemon=True,
            name=f"graph-render-{file_id}"
        ).start()

    except Exception as exc:
        tracker.stop()
        try:
            update_solve_progress(file_id, 100, f"FATAL THREAD HALT: {exc}")
            update_file_status(file_id, 'locked')
        except Exception:
            pass


def _render_graphs_async(file_id: str) -> None:
    """
    Runs in a dedicated daemon thread after the solver completes.
    Generates all five PNGs — never blocks Flask or the solver.
    """
    tracker = get_tracker(file_id)
    if tracker is None:
        return
    try:
        saved = tracker.build_graphs(
            save_dir=GRAPH_SAVE_DIR,
            show=False,
            include_remaining=True,
            include_comparison=True)

        if saved:
            paths_str = " | ".join(
                f"{k}: {os.path.basename(v)}" for k, v in saved.items())
            update_solve_progress(
                file_id, 100.0,
                f"Performance graphs rendered → {paths_str}")
    except Exception as exc:
        try:
            update_solve_progress(
                file_id, 100.0, f"[WARN] Graph render failed: {exc}")
        except Exception:
            pass
    finally:
        remove_tracker(file_id)


@app.route('/decrypt/start', methods=['POST'])
def decrypt_start_route():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file     = request.files['file']
    filename = secure_filename(file.filename)
    password = request.form.get('password', '').strip()

    file_id  = filename.replace('.enc', '')
    meta     = get_file_metadata(file_id)

    if not meta:
        return jsonify({'error':
            'Metadata missing. Ensure this file belongs to this Chronos DB.'}), 404
    if time.time() < meta['unlock_time']:
        return jsonify({'error': 'Time lock has not expired yet!'}), 403
    if meta['password_salt'] and not password:
        return jsonify({'error':
            'This specific payload requires a password to unroll.'}), 400

    ciphertext = file.read()

    if meta['status'] not in ('solving', 'unlocked'):
        update_solve_progress(file_id, 0.0)
        threading.Thread(
            target=background_puzzle_solver,
            args=(file_id, meta, ciphertext, password),
            daemon=True
        ).start()

    return jsonify({'success': True,
                    'msg': 'Puzzle solving sequence successfully spawned.'})


@app.route('/decrypt/result/<file_id>', methods=['GET'])
def fetch_decrypted_result(file_id):
    if file_id not in TMP_DECRYPTED_CACHE:
        return jsonify({'error':
            'Payload session vanished or unresolved.'}), 404

    data = TMP_DECRYPTED_CACHE.pop(file_id)
    if data['type'] == 'text':
        return jsonify({'success': True, 'type': 'text',
                        'content': data['content']})
    return send_file(io.BytesIO(data['content']),
                     mimetype='application/octet-stream',
                     as_attachment=True,
                     download_name=data['filename'])


# ─────────────────────────────────────────────────────────────────────────────
# Performance & graph routes
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/stats/performance')
def performance_stats():
    """Returns per-job delay vs execution_time pairs for the Chart.js panel."""
    return jsonify(get_performance_stats())


@app.route('/stats/graphs/<file_id>', methods=['GET'])
def list_graphs(file_id: str):
    """
    Return URLs for any PNG graphs available for the given file_id.
    The frontend polls this after status reaches 'unlocked'.

    Response:
        { "graphs": {
            "completion":  "/static/graphs/<id>_completion.png",
            "cpu":         "/static/graphs/<id>_cpu.png",
            "iterations":  "/static/graphs/<id>_iterations.png",
            "remaining":   "/static/graphs/<id>_remaining.png",
            "comparison":  "/static/graphs/<id>_comparison.png"
          }
        }
    Missing files are omitted.
    """
    graph_keys = {
        'completion': f"{file_id}_completion.png",
        'cpu':        f"{file_id}_cpu.png",
        'iterations': f"{file_id}_iterations.png",
        'remaining':  f"{file_id}_remaining.png",
        'comparison': f"{file_id}_comparison.png",
    }
    available = {}
    for key, fname in graph_keys.items():
        if os.path.isfile(os.path.join(GRAPH_SAVE_DIR, fname)):
            available[key] = f"/static/graphs/{fname}"

    return jsonify({'graphs': available})


@app.route('/stats/graphs/<file_id>/<graph_type>.png')
def serve_graph(file_id: str, graph_type: str):
    """Direct PNG download endpoint (alternative to the static handler)."""
    allowed = {'completion', 'cpu', 'iterations', 'remaining', 'comparison'}
    if graph_type not in allowed:
        return jsonify({'error': 'Unknown graph type'}), 400

    png_path = os.path.join(GRAPH_SAVE_DIR, f"{file_id}_{graph_type}.png")
    if not os.path.isfile(png_path):
        return jsonify({'error': 'Graph not yet generated'}), 404

    return send_file(png_path, mimetype='image/png')


@app.route('/stats/live/<file_id>', methods=['GET'])
def live_telemetry(file_id: str):
    """
    Return the raw sample list from the in-memory PerfTracker while a solve
    is still running.  The frontend uses this to render real-time sparklines.

    Response:
        { "samples": [ {"t": float, "iter": int, "pct": float, "cpu": float} ] }
    """
    tracker = get_tracker(file_id)
    if tracker is None:
        return jsonify({'samples': []})
    return jsonify({'samples': tracker.get_samples()})


# ─────────────────────────────────────────────────────────────────────────────
# Multi-delay benchmark route
# ─────────────────────────────────────────────────────────────────────────────

@app.route('/benchmark/start', methods=['POST'])
def benchmark_start():
    """
    Start a background multi-delay benchmark.

    POST JSON: { "delays": [1, 5, 10, 30] }   (defaults to [1,5,10,20])
    """
    with _BENCHMARK_LOCK:
        if _BENCHMARK_STATUS["running"]:
            return jsonify({'error': 'Benchmark already running'}), 409
        _BENCHMARK_STATUS["running"] = True
        _BENCHMARK_STATUS["graphs"]  = {}
        _BENCHMARK_STATUS["error"]   = ""

    data   = request.get_json(silent=True) or {}
    delays = data.get('delays', [1, 5, 10, 20])
    # Safety clamp: don't let UI accidentally request a 3600s benchmark
    delays = [max(1, min(int(d), 120)) for d in delays[:8]]

    def _done(paths: dict):
        with _BENCHMARK_LOCK:
            _BENCHMARK_STATUS["running"] = False
            _BENCHMARK_STATUS["graphs"]  = {
                k: f"/static/graphs/{os.path.basename(v)}"
                for k, v in paths.items() if v
            }

    run_delay_benchmark(
        delays=delays,
        save_dir=GRAPH_SAVE_DIR,
        show=False,
        done_callback=_done)

    return jsonify({'success': True,
                    'msg': f"Benchmark started for delays {delays}"})


@app.route('/benchmark/status', methods=['GET'])
def benchmark_status():
    """Poll endpoint for benchmark progress & graph URLs."""
    with _BENCHMARK_LOCK:
        return jsonify({
            'running': _BENCHMARK_STATUS["running"],
            'graphs':  _BENCHMARK_STATUS["graphs"],
            'error':   _BENCHMARK_STATUS["error"],
        })


# ─────────────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(debug=True, port=8000, threaded=True)