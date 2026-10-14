// Snowline Data page: the Scenes table and the Snow history charts.
// Reads static JSON written by the pipeline — no API calls:
//   data/scenes.json         build_sat_availability.py (S2 GeoParquet index)
//   data/snow_timeline.json  build_snow_timeline.py   (S2 GeoParquet index)
//   data_10m/dates.json      process_tiles.py          (dates with a snow map)
// Depends on season.js.

const PAGE = 100;

let SCENES = [];        // [{date,tile,id,cloud,snow,nodata,baseline,href:{thumbnail,visual,…}}]
let SCENES_META = null;
let MAPPED = new Set();
let shown = PAGE;
const F = { tile: '', month: '', cloud: 100, mapped: false, date: '' };

// ── small helpers ───────────────────────────────────────────────────────────
const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const fmtPct = v => (v == null ? '—' : (v < 1 && v > 0 ? v.toFixed(1) : Math.round(v)) + '%');
const fmtDay = d => new Date(d + 'T12:00:00Z').toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' });

function toast(msg) {
  let t = document.querySelector('.toast');
  if (!t) { t = document.createElement('div'); t.className = 'toast'; document.body.appendChild(t); }
  t.textContent = msg; t.style.display = 'block';
  clearTimeout(t._h); t._h = setTimeout(() => { t.style.display = 'none'; }, 1800);
}
function tip() {
  let t = document.querySelector('.viz-tip');
  if (!t) { t = document.createElement('div'); t.className = 'viz-tip'; document.body.appendChild(t); }
  return t;
}
function showTip(html, ev) {
  const t = tip(); t.innerHTML = html; t.style.display = 'block';
  const x = Math.min(ev.clientX + 14, window.innerWidth - t.offsetWidth - 8);
  const y = Math.min(ev.clientY + 14, window.innerHeight - t.offsetHeight - 8);
  t.style.left = x + 'px'; t.style.top = y + 'px';
}
function hideTip() { const t = document.querySelector('.viz-tip'); if (t) t.style.display = 'none'; }

// ── Scenes ──────────────────────────────────────────────────────────────────
async function initScenes(hash) {
  const el = document.getElementById('scene-table');
  try {
    const [sc, dates] = await Promise.all([
      fetch('data/scenes.json').then(r => { if (!r.ok) throw new Error('scenes.json ' + r.status); return r.json(); }),
      fetch('data_10m/dates.json').then(r => (r.ok ? r.json() : { dates: [] })).catch(() => ({ dates: [] })),
    ]);
    SCENES_META = sc;
    MAPPED = new Set(dates.dates || []);
    const col = Object.fromEntries(sc.columns.map((c, i) => [c, i]));
    SCENES = sc.rows.map(r => {
      const href = {};
      if (r[col.dir]) for (const [k, f] of Object.entries(sc.files || {})) href[k] = r[col.dir] + f;
      else Object.assign(href, r[col.extra] || {});
      return { date: r[col.date], tile: r[col.tile], id: r[col.id], cloud: r[col.cloud], snow: r[col.snow],
        nodata: r[col.nodata], baseline: r[col.baseline], href };
    });
  } catch (e) {
    el.className = 'loading';
    el.textContent = 'Scene table not available yet (' + e.message + ').';
    return;
  }

  // Filters
  const tiles = [...new Set(SCENES.map(s => s.tile))].sort();
  const months = [...new Set(SCENES.map(s => s.date.slice(0, 7)))].sort().reverse();
  const ft = document.getElementById('f-tile'), fm = document.getElementById('f-month');
  ft.innerHTML = `<option value="">All ${tiles.length}</option>` + tiles.map(t => `<option>${t}</option>`).join('');
  fm.innerHTML = '<option value="">All</option>' + months.map(m =>
    `<option value="${m}">${new Date(m + '-15T12:00:00Z').toLocaleDateString('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' })}</option>`).join('');
  if (hash.tile && tiles.includes(hash.tile.replace(/^T/, ''))) F.tile = hash.tile.replace(/^T/, '');
  if (hash.date) F.date = hash.date;
  ft.value = F.tile;
  ft.onchange = () => { F.tile = ft.value; writeHash({ tile: F.tile || null }); refresh(); };
  fm.onchange = () => { F.month = fm.value; F.date = ''; writeHash({ date: null }); refresh(); };
  const fc = document.getElementById('f-cloud');
  fc.oninput = () => { F.cloud = +fc.value; document.getElementById('f-cloud-val').textContent = fc.value + '%'; refresh(); };
  document.getElementById('f-mapped').onchange = e => { F.mapped = e.target.checked; refresh(); };

  const g = SCENES_META.generated ? new Date(SCENES_META.generated) : null;
  document.getElementById('scenes-source').innerHTML =
    `Source: Copernicus Sentinel-2 Collection 1 L2A (ESA), indexed by ` +
    `<a href="https://research.taylorgeospatial.org/s2-stac-geoparquet/" target="_blank" rel="noopener">s2-stac-geoparquet</a> ` +
    `(Taylor Geospatial / TGE Labs, from Element 84 Earth Search). ` +
    `Contains modified Copernicus Sentinel data ${new Date().getFullYear()}. ` +
    (g ? `Table rebuilt ${g.toLocaleString('en-US', { timeZone: 'America/Denver', dateStyle: 'medium', timeStyle: 'short' })} MT. ` : '') +
    `<a href="data/scenes.json">Download scenes.json</a>.`;
  refresh();
  initPasses();
}

