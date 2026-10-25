// The cloud adapter. Cloud sessions don't load plugins, but they do fire the
// same hook events and they do read the repo's .claude/settings.json, so this
// runs as a plain command hook instead.
//
// One copy of this file and push.js lives in each repo you want notified, under
// .claude/blipwick/. See cloud/README.md.
//
// It reads one hook event as JSON on stdin and always exits 0: on Stop, exit 2
// would tell Claude to keep going, and any other non-zero code is reported as a
// hook error. A missed push must never get in the way of the session.

import { readFile, unlink, writeFile } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import {
  basename,
  errorPush,
  errorText,
  finishedPush,
  needsInputPush,
  normalizeNotifyOn,
  normalizeServer,
  ntfyRequest,
} from './push.js'

const ERROR_TEXT = {
  rate_limit: 'Rate limited',
  overloaded: 'API overloaded',
  billing_error: 'Billing problem',
  authentication_failed: 'Authentication failed',
  invalid_request: 'Invalid request',
  max_output_tokens: 'Hit the output token limit',
  server_error: 'API server error',
  unknown: 'Unknown error',
}

function config() {
  return {
    topic: String(process.env.NTFY_TOPIC || '').trim(),
    server: normalizeServer(process.env.NTFY_SERVER),
    token: String(process.env.NTFY_TOKEN || '').trim(),
    notifyOn: normalizeNotifyOn(process.env.BLIPWICK_NOTIFY_ON),
    minTurnMs: Math.max(0, Number(process.env.BLIPWICK_MIN_TURN_SECONDS) || 0) * 1000,
  }
}

async function readEvent(stream) {
  let raw = ''
  stream.setEncoding('utf8')
  for await (const chunk of stream) raw += chunk
  return JSON.parse(raw)
}

// Classic hooks have no turn.start, so the prompt that opened the turn leaves a
// timestamp behind for Stop to pick up. Keyed by session so parallel sessions
// in one sandbox don't read each other's.
function startFile(sessionId) {
  const safe = String(sessionId || 'unknown').replace(/[^\w-]/g, '')
  return join(tmpdir(), `blipwick-${safe}.start`)
}

async function markTurnStart(event) {
  await writeFile(startFile(event.session_id), String(Date.now()))
}

async function takeTurnStart(event) {
  const path = startFile(event.session_id)
  try {
    const started = Number(await readFile(path, 'utf8'))
    await unlink(path).catch(() => {})
    return Number.isFinite(started) ? Date.now() - started : Infinity
  } catch {
    return Infinity // No mark: treat the turn as long enough to report.
  }
}

function where(event) {
  return basename(event.cwd, 'Claude Code')
}

const ABOUT_AGENT = { agent: 'Claude', product: 'Claude Code' }

function about(event) {
  return { where: where(event), ...ABOUT_AGENT }
}

export async function pushFor(event, cfg) {
  switch (event.hook_event_name) {
    case 'Stop': {
      if (cfg.notifyOn !== 'all') return null
      const tookMs = await takeTurnStart(event)
      if (tookMs < cfg.minTurnMs) return null
      return finishedPush(about(event), event.last_assistant_message, tookMs)
    }
    case 'Notification': {
      if (cfg.notifyOn === 'errors') return null
      return needsInputPush(about(event), event.title, event.message)
    }
    case 'StopFailure': {
      await takeTurnStart(event)
      const reason = ERROR_TEXT[event.error] ?? `Error: ${event.error || 'unknown'}`
      const details = [event.error_details, event.last_assistant_message].filter(Boolean).join('\n\n')
      return errorPush(about(event), reason, details)
    }
    default:
      return null
  }
}

async function main() {
  // Local sessions already have the plugin. Without this the two would both
  // fire and you would get every notification twice.
  if (process.env.CLAUDE_CODE_REMOTE !== 'true' && process.env.BLIPWICK_FORCE !== '1') return

  const cfg = config()
  if (!cfg.topic) return // Nothing configured for this environment: stay quiet.

  const event = await readEvent(process.stdin)
  if (event.hook_event_name === 'UserPromptSubmit') return markTurnStart(event)

  const push = await pushFor(event, cfg)
  if (!push) return

  const { url, init } = ntfyRequest(cfg.server, cfg.token, cfg.topic, push)
  const res = await fetch(url, init)
  if (!res.ok) {
    const body = await res.text().catch(() => '')
    throw new Error(`ntfy answered ${res.status}: ${body.slice(0, 200)}`)
  }
}

main()
  .catch(err => {
    process.stderr.write(`blipwick: ${errorText(err)}\n`)
  })
  .finally(() => {
    process.exitCode = 0
  })
