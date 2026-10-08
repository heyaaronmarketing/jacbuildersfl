# Roofle quote form — implementation guide

A drop-in replacement for a JavaScript-embed Roofle quote form. Instead of
handing the visitor straight to Roofle's widget, you own the capture form —
address, email, phone — and hand off to Roofle with everything prefilled.

Reference implementation: `jacbuildersfl.aironz.workers.dev/quote-start/`.

---

## 1. Read this before you write any code

**Roofle has no inbound REST API.** You cannot POST form fields and get a
quote back. The widget *is* the quote engine — aerial measurement and pricing
happen inside their iframe. Their entire developer surface is:

| Surface | Direction | Use |
|---|---|---|
| Script embeds | — | The widget. Keyed by a public company **tool ID**. |
| `postMessage` events | Roofle to page | 7 funnel events, analytics only |
| **Deeplinks** | **you to Roofle** | **Prefill address + contact. This is what makes a custom form possible.** |
| Webhooks | Roofle to you | Lead + quote data posted to a callback URL |
| CRM connectors | Roofle to vendor | JobNimbus, ProLine, AccuLynx, SalesRabbit, Leap, RoofLink, Zapier |

So the architecture is: **your form captures, a deeplink hands off, Roofle
quotes, a webhook returns the lead to you.**

What you gain over the plain JS embed: your own branding and layout, your own
analytics on the capture step, attribution captured before the hand-off, and
the lead data on your own infrastructure.

What you do **not** gain: control of the quote UI itself. The map and the
pricing screens are Roofle's, inside a cross-origin iframe. You cannot restyle
or remove parts of them. If that is a requirement, this is the wrong vendor.

---

## 2. Two things you must have before starting

**1. The hosted-page slug.** Pro Portal, under the RoofQuote PRO hosted page.
It is **not** the widget tool ID. Deeplinks go to:

    https://offers.roofle.com/rqp/<slug>

Test against `https://offers.roofle.com/rqp/demo` while you wait for the real
one — it needs no credentials. **Use test addresses there**: anything you
submit creates a lead in Roofle's demo account, not yours.

**2. Domain whitelisting.** Roofle returns **403 from any host not on the
whitelist**, and fails silently — the script loads, logs its tool ID, then
renders nothing. Add every host you will test from (staging, workers.dev,
localhost) in Pro Portal, Settings, Developer. This only matters if you also
embed the widget; a pure deeplink hand-off is unaffected.

---

## 3. The deeplink contract

    https://offers.roofle.com/rqp/<slug>
      ?street1=400%20N%20Tampa%20St
      &city=Tampa
      &state=FL
      &postalCode=33602
      &email=someone%40example.com
      &phone=8135550142

| Param | Required | Notes |
|---|---|---|
| `street1` | yes | Street line only |
| `city` | yes | |
| `state` | yes | Two-letter abbreviation |
| `postalCode` | **yes** | Roofle will not run the lookup without it |
| `email` | no | Prefills their contact step |
| `phone` | no | Bare 10 digits |
| `firstName` / `lastName` | no | |
| `rep` | no | Assigns the lead to a rep by email |

### The gotcha that will cost you an afternoon

**Roofle reads `+` literally, not as a space.**

`URLSearchParams.toString()` encodes spaces as `+`, producing
`street1=400+N+Tampa+St`. Roofle never matches that and **fails silently** —
no error, the address box just comes up empty. Build the query by hand with
`encodeURIComponent`, which produces `%20`:

```js
function params(f) {
  return [
    "street1=" + encodeURIComponent(f.street1),
    "city=" + encodeURIComponent(f.city),
    "state=" + encodeURIComponent(f.state),
    "postalCode=" + encodeURIComponent(f.postalCode)
  ].join("&");
}
```

Verified both ways against the demo page: `+` leaves the field empty, `%20`
prefills correctly.

### Known-unverified

Address prefill is confirmed working. The `email` / `phone` prefill is
documented by Roofle and the params pass through without breaking anything,
but confirming it requires completing their contact step, which creates a real
lead. Verify it once against your own slug.

### What does NOT work

The **embedded widget URL** (`app.roofle.com/roof-quote-pro/<toolId>`) ignores
these params entirely — tested, the input stays empty. Deeplinks only work on
`offers.roofle.com/rqp/<slug>`.

---

## 4. Why the address needs a lookup service

Roofle needs `street1`, `city`, `state` and `postalCode` **separately**, and
will not search without the ZIP. But a one-line address field converts far
better than four boxes. So the form must turn one input into four components.

Two mechanisms, in order:

1. **Autocomplete** — the visitor picks a suggestion, which arrives already
   split. This is the happy path and should handle most traffic.
2. **Parse what was typed** — a fallback, never the contract (see section 6).

### Choosing a provider

- **Google Places** is the production answer. Needs a key and billing.
- **Photon** (`photon.komoot.io`) is keyless and built for type-ahead. Good
  enough for development; it is a free community service with no SLA, so do
  not ship a client site on it.
- **Do not use Nominatim.** Its usage policy forbids autocomplete. Fine for
  one-shot validation, never per-keystroke.

### Proxy it through your own server

Do not call the provider from the browser. Proxying lets you keep the API key
server-side, cache repeated prefixes (type-ahead is extremely repetitive —
measured 2.1s to 0.2s on a cache hit), and swap providers without touching the
page.

---

## 5. The code

### 5a. Autocomplete proxy

Cloudflare Worker module. Normalises any provider to one shape, so the page
never knows which is in use. Port `handleSuggest` to your own stack if you are
not on Workers; the shape of the contract is what matters.