// ── Satellite passes: where each pass imaged, and where the next ones will ──
// Footprints come from the pass list (build_sat_availability.py). The map runs
// past the Snowline area (dashed box) so strips that only clip it still show.
// Upcoming passes repeat the track of the pass 10 days earlier.
const PASS_VIEW = [-113.7, 43.3, -107.5, 48.0];  // lon/lat, out to Jackson
const PASS_TOWNS = [['Bozeman', 45.68, -111.04], ['Big Sky', 45.28, -111.37],
  ['W. Yellowstone', 44.66, -111.10], ['Red Lodge', 45.19, -109.25], ['Ennis', 45.35, -111.73],
  ['Jackson', 43.48, -110.76], ['Cody', 44.53, -109.06], ['Helena', 46.59, -112.04], ['Billings', 45.78, -108.50]];
let PASS_ROWS = [], PASS_AOI = null, PASS_SEL = null;

async function initPasses() {
  const el = document.getElementById('pass-panel');
  try {
    const sa = await fetch('data/sat_availability.json').then(r => r.json());
    PASS_ROWS = sa.rows || [];
    PASS_AOI = sa.aoi && sa.aoi.bbox;
  } catch (e) { el.innerHTML = ''; return; }
  const today = new Date().toISOString().slice(0, 10);
  const recent = PASS_ROWS.filter(r => r.footprint && (Date.parse(today) - Date.parse(r.dt)) / 86400000 < 10);
  if (!recent.length) {
    el.innerHTML = '<div class="pass-side">Pass strips appear after the next daily update.</div>';
    return;
  }
  PASS_SEL = PASS_SEL || { dt: recent[0].dt };
  renderPasses();
}

function passUpcoming() {
  const today = new Date().toISOString().slice(0, 10);
  const out = new Map();
  for (const r of PASS_ROWS) {
    if (!r.footprint || (r.aoi_cover_pct != null && r.aoi_cover_pct < 5)) continue;
    for (const k of [10, 20]) {
      const due = new Date(Date.parse(r.dt) + k * 86400000).toISOString().slice(0, 10);
      if (due > today && !out.has(due)) out.set(due, r);
    }
  }
  return [...out.entries()].sort((a, b) => a[0].localeCompare(b[0])).slice(0, 4).map(([due, r]) => ({ due, src: r }));
}

