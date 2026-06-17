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
