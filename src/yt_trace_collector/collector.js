/**
 * collector.js — runs in the page's MAIN world
 *
 * Has full access to YouTube's player JavaScript API (getPlaybackQuality, etc.)
 * Cannot use chrome.* APIs — sends completed traces to bridge.js via postMessage.
 */
'use strict';

console.log('[YT-Trace/collector] loaded, path=', location.pathname);

// ─── constants ────────────────────────────────────────────────────────────────

const QUALITY_HEIGHT = {
    tiny: 144, small: 240, medium: 360,
    large: 480, hd720: 720, hd1080: 1080,
    hd1440: 1440, hd2160: 2160,
};
const BUFFER_SAMPLE_MS  = 500;
const RESOURCE_POLL_MS  = 1000;
const MIN_SEGMENT_BYTES = 5000;
const VIDEO_HOST_RE     = /googlevideo\.com/;

// ─── state ────────────────────────────────────────────────────────────────────

let session      = null;
let bufTimer     = null;
let resTimer     = null;
let attachTimer  = null;
let attachTries  = 0;
let saved        = false;

// ─── helpers ─────────────────────────────────────────────────────────────────

function makeUUID() {
    return crypto.randomUUID
        ? crypto.randomUUID()
        : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, c => {
            const r = Math.random() * 16 | 0;
            return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
        });
}

function nowISO() {
    return new Date().toISOString().replace('T', ' ').slice(0, 19);
}

function getRes(player) {
    return QUALITY_HEIGHT[player.getPlaybackQuality()] || 0;
}

function frameOf(video) {
    return typeof video.webkitDecodedFrameCount === 'number'
        ? video.webkitDecodedFrameCount
        : Math.round(video.currentTime * 30);
}

// ─── session ──────────────────────────────────────────────────────────────────

function startSession(player, video, pageLoadMs) {
    const vd      = player.getVideoData() || {};
    const videoId = vd.video_id || new URLSearchParams(location.search).get('v') || '';

    session = {
        videoId,
        uuid:              makeUUID(),
        timestamp:         nowISO(),
        browserInfo:       navigator.userAgent,
        osInfo:            navigator.platform,
        timeSincePageLoad: +((pageLoadMs) / 1000).toFixed(3),

        watchRanges:     [],
        frameRanges:     [],
        rangeStart:      null,
        rangeStartFrame: null,
        lastTime:        null,
        lastFrame:       null,
        lastRes:         null,

        stallDiffs:  [],
        stallTimes:  [],
        stallStart:  null,
        stallVideoT: null,

        bufferSamples:    [],
        segmentDownloads: [],
        seenUrls:         new Set(),
    };

    console.log('[YT-Trace/collector] session started for', videoId);
}

// ─── watch ranges ─────────────────────────────────────────────────────────────

function onTimeUpdate(player, video) {
    if (!session) return;
    const t   = video.currentTime;
    const res = getRes(player);
    const fr  = frameOf(video);

    if (session.rangeStart === null) {
        session.rangeStart      = t;
        session.rangeStartFrame = fr;
        session.lastRes         = res;
    } else if (res !== session.lastRes) {
        session.watchRanges.push([+session.rangeStart.toFixed(6), +session.lastTime.toFixed(6), session.lastRes]);
        session.frameRanges.push([session.rangeStartFrame, session.lastFrame, session.lastRes]);
        session.rangeStart      = t;
        session.rangeStartFrame = fr;
        session.lastRes         = res;
    }
    session.lastTime  = t;
    session.lastFrame = fr;
}

function closeRange() {
    if (!session || session.rangeStart === null || session.lastTime === null) return;
    session.watchRanges.push([+session.rangeStart.toFixed(6), +session.lastTime.toFixed(6), session.lastRes]);
    session.frameRanges.push([session.rangeStartFrame, session.lastFrame, session.lastRes]);
    session.rangeStart = null;
}

// ─── stalls ───────────────────────────────────────────────────────────────────

