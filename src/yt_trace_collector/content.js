/**
 * YouTube Trace Collector — content script
 *
 * Captures per-session playback data and saves it to chrome.storage.local.
 * Each saved row matches the original CSV schema plus extra simulator fields:
 *
 *  Original fields (unchanged):
 *    browserInfo, osInfo, timeSincePageLoad, modified, uuid,
 *    stallDiffsString, videoId, timestamp, totalWatchTimeSeconds,
 *    watchRangeFrames, watchRangeSeconds
 *
 *  Extended fields (new — for simulator):
 *    stallTimesString      – video position (s) when each stall began
 *    bufferSamplesString   – [[videoTimeSec, bufferLevelSec], …] sampled every 500 ms
 *    networkPeriodsString  – [{duration_ms, bandwidth_kbps, latency_ms}, …]
 *                            derived from segment downloads; compatible with network.json
 *    segmentDownloadsString– [{videoTime, quality, transferBytes, downloadMs, latencyMs}, …]
 *                            one entry per downloaded segment; use to reconstruct movie.json
 */

'use strict';

// Confirm the script loaded at all — visible immediately on any YouTube page
console.log('[YT-Trace] content script loaded, path=', location.pathname);

// ─── constants ───────────────────────────────────────────────────────────────

const QUALITY_HEIGHT = {
    tiny: 144, small: 240, medium: 360,
    large: 480, hd720: 720, hd1080: 1080,
    hd1440: 1440, hd2160: 2160,
};

const BUFFER_SAMPLE_MS   = 500;   // how often to sample buffer level
const RESOURCE_POLL_MS   = 1000;  // how often to scan Resource Timing entries
const MIN_SEGMENT_BYTES  = 5000;  // ignore tiny requests (manifests, thumbnails, etc.)
// YouTube video segments come from these hostnames
const VIDEO_HOST_RE      = /googlevideo\.com|videoplayback/;

// ─── state ───────────────────────────────────────────────────────────────────

let session   = null;
let bufTimer  = null;
let resTimer  = null;
let saved     = false;

// ─── helpers ─────────────────────────────────────────────────────────────────