function renderPasses() {
  const el = document.getElementById('pass-panel');
  const today = new Date().toISOString().slice(0, 10);
  const W = 340, H = 300;
  const proj = makeGeoProjection(PASS_VIEW, W, H, 6);
  const X = lon => proj.lonToX(lon).toFixed(1), Y = lat => proj.latToY(lat).toFixed(1);
  const ringPath = ring => ring.map((c, i) => `${i ? 'L' : 'M'}${X(c[0])},${Y(c[1])}`).join('') + 'Z';
  const geomPath = g => (g.type === 'Polygon' ? [g.coordinates] : g.coordinates).map(poly => poly.map(ringPath).join('')).join('');
  const sel = PASS_SEL.due
    ? { row: PASS_ROWS.find(r => r.dt === PASS_SEL.src), future: true }
    : { row: PASS_ROWS.find(r => r.dt === PASS_SEL.dt), future: false };
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Satellite pass strips">`;
  if (sel.row && sel.row.footprint) {
    const c = sel.future ? '#FFD54F' : '#ffffff';
    svg += `<path d="${geomPath(sel.row.footprint)}" fill="${c}" fill-opacity="0.08" stroke="${c}" stroke-width="1.5" stroke-dasharray="5,3"/>`;
  }
  if (PASS_AOI) {
    const [w, s, e, n] = PASS_AOI;
    svg += `<rect x="${X(w)}" y="${Y(n)}" width="${(X(e) - X(w)).toFixed(1)}" height="${(Y(s) - Y(n)).toFixed(1)}" fill="none" stroke="#4FC3F7" stroke-width="1.5"/>`;
    svg += `<text x="${X(w) - 0 + 4}" y="${+Y(n) + 12}" fill="#4FC3F7" font-size="9" font-family="var(--mono)">Snowline area</text>`;
  }
  for (const [name, lat, lon] of PASS_TOWNS) {
    svg += `<circle cx="${X(lon)}" cy="${Y(lat)}" r="2" fill="rgba(255,255,255,0.6)"/><text x="${+X(lon) + 4}" y="${+Y(lat) + 3}" fill="rgba(255,255,255,0.55)" font-size="8" font-family="var(--mono)">${name}</text>`;
  }
  svg += '</svg>';

  const recent = PASS_ROWS.filter(r => r.footprint && (Date.parse(today) - Date.parse(r.dt)) / 86400000 < 12 && (r.aoi_cover_pct == null || r.aoi_cover_pct >= 5));
  const pct = r => Math.round(r.aoi_cover_pct != null ? r.aoi_cover_pct : r.s2aoi);
  const day = d => new Date(d + 'T12:00:00Z').toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', timeZone: 'UTC' });
  const recentChips = recent.map(r => `<button type="button" class="pass-chip${!PASS_SEL.due && PASS_SEL.dt === r.dt ? ' on' : ''}" data-dt="${r.dt}"
      title="${esc(r.why || '')}">${day(r.dt)} · ${pct(r)}% · ${esc(r.q)}</button>`).join('');
  const futureChips = passUpcoming().map(u => `<button type="button" class="pass-chip future${PASS_SEL.due === u.due ? ' on' : ''}" data-due="${u.due}" data-src="${u.src.dt}"
      title="Same track as ${day(u.src.dt)}">${day(u.due)} · ~${pct(u.src)}%</button>`).join('');
  const label = sel.row ? (sel.future ? `Predicted strip for ${day(PASS_SEL.due)} (same track as ${day(sel.row.dt)})`
    : `Strip imaged ${day(sel.row.dt)}: ${pct(sel.row)}% of the area, ${sel.row.s2n} tiles, ${esc(sel.row.q)}`) : '';
  el.innerHTML = svg + `<div class="pass-side">
    <h3>Recent passes</h3><div>${recentChips || '—'}</div>
    <h3 style="margin-top:10px">Next passes (predicted)</h3><div>${futureChips || '—'}</div>
    <div style="margin-top:8px;line-height:1.5">${label}</div>
    <div style="margin-top:6px;color:var(--text-dim);font-size:10px;line-height:1.5">% = share of the Snowline area inside the strip. Each Sentinel-2 satellite repeats its track every 10 days; clouds decide whether a pass is useful. Click a recent pass to list its scenes below.</div>
  </div>`;
  el.querySelectorAll('.pass-chip[data-dt]').forEach(b => b.onclick = () => {
    PASS_SEL = { dt: b.dataset.dt };
    F.date = b.dataset.dt; F.month = ''; document.getElementById('f-month').value = '';
    writeHash({ date: F.date }); refresh(); renderPasses();
  });
  el.querySelectorAll('.pass-chip[data-due]').forEach(b => b.onclick = () => {
    PASS_SEL = { due: b.dataset.due, src: b.dataset.src }; renderPasses();
  });
}

