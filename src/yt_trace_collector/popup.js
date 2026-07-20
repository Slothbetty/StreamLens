'use strict';

// CSV column order — original fields first, then extended simulator fields
const COLUMNS = [
    'browserInfo',
    'osInfo',
    'timeSincePageLoad',
    'modified',
    'uuid',
    'stallDiffsString',
    'videoId',
    'timestamp',
    'totalWatchTimeSeconds',
    'watchRangeFrames',
    'watchRangeSeconds',
    // extended
    'stallTimesString',
    'bufferSamplesString',
    'networkPeriodsString',
    'segmentDownloadsString',
];

function escapeCSV(value) {
    const s = String(value ?? '');
    // Quote if the value contains comma, newline, or double-quote
    if (/[",\n\r]/.test(s)) {
        return '"' + s.replace(/"/g, '""') + '"';
    }
    return s;
}

function toCSV(traces) {
    const header = COLUMNS.join(',');
    const rows   = traces.map(row =>
        COLUMNS.map(col => escapeCSV(row[col])).join(',')
    );
    return [header, ...rows].join('\n');
}

function downloadCSV(csv) {
    const blob = new Blob([csv], { type: 'text/csv' });
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = `yt_traces_${new Date().toISOString().slice(0,10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
}

function showMsg(text, ok = true) {
    const el = document.getElementById('msg');
    el.textContent = text;
    el.style.color = ok ? '#27ae60' : '#e74c3c';
    setTimeout(() => { el.textContent = ''; }, 2500);
}

// ── load count on popup open ──────────────────────────────────────────────────
chrome.storage.local.get({ traces: [] }, data => {
    const n = data.traces.length;
    document.getElementById('count').textContent = n;
    document.getElementById('exportBtn').disabled = n === 0;
    document.getElementById('clearBtn').disabled  = n === 0;
});

// ── export ────────────────────────────────────────────────────────────────────
document.getElementById('exportBtn').addEventListener('click', () => {
    chrome.storage.local.get({ traces: [] }, data => {
        if (!data.traces.length) { showMsg('No traces yet.', false); return; }
        downloadCSV(toCSV(data.traces));
        showMsg(`Exported ${data.traces.length} trace(s).`);
    });
});

// ── clear ─────────────────────────────────────────────────────────────────────
document.getElementById('clearBtn').addEventListener('click', () => {
    if (!confirm('Delete all collected traces?')) return;
    chrome.storage.local.set({ traces: [] }, () => {
        document.getElementById('count').textContent = 0;
        document.getElementById('exportBtn').disabled = true;
        document.getElementById('clearBtn').disabled  = true;
        showMsg('Cleared.');
    });
});
