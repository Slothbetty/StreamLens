/**
 * bridge.js — runs in the ISOLATED world
 *
 * Cannot see YouTube's player JS API, but CAN use chrome.storage.
 * Receives completed trace rows from collector.js via window.postMessage
 * and persists them.
 *
 * Also drains any rows written to localStorage by collector.js as a
 * synchronous fallback for tab-close scenarios where postMessage may
 * not deliver before page teardown.
 */
'use strict';

console.log('[YT-Trace/bridge] loaded');

const LS_KEY = '__ytTracePending';

// ─── drain localStorage fallback (written synchronously on tab close) ─────────

function drainLocalStorage() {
    try {
        const raw = localStorage.getItem(LS_KEY);
        if (!raw) return;
        const pending = JSON.parse(raw);
        if (!Array.isArray(pending) || pending.length === 0) return;

        // Clear immediately so re-runs don't double-count
        localStorage.removeItem(LS_KEY);

        chrome.storage.local.get({ traces: [] }, data => {
            // Deduplicate by uuid — avoids double-saving when postMessage also delivered
            const existingUUIDs = new Set(data.traces.map(r => r.uuid));
            const newRows = pending.filter(r => r && r.uuid && !existingUUIDs.has(r.uuid));
            if (newRows.length === 0) return;

            data.traces.push(...newRows);
            chrome.storage.local.set({ traces: data.traces }, () => {
                console.log('[YT-Trace/bridge] drained', newRows.length,
                    'localStorage trace(s) — total:', data.traces.length);
            });
        });
    } catch (e) {
        console.warn('[YT-Trace/bridge] localStorage drain error:', e);
    }
}

// Also drain any per-session checkpoint keys
function drainCheckpoints() {
    try {
        const keys = Object.keys(localStorage).filter(k => k.startsWith(LS_KEY + '_ckpt_'));
        if (!keys.length) return;
        chrome.storage.local.get({ traces: [] }, data => {
            const existingUUIDs = new Set(data.traces.map(r => r.uuid));
            const newRows = [];
            for (const k of keys) {
                try {
                    const snap = JSON.parse(localStorage.getItem(k));
                    if (snap && snap.uuid && !existingUUIDs.has(snap.uuid)) {
                        newRows.push(snap);
                        existingUUIDs.add(snap.uuid);
                    }
                    localStorage.removeItem(k);
                } catch (e) {}
            }
            if (!newRows.length) return;
            data.traces.push(...newRows);
            chrome.storage.local.set({ traces: data.traces }, () => {
                console.log('[YT-Trace/bridge] drained', newRows.length,
                    'checkpoint trace(s) — total:', data.traces.length);
            });
        });
    } catch (e) {}
}

drainLocalStorage();
drainCheckpoints();

// ─── real-time delivery via postMessage ───────────────────────────────────────

window.addEventListener('message', event => {
    if (!event.data || !event.data.__ytTrace) return;

    if (event.data.action === 'save') {
        const row = event.data.row;
        chrome.storage.local.get({ traces: [] }, data => {
            // Deduplicate — localStorage drain may have already saved this uuid
            if (data.traces.some(r => r.uuid === row.uuid)) {
                console.log('[YT-Trace/bridge] skipping duplicate uuid', row.uuid);
                return;
            }
            data.traces.push(row);
            chrome.storage.local.set({ traces: data.traces }, () => {
                console.log('[YT-Trace/bridge] saved trace for', row.videoId,
                    '— total:', data.traces.length);
            });
        });
    }
});