```js
/**
 * Address autocomplete, proxied through the Worker.
 *
 * Proxying rather than calling a provider from the browser keeps any API key
 * server-side, lets us cache (type-ahead is request-heavy), and normalises
 * every provider to one shape so the page never knows which is in use.
 *
 * Provider is chosen by what is configured:
 *   GOOGLE_PLACES_API_KEY set -> Google Places (production path)
 *   otherwise                 -> Photon, keyless, fine for testing
 *
 * Deliberately NOT used: Nominatim. Its usage policy forbids autocomplete.
 */

const US_STATES = {
  alabama:'AL',alaska:'AK',arizona:'AZ',arkansas:'AR',california:'CA',colorado:'CO',
  connecticut:'CT',delaware:'DE',florida:'FL',georgia:'GA',hawaii:'HI',idaho:'ID',
  illinois:'IL',indiana:'IN',iowa:'IA',kansas:'KS',kentucky:'KY',louisiana:'LA',
  maine:'ME',maryland:'MD',massachusetts:'MA',michigan:'MI',minnesota:'MN',
  mississippi:'MS',missouri:'MO',montana:'MT',nebraska:'NE',nevada:'NV',
  'new hampshire':'NH','new jersey':'NJ','new mexico':'NM','new york':'NY',
  'north carolina':'NC','north dakota':'ND',ohio:'OH',oklahoma:'OK',oregon:'OR',
  pennsylvania:'PA','rhode island':'RI','south carolina':'SC','south dakota':'SD',
  tennessee:'TN',texas:'TX',utah:'UT',vermont:'VT',virginia:'VA',washington:'WA',
  'west virginia':'WV',wisconsin:'WI',wyoming:'WY','district of columbia':'DC',
};

function abbrev(state) {
  if (!state) return '';
  const s = String(state).trim();
  if (/^[A-Za-z]{2}$/.test(s)) return s.toUpperCase();
  return US_STATES[s.toLowerCase()] || '';
}

/** Roofle needs street1/city/state/postalCode, so a hit without a ZIP is useless. */
function usable(x) {
  return !!(x.street1 && x.city && x.state && x.postalCode);
}

function label(x) {
  return `${x.street1}, ${x.city}, ${x.state} ${x.postalCode}`;
}

/* ------------------------------------------------------------------ photon -- */
// Bias toward JAC's territory so Tampa/Orlando beat identically named streets
// elsewhere. Photon treats this as a hint, not a filter.
const BIAS = { lat: 27.99, lon: -82.3, zoom: 9 };

async function photon(q) {
  const u = new URL('https://photon.komoot.io/api');
  u.searchParams.set('q', q);
  u.searchParams.set('limit', '8');
  u.searchParams.set('lang', 'en');
  u.searchParams.set('lat', String(BIAS.lat));
  u.searchParams.set('lon', String(BIAS.lon));
  u.searchParams.set('zoom', String(BIAS.zoom));

  const r = await fetch(u, { headers: { Accept: 'application/json' } });
  if (!r.ok) throw new Error(`photon ${r.status}`);
  const data = await r.json();

  return (data.features || [])
    .map((f) => f.properties || {})
    .filter((p) => (p.countrycode || 'US') === 'US')
    .map((p) => ({
      street1: [p.housenumber, p.street || p.name].filter(Boolean).join(' ').trim(),
      city: p.city || p.town || p.village || p.district || '',
      state: abbrev(p.state),
      postalCode: p.postcode || '',
    }))
    .filter(usable);
}

/* ------------------------------------------------------------------ google -- */
/**
 * UNVERIFIED: written from the Places API (New) docs but never run — there is
 * no key on this account yet. Expect to debug it on first use. Autocomplete
 * returns placeId only, so each pick costs a second Details call; that is why
 * results are cached.
 */
async function google(q, key) {
  const r = await fetch('https://places.googleapis.com/v1/places:autocomplete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Goog-Api-Key': key },
    body: JSON.stringify({
      input: q,
      includedRegionCodes: ['us'],
      includedPrimaryTypes: ['street_address', 'premise', 'subpremise'],
      locationBias: {
        circle: {
          center: { latitude: BIAS.lat, longitude: BIAS.lon },
          radius: 150000.0,
        },
      },
    }),
  });
  if (!r.ok) throw new Error(`google autocomplete ${r.status}`);
  const data = await r.json();
  const ids = (data.suggestions || [])
    .map((s) => s.placePrediction && s.placePrediction.placeId)
    .filter(Boolean)
    .slice(0, 6);

  const details = await Promise.all(ids.map(async (id) => {
    const d = await fetch(
      `https://places.googleapis.com/v1/places/${encodeURIComponent(id)}?fields=addressComponents`,
      { headers: { 'X-Goog-Api-Key': key } }
    );
    if (!d.ok) return null;
    const j = await d.json();
    const get = (type, short) => {
      const c = (j.addressComponents || []).find((a) => (a.types || []).includes(type));
      return c ? (short ? c.shortText : c.longText) : '';
    };
    return {
      street1: [get('street_number'), get('route')].filter(Boolean).join(' ').trim(),
      city: get('locality') || get('sublocality') || get('postal_town'),
      state: abbrev(get('administrative_area_level_1', true)),
      postalCode: get('postal_code'),
    };
  }));

  return details.filter(Boolean).filter(usable);
}

/* ----------------------------------------------------------------- handler -- */

