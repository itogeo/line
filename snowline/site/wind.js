// Snowline — wind: a 48-hour wind map (NOAA RTMA, 2.5 km) and station wind for
// the last 7 days (Montana Mesonet, SNOTEL, NWS mountain stations). Data from fetch_wind.py (hourly), served
// from R2 at /snow/api/wind/. The map page calls Wind.init(map) once the map
// is ready and Wind.addLayers(map) whenever the basemap style is (re)loaded.

const Wind = (() => {
  const API = '/snow/api/wind';
  const TZ = 'America/Denver';
  let MAP = null, GRID = null, STATIONS = null, HOUR = null, playTimer = null, popup = null;
  // Which arrows show: the RTMA grid, the stations, or both. Remembered per browser.
  let SHOW = 'both';
  try { SHOW = localStorage.getItem('snowline-wind-show') || 'both'; } catch (e) { /* default */ }

  // Speed colours (mph): calm grey to strong red. Blue stays reserved for snow.
  const STOPS = [[0, '#c9cdd2'], [5, '#e9e2a8'], [10, '#ffd166'], [15, '#ffb74d'], [25, '#ff7043'], [40, '#d84315']];
  const colorExpr = ['interpolate', ['linear'], ['get', 'spd'], ...STOPS.flat()];
  const colorOf = v => { let c = STOPS[0][1]; for (const [s, col] of STOPS) if (v >= s) c = col; return c; };
  const COMPASS = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
  const compass = d => COMPASS[Math.round(((d % 360) + 360) % 360 / 45) % 8];
  const fmtHour = t => new Date(t).toLocaleString('en-US', { weekday: 'short', hour: 'numeric', timeZone: TZ });
  const fmtDay = t => new Date(t).toLocaleDateString('en-US', { weekday: 'short', timeZone: TZ });
  const on = () => document.getElementById('tog-wind')?.checked;

  async function getJSON(name) {
    for (const url of [`${API}/${name}`, `data/wind/${name}`]) {   // R2, then a local build
      try { const r = await fetch(url); if (r.ok) return await r.json(); } catch (e) { /* next */ }
    }
    return null;
  }
  const bytes = b64 => Uint8Array.from(atob(b64), c => c.charCodeAt(0));

  // Downwind arrow, drawn once as an SDF so the layer can colour it.
  function arrowImage() {
    const s = 32, c = document.createElement('canvas');
    c.width = c.height = s;
    const g = c.getContext('2d');
    g.fillStyle = '#fff';
    g.beginPath();
    g.moveTo(s / 2, 2); g.lineTo(s - 7, s / 2 + 1); g.lineTo(s / 2 + 3, s / 2 - 2); g.lineTo(s / 2 + 3, s - 2);
    g.lineTo(s / 2 - 3, s - 2); g.lineTo(s / 2 - 3, s / 2 - 2); g.lineTo(7, s / 2 + 1);
    g.closePath(); g.fill();
    return { width: s, height: s, data: new Uint8Array(g.getImageData(0, 0, s, s).data.buffer) };
  }

  function gridFeatures(h) {
    if (!GRID || !GRID.hours.length) return { type: 'FeatureCollection', features: [] };
    const g = GRID.grid, hr = GRID.hours[h];
    const spd = bytes(hr.spd), gst = bytes(hr.gst), dir = bytes(hr.dir);
    const features = [];
    for (let i = 0; i < g.ny; i++) for (let j = 0; j < g.nx; j++) {
      const k = i * g.nx + j;
      features.push({ type: 'Feature',
        geometry: { type: 'Point', coordinates: [g.west + (j + 0.5) * g.res, g.north - (i + 0.5) * g.res] },
        properties: { spd: spd[k], gst: gst[k], dir: dir[k] * 2 } });
    }
    return { type: 'FeatureCollection', features };
  }

  function stationFeatures() {
    return { type: 'FeatureCollection', features: (STATIONS?.stations || []).map(s => {
      const last = s.obs[s.obs.length - 1];
      return { type: 'Feature', geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
        properties: { id: s.id, name: s.name, elev: s.elevation_ft, spd: last[1] || 0, dir: last[3] == null ? 0 : last[3], hasdir: last[3] != null } };
    }) };
  }

  function addLayers(map) {
    MAP = map || MAP;
    if (!MAP || !MAP.getStyle()) return;
    if (!MAP.hasImage('wind-arrow')) MAP.addImage('wind-arrow', arrowImage(), { sdf: true });
    const vis = on() ? 'visible' : 'none';
    if (!MAP.getSource('wind-grid')) MAP.addSource('wind-grid', { type: 'geojson', data: gridFeatures(HOUR ?? 0) });
    if (!MAP.getLayer('wind-grid')) {
      MAP.addLayer({ id: 'wind-grid', type: 'symbol', source: 'wind-grid', layout: {
        visibility: vis, 'icon-image': 'wind-arrow', 'icon-rotate': ['+', ['get', 'dir'], 180],
        'icon-rotation-alignment': 'map', 'icon-allow-overlap': false, 'icon-ignore-placement': false,
        // Wide padding thins the grid: Mapbox drops arrows that would collide, so
        // zoomed out shows roughly one per 40 px and zooming in fills in detail.
        'icon-padding': 14, 'symbol-sort-key': ['-', 0, ['get', 'spd']],
        'icon-size': ['interpolate', ['linear'], ['get', 'spd'], 0, 0.35, 10, 0.5, 30, 0.75] },
        paint: { 'icon-color': colorExpr, 'icon-opacity': 0.7 } });
    }
    if (!MAP.getSource('wind-stations')) MAP.addSource('wind-stations', { type: 'geojson', data: stationFeatures() });
    if (!MAP.getLayer('wind-station-dots')) {
      MAP.addLayer({ id: 'wind-station-dots', type: 'circle', source: 'wind-stations', layout: { visibility: vis },
        paint: { 'circle-radius': ['interpolate', ['linear'], ['get', 'elev'], 4500, 5, 9000, 8], 'circle-color': '#17171a', 'circle-stroke-width': 2, 'circle-stroke-color': colorExpr } });
      MAP.addLayer({ id: 'wind-station-arrows', type: 'symbol', source: 'wind-stations', filter: ['get', 'hasdir'], layout: {
        visibility: vis, 'icon-image': 'wind-arrow', 'icon-size': 0.42, 'icon-allow-overlap': true,
        'icon-rotate': ['+', ['get', 'dir'], 180], 'icon-rotation-alignment': 'map' },
        paint: { 'icon-color': colorExpr } });
      MAP.on('click', 'wind-station-dots', e => openStation(e.features[0].properties.id));
      MAP.on('mouseenter', 'wind-station-dots', () => MAP.getCanvas().style.cursor = 'pointer');
      MAP.on('mouseleave', 'wind-station-dots', () => MAP.getCanvas().style.cursor = '');
    }
  }

  function setVisible(v) {
    const want = { 'wind-grid': SHOW !== 'stations', 'wind-station-dots': SHOW !== 'grid', 'wind-station-arrows': SHOW !== 'grid' };
    Object.entries(want).forEach(([id, w]) => {
      if (MAP?.getLayer(id)) MAP.setLayoutProperty(id, 'visibility', v && w ? 'visible' : 'none');
    });
    document.querySelectorAll('#wind-show button').forEach(b => b.classList.toggle('on', b.dataset.show === SHOW));
    document.getElementById('wind-control').style.display = v && GRID?.hours.length ? '' : 'none';
    if (!v) return stop();
    // Above the imagery and shading added since; the page then lifts its own pins over these.
    ['wind-grid', 'wind-station-dots', 'wind-station-arrows'].forEach(id => { if (MAP?.getLayer(id)) MAP.moveLayer(id); });
    if (typeof bringSnotelToTop === 'function') bringSnotelToTop();
  }

  function setHour(h) {
    if (!GRID?.hours.length) return;
    HOUR = Math.max(0, Math.min(GRID.hours.length - 1, h));
    MAP?.getSource('wind-grid')?.setData(gridFeatures(HOUR));
    document.getElementById('wind-hour').value = HOUR;
    document.getElementById('wind-time').textContent = fmtHour(GRID.hours[HOUR].t);
  }
  function stop() { clearInterval(playTimer); playTimer = null; const b = document.getElementById('wind-play'); if (b) b.textContent = '▶'; }
  function play() {
    if (playTimer) return stop();
    document.getElementById('wind-play').textContent = '❚❚';
    if (HOUR >= GRID.hours.length - 1) setHour(0);
    playTimer = setInterval(() => { if (HOUR >= GRID.hours.length - 1) stop(); else setHour(HOUR + 1); }, 450);
  }

  // ── Station summaries and charts ──
  function summary(s, hours) {
    const cut = Date.now() - hours * 3600e3;
    const rows = s.obs.filter(o => Date.parse(o[0]) >= cut);
    if (!rows.length) return null;
    let gmax = null, smax = 0, x = 0, y = 0;
    for (const [t, spd, gst, dir] of rows) {
      if (gst != null && (!gmax || gst > gmax[1])) gmax = [t, gst];
      smax = Math.max(smax, spd);
      if (dir != null) { x += spd * Math.sin(dir * Math.PI / 180); y += spd * Math.cos(dir * Math.PI / 180); }
    }
    const mean = rows.reduce((a, o) => a + o[1], 0) / rows.length;
    const prevailing = (x || y) ? compass(Math.atan2(x, y) * 180 / Math.PI) : null;
    return { rows, gmax, smax, mean, prevailing };
  }

  function chart48(s) {
    const sm = summary(s, 48);
    if (!sm) return '<div style="color:var(--text-dim)">No readings in the last 48 hours.</div>';
    const W = 268, H = 90, P = 16, t0 = Date.now() - 48 * 3600e3, t1 = Date.now();
    const top = Math.max(10, Math.ceil(Math.max(sm.smax, sm.gmax ? sm.gmax[1] : 0) / 10) * 10);
    const X = t => P + (Date.parse(t) - t0) / (t1 - t0) * (W - P - 4), Y = v => H - 12 - v / top * (H - 26);
    const spd = sm.rows.map((o, i) => `${i ? 'L' : 'M'}${X(o[0]).toFixed(1)},${Y(o[1]).toFixed(1)}`).join('');
    const gst = sm.rows.filter(o => o[2] != null).map(o => `<circle cx="${X(o[0]).toFixed(1)}" cy="${Y(o[2]).toFixed(1)}" r="1.2" fill="#ff7043" opacity="0.7"/>`).join('');
    const arrows = sm.rows.filter((o, i) => i % 3 === 0 && o[3] != null).map(o =>
      `<path d="M0,-4 L3,2 L0,0.5 L-3,2 Z" fill="${colorOf(o[1])}" transform="translate(${X(o[0]).toFixed(1)},8) rotate(${o[3] + 180})"/>`).join('');
    const ticks = [0, 12, 24, 36, 48].map(h => { const t = new Date(t0 + h * 3600e3).toISOString();
      return `<text x="${X(t).toFixed(1)}" y="${H - 1}" font-size="7" fill="var(--text-dim)" text-anchor="middle">${h === 48 ? 'now' : fmtHour(t)}</text>`; }).join('');
    return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block">
      <text x="2" y="${Y(top) + 3}" font-size="7" fill="var(--text-dim)">${top}</text><text x="2" y="${Y(0)}" font-size="7" fill="var(--text-dim)">0</text>
      <line x1="${P}" x2="${W - 4}" y1="${Y(0)}" y2="${Y(0)}" stroke="var(--border)"/>${arrows}${gst}
      <path d="${spd}" fill="none" stroke="#ffd166" stroke-width="1.4"/>${ticks}</svg>`;
  }

  function chart7d(s) {
    const days = {};
    for (const [t, spd, gst] of s.obs) {
      const d = new Date(t).toLocaleDateString('en-CA', { timeZone: TZ });
      const v = days[d] || (days[d] = { t, gmax: 0, smax: 0 });
      v.gmax = Math.max(v.gmax, gst ?? spd); v.smax = Math.max(v.smax, spd);
    }
    const ks = Object.keys(days).sort().slice(-7);
    if (!ks.length) return '';
    const top = Math.max(10, Math.ceil(Math.max(...ks.map(k => days[k].gmax)) / 10) * 10);
    const W = 268, H = 64, bw = (W - 10) / ks.length;
    const bars = ks.map((k, i) => { const v = days[k], x = 6 + i * bw, h = v.gmax / top * (H - 24), h2 = v.smax / top * (H - 24);
      return `<rect x="${x + 3}" y="${H - 12 - h}" width="${bw - 6}" height="${h}" fill="${colorOf(v.gmax)}" opacity="0.45"/>
        <rect x="${x + 3}" y="${H - 12 - h2}" width="${bw - 6}" height="${h2}" fill="${colorOf(v.smax)}"/>
        <text x="${x + bw / 2}" y="${H - 14 - h}" font-size="7" fill="var(--text)" text-anchor="middle">${Math.round(v.gmax)}</text>
        <text x="${x + bw / 2}" y="${H - 2}" font-size="7" fill="var(--text-dim)" text-anchor="middle">${fmtDay(v.t)}</text>`; }).join('');
    return `<svg viewBox="0 0 ${W} ${H}" width="100%" style="display:block">${bars}</svg>`;
  }

  function popupHTML(s) {
    const a = summary(s, 48), w = summary(s, 24 * 7);
    const line = (lab, sm) => sm ? `<div><b>${lab}</b>: highest gust ${sm.gmax ? Math.round(sm.gmax[1]) + ' mph (' + fmtHour(sm.gmax[0]) + ')' : '–'}, `
      + `average ${Math.round(sm.mean)} mph${sm.prevailing ? ', mostly from the ' + sm.prevailing : ''}</div>` : '';
    return `<div class="wind-pop"><div class="popup-name">${s.name}</div>
      <div style="font-size:10px;color:var(--text-dim);margin-bottom:5px">${s.elevation_ft.toLocaleString('en-US')} ft &middot; ${s.sensor_height ? 'sensor ' + s.sensor_height + ' &middot; ' : ''}${s.source || 'Montana Mesonet'}</div>
      <div style="font-size:10px;line-height:1.5">${line('Last 48 h', a)}${line('Last 7 days', w)}</div>
      <div class="wind-h">Last 48 hours <span>speed <i style="background:#ffd166"></i> gusts <i style="background:#ff7043"></i> arrows point downwind</span></div>${chart48(s)}
      <div class="wind-h">Last 7 days <span>daily high gust (light) and high speed (solid), mph</span></div>${chart7d(s)}</div>`;
  }

  function openStation(id) {
    const s = STATIONS?.stations.find(x => x.id === id);
    if (!s || !MAP) return;
    const box = document.getElementById('tog-wind');
    if (box && !box.checked) { box.checked = true; setVisible(true); }
    if (popup) popup.remove();
    popup = new mapboxgl.Popup({ offset: 12, maxWidth: '310px' }).setLngLat([s.lon, s.lat]).setHTML(popupHTML(s)).addTo(MAP);
    if (!MAP.getBounds().contains([s.lon, s.lat])) MAP.easeTo({ center: [s.lon, s.lat] });
  }

  function renderPanel() {
    const el = document.getElementById('wind-stations');
    if (!el) return;
    const rows = (STATIONS?.stations || []).map(s => ({ s, a: summary(s, 48), w: summary(s, 24 * 7) })).filter(r => r.a)
      .sort((p, q) => ((q.a.gmax || [0, 0])[1]) - ((p.a.gmax || [0, 0])[1]));
    if (!rows.length) { el.innerHTML = '<div style="font-size:10px;color:var(--text-dim)">Wind data not available yet.</div>'; return; }
    const row = ({ s, a, w }) => {
      const pts = a.rows.map(o => o[1]), mx = Math.max(10, ...pts);
      const spark = pts.map((v, i) => `${i ? 'L' : 'M'}${(i / Math.max(1, pts.length - 1) * 60).toFixed(1)},${(14 - v / mx * 13).toFixed(1)}`).join('');
      const last = s.obs[s.obs.length - 1];
      const arrow = last[3] == null ? '' : `<svg width="12" height="12" viewBox="-6 -6 12 12"><path d="M0,-5 L4,3 L0,1 L-4,3 Z" fill="${colorOf(last[1])}" transform="rotate(${last[3] + 180})"/></svg>`;
      return `<div class="wind-row" data-id="${s.id}" title="${s.name}: click for 48-hour and 7-day charts">
        <span class="wr-name">${s.name}</span><svg class="wr-spark" viewBox="0 0 60 15"><path d="${spark}" fill="none" stroke="#ffd166" stroke-width="1"/></svg>
        <span class="wr-g" style="color:${colorOf(a.gmax ? a.gmax[1] : 0)}">${a.gmax ? Math.round(a.gmax[1]) : '–'}</span>
        <span class="wr-g wr-dim">${w && w.gmax ? Math.round(w.gmax[1]) : '–'}</span>${arrow}</div>`;
    };
    el.innerHTML = `<div class="wind-row wind-head"><span class="wr-name"></span><span class="wr-spark">48 h speed</span><span class="wr-g">gust 48h</span><span class="wr-g wr-dim">7 d</span><span style="width:12px"></span></div>`
      + rows.slice(0, 8).map(row).join('')
      + (rows.length > 8 ? `<details class="wind-more"><summary>All ${rows.length} stations</summary>${rows.slice(8).map(row).join('')}</details>` : '');
    el.querySelectorAll('.wind-row[data-id]').forEach(r => r.onclick = () => openStation(r.dataset.id));
  }

  async function init(map) {
    MAP = map;
    [GRID, STATIONS] = await Promise.all([getJSON('grid_48h.json'), getJSON('stations_7d.json')]);
    if (GRID?.hours.length) HOUR = GRID.hours.length - 1;
    addLayers(map);
    if (GRID?.hours.length) {
      const sl = document.getElementById('wind-hour');
      sl.max = GRID.hours.length - 1;
      sl.oninput = () => { stop(); setHour(+sl.value); };
      document.getElementById('wind-play').onclick = play;
      setHour(HOUR);
    }
    MAP.getSource('wind-stations')?.setData(stationFeatures());
    document.getElementById('tog-wind').addEventListener('change', e => setVisible(e.target.checked));
    document.querySelectorAll('#wind-show button').forEach(b => b.onclick = () => {
      SHOW = b.dataset.show;
      try { localStorage.setItem('snowline-wind-show', SHOW); } catch (e) { /* not kept */ }
      setVisible(on());
    });
    setVisible(on());
    renderPanel();
    const note = document.getElementById('wind-note');
    if (note && STATIONS?.generated) note.textContent = `Updated ${new Date(STATIONS.generated).toLocaleString('en-US', { weekday: 'short', hour: 'numeric', minute: '2-digit', timeZone: TZ })}`;
  }

  // layers: clickable (the map's spot-click skips them); top: kept above the imagery.
  return { init, addLayers, openStation, layers: ['wind-station-dots', 'wind-station-arrows'],
           top: ['wind-grid', 'wind-station-dots', 'wind-station-arrows'] };
})();
