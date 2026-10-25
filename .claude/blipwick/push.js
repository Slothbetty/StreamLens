// What a blipwick push looks like, and how it reaches ntfy.
//
// Shared by every adapter: the Claude Code plugin (hooks/register.ts) and the
// browser extension (extension/). Plain ESM with no I/O and no platform APIs
// beyond crypto, so each runtime loads this file as-is and only brings its own
// fetch and its own storage.

export const MAX_MESSAGE = 400

export const DEFAULT_SERVER = 'https://ntfy.sh'

/** @typedef {{ title: string, message: string, tags: string[], priority: number }} Push */

/** @typedef {'all' | 'input-and-errors' | 'errors'} NotifyOn */

/** Cut a message down to what fits in a push, keeping whole characters. */
export function clip(text, max = MAX_MESSAGE) {
  return text.length > max ? `${text.slice(0, max - 1)}…` : text
}

/** The last segment of a path, for telling sessions apart in a push title. */
export function basename(path, fallback) {
  if (!path) return fallback
  const parts = path.split(/[\\/]+/).filter(Boolean)
  return parts[parts.length - 1] || path
}

export function formatDuration(ms) {
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  return m < 60 ? `${m}m ${s % 60}s` : `${Math.floor(m / 60)}h ${m % 60}m`
}

/** A topic nobody can guess, from an alphabet without look-alike characters. */
export function randomId(length) {
  const alphabet = 'abcdefghijkmnpqrstuvwxyz23456789'
  const bytes = crypto.getRandomValues(new Uint8Array(length))
  return Array.from(bytes, b => alphabet[b % alphabet.length]).join('')
}

export function normalizeServer(server) {
  return String(server || DEFAULT_SERVER).trim().replace(/\/+$/, '') || DEFAULT_SERVER
}

export function errorText(err) {
  return err instanceof Error ? err.message : String(err)
}

/** @returns {NotifyOn} */
export function normalizeNotifyOn(value) {
  const notifyOn = String(value || 'all')
  return notifyOn === 'errors' || notifyOn === 'input-and-errors' ? notifyOn : 'all'
}

// The pushes blipwick sends, so every adapter words them the same way.
//
// `about` says which assistant and which session this is:
//   where   - what tells one session from another, and opens every title: a
//             project folder for Claude Code, a conversation title for ChatGPT
//   agent   - the name in the title ("Claude", "ChatGPT")
//   product - the name in the fallback body ("Claude Code", "ChatGPT")

/** @typedef {{ where: string, agent: string, product: string }} About */

/** @returns {Push} */
export function finishedPush(about, message, tookMs) {
  const took = Number.isFinite(tookMs) ? ` (${formatDuration(tookMs)})` : ''
  return {
    title: `${about.where}: ${about.agent} finished${took}`,
    message: message?.trim() || `${about.product} is done and waiting for you.`,
    tags: ['white_check_mark'],
    priority: 3,
  }
}

/** @returns {Push} */
export function needsInputPush(about, title, message) {
  return {
    title: `${about.where}: ${title || `${about.agent} needs your input`}`,
    message: message || `${about.product} is waiting for you.`,
    tags: ['bell'],
    priority: 4,
  }
}

/** @returns {Push} */
export function errorPush(about, reason, details) {
  return {
    title: `${about.where}: ${about.agent} stopped - ${reason}`,
    message: details || reason,
    tags: ['warning'],
    priority: 5,
  }
}

/** @returns {Push} */
export function testPush(what) {
  return {
    title: 'blipwick is working',
    message: `You will get a push here when ${what}.`,
    tags: ['tada'],
    priority: 3,
  }
}

/**
 * The HTTP request that publishes one push, as plain data. Adapters pass it to
 * whatever fetch they have: `$.http.fetch` in the plugin, the service worker's
 * own `fetch` in the extension (where the page's CSP does not apply).
 */
export function ntfyRequest(server, token, topic, push) {
  const headers = { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Bearer ${token}`
  return {
    url: normalizeServer(server),
    init: {
      method: 'POST',
      headers,
      body: JSON.stringify({ topic, ...push, message: clip(push.message) }),
    },
  }
}