export async function handleSuggest(request, url, env) {
  const q = (url.searchParams.get('q') || '').trim();
  const headers = { 'Content-Type': 'application/json', 'Cache-Control': 'public, max-age=300' };
  if (q.length < 4) {
    return new Response(JSON.stringify({ provider: null, suggestions: [] }), { headers });
  }

  // Type-ahead repeats the same prefixes constantly; serve those from cache so
  // the upstream provider sees a fraction of the keystrokes.
  const cache = caches.default;
  const key = new Request(`${url.origin}/api/geo/suggest?q=${encodeURIComponent(q.toLowerCase())}`, request);
  const hit = await cache.match(key);
  if (hit) return hit;

  const provider = env.GOOGLE_PLACES_API_KEY ? 'google' : 'photon';
  let suggestions = [];
  try {
    suggestions = provider === 'google'
      ? await google(q, env.GOOGLE_PLACES_API_KEY)
      : await photon(q);
  } catch (e) {
    console.error('geo suggest failed', provider, e.message);
    return new Response(
      JSON.stringify({ provider, suggestions: [], error: 'provider_unavailable' }),
      { status: 200, headers: { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' } }
    );
  }

  // De-duplicate: providers happily return the same address twice.
  const seen = new Set();
  suggestions = suggestions.filter((s) => {
    const k = label(s).toLowerCase();
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  }).slice(0, 6).map((s) => ({ ...s, label: label(s) }));

  const res = new Response(JSON.stringify({ provider, suggestions }), { headers });
  await cache.put(key, res.clone());
  return res;
}
```

Wire it into your router:

```js
import { handleSuggest } from './geo.js';

if (path === '/api/geo/suggest' && request.method === 'GET') {
  return handleSuggest(request, url, env);
}
```

It returns:

```json
{ "provider": "photon",
  "suggestions": [
    { "street1": "400 North Tampa Street", "city": "Tampa",
      "state": "FL", "postalCode": "33602",
      "label": "400 North Tampa Street, Tampa, FL 33602" }
  ] }
```

### 5b. Capture log

Log the submission **before** the hand-off. The gap between your count and
Roofle's own `Address Only` webhook is the drop-off at the hand-off itself,
and it is the only way to see it.

```js
if (path === '/api/quote/start' && request.method === 'POST') {
  const body = await request.json().catch(() => ({}));
  const row = {
    id: crypto.randomUUID(),
    at: new Date().toISOString(),
    event: 'Form Address Submitted',
    payload: body,
  };
  ctx.waitUntil(store(env, row));   // D1, KV, or your own sink
  return new Response(JSON.stringify({ ok: true, id: row.id }), {
    headers: { 'Content-Type': 'application/json' },
  });
}
```

Logging must never delay the redirect. On the page it races a 1.2s timeout and
uses `keepalive: true` so it survives the navigation.

### 5c. The form page

Complete and self-contained — no build step, no dependencies. Replace the
brand tokens at the top of the style block, the logo, and the phone number.
The slug is served from `/api/health` as `offersSlug` and is overridable
per-browser from the test panel; delete that panel before launch.

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Start your roof quote | JAC Builders</title>
<meta name="description" content="Enter your address and see your roof replacement price.">
<meta name="robots" content="noindex,nofollow">
<link rel="preconnect" href="https://offers.roofle.com">
<link rel="stylesheet" href="/wp-content/uploads/elementor/google-fonts/css/poppins.css">
<style>
  :root{
    --gold:#D9BB71; --gold-dark:#c3a65d; --ink:#121316; --body:#4a5058;
    --line:#dfe2e7; --bg:#fff; --bg-alt:#f7f7f5; --bad:#D9534F; --ok:#5CB85C;
  }
  *,*::before,*::after{box-sizing:border-box}
  body{margin:0;background:var(--ink);color:var(--body);
       font:16px/1.6 Poppins,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;
       -webkit-font-smoothing:antialiased;min-height:100vh;
       display:flex;flex-direction:column}
  h1{color:#fff;font-size:clamp(1.75rem,4vw,2.6rem);line-height:1.15;margin:0 0 .4em;
     letter-spacing:-.015em;max-width:16ch}
  a{color:var(--gold)}
  .wrap{width:100%;max-width:620px;margin:0 auto;padding:0 20px}
  .top{padding:26px 0 0}
  .top img{height:42px;width:auto;display:block}
  main{flex:1;display:flex;align-items:center;padding:clamp(26px,5vw,52px) 0}
  .lede{color:#c6ccd4;font-size:1.03rem;margin:0 0 28px;max-width:46ch}
  .lede strong{color:#fff}

  .card{background:#fff;border-radius:14px;padding:clamp(20px,3vw,30px);
        box-shadow:0 18px 44px rgba(0,0,0,.3)}
  label{display:block;font-weight:600;color:var(--ink);font-size:.9rem;margin:0 0 6px}
  .hint{font-size:.82rem;color:#6d747d;margin:6px 0 0}
  input{
    width:100%;padding:15px 16px;border:1.5px solid var(--line);border-radius:10px;
    font:1.02rem/1.3 Poppins,system-ui,sans-serif;color:var(--ink);background:#fff;
  }
  input:focus{outline:0;border-color:var(--gold);box-shadow:0 0 0 3px rgba(217,187,113,.28)}
  input::placeholder{color:#9aa1aa}
  .ac{position:relative}
  .ac__list{
    position:absolute;z-index:20;left:0;right:0;top:calc(100% + 6px);margin:0;padding:6px;
    list-style:none;background:#fff;border:1px solid var(--line);border-radius:10px;
    box-shadow:0 14px 34px rgba(0,0,0,.18);max-height:286px;overflow-y:auto;
  }
  .ac__list[hidden]{display:none}
  .ac__opt{padding:11px 12px;border-radius:7px;cursor:pointer;font-size:.95rem;
           color:var(--ink);line-height:1.35}
  .ac__opt small{display:block;color:#6d747d;font-size:.8rem;margin-top:2px}
  .ac__opt[aria-selected="true"],.ac__opt:hover{background:var(--bg-alt)}
  .ac__status{padding:11px 12px;font-size:.88rem;color:#6d747d}
  .parts{display:grid;grid-template-columns:1fr 92px 120px;gap:10px}
  @media (max-width:520px){.parts{grid-template-columns:1fr 1fr;}.parts .city{grid-column:1/-1}}
  .sr-only{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);
           white-space:nowrap}
  .contact{margin-top:18px;padding-top:18px;border-top:1px solid var(--line)}
  .contact__row{display:grid;grid-template-columns:1fr 1fr;gap:12px}
  @media (max-width:520px){.contact__row{grid-template-columns:1fr}}
  .contact label{margin-bottom:6px}
  .result{margin-top:16px;border:1px solid var(--line);border-radius:10px;
          background:var(--bg-alt);padding:16px}
  .result__ok{margin:0 0 6px;font-weight:700;color:var(--ink);font-size:.98rem}
  .result__msg{margin:0;font-size:.88rem;color:#5c636c}
  .result__btns{margin-top:12px}
  .btn-sm{display:inline-block;background:var(--ink);color:#fff;text-decoration:none;
          font-weight:700;font-size:.88rem;padding:11px 18px;border-radius:8px}
  .btn-sm:hover{background:#2a2d33}
  #result-url{display:block;margin-top:10px;font-size:.73rem;color:#7b828b;word-break:break-all;
              font-family:ui-monospace,Menlo,Consolas,monospace;line-height:1.5}
  .err{color:var(--bad);font-size:.85rem;margin-top:10px;display:none}
  .err.on{display:block}
  input.bad{border-color:var(--bad)}

  .oneline{display:flex;gap:10px;align-items:stretch}
  .oneline .ac{flex:1 1 auto;min-width:0}
  .oneline button{width:auto;flex:0 0 auto;margin:0;padding:0 30px}
  @media (max-width:520px){
    .oneline{flex-direction:column}
    .oneline button{width:100%;padding:0}
  }
  button{
    width:100%;margin-top:16px;min-height:56px;border:0;border-radius:10px;cursor:pointer;
    background:var(--gold);color:var(--ink);font:700 1.05rem/1 Poppins,system-ui,sans-serif;
  }
  button:hover:not(:disabled){background:var(--gold-dark)}
  button:disabled{opacity:.5;cursor:not-allowed}
  .reassure{display:flex;flex-wrap:wrap;gap:8px 18px;margin:16px 0 0;padding:0;list-style:none;
            font-size:.84rem;color:#6d747d}
  .reassure li{display:flex;align-items:center;gap:6px}
  .reassure svg{width:14px;height:14px;color:var(--ok);flex:none}

  /* Test panel — visible only while we're wiring this up. */
  .lab{margin-top:22px;background:#191c21;border:1px solid #2a2f37;border-radius:12px;
       padding:16px;color:#aeb6c0;font-size:.84rem}
  .lab h2{margin:0 0 10px;font-size:.78rem;letter-spacing:.14em;text-transform:uppercase;
          color:var(--gold)}
  .lab label{color:#aeb6c0;font-size:.8rem}
  .lab input{background:#0f1216;border-color:#2a2f37;color:#e8ebef;padding:9px 11px;
             font-size:.84rem;font-family:ui-monospace,Menlo,Consolas,monospace}
  .lab code{word-break:break-all;color:#cfd6de;font-family:ui-monospace,Menlo,Consolas,monospace;
            font-size:.78rem;display:block;background:#0f1216;border:1px solid #2a2f37;
            border-radius:8px;padding:10px;margin-top:8px;line-height:1.5}
  .warn{color:#F0AD4E}
  footer{padding:22px 0 30px;color:#7d858f;font-size:.82rem}
</style>
</head>
<body>
<div class="wrap top">
  <a href="/" aria-label="JAC Builders home">
    <img src="/wp-content/uploads/2024/09/image_1-removebg-preview-1.svg" alt="JAC Builders" width="138" height="42">
  </a>
</div>

<main>
  <div class="wrap">
    <h1>What's the address?</h1>
    <p class="lede">That's all we need to start. We'll measure the roof from aerial
       imagery and show you a price. <strong>You'll see it on screen first</strong> &mdash;
       we only use your details to send the estimate and follow up.</p>

    <form class="card" id="f" novalidate>
      <label for="street">Property address</label>
      <div class="oneline">
        <div class="ac">
          <input id="street" name="street" type="text" autocomplete="off"
                 placeholder="Enter your street address to see your price" required
                 enterkeyhint="search" role="combobox" aria-expanded="false"
                 aria-controls="ac-list" aria-autocomplete="list" aria-describedby="street-hint">
          <ul class="ac__list" id="ac-list" role="listbox" aria-label="Address suggestions" hidden></ul>
        </div>
        <button type="submit" id="go">Start</button>
      </div>
      <p class="hint" id="street-hint">Pick your address from the list.</p>
      <p class="sr-only" id="ac-live" aria-live="polite"></p>

      <!-- Revealed only when the lookup can't resolve what was typed. Roofle
           needs the parts separately and won't search without the ZIP, so
           there has to be a manual way through — just not in everyone's face. -->
      <div id="manual" hidden>
        <p class="hint" style="margin:14px 0 8px;color:var(--ink);font-weight:600">
          We couldn't match that one &mdash; fill these in and we'll carry on.</p>
        <div class="parts">
          <input id="city" class="city" type="text" autocomplete="address-level2"
                 placeholder="City" aria-label="City">
          <input id="state" type="text" autocomplete="address-level1" maxlength="2"
                 placeholder="FL" aria-label="State">
          <input id="zip" type="text" inputmode="numeric" autocomplete="postal-code"
                 maxlength="10" placeholder="ZIP" aria-label="ZIP code">
        </div>
      </div>

      <div class="contact">
        <div class="contact__row">
          <div>
            <label for="email">Email</label>
            <input id="email" type="email" inputmode="email" autocomplete="email"
                   placeholder="you@example.com" required>
          </div>
          <div>
            <label for="phone">Phone</label>
            <input id="phone" type="tel" inputmode="tel" autocomplete="tel"
                   placeholder="(813) 555-0142" required>
          </div>
        </div>
      </div>

      <p class="err" id="err"></p>

      <div id="result" hidden>
        <div class="result">
          <p class="result__ok" id="result-addr"></p>
          <p class="result__msg" id="result-msg"></p>
          <div class="result__btns">
            <a id="result-go" class="btn-sm" href="#" target="_blank" rel="noopener">Open the Roofle demo with this address</a>
          </div>
          <code id="result-url"></code>
        </div>
      </div>

      <ul class="reassure">
        <li><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z"/></svg> Free, no obligation</li>
        <li><svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M9 16.2 4.8 12l-1.4 1.4L9 19 21 7l-1.4-1.4z"/></svg> No sales visit to book</li>
      </ul>
    </form>

    <div class="lab" id="lab">
      <h2>Test panel</h2>
      <div id="slugstate"></div>
      <label for="slug" style="margin-top:10px">Roofle hosted-page slug
        (<code style="display:inline;background:none;border:0;padding:0">offers.roofle.com/rqp/<b>&lt;slug&gt;</b></code>)</label>
      <input id="slug" type="text" placeholder="read it from the Pro Portal" autocomplete="off">
      <p class="hint" style="color:#7d858f">Stored in this browser only, for testing. Set
         <code style="display:inline;background:none;border:0;padding:0">ROOFLE_OFFERS_SLUG</code>
         on the Worker to make it the default for everyone.</p>
      <div style="margin-top:12px">Hand-off URL this form will open:</div>
      <code id="preview">&mdash;</code>
    </div>
  </div>
</main>

<footer class="wrap">&copy; JAC Builders &middot; <a href="/">Main site</a></footer>

<script>
(function () {
  "use strict";
  var $ = function (id) { return document.getElementById(id); };
  var slugFromWorker = null;

  /* ---- address parsing ---------------------------------------------------
     One field that behaves like one field: paste a whole address and it
     splits. Roofle's deeplink needs street1/city/state/postalCode separately
     and postalCode is mandatory for the lookup, so the parts stay visible and
     editable rather than being guessed at silently. */
  var STATES = ("AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS " +
    "MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC")
    .split(" ");

  function parseAddress(text) {
    var s = String(text)
      .replace(/[\u00a0\u202f\u2007]/g, " ")   // non-breaking spaces paste in constantly
      .replace(/\s*,\s*/g, ", ")                // normalise comma spacing
      .replace(/,\s*(?=,)/g, "")                // collapse doubled commas
      .replace(/[.,\s]+$/, "")                  // trailing punctuation/space
      .replace(/\s+/g, " ")
      .trim();
    // "..., FL. 33602" -> "..., FL 33602"
    s = s.replace(/\b([A-Za-z]{2})\.\s+(\d{5})/, "$1 $2");
    // "123 Main St, Tampa, FL 33606"  /  "123 Main St Tampa FL 33606"
    var m = s.match(/^(.*?)[,\s]+([A-Za-z .'-]+?)[,\s]+([A-Za-z]{2})[,\s]+(\d{5}(?:-\d{4})?)$/);
    if (!m) return null;
    var st = m[3].toUpperCase();
    if (STATES.indexOf(st) === -1) return null;
    var street = m[1].replace(/,$/, "").trim();
    var city = m[2].trim();
    // Without commas the split lands in the wrong place — "400 N Tampa St Tampa
    // FL 33602" parses as street "400", city "N Tampa St Tampa". A city holding
    // a street suffix, or a street with no number, means we guessed. Return
    // null so the geocoder gets a go instead of a confidently wrong answer.
    if (/\b(st|street|ave|avenue|blvd|boulevard|rd|road|dr|drive|ln|lane|ct|court|way|pkwy|parkway|hwy|highway|cir|circle|ter|terrace|pl|place)\b\.?/i.test(city)) return null;
    if (!/\d/.test(street)) return null;
    return { street: street, city: city, state: st, zip: m[4] };
  }

  function trySplit() {
    var parsed = parseAddress($("street").value);
    if (!parsed) return;
    $("street").value = parsed.street;
    lastQ = parsed.street;
    markResolved({ street1: parsed.street, city: parsed.city,
                   state: parsed.state, postalCode: parsed.zip });
  }
  $("street").addEventListener("paste", function () { setTimeout(trySplit, 0); });

  /* ---- autocomplete -------------------------------------------------------
     Debounced, proxied through our Worker so the provider can be swapped
     without touching this page. Picking a suggestion fills all four fields,
     which is the whole point: Roofle's deeplink needs them separately. */
  var list = $("ac-list"), live = $("ac-live");
  var items = [], active = -1, acTimer = null, acSeq = 0, lastQ = "";

  function closeList() {
    list.hidden = true; list.innerHTML = ""; items = []; active = -1;
    $("street").setAttribute("aria-expanded", "false");
    $("street").removeAttribute("aria-activedescendant");
  }

  function openList(html) {
    list.innerHTML = html; list.hidden = false;
    $("street").setAttribute("aria-expanded", "true");
  }

  function renderStatus(text) {
    openList('<li class="ac__status">' + esc(text) + "</li>");
    items = []; active = -1;
  }

  function render(suggestions) {
    items = suggestions;
    if (!items.length) { renderStatus("No matches for that."); showManual(); return; }
    openList(items.map(function (s, i) {
      return '<li class="ac__opt" role="option" id="ac-opt-' + i + '" aria-selected="false">' +
             esc(s.street1) + "<small>" + esc(s.city + ", " + s.state + " " + s.postalCode) +
             "</small></li>";
    }).join(""));
    live.textContent = items.length + " address suggestions available.";
    [].forEach.call(list.children, function (li, i) {
      li.addEventListener("mousedown", function (e) { e.preventDefault(); choose(i); });
    });
  }

  function highlight(i) {
    if (!items.length) return;
    active = (i + items.length) % items.length;
    [].forEach.call(list.children, function (li, n) {
      li.setAttribute("aria-selected", String(n === active));
    });
    $("street").setAttribute("aria-activedescendant", "ac-opt-" + active);
    list.children[active].scrollIntoView({ block: "nearest" });
  }

  function choose(i) {
    var s = items[i];
    if (!s) return;
    $("street").value = s.street1;
    lastQ = s.street1;
    closeList();
    markResolved(s);
    $("go").focus();
  }

  function suggest() {
    var q = $("street").value.trim();
    if (q === lastQ) return;
    lastQ = q;
    if (q.length < 4) { closeList(); return; }
    var seq = ++acSeq;
    fetch("/api/geo/suggest?q=" + encodeURIComponent(q))
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (seq !== acSeq) return;            // a newer keystroke already won
        if (d.error) { renderStatus("Lookup unavailable."); showManual(); return; }
        render(d.suggestions || []);
      })
      .catch(function () { if (seq === acSeq) closeList(); });
  }

  $("street").addEventListener("input", function () {
    if (resolved) invalidate();      // text changed: the old parts no longer apply
    clearTimeout(acTimer);
    acTimer = setTimeout(suggest, 250);
  });
  $("street").addEventListener("blur", function () {
    setTimeout(function () { closeList(); trySplit(); }, 120);
  });
  $("street").addEventListener("keydown", function (e) {
    if (list.hidden) return;
    if (e.key === "ArrowDown") { e.preventDefault(); highlight(active + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); highlight(active - 1); }
    else if (e.key === "Enter" && active >= 0) { e.preventDefault(); choose(active); }
    else if (e.key === "Escape") { closeList(); }
  });

  /* ---- slug --------------------------------------------------------------- */
  function slug() {
    var override = "";
    try { override = localStorage.getItem("roofleSlug") || ""; } catch (e) {}
    return (override || slugFromWorker || "").trim();
  }
  $("slug").addEventListener("input", function () {
    try { localStorage.setItem("roofleSlug", $("slug").value.trim()); } catch (e) {}
    paintSlug(); preview();
  });

  function paintSlug() {
    var s = slug();
    $("slugstate").innerHTML = s
      ? '<span style="color:#5CB85C">Slug set: <b>' + esc(s) + "</b></span>" +
        (slugFromWorker && s === slugFromWorker ? " (from the Worker)" : " (this browser only)")
      : '<span class="warn">No slug yet.</span> ' +
        "The form still captures and logs; the hand-off shows a demo link instead " +
        "of going to JAC's own instance.";
  }

  /* ---- deeplink ----------------------------------------------------------- */
  /* ---- contact ------------------------------------------------------------ */
  // Deliberately loose: the only email check worth doing in a browser is
  // "something@something.something". Anything stricter rejects real addresses.
  var EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

  function digits(v) { return String(v).replace(/\D/g, ""); }

  function contact() {
    var email = $("email").value.trim();
    var phoneDigits = digits($("phone").value);
    // Accept a leading country code but hand Roofle the bare 10 digits.
    if (phoneDigits.length === 11 && phoneDigits.charAt(0) === "1") {
      phoneDigits = phoneDigits.slice(1);
    }
    return { email: email, phone: phoneDigits };
  }

  // Light formatting on blur only — reformatting mid-typing fights the caret.
  $("phone").addEventListener("blur", function () {
    var d = digits($("phone").value);
    if (d.length === 11 && d.charAt(0) === "1") d = d.slice(1);
    if (d.length === 10) {
      $("phone").value = "(" + d.slice(0, 3) + ") " + d.slice(3, 6) + "-" + d.slice(6);
    }
  });

  // Roofle's parameter names, in their documented order. One builder so the
  // demo URL and the real one can never drift apart.
  //
  // Built by hand rather than with URLSearchParams: that encodes a space as
  // "+", and Roofle's parser reads "+" literally, so "400+North+Tampa+Street"
  // never matches an address. Their own documented examples use %20, which is
  // what encodeURIComponent produces.
  function params(f) {
    var c = contact();
    var out = [
      "street1=" + encodeURIComponent(f.street1),
      "city=" + encodeURIComponent(f.city),
      "state=" + encodeURIComponent(f.state),
      "postalCode=" + encodeURIComponent(f.postalCode)
    ];
    // Optional on Roofle's side; prefilling means they are not asked twice.
    if (c.email) out.push("email=" + encodeURIComponent(c.email));
    if (c.phone) out.push("phone=" + encodeURIComponent(c.phone));
    return out.join("&");
  }

  function deeplink() {
    var f = resolved || {
      street1: $("street").value.trim(), city: $("city").value.trim(),
      state: $("state").value.trim().toUpperCase(), postalCode: $("zip").value.trim()
    };
    return "https://offers.roofle.com/rqp/" + encodeURIComponent(slug()) + "?" +
           params(f);
  }

  function preview() {
    if (!slug()) { $("preview").textContent = "— set a slug above —"; return; }
    $("preview").textContent = resolved ? deeplink() : "— address not resolved yet —";
  }

  /* ---- resolution ---------------------------------------------------------
     The visible field is one line. Roofle still needs four parts, so a street
     string is only "resolved" once we have all four — from a suggestion, from
     a pasted address that parses, or from the manual fields if we had to show
     them. Editing the street text after resolving invalidates it, so a stale
     ZIP can never ride along with a different address. */
  var resolved = null;

  function markResolved(parts) {
    resolved = parts;
    $("city").value = parts.city;
    $("state").value = parts.state;
    $("zip").value = parts.postalCode;
    $("street-hint").textContent = parts.city + ", " + parts.state + " " + parts.postalCode;
    $("manual").hidden = true;
    preview();
  }

  function invalidate() {
    resolved = null;
    // Clear the parts too, unless the visitor is filling them in by hand.
    // Leaving a previous pick's ZIP behind lets fromManual() resurrect it
    // against a different street — a wrong-address quote with no visible cause.
    if ($("manual").hidden) {
      $("city").value = ""; $("state").value = ""; $("zip").value = "";
    }
    $("street-hint").textContent = "Pick your address from the list.";
    $("result").hidden = true;
    preview();
  }

  function showManual() {
    $("manual").hidden = false;
    $("street-hint").textContent = "Pick your address from the list.";
  }

  // Manual entry counts as resolved too, once all three are filled sensibly.
  function fromManual() {
    // Only authoritative while visible; otherwise these are leftovers from a
    // previous pick, not something the visitor stands behind.
    if ($("manual").hidden) return null;
    var city = $("city").value.trim();
    var state = $("state").value.trim().toUpperCase();
    var zip = $("zip").value.trim();
    if (!city || STATES.indexOf(state) === -1 || !/^\d{5}(-\d{4})?$/.test(zip)) return null;
    return { street1: $("street").value.trim(), city: city, state: state, postalCode: zip };
  }
  ["city", "state", "zip"].forEach(function (id) {
    $(id).addEventListener("input", function () {
      var m = fromManual();
      if (m) { resolved = m; }
      preview();
    });
  });

  /* ---- geocoder fallback ---------------------------------------------------
     Parsing a free-text address with a regex only ever half works — a trailing
     space, a missing comma or "Fl." and it returns nothing. The lookup service
     already hands back proper components, so ask it rather than guess. */
  function resolveViaLookup(text) {
    return fetch("/api/geo/suggest?q=" + encodeURIComponent(text))
      .then(function (r) { return r.json(); })
      .then(function (d) { return d.suggestions || []; })
      .catch(function () { return []; });
  }

  /* ---- submit -------------------------------------------------------------- */
  function fail(msg) {
    $("err").textContent = msg;
    $("err").classList.add("on");
    return false;
  }

  $("f").addEventListener("submit", function (e) {
    e.preventDefault();
    $("err").classList.remove("on");

    if (!$("street").value.trim()) { $("street").focus(); return fail("Please enter your address."); }

    var c = contact();
    if (!EMAIL_RE.test(c.email)) { $("email").focus(); return fail("Please check your email address."); }
    if (c.phone.length !== 10) { $("phone").focus(); return fail("Please enter a 10-digit phone number."); }

    // Last chance: a pasted address that was never blurred, or manual fields.
    if (!resolved) { trySplit(); }
    if (!resolved) { resolved = fromManual(); }
    if (!resolved) {
      // Hand the raw text to the lookup before asking the visitor to redo work
      // they have already done. Only if that misses do we show the fields.
      $("go").disabled = true;
      $("go").textContent = "Looking it up\u2026";
      resolveViaLookup($("street").value.trim()).then(function (hits) {
        $("go").disabled = false;
        $("go").textContent = "Start";
        if (hits.length) {
          // Offer them, never auto-pick. The top hit is not always the house
          // that was typed — "1234 W Swann Ave" comes back as 2901 W Swann Ave
          // — and silently swapping it would quote the wrong roof.
          render(hits);
          $("street").focus();
          fail("Pick your address from the list so we measure the right roof.");
          return;
        }
        showManual();
        $("city").focus();
        fail("We couldn't find that address. Add the city, state and ZIP and we'll carry on.");
      });
      return false;
    }
    var f = resolved;
    var haveSlug = !!slug();
    var url = deeplink();

    if (haveSlug) {
      $("go").disabled = true;
      $("go").textContent = "Working\u2026";
    } else {
      // No slug yet. The capture half still works and is worth showing, rather
      // than leaving a click that does nothing.
      var demo = "https://offers.roofle.com/rqp/demo?" + params(f);
      $("result-addr").textContent = "Address captured: " + f.street1 + ", " +
        f.city + ", " + f.state + " " + f.postalCode;
      $("result-msg").innerHTML =
        "Logged on our side \u2014 it will show in <a href=\"/roofle-lab/\">the lab</a>. " +
        "The hand-off to Roofle needs your hosted-page slug, which isn't set yet. " +
        "Paste it in the test panel below and this button will go straight through.";
      $("result-go").href = demo;
      $("result-url").textContent = demo;
      $("result").hidden = false;
      $("result").scrollIntoView({ behavior: "smooth", block: "nearest" });
    }

    var done = false;
    function handoff() { if (!haveSlug || done) return; done = true; location.href = url; }
    try {
      fetch("/api/quote/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          webhookType: "Form Address Submitted",
          street: f.street1, city: f.city, state: f.state, zip: f.postalCode,
          email: c.email, phone: c.phone,
          fullAddress: f.street1 + ", " + f.city + ", " + f.state + " " + f.postalCode,
          externalUrl: location.href,
          handoffUrl: url,
          referrer: document.referrer || null,
          timestamp: new Date().toISOString()
        }),
        keepalive: true
      }).then(handoff, handoff);
    } catch (err) { handoff(); }
    setTimeout(handoff, 1200);
  });

  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* ---- boot ---------------------------------------------------------------- */
  try { $("slug").value = localStorage.getItem("roofleSlug") || ""; } catch (e) {}
  fetch("/api/health").then(function (r) { return r.json(); }).then(function (d) {
    slugFromWorker = d.offersSlug || null;
    if (d.geoProvider) {
      $("slugstate").insertAdjacentHTML("afterend",
        '<div style="margin-top:6px">Autocomplete provider: <b>' + esc(d.geoProvider) +
        (d.geoProvider === "photon"
          ? '</b> <span class="warn">(keyless, testing only)</span>'
          : "</b>") + "</div>");
    }
    paintSlug(); preview();
  }).catch(function () { paintSlug(); preview(); });
  paintSlug(); preview();
})();
</script>
</body>
</html>
```

---

## 6. Gotchas, each of which was a real bug

**Never ship a disabled submit button.** The first build disabled Start until
a slug was configured, with the reason in a panel below. From the visitor's
seat: type an address, click Start, nothing happens. Always let the submit run
and report what it found.

**Do not trust a regex to split an address.** Trailing spaces, non-breaking
spaces (these paste in constantly), commas without spaces, `Fl.` instead of
`FL` — each returns null and tells the visitor to re-enter what they just
typed. Normalise first, then parse, then **fall back to the lookup service**
with the raw string.

**Reject confidently-wrong parses.** Without commas, `400 N Tampa St Tampa FL
33602` splits as street `400`, city `N Tampa St Tampa` — a *success* that
hands Roofle a wrong address. Guard: a city containing a street suffix
(st, ave, blvd, rd, dr, ln, ct, way, pkwy, hwy, cir, ter, pl), or a street
with no digit, means you guessed. Return null and let the geocoder answer.

**Never auto-pick the geocoder's top hit.** `1234 W Swann Ave Tampa Florida`
resolves to **2901** West Swann Avenue — a different house. Auto-accepting it
quotes the wrong roof with nothing on screen to notice. Offer the matches and
make the visitor choose.

**Invalidate the parts when the street text changes.** Clearing the resolved
object but leaving a previous pick's ZIP in a hidden field lets it ride along
with a different street. Wipe the components unless the visitor is actively
filling them in by hand.

**Reformat the phone on blur, not while typing.** Mid-typing reformatting
fights the caret.

**Keep the email check loose.** something@something.something is the only
check worth doing in a browser; anything stricter rejects real addresses.

---

## 7. Webhooks — closing the loop

Configure three separate URLs in Pro Portal, Settings, Developer, Webhooks.
Each posts JSON, discriminated by a **`webhookType`** field (not `event` or
`type`):

| `webhookType` | Fires when |
|---|---|
| `Address Only` | an address is submitted |
| `Contact Form Completed` | **a lead converts** |
| `Product Requested` | a specific product is requested |

`Contact Form Completed` and `Product Requested` carry the full payload:
contact, parsed address, per-structure measurements (`squareFeet`, `slope`,
`roofComplexity`), `products[]` with `priceInfo` and `priceRange`,
`weatherReports[]`, and attribution (`externalUrl`, `sessionId`, `jobId`).

Two things in there are easy to miss:

- **`weatherReports[]`** carries hail size and distance with every lead — a
  storm-campaign trigger, free.
- **`communicationOptions.smsOptIn`** is the TCPA consent record. It is
  **nested**, not top-level (Roofle's own Zapier article implies otherwise).
  Store it; it governs whether you may legally text that person.

Your receiver should answer **200 before doing any storage work**. A slow 200
invites retries, and a storage failure must never read as a failed delivery.

Full field list: `https://roofquotepro.com/webhooks-documentation` — the page
is JS-rendered, so open it in a browser; curl returns an empty shell.

---

## 8. Testing checklist

- [ ] Type a partial address, suggestions appear, arrow keys and Enter work
- [ ] Pick a suggestion, all four components captured
- [ ] Paste a full address, splits correctly
- [ ] Paste with a trailing space, without commas, with `Fl.` — all still work
- [ ] Type an unmatchable address, offered choices or manual fields appear
- [ ] Edit the street after picking, old ZIP is cleared not reused
- [ ] Bad email and short phone caught before hand-off
- [ ] Generated URL contains **%20, never +**
- [ ] Follow the URL, address prefilled in Roofle
- [ ] Submission appears in your capture log
- [ ] 375px wide, no horizontal overflow, tap targets at least 44px
