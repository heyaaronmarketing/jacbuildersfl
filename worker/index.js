/**
 * jacbuildersfl.com — site worker.
 *
 *   POST   /api/roofle/webhook   Roofle callback URL. Always answers 200 fast.
 *   GET    /api/roofle/events    Recent deliveries. Gated by ROOFLE_LAB_TOKEN.
 *   POST   /api/roofle/test      Inject a synthetic delivery. Gated.
 *   DELETE /api/roofle/events    Clear the log. Gated.
 *   GET    /api/health           Build probe. No secrets.
 *
 * Everything else falls through to the static mirror in site/.
 *
 * Storage is OPTIONAL by design so this deploys before any binding exists:
 * with a D1 binding named DB deliveries persist, without one they live in an
 * in-isolate ring buffer that survives only as long as the isolate. The lab UI
 * reports which store is active so nobody mistakes the scratch buffer for a
 * durable record. See ROOFLE.md for the one command that upgrades it.
 */

const JSON_HEADERS = { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' };
const MAX_BODY = 64 * 1024;   // a lead payload is a few KB; this is a spam cap
const MEM_LIMIT = 50;

// Ephemeral fallback store. Module scope = per isolate, not shared, not durable.
let MEM = [];

function json(body, status = 200, extra = {}) {
  return new Response(JSON.stringify(body, null, 2), {
    status,
    headers: { ...JSON_HEADERS, ...extra },
  });
}

/** Constant-time string compare so a token cannot be guessed byte by byte. */
function safeEqual(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string') return false;
  const enc = new TextEncoder();
  const x = enc.encode(a);
  const y = enc.encode(b);
  if (x.length !== y.length) return false;
  let diff = 0;
  for (let i = 0; i < x.length; i++) diff |= x[i] ^ y[i];
  return diff === 0;
}

/* ---------------------------------------------------------------- storage -- */

async function ensureTable(env) {
  await env.DB.exec(
    'CREATE TABLE IF NOT EXISTS roofle_events (' +
    'id TEXT PRIMARY KEY, at TEXT NOT NULL, verified INTEGER NOT NULL, ' +
    'verified_by TEXT, source TEXT, content_type TEXT, event TEXT, payload TEXT)'
  );
}

async function putEvent(env, row) {
  if (!env.DB) {
    MEM.unshift(row);
    MEM = MEM.slice(0, MEM_LIMIT);
    return 'memory';
  }
  await ensureTable(env);
  await env.DB.prepare(
    'INSERT INTO roofle_events (id, at, verified, verified_by, source, content_type, event, payload) ' +
    'VALUES (?,?,?,?,?,?,?,?)'
  ).bind(
    row.id, row.at, row.verified ? 1 : 0, row.verifiedBy,
    row.source, row.contentType, row.event, JSON.stringify(row.payload)
  ).run();
  return 'd1';
}

async function listEvents(env, limit) {
  if (!env.DB) return { store: 'memory', durable: false, events: MEM.slice(0, limit) };
  await ensureTable(env);
  const { results } = await env.DB
    .prepare('SELECT * FROM roofle_events ORDER BY at DESC LIMIT ?')
    .bind(limit).all();
  return {
    store: 'd1',
    durable: true,
    events: (results || []).map((r) => ({
      id: r.id,
      at: r.at,
      verified: !!r.verified,
      verifiedBy: r.verified_by,
      source: r.source,
      contentType: r.content_type,
      event: r.event,
      payload: safeParse(r.payload),
    })),
  };
}

async function clearEvents(env) {
  if (!env.DB) { MEM = []; return 'memory'; }
  await ensureTable(env);
  await env.DB.exec('DELETE FROM roofle_events');
  return 'd1';
}

function safeParse(s) {
  try { return JSON.parse(s); } catch (e) { return s; }
}

/* ------------------------------------------------------------------ auth -- */

function labAuthorized(request, url, env) {
  if (!env.ROOFLE_LAB_TOKEN) return 'unconfigured';
  const supplied =
    request.headers.get('x-lab-token') ||
    (request.headers.get('authorization') || '').replace(/^Bearer\s+/i, '') ||
    url.searchParams.get('token') || '';
  return safeEqual(supplied, env.ROOFLE_LAB_TOKEN) ? 'ok' : 'denied';
}

function labGate(request, url, env) {
  const state = labAuthorized(request, url, env);
  if (state === 'ok') return null;
  if (state === 'unconfigured') {
    return json({
      error: 'not_configured',
      message:
        'Set the ROOFLE_LAB_TOKEN secret on this Worker, then reload the lab ' +
        'and paste the same value. Reads stay closed until then because ' +
        'deliveries contain homeowner contact details.',
    }, 503);
  }
  return json({ error: 'unauthorized' }, 401);
}

/**
 * Roofle's auth mechanism for outbound webhooks is not published, so rather
 * than assume one shape we check the usual carriers and record which (if any)
 * matched. Once a real delivery lands, the lab shows the exact headers and the
 * check can be narrowed to just that one.
 */
function verify(request, url, env) {
  const secret = env.ROOFLE_WEBHOOK_SECRET;
  if (!secret) return { verified: false, verifiedBy: 'no-secret-configured' };
  const candidates = [
    ['x-roofle-signature', request.headers.get('x-roofle-signature')],
    ['x-roofle-token', request.headers.get('x-roofle-token')],
    ['x-webhook-token', request.headers.get('x-webhook-token')],
    ['authorization', (request.headers.get('authorization') || '').replace(/^Bearer\s+/i, '')],
    ['query:token', url.searchParams.get('token')],
  ];
  for (const [name, value] of candidates) {
    if (value && safeEqual(value, secret)) return { verified: true, verifiedBy: name };
  }
  return { verified: false, verifiedBy: 'no-match' };
}

/* --------------------------------------------------------------- handlers -- */

async function readBody(request) {
  const contentType = request.headers.get('content-type') || '';
  const raw = await request.text();
  if (raw.length > MAX_BODY) return { contentType, payload: null, tooLarge: true };
  if (contentType.includes('application/json')) {
    try { return { contentType, payload: JSON.parse(raw) }; }
    catch (e) { return { contentType, payload: { _unparsed: raw } }; }
  }
  if (contentType.includes('application/x-www-form-urlencoded')) {
    return { contentType, payload: Object.fromEntries(new URLSearchParams(raw)) };
  }
  return { contentType, payload: raw ? { _raw: raw } : {} };
}

async function handleWebhook(request, url, env, ctx) {
  const { contentType, payload, tooLarge } = await readBody(request);
  if (tooLarge) return json({ ok: false, error: 'payload_too_large' }, 413);

  const { verified, verifiedBy } = verify(request, url, env);
  const row = {
    id: crypto.randomUUID(),
    at: new Date().toISOString(),
    verified,
    verifiedBy,
    source: request.headers.get('cf-connecting-ip') || 'unknown',
    contentType,
    // Roofle's discriminator is `webhookType` ("Address Only" | "Contact Form
    // Completed" | "Product Requested"); the rest are fallbacks for test posts.
    event: (payload && (payload.webhookType || payload.event || payload.type)) || 'webhook',
    payload,
    headers: Object.fromEntries(
      [...request.headers].filter(([k]) => !/^(cookie|authorization)$/i.test(k))
    ),
  };

  // Answer Roofle before doing storage work: a slow 200 invites retries, and a
  // storage failure must never turn into a failed delivery on their side.
  ctx.waitUntil(
    putEvent(env, row).catch((e) => console.error('roofle store failed', e.message))
  );
  console.log('roofle webhook', JSON.stringify({ id: row.id, event: row.event, verified }));
  return json({ ok: true, id: row.id, received: row.at });
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, '') || '/';

    if (path === '/api/health') {
      return json({
        ok: true,
        worker: 'jacbuildersfl',
        time: new Date().toISOString(),
        storage: env.DB ? 'd1' : 'memory (ephemeral — no D1 binding)',
        labTokenConfigured: !!env.ROOFLE_LAB_TOKEN,
        webhookSecretConfigured: !!env.ROOFLE_WEBHOOK_SECRET,
      });
    }

    if (path === '/api/roofle/webhook') {
      if (request.method === 'GET') {
        // Lets Roofle (and you) confirm the URL resolves before saving it.
        return json({ ok: true, message: 'Roofle callback endpoint. POST here.' });
      }
      if (request.method !== 'POST') return json({ error: 'method_not_allowed' }, 405);
      return handleWebhook(request, url, env, ctx);
    }

    if (path === '/api/roofle/events') {
      const denied = labGate(request, url, env);
      if (denied) return denied;
      if (request.method === 'DELETE') {
        return json({ ok: true, cleared: await clearEvents(env) });
      }
      const limit = Math.min(Number(url.searchParams.get('limit')) || 25, 100);
      return json(await listEvents(env, limit));
    }

    if (path === '/api/roofle/test' && request.method === 'POST') {
      const denied = labGate(request, url, env);
      if (denied) return denied;
      const { contentType, payload } = await readBody(request);
      const row = {
        id: crypto.randomUUID(),
        at: new Date().toISOString(),
        verified: true,
        verifiedBy: 'lab-test',
        source: 'lab',
        contentType,
        event: (payload && payload.event) || 'lab-test',
        payload,
        headers: {},
      };
      const store = await putEvent(env, row);
      return json({ ok: true, id: row.id, store });
    }

    return env.ASSETS.fetch(request);
  },
};