function filtered() {
  return SCENES.filter(s =>
    (!F.tile || s.tile === F.tile) &&
    (!F.date || s.date === F.date) &&
    (!F.month || s.date.startsWith(F.month)) &&
    (F.cloud >= 100 || (s.cloud ?? 100) <= F.cloud) &&
    (!F.mapped || MAPPED.has(s.date)));
}

function refresh() {
  shown = PAGE;
  const chip = document.getElementById('f-date-chip');
  if (F.date) {
    chip.style.display = '';
    chip.textContent = `${fmtDay(F.date)} ✕`;
    chip.title = 'Clear the date filter';
    chip.onclick = () => { F.date = ''; writeHash({ date: null }); refresh(); };
  } else chip.style.display = 'none';
  renderSceneStats();
  renderSceneTable();
}

function renderSceneStats() {
  const rows = filtered();
  const days = new Set(rows.map(r => r.date));
  const clear = rows.filter(r => (r.cloud ?? 100) < 30).length;
  const mapped = [...days].filter(d => MAPPED.has(d)).length;
  const first = rows.length ? rows[rows.length - 1].date : null;
  document.getElementById('scene-stats').innerHTML = [
    [rows.length.toLocaleString(), 'scenes'],
    [days.size.toLocaleString(), 'pass days'],
    [rows.length ? Math.round(clear / rows.length * 100) + '%' : '—', 'under 30% cloud'],
    [mapped, 'days with a snow map'],
    [first ? fmtDay(first) : '—', 'earliest shown'],
  ].map(([v, l]) => `<div class="stat-card"><div class="sv">${v}</div><div class="sl">${l}</div></div>`).join('');
}

function renderSceneTable() {
  const rows = filtered();
  const el = document.getElementById('scene-table');
  el.className = '';
  if (!rows.length) { el.innerHTML = '<div class="loading">No scenes match these filters.</div>'; document.getElementById('scene-more').innerHTML = ''; return; }
  const body = rows.slice(0, shown).map((s, i) => {
    const map = MAPPED.has(s.date) ? `<a href="/snow/#date=${s.date}" title="Open this day's snow map">map</a>` : '';
    return `<tr>
      <td>${s.href.thumbnail ? `<a href="${esc(s.href.thumbnail)}" target="_blank" rel="noopener"><img class="thumb" loading="lazy" src="${esc(s.href.thumbnail)}" alt="Sentinel-2 preview of tile ${esc(s.tile)} on ${esc(s.date)}"></a>` : ''}</td>
      <td>${esc(s.date)}${MAPPED.has(s.date) ? '<span class="mapped-dot" title="Snowline made a snow map this day"></span>' : ''}</td>
      <td>${esc(s.tile)}</td>
      <td class="num">${fmtPct(s.cloud)}</td>
      <td class="num">${fmtPct(s.snow)}</td>
      <td class="num">${fmtPct(s.nodata)}</td>
      <td title="${esc(s.id)}">${esc(s.id.replace(/_L2A$/, ''))}</td>
      <td class="row-links">
        ${s.href.visual ? `<a href="${esc(s.href.visual)}" target="_blank" rel="noopener" title="True-colour COG (TCI.tif)">COG</a>` : ''}
        ${map}
      </td></tr>`;
  }).join('');
  el.innerHTML = `<table><thead><tr>
      <th></th><th>Date (UTC)</th><th>Tile</th><th class="num">Cloud</th><th class="num">Snow</th><th class="num">Nodata</th><th>Scene id</th><th></th>
    </tr></thead><tbody>${body}</tbody></table>`;
  const more = document.getElementById('scene-more');
  more.innerHTML = rows.length > shown
    ? `<button class="filter-btn" id="more-btn" type="button">Show ${Math.min(PAGE, rows.length - shown)} more of ${rows.length - shown}</button>`
    : `<span class="filter-label">${rows.length} scene${rows.length === 1 ? '' : 's'}</span>`;
  const mb = document.getElementById('more-btn');
  if (mb) mb.onclick = () => { shown += PAGE; renderSceneTable(); };
}

