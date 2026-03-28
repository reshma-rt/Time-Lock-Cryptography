document.addEventListener('DOMContentLoaded', () => {

    // ── TAB SWITCHING ──────────────────────────────────────────────────────────
    const tabs        = document.querySelectorAll('.tab-btn');
    const tabContents = document.querySelectorAll('.tab-content');
    let   perfChartInstance = null;

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            tabContents.forEach(c => c.classList.add('hidden'));
            tab.classList.add('active');
            const target = tab.dataset.tab;
            document.getElementById(target).classList.remove('hidden');
            if (target === 'performance') loadPerformance();
            if (target === 'dashboard')   initDashboard();
        });
    });

    // ── GLOBAL PERFORMANCE CHART (existing tab) ────────────────────────────────
    async function loadPerformance() {
        try {
            const res  = await fetch('/stats/performance');
            if (!res.ok) return;
            const data = await res.json();
            const ctx  = document.getElementById('perfChart').getContext('2d');
            if (perfChartInstance) perfChartInstance.destroy();
            perfChartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels:   data.map(d => `${d.delay}s Target`),
                    datasets: [{
                        label:           'Actual Backend Computation Thread Yield (seconds)',
                        data:            data.map(d => parseFloat(d.execution_time).toFixed(2)),
                        borderColor:     '#8957e5',
                        backgroundColor: 'rgba(137,87,229,0.2)',
                        borderWidth: 2, tension: 0.3, fill: true,
                        pointBackgroundColor: '#58a6ff', pointRadius: 4
                    }]
                },
                options: {
                    responsive: true,
                    plugins: { legend: { labels: { color: '#c9d1d9' } } },
                    scales: {
                        y: {
                            beginAtZero: true,
                            title: { display: true, text: 'Actual Seconds CPU Time', color: '#c9d1d9' },
                            ticks: { color: '#8b949e' },
                            grid:  { color: 'rgba(255,255,255,0.05)' }
                        },
                        x: { ticks: { color: '#8b949e' }, grid: { display: false } }
                    }
                }
            });
        } catch(e) { console.error("Error drawing ChartJS matrix", e); }
    }

    // ── ENCRYPT TOGGLE ─────────────────────────────────────────────────────────
    let encryptMode = 'file';
    document.querySelectorAll('.toggle-btn').forEach(btn => {
        btn.addEventListener('click', e => {
            e.preventDefault();
            document.querySelectorAll('.toggle-btn').forEach(t => t.classList.remove('active'));
            btn.classList.add('active');
            encryptMode = btn.dataset.mode;
            document.getElementById('file-input-group').classList.toggle('hidden', encryptMode !== 'file');
            document.getElementById('text-input-group').classList.toggle('hidden', encryptMode !== 'text');
        });
    });

    // ── ENCRYPT LOGIC ──────────────────────────────────────────────────────────
    const encryptForm = document.getElementById('encrypt-form');
    const encryptBtn  = document.getElementById('encrypt-btn');
    const encBtnText  = encryptBtn.querySelector('.btn-text');
    const encSpinner  = encryptBtn.querySelector('.spinner');
    const encMsg      = document.getElementById('encrypt-message');

    encryptForm.addEventListener('submit', async e => {
        e.preventDefault();
        const fileInput  = document.getElementById('enc-file');
        const textInput  = document.getElementById('enc-text');
        const delayInput = document.getElementById('delay');
        const passInput  = document.getElementById('enc-password');

        if (encryptMode === 'file' && !fileInput.files.length) return alert('Select a file to encrypt');
        if (encryptMode === 'text' && !textInput.value.trim())  return alert('Enter a text message');

        encryptBtn.disabled = true;
        encBtnText.classList.add('hidden');
        encSpinner.classList.remove('hidden');
        showMsg(encMsg, 'Computing hardware block sequence...', 'msg-info');

        try {
            if (encryptMode === 'file') {
                const fd = new FormData();
                fd.append('file', fileInput.files[0]);
                fd.append('delay', delayInput.value);
                fd.append('password', passInput.value);
                const res = await fetch('/encrypt/file', { method: 'POST', body: fd });
                if (res.ok) {
                    triggerDownload(await res.blob(), extractFilename(res, 'locked.enc'));
                    showMsg(encMsg, 'EAX Protocol Sealed & Verified! .enc deployed natively.', 'msg-success');
                    encryptForm.reset();
                } else {
                    showMsg(encMsg, (await res.json()).error || 'Fatal encryption failure', 'msg-error');
                }
            } else {
                const res  = await fetch('/encrypt/text', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: textInput.value,
                                          delay: delayInput.value,
                                          password: passInput.value })
                });
                const data = await res.json();
                if (res.ok) {
                    const bytes = Uint8Array.from(atob(data.ciphertext_b64), c => c.charCodeAt(0));
                    triggerDownload(new Blob([bytes], { type: 'application/octet-stream' }), data.filename);
                    showMsg(encMsg, 'EAX Protocol Sealed! Native text .enc packet delivered.', 'msg-success');
                    encryptForm.reset();
                } else {
                    showMsg(encMsg, data.error || 'Text serialization collapsed.', 'msg-error');
                }
            }
        } catch { showMsg(encMsg, 'Network error during compilation.', 'msg-error'); }
        finally {
            encryptBtn.disabled = false;
            encBtnText.classList.remove('hidden');
            encSpinner.classList.add('hidden');
        }
    });

    // ── DECRYPT UI ─────────────────────────────────────────────────────────────
    const decFile          = document.getElementById('dec-file');
    const countdownBox     = document.getElementById('countdown-box');
    const timerText        = document.getElementById('dec-timer');
    const decryptBtn       = document.getElementById('decrypt-btn');
    const decryptForm      = document.getElementById('decrypt-form');
    const decMsg           = document.getElementById('decrypt-message');
    const decBtnText       = decryptBtn.querySelector('.btn-text');
    const decSpinner       = decryptBtn.querySelector('.spinner');
    const progressBox      = document.getElementById('progress-box');
    const progressFill     = document.getElementById('progress-fill');
    const progressText     = document.getElementById('progress-text');
    const progressLogs     = document.getElementById('dec-logs');
    const decPasswordGroup = document.getElementById('dec-password-group');
    const passwordInput    = document.getElementById('dec-password');
    const textBoxOutput    = document.getElementById('dec-text-box');
    const textOutput       = document.getElementById('dec-text-output');
    const fileResultBox    = document.getElementById('decryption-ready-box');
    const dlResultBtn      = document.getElementById('download-result-btn');

    // Perf graphs panel
    const graphsBox      = document.getElementById('perf-graphs-box');
    const graphPollBtn   = document.getElementById('graph-poll-btn');
    const graphStatusMsg = document.getElementById('graph-status-msg');

    let timerInterval = null, pollInterval = null;
    let selectedFilename = null, selectedFileId = null;
    let liveCharts = {};   // Chart.js instances keyed by graph name

    // ── FILE SELECTED ──────────────────────────────────────────────────────────
    decFile.addEventListener('change', async e => {
        if (!e.target.files.length) return;
        selectedFilename = e.target.files[0].name;
        selectedFileId   = selectedFilename.replace('.enc', '');

        [countdownBox, progressBox, decPasswordGroup,
         textBoxOutput, fileResultBox, decMsg, graphsBox].forEach(el => el.classList.add('hidden'));
        decryptBtn.disabled = true;
        decryptBtn.classList.remove('ready');

        try {
            const res  = await fetch(`/status/${selectedFilename}`);
            if (!res.ok) { showMsg(decMsg, 'Unknown .enc file.', 'msg-error'); return; }
            const meta = await res.json();

            if (meta.has_password) decPasswordGroup.classList.remove('hidden');

            const diff = meta.unlock_time - Date.now() / 1000;
            if (diff > 0) {
                countdownBox.classList.remove('hidden');
                startCountdown(meta.unlock_time);
            } else {
                decryptBtn.disabled = false;
                decryptBtn.classList.add('ready');
                showMsg(decMsg, 'Time-Lock Constraint Satisfied', 'msg-success');
                if (meta.status === 'unlocked') {
                    progressBox.classList.remove('hidden');
                    progressFill.style.width = '100%';
                    progressText.innerText   = '100.00%';
                    progressLogs.value       = meta.logs || '';
                    scheduleGraphPoll(0);
                }
            }
        } catch { showMsg(decMsg, 'Status probe failed.', 'msg-error'); }
    });

    function startCountdown(unlockTime) {
        if (timerInterval) clearInterval(timerInterval);
        timerInterval = setInterval(() => {
            const rem  = Math.max(0, unlockTime - Date.now() / 1000);
            const mins = String(Math.floor(rem / 60)).padStart(2,'0');
            const secs = String(Math.floor(rem % 60)).padStart(2,'0');
            timerText.textContent = `${mins}:${secs}`;
            if (rem <= 0) {
                clearInterval(timerInterval);
                countdownBox.classList.add('hidden');
                decryptBtn.disabled = false;
                decryptBtn.classList.add('ready');
                showMsg(decMsg, 'Time-Lock Constraint Satisfied', 'msg-success');
            }
        }, 1000);
    }

    // ── DECRYPT SUBMIT ─────────────────────────────────────────────────────────
    decryptForm.addEventListener('submit', async e => {
        e.preventDefault();
        if (!decFile.files.length) return alert('Upload a .enc file first.');

        decryptBtn.disabled = true;
        decBtnText.classList.add('hidden');
        decSpinner.classList.remove('hidden');
        progressBox.classList.remove('hidden');
        progressFill.style.width = '0%';
        progressText.innerText   = '0.0%';
        progressLogs.value       = 'Hardware Thread Initializing...\n';
        showMsg(decMsg, 'Spawning isolated background thread...', 'msg-info');

        const fd = new FormData();
        fd.append('file', decFile.files[0]);
        fd.append('password', passwordInput.value);

        try {
            const res  = await fetch('/decrypt/start', { method: 'POST', body: fd });
            const data = await res.json();
            if (!res.ok) { showMsg(decMsg, data.error, 'msg-error'); resetDecBtn(); return; }
            startPolling();
        } catch {
            showMsg(decMsg, 'Network interruption.', 'msg-error');
            resetDecBtn();
        }
    });

    // ── PROGRESS POLLER ────────────────────────────────────────────────────────
    function startPolling() {
        if (pollInterval) clearInterval(pollInterval);
        let errCount = 0;

        pollInterval = setInterval(async () => {
            try {
                const r = await fetch(`/status/${selectedFilename}`);
                if (!r.ok) { if (++errCount >= 5) stopPoll('Lost contact.'); return; }
                errCount = 0;
                const meta    = await r.json();
                const percent = Math.min(100, Math.max(0, meta.solve_progress || 0));

                progressFill.style.width = percent + '%';
                progressText.innerText   = percent.toFixed(2) + '%';
                if (meta.logs) { progressLogs.value = meta.logs; progressLogs.scrollTop = 99999; }

                if (meta.status === 'locked') {
                    stopPoll('Security halt — check logs.', 'msg-error');
                } else if (meta.status === 'unlocked') {
                    stopPoll('Decryption Completed Successfully', 'msg-success');
                    progressFill.style.width = '100%';
                    progressText.innerText   = '100.00%';
                    loadFinalPayload(meta.payload_type);
                    scheduleGraphPoll();
                }
            } catch { if (++errCount >= 5) stopPoll('Poll stream interrupted.'); }
        }, 500);
    }

    function stopPoll(msg, cls = 'msg-error') {
        clearInterval(pollInterval); pollInterval = null;
        showMsg(decMsg, msg, cls);
        resetDecBtn();
    }

    // ── REAL-TIME SPARKLINES (live telemetry during solve) ────────────────────
    // Polls /stats/live/<file_id> every second while solving, feeds Chart.js
    // sparkline instances in the perf-graphs-box so users see progress live.
    let liveInterval = null;

    function startLiveTelemetry() {
        stopLiveTelemetry();
        // Show graphs box early for live sparklines
        if (graphsBox) graphsBox.classList.remove('hidden');
        if (graphStatusMsg) graphStatusMsg.textContent = 'Live telemetry — solver running…';

        _ensureLiveCharts();

        liveInterval = setInterval(async () => {
            try {
                const r = await fetch(`/stats/live/${selectedFileId}`);
                if (!r.ok) return;
                const { samples } = await r.json();
                if (!samples || !samples.length) return;

                const ts   = samples.map(s => parseFloat(s.t.toFixed(2)));
                _updateSparkline('live-completion', ts, samples.map(s => s.pct), '#58a6ff');
                _updateSparkline('live-cpu',        ts, samples.map(s => s.cpu), '#f0883e');
                _updateSparkline('live-iterations', ts, samples.map(s => s.iter), '#3fb950');
            } catch { /* non-fatal */ }
        }, 1000);
    }

    function stopLiveTelemetry() {
        if (liveInterval) { clearInterval(liveInterval); liveInterval = null; }
    }

    function _ensureLiveCharts() {
        const specs = [
            { id: 'live-completion', label: 'Completion %',        color: '#58a6ff', ymax: 100 },
            { id: 'live-cpu',        label: 'CPU Usage %',          color: '#f0883e', ymax: 100 },
            { id: 'live-iterations', label: 'Squarings Completed',  color: '#3fb950', ymax: null },
        ];
        specs.forEach(({ id, label, color, ymax }) => {
            const canvas = document.getElementById(id);
            if (!canvas) return;
            if (liveCharts[id]) { liveCharts[id].destroy(); }
            liveCharts[id] = new Chart(canvas.getContext('2d'), {
                type: 'line',
                data: { labels: [], datasets: [{ label, data: [],
                    borderColor: color, backgroundColor: color + '1a',
                    borderWidth: 1.6, fill: true, tension: 0.3, pointRadius: 0 }] },
                options: {
                    animation: false, responsive: true,
                    plugins: { legend: { display: false } },
                    scales: {
                        x: { ticks: { color: '#8b949e', maxTicksLimit: 6 },
                             grid: { display: false } },
                        y: { beginAtZero: true, max: ymax || undefined,
                             ticks: { color: '#8b949e', maxTicksLimit: 4 },
                             grid:  { color: 'rgba(255,255,255,0.04)' } }
                    }
                }
            });
        });
    }

    function _updateSparkline(id, labels, data, color) {
        const c = liveCharts[id];
        if (!c) return;
        c.data.labels = labels;
        c.data.datasets[0].data = data;
        c.update('none');
    }

    // Kick off live charts when decryption starts
    const _origStartPolling = startPolling;
    // (already calls startPolling; wrap to also start live telemetry)
    decryptForm.addEventListener('submit', () => {
        // small delay to ensure thread is spawned before first poll
        setTimeout(startLiveTelemetry, 800);
    }, true);

    // ── STATIC GRAPH POLLING (after solve completes) ───────────────────────────
    let graphPollTimer = null;
    const GRAPH_MAX = 18;    // 18 × 2 s = 36 s ceiling

    function scheduleGraphPoll(attempt = 0) {
        stopLiveTelemetry();
        if (graphPollTimer) clearTimeout(graphPollTimer);
        if (attempt >= GRAPH_MAX) {
            if (graphStatusMsg) graphStatusMsg.textContent =
                'Graphs not yet ready — click Refresh to retry.';
            return;
        }
        graphPollTimer = setTimeout(() => tryLoadGraphs(attempt + 1), 2000);
    }

    async function tryLoadGraphs(attempt) {
        try {
            const res  = await fetch(`/stats/graphs/${selectedFileId}`);
            if (!res.ok) { scheduleGraphPoll(attempt); return; }
            const { graphs } = await res.json();
            const keys = graphs ? Object.keys(graphs) : [];

            if (keys.length === 0 && attempt < GRAPH_MAX) {
                scheduleGraphPoll(attempt); return;
            }

            if (graphsBox) graphsBox.classList.remove('hidden');
            if (graphStatusMsg) graphStatusMsg.textContent =
                `${keys.length} performance graph${keys.length !== 1 ? 's' : ''} rendered.`;

            const stamp = `?t=${Date.now()}`;
            const imgMap = {
                completion: 'graph-img-completion',
                cpu:        'graph-img-cpu',
                iterations: 'graph-img-iterations',
                remaining:  'graph-img-remaining',
                comparison: 'graph-img-comparison',
            };
            Object.entries(imgMap).forEach(([key, imgId]) => {
                if (!graphs[key]) return;
                const img  = document.getElementById(imgId);
                const wrap = img && img.parentElement;
                if (img) { img.src = graphs[key] + stamp; }
                if (wrap) wrap.classList.remove('hidden');
            });
        } catch { scheduleGraphPoll(attempt); }
    }

    if (graphPollBtn) {
        graphPollBtn.addEventListener('click', () => tryLoadGraphs(0));
    }

    // ── FINAL PAYLOAD ──────────────────────────────────────────────────────────
    async function loadFinalPayload(type) {
        if (type === 'text') {
            try {
                const res = await fetch(`/decrypt/result/${selectedFileId}`);
                if (res.ok) {
                    textBoxOutput.classList.remove('hidden');
                    textOutput.value = (await res.json()).content;
                } else {
                    showMsg(decMsg,
                        ((await res.json().catch(() => ({}))).error) ||
                        'Result expired — re-upload and decrypt again.', 'msg-error');
                }
            } catch { showMsg(decMsg, 'Failed to retrieve text payload.', 'msg-error'); }
        } else {
            fileResultBox.classList.remove('hidden');
        }
    }

    dlResultBtn.addEventListener('click', async () => {
        dlResultBtn.disabled = true; dlResultBtn.textContent = 'Downloading…';
        try {
            const res = await fetch(`/decrypt/result/${selectedFileId}`);
            if (res.ok) {
                triggerDownload(await res.blob(),
                    extractFilename(res, 'verified_payload_' + selectedFileId));
            } else {
                showMsg(decMsg, ((await res.json().catch(() => ({}))).error) ||
                    'File result expired.', 'msg-error');
                fileResultBox.classList.add('hidden');
            }
        } catch { showMsg(decMsg, 'Download fetch failed.', 'msg-error'); }
        finally { dlResultBtn.disabled = false; dlResultBtn.textContent = 'Download Decrypted File'; }
    });

    // ─────────────────────────────────────────────────────────────────────────
    // PERFORMANCE DASHBOARD TAB
    // ─────────────────────────────────────────────────────────────────────────

    let dashboardInit = false;
    let benchmarkPollInterval = null;

    function initDashboard() {
        if (dashboardInit) return;
        dashboardInit = true;
        // Pre-populate the global stats chart
        loadPerformance();
    }

    // Benchmark start button
    const benchBtn     = document.getElementById('benchmark-start-btn');
    const benchMsg     = document.getElementById('benchmark-msg');
    const benchGraphs  = document.getElementById('benchmark-graphs-box');
    const benchImgWrap = document.getElementById('benchmark-img-wrap');
    const benchImg     = document.getElementById('benchmark-img');
    const delayPills   = document.querySelectorAll('.delay-pill');
    const customDelays = document.getElementById('custom-delays');

    if (benchBtn) {
        benchBtn.addEventListener('click', async () => {
            const selected = [...(delayPills || [])]
                .filter(p => p.classList.contains('active'))
                .map(p => parseInt(p.dataset.delay));
            const custom = (customDelays && customDelays.value.trim())
                ? customDelays.value.split(',')
                    .map(v => parseInt(v.trim()))
                    .filter(v => !isNaN(v) && v > 0)
                : [];
            const delays = [...new Set([...selected, ...custom])].sort((a,b) => a-b);
            if (!delays.length) {
                showMsg(benchMsg, 'Select at least one delay target.', 'msg-error');
                return;
            }

            benchBtn.disabled = true;
            showMsg(benchMsg, `Running benchmark for delays: [${delays.join(', ')}]s …`, 'msg-info');

            try {
                const res = await fetch('/benchmark/start', {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ delays })
                });
                if (!res.ok) {
                    showMsg(benchMsg, (await res.json()).error || 'Benchmark start failed.', 'msg-error');
                    benchBtn.disabled = false; return;
                }
                startBenchmarkPoll();
            } catch {
                showMsg(benchMsg, 'Network error starting benchmark.', 'msg-error');
                benchBtn.disabled = false;
            }
        });
    }

    // Delay pill toggle
    delayPills && delayPills.forEach(pill => {
        pill.addEventListener('click', () => pill.classList.toggle('active'));
    });

    function startBenchmarkPoll() {
        if (benchmarkPollInterval) clearInterval(benchmarkPollInterval);
        benchmarkPollInterval = setInterval(async () => {
            try {
                const res  = await fetch('/benchmark/status');
                const data = await res.json();

                if (!data.running && data.graphs && data.graphs.benchmark) {
                    clearInterval(benchmarkPollInterval);
                    benchmarkPollInterval = null;
                    benchBtn.disabled = false;
                    showMsg(benchMsg, 'Benchmark complete.', 'msg-success');
                    if (benchGraphs) benchGraphs.classList.remove('hidden');
                    if (benchImg) {
                        benchImg.src = data.graphs.benchmark + `?t=${Date.now()}`;
                        if (benchImgWrap) benchImgWrap.classList.remove('hidden');
                    }
                } else if (!data.running && data.error) {
                    clearInterval(benchmarkPollInterval);
                    benchBtn.disabled = false;
                    showMsg(benchMsg, `Benchmark error: ${data.error}`, 'msg-error');
                }
            } catch { /* keep polling */ }
        }, 1500);
    }

    // ── HELPERS ────────────────────────────────────────────────────────────────
    function resetDecBtn() {
        decryptBtn.disabled = false;
        decBtnText.classList.remove('hidden');
        decSpinner.classList.add('hidden');
    }

    function triggerDownload(blob, filename) {
        const url = URL.createObjectURL(blob);
        const a   = Object.assign(document.createElement('a'),
            { href: url, download: filename, style: 'display:none' });
        document.body.appendChild(a);
        a.click(); document.body.removeChild(a);
        URL.revokeObjectURL(url);
    }

    function extractFilename(response, fallback) {
        const disp = response.headers.get('content-disposition') || '';
        const m    = /filename[^;=\n]*=((['"]).*?\2|[^;\n]*)/.exec(disp);
        return (m && m[1]) ? m[1].replace(/['"]/g, '') : fallback;
    }

    function showMsg(el, text, cls) {
        if (!el) return;
        el.className = ''; el.classList.add(cls);
        el.textContent = text; el.classList.remove('hidden');
    }

});