function onWaiting(video) {
    if (!session || session.stallStart !== null) return;
    session.stallStart  = performance.now();
    session.stallVideoT = video.currentTime;
}

function onPlaying() {
    if (!session || session.stallStart === null) return;
    session.stallDiffs.push(+(performance.now() - session.stallStart).toFixed(0));
    session.stallTimes.push(+session.stallVideoT.toFixed(6));
    session.stallStart  = null;
    session.stallVideoT = null;
}

// ─── buffer ───────────────────────────────────────────────────────────────────

function sampleBuffer(video) {
    if (!session) return;
    const t = video.currentTime;
    let buffered = 0;
    for (let i = 0; i < video.buffered.length; i++) {
        if (video.buffered.start(i) <= t && t <= video.buffered.end(i)) {
            buffered = video.buffered.end(i) - t;
            break;
        }
    }
    session.bufferSamples.push([+t.toFixed(3), +buffered.toFixed(3)]);
}

// ─── resource timing ─────────────────────────────────────────────────────────

function pollResources(player) {
    if (!session) return;
    for (const e of performance.getEntriesByType('resource')) {
        if (session.seenUrls.has(e.name))           continue;
        if (!VIDEO_HOST_RE.test(e.name))             continue;
        if ((e.transferSize || 0) < MIN_SEGMENT_BYTES &&
            (e.decodedBodySize || 0) < MIN_SEGMENT_BYTES) continue;

        session.seenUrls.add(e.name);
        const bytes      = e.transferSize || e.decodedBodySize || 0;
        const downloadMs = +e.duration.toFixed(1);
        const latencyMs  = +(e.responseStart - e.requestStart).toFixed(1);
        const bwKbps     = downloadMs > 0 ? +((bytes * 8) / downloadMs).toFixed(1) : 0;

        session.segmentDownloads.push({
            videoTime:     +(player.getCurrentTime()).toFixed(3),
            quality:       player.getPlaybackQuality(),
            transferBytes: bytes,
            downloadMs,
            latencyMs,
            bandwidthKbps: bwKbps,
        });
    }
}

// ─── derive network periods ───────────────────────────────────────────────────

function deriveNetworkPeriods(downloads) {
    if (!downloads.length) return [];
    const BUCKET_S = 5;
    const buckets  = {};
    for (const d of downloads) {
        const k = Math.floor(d.videoTime / BUCKET_S) * BUCKET_S;
        (buckets[k] = buckets[k] || []).push(d);
    }
    return Object.keys(buckets).sort((a, b) => a - b).map(k => {
        const ds  = buckets[k];
        const bw  = ds.reduce((s, d) => s + d.bandwidthKbps, 0) / ds.length;
        const lat = ds.reduce((s, d) => s + d.latencyMs, 0) / ds.length;
        return { duration_ms: BUCKET_S * 1000, bandwidth_kbps: +bw.toFixed(1), latency_ms: +lat.toFixed(1) };
    });
}

// ─── save ─────────────────────────────────────────────────────────────────────

const LS_KEY = '__ytTracePending';

function buildRow(video) {
    closeRange();
    return {
        browserInfo:            session.browserInfo,
        osInfo:                 session.osInfo,
        timeSincePageLoad:      session.timeSincePageLoad,
        modified:               1,
        uuid:                   session.uuid,
        stallDiffsString:       JSON.stringify(session.stallDiffs),
        videoId:                session.videoId,
        timestamp:              session.timestamp,
        totalWatchTimeSeconds:  +(video.currentTime).toFixed(6),
        watchRangeFrames:       JSON.stringify(session.frameRanges),
        watchRangeSeconds:      JSON.stringify(session.watchRanges),
        stallTimesString:       JSON.stringify(session.stallTimes),
        bufferSamplesString:    JSON.stringify(session.bufferSamples),
        networkPeriodsString:   JSON.stringify(deriveNetworkPeriods(session.segmentDownloads)),
        segmentDownloadsString: JSON.stringify(session.segmentDownloads),
    };
}

