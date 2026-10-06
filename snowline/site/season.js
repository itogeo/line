// Snowline — season helpers shared by the map (index.html) and the Data page.
//
// A snow season is labelled by the year it starts in and runs from Oct 1.
// Charts and the timeline draw Oct 1 → May 31; a date from Jun–Sep belongs
// to the season that started the previous October.
//
//   seasonOf('2026-10-05') → { label: '2026–27', start: '2026-10-01', end: '2027-05-31', year: 2026 }
//   seasonOf('2026-05-06') → { label: '2025–26', start: '2025-10-01', end: '2026-05-31', year: 2025 }

function seasonOf(dateStr) {
  const y = parseInt(dateStr.slice(0, 4), 10);
  const m = parseInt(dateStr.slice(5, 7), 10);
  const start = m >= 10 ? y : y - 1;
  return {
    year: start,
    label: `${start}–${String(start + 1).slice(2)}`,
    start: `${start}-10-01`,
    end: `${start + 1}-05-31`,
  };
}

// 'YYYY-MM' keys for Oct … May of a season (8 entries).
function seasonMonthKeys(s) {
  const out = [];
  for (let i = 0; i < 8; i++) {
    const m = ((9 + i) % 12) + 1;
    const y = m >= 10 ? s.year : s.year + 1;
    out.push(`${y}-${String(m).padStart(2, '0')}`);
  }
  return out;
}

function seasonDays(s) {
  return Math.round((Date.parse(s.end) - Date.parse(s.start)) / 86400000);
}

function todayStr() {
  return new Date().toISOString().slice(0, 10);
}

// NRCS end date for a season's SNOTEL request: today, or the season end if
// the season is over.
function seasonFetchEnd(s) {
  const t = todayStr();
  return t < s.end ? t : s.end;
}

// ── Shareable URL state ─────────────────────────────────────────────────────
// #date=2026-04-19&map=9.2/45.68/-110.95  (zoom/lat/lon, like the Taylor explorer)
function readHash() {
  const p = new URLSearchParams(location.hash.replace(/^#/, ''));
  const out = {};
  if (/^\d{4}-\d{2}-\d{2}$/.test(p.get('date') || '')) out.date = p.get('date');
  const m = (p.get('map') || '').split('/').map(Number);
  if (m.length === 3 && m.every(Number.isFinite)) out.map = { zoom: m[0], lat: m[1], lon: m[2] };
  if (p.get('tile')) out.tile = p.get('tile').toUpperCase();
  return out;
}

function writeHash(state) {
  const cur = new URLSearchParams(location.hash.replace(/^#/, ''));
  for (const [k, v] of Object.entries(state)) {
    if (v == null || v === '') cur.delete(k); else cur.set(k, v);
  }
  const next = '#' + cur.toString().replace(/%2F/g, '/');
  if (next !== location.hash) history.replaceState(null, '', next);
}