function uuid() {
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

// Approximate frame number — Chrome exposes webkitDecodedFrameCount on <video>
function frameOf(video) {
    return typeof video.webkitDecodedFrameCount === 'number'
        ? video.webkitDecodedFrameCount
        : Math.round(video.currentTime * 30);
}

// ─── session init ─────────────────────────────────────────────────────────────

function startSession(player, video, pageLoadMs) {
    const vd      = player.getVideoData() || {};
    const videoId = vd.video_id
        || new URLSearchParams(location.search).get('v')
        || '';

    session = {
        videoId,
        uuid:              uuid(),
        timestamp:         nowISO(),
        browserInfo:       navigator.userAgent,
        osInfo:            navigator.platform,
        timeSincePageLoad: +(pageLoadMs / 1000).toFixed(3),

        // watch ranges
        watchRanges:    [],   // [[startSec, endSec, heightPx], …]
        frameRanges:    [],   // [[startFrame, endFrame, heightPx], …]
        rangeStart:     null,
        rangeStartFrame:null,
        lastTime:       null,
        lastFrame:      null,
        lastRes:        null,

        // stalls
        stallDiffs:  [],   // durations ms
        stallTimes:  [],   // video position s when stall began
        stallStart:  null, // wall-clock ms
        stallVideoT: null, // video time s when stall began

        // buffer
        bufferSamples: [],  // [[videoTimeSec, bufLevelSec], …]

        // network / segments
        segmentDownloads: [],  // enriched Resource Timing entries
        seenUrls:         new Set(),
    };

    console.log('[YT-Trace] session started', videoId);
}

// ─── watch-range tracking ─────────────────────────────────────────────────────

function onTimeUpdate(player, video) {
    if (!session) return;
    const t   = video.currentTime;
    const res = getRes(player);
    const fr  = frameOf(video);

    if (session.rangeStart === null) {
        // first tick — open first range
        session.rangeStart      = t;
        session.rangeStartFrame = fr;
        session.lastRes         = res;
    } else if (res !== session.lastRes) {
        // quality changed — close current range, open new one
        session.watchRanges.push([
            +session.rangeStart.toFixed(6),
            +session.lastTime.toFixed(6),
            session.lastRes,
        ]);
        session.frameRanges.push([
            session.rangeStartFrame,
            session.lastFrame,
            session.lastRes,
        ]);
        session.rangeStart      = t;
        session.rangeStartFrame = fr;
        session.lastRes         = res;
    }

    session.lastTime  = t;
    session.lastFrame = fr;
}

function closeCurrentRange() {
    if (!session || session.rangeStart === null) return;
    session.watchRanges.push([
        +session.rangeStart.toFixed(6),
        +session.lastTime.toFixed(6),
        session.lastRes,
    ]);
    session.frameRanges.push([
        session.rangeStartFrame,
        session.lastFrame,
        session.lastRes,
    ]);
    session.rangeStart = null;
}

// ─── stall tracking ───────────────────────────────────────────────────────────

function onWaiting(video) {
    if (!session || session.stallStart !== null) return;
    session.stallStart  = performance.now();
    session.stallVideoT = video.currentTime;
}

function onPlaying() {
    if (!session || session.stallStart === null) return;
    const dur = performance.now() - session.stallStart;
    session.stallDiffs.push(+dur.toFixed(0));
    session.stallTimes.push(+session.stallVideoT.toFixed(6));
    session.stallStart  = null;
    session.stallVideoT = null;
}

// ─── buffer sampling ─────────────────────────────────────────────────────────

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

// ─── Resource Timing (segment downloads) ─────────────────────────────────────
// Captures size + download time for each video segment fetched by the player.
// YouTube sends Timing-Allow-Origin: * so transferSize is non-zero cross-origin.

function pollResourceTiming(player) {
    if (!session) return;
    const entries = performance.getEntriesByType('resource');
    for (const e of entries) {
        if (session.seenUrls.has(e.name)) continue;
        if (!VIDEO_HOST_RE.test(e.name))  continue;
        if (e.transferSize < MIN_SEGMENT_BYTES) continue;

        session.seenUrls.add(e.name);

        const downloadMs = +(e.duration).toFixed(1);
        const latencyMs  = +(e.responseStart - e.requestStart).toFixed(1);
        const bytes      = e.transferSize || e.decodedBodySize || 0;
        const bwKbps     = downloadMs > 0
            ? +((bytes * 8) / downloadMs).toFixed(1)   // bits/ms = kbit/s
            : 0;

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

// ─── derive network.json-compatible periods from segment downloads ────────────

function deriveNetworkPeriods(downloads) {
    // Group into ~5-second buckets and average bandwidth/latency per bucket.
    if (downloads.length === 0) return [];
    const BUCKET_S = 5;
    const buckets  = {};
    for (const d of downloads) {
        const key = Math.floor(d.videoTime / BUCKET_S) * BUCKET_S;
        if (!buckets[key]) buckets[key] = [];
        buckets[key].push(d);
    }
    return Object.keys(buckets)
        .sort((a, b) => a - b)
        .map(k => {
            const ds  = buckets[k];
            const bw  = ds.reduce((s, d) => s + d.bandwidthKbps, 0) / ds.length;
            const lat = ds.reduce((s, d) => s + d.latencyMs, 0)     / ds.length;
            return {
                duration_ms:    BUCKET_S * 1000,
                bandwidth_kbps: +bw.toFixed(1),
                latency_ms:     +lat.toFixed(1),
            };
        });
}

// ─── save completed session ───────────────────────────────────────────────────

function saveSession(video) {
    if (!session || saved) return;
    saved = true;

    closeCurrentRange();

    const networkPeriods = deriveNetworkPeriods(session.segmentDownloads);

    const row = {
        // ── original fields ──────────────────────────────────────────
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

        // ── extended fields (simulator) ──────────────────────────────
        stallTimesString:       JSON.stringify(session.stallTimes),
        bufferSamplesString:    JSON.stringify(session.bufferSamples),
        networkPeriodsString:   JSON.stringify(networkPeriods),
        segmentDownloadsString: JSON.stringify(session.segmentDownloads),
    };

    chrome.storage.local.get({ traces: [] }, data => {
        data.traces.push(row);
        chrome.storage.local.set({ traces: data.traces }, () => {
            console.log('[YT-Trace] saved trace for', session.videoId,
                        '—', data.traces.length, 'total');
        });
    });
}

// ─── teardown ────────────────────────────────────────────────────────────────

function teardown() {
    clearInterval(bufTimer);
    clearInterval(resTimer);
}

// ─── main: wait for player + video element ────────────────────────────────────

const pageLoadMs = performance.now();
let attachTimer  = null;
let attachAttempts = 0;

function attach() {
    // Only collect on watch pages
    if (!location.pathname.startsWith('/watch')) return;

    const player = document.querySelector('#movie_player');
    const video  = document.querySelector('video');
    const hasAPI = player && typeof player.getPlaybackQuality === 'function';

    console.log(`[YT-Trace] attach attempt ${attachAttempts + 1}:`,
        'player=', !!player, 'video=', !!video, 'api=', hasAPI);

    // Player not ready yet — retry up to ~15 seconds
    if (!player || !video || !hasAPI) {
        attachAttempts++;
        if (attachAttempts < 25) {
            attachTimer = setTimeout(attach, 600);
        } else {
            console.warn('[YT-Trace] gave up waiting for player after 15s.',
                'player=', !!player, 'video=', !!video, 'api=', hasAPI);
        }
        return;
    }

    attachAttempts = 0;
    startSession(player, video, pageLoadMs);
    saved = false;

    // watch ranges + quality
    video.addEventListener('timeupdate', () => onTimeUpdate(player, video));

    // stalls
    video.addEventListener('waiting', () => onWaiting(video));
    video.addEventListener('playing', onPlaying);
    video.addEventListener('play',    onPlaying);  // catches initial play too

    // end of video
    video.addEventListener('ended', () => {
        saveSession(video);
        teardown();
    });

    // buffer sampling
    bufTimer = setInterval(() => sampleBuffer(video), BUFFER_SAMPLE_MS);

    // resource timing polling
    resTimer = setInterval(() => pollResourceTiming(player), RESOURCE_POLL_MS);

    // Save when navigating away — YouTube is a SPA so both events matter
    const saveOnLeave = () => { saveSession(video); teardown(); };
    window.addEventListener('beforeunload',        saveOnLeave, { once: true });
    document.addEventListener('yt-navigate-start', saveOnLeave, { once: true });

    console.log('[YT-Trace] attached to', player.getVideoData()?.video_id);
}

// Re-attach on every SPA navigation (homepage → watch, watch → watch, etc.)
document.addEventListener('yt-navigate-finish', () => {
    console.log('[YT-Trace] yt-navigate-finish, path=', location.pathname);
    clearTimeout(attachTimer);
    teardown();
    session        = null;
    saved          = false;
    attachAttempts = 0;

    if (!location.pathname.startsWith('/watch')) return;
    attachTimer = setTimeout(attach, 1000);
});

// Also handle a direct load of a /watch URL (full page load, no yt-navigate-finish)
if (location.pathname.startsWith('/watch')) {
    console.log('[YT-Trace] direct watch page load, scheduling attach');
    attachTimer = setTimeout(attach, 1000);
}