// ── Snow history ────────────────────────────────────────────────────────────
let HISTORY = null;
async function loadHistory() {
  if (HISTORY) return;
  const box = document.getElementById('history-chart');
  try {
    HISTORY = await fetch('data/snow_timeline.json').then(r => { if (!r.ok) throw new Error(r.status); return r.json(); });
  } catch (e) {
    box.textContent = 'Snow history not available yet.';
    return;
  }
  box.classList.remove('loading');
  renderSeasons();
  renderMultiples();
  window.addEventListener('resize', () => { renderSeasons(); renderMultiples(); });
  document.getElementById('history-caveat').textContent = 'Why some years are thin: ' + (HISTORY.caveat || '');
  const g = HISTORY.generated ? new Date(HISTORY.generated) : null;
  document.getElementById('history-source').innerHTML =
    `Source: <code>s2:snow_ice_percentage</code> from Copernicus Sentinel-2 C1 L2A scene metadata via ` +
    `<a href="https://research.taylorgeospatial.org/s2-stac-geoparquet/" target="_blank" rel="noopener">s2-stac-geoparquet</a>. ` +
    (g ? `Rebuilt ${g.toLocaleDateString('en-US', { dateStyle: 'medium' })}. ` : '') +
    `<a href="data/snow_timeline.json">Download snow_timeline.json</a>.`;
}

// Weekly bins per season: mean snow % over every clear tile-scene that week.
const SEASON_SPAN_DAYS = 273; // Oct 1 → Jun 30
function seasonBins() {
  const bins = {}; // label -> {weekIdx: [vals]}
  for (const rows of Object.values(HISTORY.tiles)) {
    for (const [date, snow] of rows) {
      const m = +date.slice(5, 7);
      if (m >= 7 && m <= 9) continue;
      const s = seasonOf(date);
      const day = (Date.parse(date) - Date.parse(s.start)) / 86400000;
      if (day < 0 || day >= SEASON_SPAN_DAYS) continue;
      const w = Math.floor(day / 7);
      ((bins[s.label] ||= {})[w] ||= []).push(snow);
    }
  }
  // Smooth with a centred 3-week window (pooling the scenes, so a week with
  // many scenes counts for more). Different orbits image different tiles,
  // and single weeks jump around with whichever tiles were clear.
  const out = {};
  for (const [label, weeks] of Object.entries(bins)) {
    const ws = Object.keys(weeks).map(Number).sort((a, b) => a - b);
    out[label] = ws.map(w => {
      const pool = [w - 1, w, w + 1].flatMap(k => weeks[k] || []);
      return { w, v: pool.reduce((a, b) => a + b, 0) / pool.length, n: (weeks[w] || []).length };
    }).filter(p => p.n >= 2);
  }
  return out;
}