function saveSession(video) {
    if (!session || saved) return;
    saved = true;

    const row = buildRow(video);

    // 1. Write to localStorage synchronously — survives tab close, read by bridge.js on next load
    try {
        const pending = JSON.parse(localStorage.getItem(LS_KEY) || '[]');
        pending.push(row);
        localStorage.setItem(LS_KEY, JSON.stringify(pending));
    } catch (e) { /* storage full — ignore */ }

    // 2. Clean up checkpoint key now that we have the final row
    try { localStorage.removeItem(LS_KEY + '_ckpt_' + session.uuid); } catch (e) {}

    // 3. Also postMessage for same-session delivery (SPA navigation, video end)
    window.postMessage({ __ytTrace: true, action: 'save', row }, '*');

    console.log('[YT-Trace/collector] saved for', session.videoId,
        '— ranges:', session.watchRanges.length,
        'stalls:', session.stallDiffs.length,
        'segments:', session.segmentDownloads.length);
}

// Periodic checkpoint every 30 s so long sessions aren't lost on unexpected tab close
let checkpointTimer = null;
function startCheckpoint(video) {
    checkpointTimer = setInterval(() => {
        if (!session || saved) return;
        try {
            const snapshot = buildRow(video);
            // Mark as checkpoint (not final) so bridge knows to overwrite, not append
            snapshot.__checkpoint = true;
            snapshot.__checkpointUUID = session.uuid;
            localStorage.setItem(LS_KEY + '_ckpt_' + session.uuid, JSON.stringify(snapshot));
        } catch (e) {}
    }, 30000);
}

// ─── teardown ────────────────────────────────────────────────────────────────

function teardown() {
    clearInterval(bufTimer);
    clearInterval(resTimer);
    clearInterval(checkpointTimer);
    clearTimeout(attachTimer);
    bufTimer = resTimer = checkpointTimer = null;
}

// ─── attach ───────────────────────────────────────────────────────────────────

const pageLoadMs = performance.now();

function attach() {
    if (!location.pathname.startsWith('/watch')) return;

    const player = document.querySelector('#movie_player');
    const video  = document.querySelector('video');
    const hasAPI = player && typeof player.getPlaybackQuality === 'function';

    if (!player || !video || !hasAPI) {
        attachTries++;
        if (attachTries <= 30) {
            attachTimer = setTimeout(attach, 600);
        } else {
            console.warn('[YT-Trace/collector] gave up — player=', !!player,
                'video=', !!video, 'api=', hasAPI);
        }
        return;
    }

    attachTries = 0;
    saved = false;
    startSession(player, video, pageLoadMs);

    video.addEventListener('timeupdate', () => onTimeUpdate(player, video));
    video.addEventListener('waiting',    () => onWaiting(video));
    video.addEventListener('playing',    onPlaying);
    video.addEventListener('play',       onPlaying);
    video.addEventListener('ended',      () => { saveSession(video); teardown(); });

    bufTimer = setInterval(() => sampleBuffer(video),        BUFFER_SAMPLE_MS);
    resTimer = setInterval(() => pollResources(player),      RESOURCE_POLL_MS);
    startCheckpoint(video);

    const leave = () => { saveSession(video); teardown(); };
    window.addEventListener('beforeunload',        leave, { once: true });
    document.addEventListener('yt-navigate-start', leave, { once: true });
}

// ─── SPA navigation ───────────────────────────────────────────────────────────

document.addEventListener('yt-navigate-finish', () => {
    console.log('[YT-Trace/collector] yt-navigate-finish ->', location.pathname);
    teardown();
    session = null;
    saved   = false;
    attachTries = 0;
    if (location.pathname.startsWith('/watch')) {
        attachTimer = setTimeout(attach, 1000);
    }
});

// Direct load of a watch page
if (location.pathname.startsWith('/watch')) {
    attachTimer = setTimeout(attach, 1000);
}
