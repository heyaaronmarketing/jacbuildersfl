# Roofle (RoofQuote PRO) integration

## What Roofle actually exposes

There is **no inbound REST API**. You cannot POST form fields to Roofle and get
a quote back — the widget *is* the quote engine, and the aerial measurement and
pricing happen inside their iframe. The developer surface is:

1. Two script embeds keyed by a public company tool ID
   (`Ia1SS2XzahX7CnVfYGzn7` for JAC — the same one on all 14 existing pages).
2. Seven `postMessage` events, for analytics only.
3. **Outbound webhooks** — Roofle POSTs lead data to a callback URL you own.
4. Direct CRM integrations (ProLine, JobNimbus, AccuLynx, Zapier).

An API key that "requires a callback URL" is #3. That is the one place real
control lives: the lead data arrives on our infrastructure instead of only
living in their portal.

## The callback URL

```
https://jacbuildersfl.aironz.workers.dev/api/roofle/webhook
```

After the DNS cutover it also answers at
`https://www.jacbuildersfl.com/api/roofle/webhook`. Register whichever host is
actually serving traffic — and if you register the production one before
cutover, deliveries will go to WordPress and be lost.

`GET` returns 200 so Roofle's URL check passes; real deliveries are `POST`.
The endpoint answers 200 *before* writing anything, because a slow 200 invites
retries and a storage failure must never read as a failed delivery.

## Lab

`/roofle-lab/` (noindex) shows what actually arrives: full payload, headers,
and whether the delivery carried a recognised secret. Use it to discover
Roofle's real payload shape — they don't publish one, so the sample in the lab
is a placeholder, not documentation.

## Setup

Two secrets. Neither may be committed: this repo is public and deliveries carry
homeowner names, phones and addresses.

```bash
# Required — gates all reads. Reads refuse outright until this exists.
npx wrangler secret put ROOFLE_LAB_TOKEN --name jacbuildersfl

# Optional — set it if Roofle lets you send a shared secret with deliveries.
npx wrangler secret put ROOFLE_WEBHOOK_SECRET --name jacbuildersfl
```

Roofle does not publish how its webhooks authenticate, so the Worker checks the
usual carriers (`x-roofle-signature`, `x-roofle-token`, `x-webhook-token`,
`Authorization: Bearer`, `?token=`) and records which one matched. Once a real
delivery lands, read its headers in the lab and narrow the check to just that.

## Durable storage

Until a D1 database is bound, deliveries live in an **in-isolate ring buffer**
that dies with the isolate. Fine for the lab, useless as a record of leads:

```bash
npx wrangler d1 create jacbuildersfl
```

Paste the returned id into the commented `d1_databases` block in
`wrangler.jsonc`, uncomment it, and push. The table is created on first write;
no migration step. Every consumer treats `DB` as optional, so nothing breaks
while it is absent.

## Known blocker

**Roofle enforces a domain whitelist and returns 403 from any host not on it.**
Today the widget renders nowhere except jacbuildersfl.com — on workers.dev the
script loads, logs its tool ID, takes two 403s and mounts nothing. Add the
preview host in the Pro Portal (Settings → Developer) before testing any page
that embeds the widget.