function renderSeasons() {
  const box = document.getElementById('history-chart');
  const bins = seasonBins();
  const cur = seasonOf(todayStr()).label;
  const labels = Object.keys(bins).sort();
  const prev = labels.filter(l => l < cur).pop();
  const W = Math.max(320, box.clientWidth - 20), H = W < 500 ? 220 : 280;
  const P = { l: 36, r: 70, t: 12, b: 26 };
  const cw = W - P.l - P.r, ch = H - P.t - P.b;
  const nW = Math.ceil(SEASON_SPAN_DAYS / 7);
  const x = w => P.l + (w + 0.5) / nW * cw;
  const y = v => P.t + ch - (v / 100) * ch;
  let g = '';
  for (const t of [0, 25, 50, 75, 100]) {
    g += `<line x1="${P.l}" x2="${W - P.r}" y1="${y(t)}" y2="${y(t)}" stroke="rgba(255,255,255,${t ? 0.05 : 0.15})"/>`;
    g += `<text x="${P.l - 6}" y="${y(t) + 3}" text-anchor="end" font-size="9" fill="var(--text-dim)" font-family="var(--mono)">${t}%</text>`;
  }
  ['Oct', 'Nov', 'Dec', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun'].forEach((m, i) => {
    const d = (Date.UTC(2001 + (i >= 3 ? 1 : 0), (9 + i) % 12, 1) - Date.UTC(2001, 9, 1)) / 86400000;
    g += `<text x="${P.l + d / SEASON_SPAN_DAYS * cw}" y="${H - 8}" font-size="9" fill="var(--text-dim)" font-family="var(--mono)">${m}</text>`;
  });
  const path = pts => pts.map((p, i) => `${i ? 'L' : 'M'}${x(p.w).toFixed(1)},${y(p.v).toFixed(1)}`).join('');
  const endLabel = (pts, text, color) => pts.length
    ? `<text x="${x(pts[pts.length - 1].w) + 6}" y="${y(pts[pts.length - 1].v) + 3}" font-size="10" fill="${color}" font-family="var(--mono)">${text}</text>` : '';
  for (const l of labels) {
    if (l === cur || l === prev) continue;
    g += `<path d="${path(bins[l])}" fill="none" stroke="rgba(154,166,184,0.28)" stroke-width="1"/>`;
  }
  if (prev) {
    g += `<path d="${path(bins[prev])}" fill="none" stroke="rgba(200,210,225,0.7)" stroke-width="1.5" stroke-dasharray="4 3"/>`;
    g += endLabel(bins[prev], prev, 'var(--text-muted)');
  }
  const curPts = bins[cur] || [];
  if (curPts.length) {
    g += `<path d="${path(curPts)}" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linejoin="round"/>`;
    for (const p of curPts) g += `<circle cx="${x(p.w)}" cy="${y(p.v)}" r="3" fill="var(--accent)" stroke="var(--bg)" stroke-width="1.5"/>`;
    g += endLabel(curPts, cur, 'var(--accent)');
  }
  g += `<line id="xh" x1="0" x2="0" y1="${P.t}" y2="${P.t + ch}" stroke="rgba(255,255,255,0.25)" style="display:none"/>`;
  g += `<rect id="hit" x="${P.l}" y="${P.t}" width="${cw}" height="${ch}" fill="transparent"/>`;
  const legend = `<div class="mult-title" style="justify-content:flex-start;gap:16px;margin-bottom:6px">
    <span><span style="display:inline-block;width:16px;height:3px;background:var(--accent);vertical-align:middle"></span> ${cur} (this season${curPts.length ? `, ${curPts.length} week${curPts.length === 1 ? '' : 's'} so far` : ', no clear weeks yet'})</span>
    ${prev ? `<span><span style="display:inline-block;width:16px;border-top:2px dashed rgba(200,210,225,0.7);vertical-align:middle"></span> ${prev}</span>` : ''}
    <span><span style="display:inline-block;width:16px;height:1px;background:rgba(154,166,184,0.5);vertical-align:middle"></span> earlier seasons</span></div>`;
  box.innerHTML = legend + `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Weekly snow cover by season">${g}</svg>`;
  const svg = box.querySelector('svg'), xh = svg.querySelector('#xh');
  svg.querySelector('#hit').addEventListener('mousemove', ev => {
    const r = svg.getBoundingClientRect();
    const px = (ev.clientX - r.left) * (W / r.width);
    const w = Math.max(0, Math.min(nW - 1, Math.round((px - P.l) / cw * nW - 0.5)));
    xh.setAttribute('x1', x(w)); xh.setAttribute('x2', x(w)); xh.style.display = '';
    const d0 = new Date(Date.UTC(2001, 9, 1) + w * 7 * 86400000);
    const lab = d0.toLocaleDateString('en-US', { month: 'short', day: 'numeric', timeZone: 'UTC' });
    const at = l => (bins[l] || []).find(p => p.w === w);
    const others = labels.filter(l => l !== cur).map(at).filter(Boolean).map(p => p.v).sort((a, b) => a - b);
    const med = others.length ? others[Math.floor(others.length / 2)] : null;
    const c = at(cur), pv = prev && at(prev);
    showTip(`<b>Week of ${lab}</b><br>` +
      `${cur}: ${c ? Math.round(c.v) + '%' : 'no clear scenes'}<br>` +
      (prev ? `${prev}: ${pv ? Math.round(pv.v) + '%' : '—'}<br>` : '') +
      (med != null ? `Past seasons median: ${Math.round(med)}% (${others.length} seasons)` : ''), ev);
  });
  svg.querySelector('#hit').addEventListener('mouseleave', () => { xh.style.display = 'none'; hideTip(); });
}

