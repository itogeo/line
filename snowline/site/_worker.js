export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // ── R2 tile serving ──
    // Tiles are uploaded to R2 during pipeline runs. If not found in R2,
    // fall back to the legacy Pages static path (for dates still in git).
    if (url.pathname.startsWith('/api/tile/')) {
      const tilePath = url.pathname.slice('/api/tile'.length); // "/2026-06-17/snow_r0c0.webp"
      const key = 'tiles' + tilePath;                          // "tiles/2026-06-17/snow_r0c0.webp"
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
      // Fall back to legacy git-served path for dates not yet migrated to R2
      const legacyReq = new Request(
        new URL('/data_10m' + tilePath, request.url).toString(),
        request,
      );
      return env.ASSETS.fetch(legacyReq);
    }

    // ── Image proxy (for webcams blocked by CORS) ──
    if (url.pathname === '/api/camproxy' && url.searchParams.get('url')) {
      const imgUrl = url.searchParams.get('url');
      // Only allow known domains
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

    // ── MDT camera API proxy ──
    if (url.pathname === '/api/mdtcam' && url.searchParams.get('id')) {
      const posId = url.searchParams.get('id');
      try {
        const r = await fetch(`https://app.mdt.mt.gov/atms/public/camera/lastFiveImages/${posId}`);
        const data = await r.json();
        const imgUrl = data?.data?.lastFivePolledImages?.[0]?.publicSharePath;
        if (imgUrl) {
          // Fetch and proxy the actual image
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

    // ── SNOTEL API proxy (CORS) ──
    if (url.pathname === '/api/snotel' && url.searchParams.get('triplets')) {
      const triplets = url.searchParams.get('triplets');
      const begin = url.searchParams.get('begin') || '2025-10-01';
      const end = url.searchParams.get('end') || new Date().toISOString().slice(0, 10);
      const apiUrl = `https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data?stationTriplets=${triplets}&elements=SNWD,WTEQ&duration=DAILY&beginDate=${begin}&endDate=${end}`;
      try {
        const r = await fetch(apiUrl, { headers: { 'User-Agent': 'snowline/1.0' } });
        const body = await r.text();
        return new Response(body, {
          headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*', 'Cache-Control': 'public, max-age=3600' },
        });
      } catch (e) {
        return new Response(JSON.stringify({ error: 'SNOTEL API error' }), { status: 502 });
      }
    }

    // ── Feedback POST ──
    if (url.pathname === '/api/feedback' && request.method === 'POST') {
      try {
        const { text, date } = await request.json();
        if (!text || text.trim().length === 0) {
          return new Response(JSON.stringify({ error: 'Empty feedback' }), { status: 400 });
        }

        const title = 'Feedback: ' + text.substring(0, 60) + (text.length > 60 ? '...' : '');
        const body = text + '\n\n---\n*Submitted from snowline.itogeospatial.com*\n*Date viewed: ' + (date || 'unknown') + '*\n*' + new Date().toISOString() + '*';

        const ghResp = await fetch('https://api.github.com/repos/itogeo/snowline/issues', {
          method: 'POST',
          headers: {
            'Authorization': 'Bearer ' + env.GH_FEEDBACK_TOKEN,
            'Content-Type': 'application/json',
            'User-Agent': 'snowline-feedback',
          },
          body: JSON.stringify({ title, body, labels: ['feedback'] }),
        });

        if (ghResp.ok) {
          return new Response(JSON.stringify({ ok: true }), {
            headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
          });
        } else {
          return new Response(JSON.stringify({ error: 'GitHub API error' }), { status: 502 });
        }
      } catch (e) {
        return new Response(JSON.stringify({ error: 'Server error' }), { status: 500 });
      }
    }

    // CORS preflight
    if (url.pathname.startsWith('/api/') && request.method === 'OPTIONS') {
      return new Response(null, {
        headers: {
          'Access-Control-Allow-Origin': '*',
          'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
          'Access-Control-Allow-Headers': 'Content-Type',
        },
      });
    }

    // Pass through to static assets
    return env.ASSETS.fetch(request);
  },
};
