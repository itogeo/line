export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === '/api/current') {
      const val = await env.RIVERLINE_KV.get('gateway:current');
      if (!val) return new Response('No data yet', { status: 503 });
      return new Response(val, {
        headers: {
          'Content-Type': 'application/json',
          'Access-Control-Allow-Origin': '*',
          'Cache-Control': 'no-store',
        },
      });
    }

    if (url.pathname === '/api/chart') {
      const [hist, bands] = await Promise.all([
        env.RIVERLINE_DB.prepare(
          'SELECT date, cfs FROM daily_flow ORDER BY date DESC LIMIT 90'
        ).all(),
        env.RIVERLINE_DB.prepare(
          'SELECT doy, p10, p25, p50, p75, p90 FROM doy_stats ORDER BY doy'
        ).all(),
      ]);
      return new Response(
        JSON.stringify({ history: hist.results, bands: bands.results }),
        {
          headers: {
            'Content-Type': 'application/json',
            'Access-Control-Allow-Origin': '*',
            'Cache-Control': 'public, max-age=300',
          },
        }
      );
    }

    if (url.pathname === '/api/snotel') {
      const triplet = url.searchParams.get('triplet');
      const days = Math.min(parseInt(url.searchParams.get('days') || '49', 10), 400);
      if (!triplet) return new Response('Bad request', { status: 400 });
      const end = new Date();
      const start = new Date(+end - days * 86400000);
      const fmt = d => d.toISOString().slice(0, 10);
      const awdbUrl = `https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data?stationTriplets=${encodeURIComponent(triplet)}&elements=WTEQ,SNWD,TOBS&duration=DAILY&beginDate=${fmt(start)}&endDate=${fmt(end)}&periodRef=END`;
      try {
        const r = await fetch(awdbUrl, { headers: { 'User-Agent': 'RiverLine/1.0 (Ito Geospatial)' } });
        const body = await r.text();
        return new Response(body, {
          headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*', 'Cache-Control': 'public, max-age=3600' },
        });
      } catch (_) {
        return new Response('[]', { status: 502, headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' } });
      }
    }

    if (url.pathname.startsWith('/api/') && request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type',
        },
      });
    }

    return env.ASSETS.fetch(request);
  },
};