function renderMultiples() {
  const el = document.getElementById('tile-multiples');
  const tiles = Object.keys(HISTORY.tiles).sort();
  const t0 = Date.parse('2018-01-01'), t1 = Date.now();
  el.innerHTML = tiles.map(t => `<div class="chart-box" data-tile="${t}"><div class="mult-title"><span>${t}</span><span>${HISTORY.tiles[t].length} clear scenes</span></div><svg></svg></div>`).join('');
  el.querySelectorAll('.chart-box').forEach(box => {
    const t = box.dataset.tile, rows = HISTORY.tiles[t];
    const W = Math.max(240, box.clientWidth - 16), H = 90, P = { l: 26, r: 4, t: 4, b: 14 };
    const cw = W - P.l - P.r, ch = H - P.t - P.b;
    const x = d => P.l + (Date.parse(d) - t0) / (t1 - t0) * cw;
    const y = v => P.t + ch - v / 100 * ch;
    let g = `<line x1="${P.l}" x2="${W - P.r}" y1="${y(0)}" y2="${y(0)}" stroke="rgba(255,255,255,0.15)"/>`;
    g += `<text x="${P.l - 4}" y="${y(100) + 6}" text-anchor="end" font-size="8" fill="var(--text-dim)" font-family="var(--mono)">100%</text>`;
    for (let yr = 2018; yr <= new Date().getUTCFullYear(); yr++) {
      const xx = x(`${yr}-01-01`);
      g += `<line x1="${xx}" x2="${xx}" y1="${P.t}" y2="${P.t + ch}" stroke="rgba(255,255,255,0.04)"/>`;
      if (W > 300 || yr % 2 === 0) g += `<text x="${xx + 2}" y="${H - 3}" font-size="8" fill="var(--text-dim)" font-family="var(--mono)">${String(yr).slice(2)}</text>`;
    }
    for (const [d, v] of rows) g += `<circle cx="${x(d).toFixed(1)}" cy="${y(v).toFixed(1)}" r="1.6" fill="var(--accent)" fill-opacity="0.65"/>`;
    const svg = box.querySelector('svg');
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', `Snow cover on tile ${t}, 2018 to today`);
    svg.innerHTML = g;
    svg.addEventListener('mousemove', ev => {
      const r = svg.getBoundingClientRect();
      const px = (ev.clientX - r.left) * (W / r.width), py = (ev.clientY - r.top) * (H / r.height);
      let best = null, bd = 64;
      for (const row of rows) {
        const dx = x(row[0]) - px, dy = y(row[1]) - py, dd = dx * dx + dy * dy;
        if (dd < bd) { bd = dd; best = row; }
      }
      if (best) showTip(`<b>${t}</b> · ${fmtDay(best[0])}<br>snow ${fmtPct(best[1])} · cloud ${fmtPct(best[2])}`, ev);
      else hideTip();
    });
    svg.addEventListener('mouseleave', hideTip);
  });
}
