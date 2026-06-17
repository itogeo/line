// ═══════════════════════════════════════════════════
// Snowline — Shared constants and utilities
// Used by both index.html (map) and metadata.html (data catalog)
// ═══════════════════════════════════════════════════

// Mountain ranges
const RANGES = {
  'Gallatin':      { lat: [45.2, 45.7], lon: [-111.3, -110.8], color: '#4FC3F7', hue: 195 },
  'Bridger':       { lat: [45.7, 46.0], lon: [-111.1, -110.8], color: '#26c6da', hue: 175 },
  'Madison':       { lat: [44.9, 45.3], lon: [-111.5, -111.2], color: '#81d4fa', hue: 210 },
  'Gravelly':      { lat: [44.7, 45.1], lon: [-112.1, -111.6], color: '#b39ddb', hue: 270 },
  'Tobacco Root':  { lat: [45.4, 45.7], lon: [-112.1, -111.8], color: '#b2ebf2', hue: 185 },
  'Crazy':         { lat: [45.9, 46.2], lon: [-110.6, -110.3], color: '#ffcc80', hue: 35 },
  'Absaroka':      { lat: [45.0, 45.5], lon: [-110.5, -110.2], color: '#80deea', hue: 165 },
  'Beartooth':     { lat: [44.9, 45.6], lon: [-110.2, -109.5], color: '#a7ffeb', hue: 155 },
  'Yellowstone':   { lat: [44.5, 45.0], lon: [-111.2, -110.4], color: '#fff59d', hue: 50 },
};

// Season timeline
const SEASON_START = '2025-10-01';
const SEASON_END = '2026-05-31';
const SEASON_DAYS = Math.round((new Date(SEASON_END) - new Date(SEASON_START)) / 86400000);

// Get range base color
function rangeColor(rng) {
  return RANGES[rng]?.color || '#4FC3F7';
}

// Get unique color for a station within its range
const _stationColorCache = {};
function stationColor(triplet, snotelList, normalsStations) {
  if (_stationColorCache[triplet]) return _stationColorCache[triplet];
  // Find station's range
  const info = normalsStations?.[triplet] || (snotelList || []).find(s => s.id === triplet);
  if (!info) return '#4FC3F7';
  let rng = 'Other';
  for (const [r, b] of Object.entries(RANGES)) {
    if (info.lat >= b.lat[0] && info.lat <= b.lat[1] && info.lon >= b.lon[0] && info.lon <= b.lon[1]) { rng = r; break; }
  }
  const color = RANGES[rng]?.color || '#4FC3F7';
  _stationColorCache[triplet] = color;
  return color;
}

// Convert a date string to an x position on the fixed Oct-May timeline
function dateToSeasonX(dateStr, w, padL) {
  const d = (new Date(dateStr) - new Date(SEASON_START)) / 86400000;
  return padL + (d / SEASON_DAYS) * (w - padL - 2);
}

// Assign a station to a mountain range
function stationRange(s) {
  for (const [rng, b] of Object.entries(RANGES)) {
    if (s.lat >= b.lat[0] && s.lat <= b.lat[1] && s.lon >= b.lon[0] && s.lon <= b.lon[1]) return rng;
  }
  return 'Other';
}
