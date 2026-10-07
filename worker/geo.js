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
