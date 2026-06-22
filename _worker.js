export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const host = url.hostname;
    const path = url.pathname;

    // ── SNOW ──────────────────────────────────────────────────────────────────

    if (host.includes('snow')) {
      // R2 tile serving — fall back to git-committed tiles if not in R2
      if (path.startsWith('/api/tile/')) {
        const tilePath = path.slice('/api/tile'.length);
        const key = 'tiles' + tilePath;
        if (env.SNOWLINE_BUCKET) {
          const obj = await env.SNOWLINE_BUCKET.get(key);
          if (obj) {
            return new Response(obj.body, {
              headers: {
                'Content-Type': 'image/webp',
                'Cache-Control': 'public, max-age=86400',
                'Access-Control-Allow-Origin': '*',
              },
            });
          }
        }
        return env.ASSETS.fetch(new Request(
          new URL('/snowline/site/data_10m' + tilePath, url),
          request,
        ));
      }

      // Image proxy (webcams blocked by CORS)
      if (path === '/api/camproxy' && url.searchParams.get('url')) {
        const imgUrl = url.searchParams.get('url');
        const allowed = ['nps.gov', 'mdt.mt.gov', 'ipcamlive.com', 'mediaassets.kbzk.com'];
        const imgHost = new URL(imgUrl).hostname;
        if (!allowed.some(d => imgHost.endsWith(d))) {
          return new Response('Forbidden', { status: 403 });
        }
        try {
          const imgResp = await fetch(imgUrl, { headers: { 'User-Agent': 'snowline-webcam/1.0' } });
          const body = await imgResp.arrayBuffer();
          return new Response(body, {
            headers: {
              'Content-Type': imgResp.headers.get('Content-Type') || 'image/jpeg',
              'Access-Control-Allow-Origin': '*',
              'Cache-Control': 'public, max-age=120',
            },
          });
        } catch (e) {
          return new Response('Proxy error', { status: 502 });
        }
      }

      // MDT camera API proxy
      if (path === '/api/mdtcam' && url.searchParams.get('id')) {
        const posId = url.searchParams.get('id');
        try {
          const r = await fetch(`https://app.mdt.mt.gov/atms/public/camera/lastFiveImages/${posId}`);
          const data = await r.json();
          const imgUrl = data?.data?.lastFivePolledImages?.[0]?.publicSharePath;
          if (imgUrl) {
            const imgResp = await fetch(imgUrl);
            const body = await imgResp.arrayBuffer();
            return new Response(body, {
              headers: {
                'Content-Type': 'image/jpeg',
                'Access-Control-Allow-Origin': '*',
                'Cache-Control': 'public, max-age=300',
              },
            });
          }
          return new Response('No image', { status: 404 });
        } catch (e) {
          return new Response('MDT error', { status: 502 });
        }
      }

      // SNOTEL API proxy (CORS)
      if (path === '/api/snotel' && url.searchParams.get('triplets')) {
        const triplets = url.searchParams.get('triplets');
        const begin = url.searchParams.get('begin') || '2025-10-01';
        const end = url.searchParams.get('end') || new Date().toISOString().slice(0, 10);
        const apiUrl = `https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data?stationTriplets=${triplets}&elements=SNWD,WTEQ&duration=DAILY&beginDate=${begin}&endDate=${end}`;
        try {
          const r = await fetch(apiUrl, { headers: { 'User-Agent': 'snowline/1.0' } });
          const body = await r.text();
          return new Response(body, {
            headers: {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*',
              'Cache-Control': 'public, max-age=3600',
            },
          });
        } catch (e) {
          return new Response(JSON.stringify({ error: 'SNOTEL API error' }), { status: 502 });
        }
      }

      // Feedback POST → creates issue in itogeo/line
      if (path === '/api/feedback' && request.method === 'POST') {
        try {
          const { text, date } = await request.json();
          if (!text || text.trim().length === 0) {
            return new Response(JSON.stringify({ error: 'Empty feedback' }), { status: 400 });
          }
          const title = 'Feedback: ' + text.substring(0, 60) + (text.length > 60 ? '...' : '');
          const body =
            text +
            '\n\n---\n*Submitted from snow.line.itogeospatial.com*\n*Date viewed: ' +
            (date || 'unknown') +
            '*\n*' +
            new Date().toISOString() +
            '*';
          const ghResp = await fetch('https://api.github.com/repos/itogeo/line/issues', {
            method: 'POST',
            headers: {
              Authorization: 'Bearer ' + env.GH_FEEDBACK_TOKEN,
              'Content-Type': 'application/json',
              'User-Agent': 'snowline-feedback',
            },
            body: JSON.stringify({ title, body, labels: ['feedback', 'snowline'] }),
          });
          if (ghResp.ok) {
            return new Response(JSON.stringify({ ok: true }), {
              headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
            });
          }
          return new Response(JSON.stringify({ error: 'GitHub API error' }), { status: 502 });
        } catch (e) {
          return new Response(JSON.stringify({ error: 'Server error' }), { status: 500 });
        }
      }

      // CORS preflight
      if (path.startsWith('/api/') && request.method === 'OPTIONS') {
        return new Response(null, {
          status: 204,
          headers: {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
          },
        });
      }

      // Shared freshness utilities
      if (path === '/shared/freshness.js') {
        return env.ASSETS.fetch(new Request(new URL('/_shared/freshness.js', url), request));
      }

      // Static assets → rewrite to snowline/site/ prefix
      // Use trailing slash for root — ASSETS normalizes /dir/index.html → /dir/ with 308
      const snowPath = path === '/' ? '/snowline/site/' : '/snowline/site' + path;
      return env.ASSETS.fetch(new Request(new URL(snowPath, url), request));
    }

    // ── RIVER ──────────────────────────────────────────────────────────────────

    if (host.includes('river')) {
      if (path === '/api/current') {
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

      if (path === '/api/chart') {
        const site = url.searchParams.get('site') || '06043500';
        const [hist, bands] = await Promise.all([
          env.RIVERLINE_DB.prepare(
            'SELECT date, cfs FROM daily_flow WHERE site_id = ? ORDER BY date DESC LIMIT 90',
          ).bind(site).all(),
          env.RIVERLINE_DB.prepare(
            'SELECT doy, p10, p25, p50, p75, p90 FROM doy_stats WHERE site_id = ? ORDER BY doy',
          ).bind(site).all(),
        ]);
        return new Response(
          JSON.stringify({ site, history: hist.results, bands: bands.results }),
          {
            headers: {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*',
              'Cache-Control': 'public, max-age=300',
            },
          },
        );
      }

      // Shared freshness utilities
      if (path === '/shared/freshness.js') {
        return env.ASSETS.fetch(new Request(new URL('/_shared/freshness.js', url), request));
      }

      // CORS preflight
      if (path.startsWith('/api/') && request.method === 'OPTIONS') {
        return new Response(null, {
          status: 204,
          headers: {
            'Access-Control-Allow-Origin': '*',
            'Access-Control-Allow-Methods': 'GET, OPTIONS',
            'Access-Control-Allow-Headers': 'Content-Type',
          },
        });
      }

      // Static assets → rewrite to riverline/site/ prefix
      const riverPath = path === '/' ? '/riverline/site/' : '/riverline/site' + path;
      return env.ASSETS.fetch(new Request(new URL(riverPath, url), request));
    }

    // Default: serve repo root (line.itogeospatial.com landing)
    return env.ASSETS.fetch(request);
  },
};
