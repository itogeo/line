export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const host = url.hostname;
    const path = url.pathname;

    // ── SHARED (all Line Network sites) ──────────────────────────────────────
    if (path.startsWith('/shared/')) {
      const sharedPath = '/_shared' + path.slice('/shared'.length);
      return env.ASSETS.fetch(new Request(new URL(sharedPath, url), request));
    }

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

      // SNOTEL proxy — AWDB has no CORS headers; proxy single station's 30-day data
      if (path === '/api/snotel' && url.searchParams.get('triplet')) {
        const triplet = url.searchParams.get('triplet');
        const today = new Date().toISOString().slice(0, 10);
        const thirtyAgo = new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
        const apiUrl = `https://wcc.sc.egov.usda.gov/awdbRestApi/services/v1/data?stationTriplets=${encodeURIComponent(triplet)}&elements=WTEQ,SNWD,TOBS&duration=DAILY&beginDate=${thirtyAgo}&endDate=${today}&periodRef=END`;
        try {
          const r = await fetch(apiUrl, { headers: { 'User-Agent': 'riverline/1.0' } });
          const body = await r.text();
          return new Response(body, {
            headers: {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*',
              'Cache-Control': 'public, max-age=3600',
            },
          });
        } catch (e) {
          return new Response(JSON.stringify({ error: 'SNOTEL proxy error' }), {
            status: 502,
            headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
          });
        }
      }

      // NOAA NWPS stageflow proxy — NOAA has no CORS headers
      if (path.startsWith('/api/noaa/') && path.endsWith('/stageflow')) {
        const parts = path.split('/');
        const lid = parts[3];
        if (!/^[A-Z0-9]{3,10}$/i.test(lid)) {
          return new Response('Invalid lid', { status: 400 });
        }
        try {
          const noaaUrl = `https://api.water.noaa.gov/nwps/v1/gauges/${lid}/stageflow`;
          const r = await fetch(noaaUrl, { headers: { 'User-Agent': 'riverline/1.0' } });
          const body = await r.text();
          return new Response(body, {
            headers: {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*',
              'Cache-Control': 'public, max-age=1800',
            },
          });
        } catch (e) {
          return new Response(JSON.stringify({ error: 'NOAA API error' }), {
            status: 502,
            headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
          });
        }
      }

      // DNRC StAGE tsQuery proxy — async GP job pattern, returns 14/30-day discharge JSON
      if (path.startsWith('/api/dnrc/') && url.searchParams.has('days')) {
        const locationId = path.split('/')[3] || '';
        if (!/^[a-f0-9]{32}$/i.test(locationId)) {
          return new Response('Invalid locationId', { status: 400, headers: { 'Access-Control-Allow-Origin': '*' } });
        }
        const days = Math.min(365, Math.max(1, parseInt(url.searchParams.get('days')) || 14));
        const DNRC_MAP = 'https://gis.dnrc.mt.gov/arcgis/rest/services/WRD/WMB_StAGE/MapServer';
        const DNRC_GP  = 'https://gis.dnrc.mt.gov/arcgis/rest/services/WRD/WMB_StAGE_GPTools/GPServer/tsQuery';

        async function unzipFirstEntry(buf) {
          const v = new DataView(buf);
          if (v.getUint32(0, true) !== 0x04034b50) throw new Error('Not a ZIP');
          const method = v.getUint16(8, true);
          const fnLen  = v.getUint16(26, true);
          const exLen  = v.getUint16(28, true);
          const dataStart = 30 + fnLen + exLen;
          if (method === 0) {
            return new TextDecoder().decode(new Uint8Array(buf, dataStart));
          }
          if (method === 8) {
            const compSize = v.getUint32(18, true);
            const compressed = new Uint8Array(buf, dataStart, compSize);
            const ds = new DecompressionStream('deflate-raw');
            const writer = ds.writable.getWriter();
            writer.write(compressed);
            writer.close();
            const reader = ds.readable.getReader();
            const chunks = [];
            while (true) {
              const { done, value } = await reader.read();
              if (done) break;
              if (value) chunks.push(value);
            }
            let total = 0; for (const c of chunks) total += c.length;
            const out = new Uint8Array(total); let pos = 0;
            for (const c of chunks) { out.set(c, pos); pos += c.length; }
            return new TextDecoder().decode(out);
          }
          throw new Error('Unsupported ZIP compression: ' + method);
        }

        try {
          // Step 1 — find real-time discharge SensorID
          const sensorQ = await fetch(
            `${DNRC_MAP}/3/query?where=${encodeURIComponent(`LocationID='${locationId}' AND Parameter='QR' AND ComputationPeriod<>'Daily'`)}&outFields=SensorID&f=json`,
            { headers: { 'User-Agent': 'riverline/1.0' } },
          );
          const sensorData = await sensorQ.json();
          let sensorId = sensorData?.features?.[0]?.attributes?.SensorID;
          if (!sensorId) {
            // Fallback to daily if no real-time
            const fallQ = await fetch(
              `${DNRC_MAP}/3/query?where=${encodeURIComponent(`LocationID='${locationId}' AND Parameter='QR'`)}&outFields=SensorID&f=json`,
              { headers: { 'User-Agent': 'riverline/1.0' } },
            );
            const fallData = await fallQ.json();
            sensorId = fallData?.features?.[0]?.attributes?.SensorID;
          }
          if (!sensorId) {
            return new Response(JSON.stringify({ error: 'No discharge sensor' }), {
              status: 404,
              headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
            });
          }

          // Step 2 — submit tsQuery job (dates as Unix ms timestamps)
          const endMs   = Date.now();
          const startMs = endMs - days * 24 * 60 * 60 * 1000;
          const jobResp = await fetch(`${DNRC_GP}/submitJob`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded', 'User-Agent': 'riverline/1.0' },
            body: `SensorID=${sensorId}&StartDate=${startMs}&EndDate=${endMs}&OutputType=csv&f=pjson`,
          });
          const jobData = await jobResp.json();
          const jobId   = jobData?.jobId;
          if (!jobId) throw new Error('No jobId');

          // Step 3 — poll until done (typically 2–4 s)
          let status = jobData?.jobStatus;
          for (let i = 0; i < 12 && status !== 'esriJobSucceeded' && status !== 'esriJobFailed'; i++) {
            await new Promise(r => setTimeout(r, 1500));
            const poll = await fetch(`${DNRC_GP}/jobs/${jobId}?f=pjson`, { headers: { 'User-Agent': 'riverline/1.0' } });
            status = (await poll.json())?.jobStatus;
          }
          if (status !== 'esriJobSucceeded') throw new Error('Job failed: ' + status);

          // Step 4 — get output file URL
          const outResp = await fetch(`${DNRC_GP}/jobs/${jobId}/results/OutputFile?f=pjson`, { headers: { 'User-Agent': 'riverline/1.0' } });
          const outData = await outResp.json();
          const fileUrl = outData?.value?.url;
          if (!fileUrl) throw new Error('No output URL');

          // Step 5 — fetch ZIP, unzip, parse CSV
          const zipResp = await fetch(fileUrl, { headers: { 'User-Agent': 'riverline/1.0' } });
          const zipBuf  = await zipResp.arrayBuffer();
          const csv     = await unzipFirstEntry(zipBuf);

          const allLines = csv.trim().split('\n');
          const hdrs = allLines[0].split(',').map(h => h.trim().replace(/^"|"$/g, '').toLowerCase());
          const dtIdx  = Math.max(0, hdrs.findIndex(h => h.includes('date') || h.includes('time')));
          const valIdx = hdrs.findIndex(h => h.includes('value') || h === 'discharge' || h === 'cfs');
          const vi = valIdx >= 0 ? valIdx : 1;
          const rows = [];
          for (const line of allLines.slice(1)) {
            const parts = line.split(',');
            if (parts.length <= vi) continue;
            const dt  = parts[dtIdx].trim().replace(/^"|"$/g, '');
            const cfs = parseFloat(parts[vi].trim().replace(/^"|"$/g, ''));
            if (dt && !isNaN(cfs) && cfs >= 0 && cfs < 9000) rows.push({ dt, cfs });
          }

          return new Response(JSON.stringify({ rows }), {
            headers: {
              'Content-Type': 'application/json',
              'Access-Control-Allow-Origin': '*',
              'Cache-Control': 'public, max-age=900',
            },
          });
        } catch (e) {
          return new Response(JSON.stringify({ error: 'DNRC API error', detail: e.message }), {
            status: 502,
            headers: { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' },
          });
        }
      }

      // DNRC WRQS proxy — FeatureServer has no CORS headers
      if (path.startsWith('/api/wrqs')) {
        const layer = url.searchParams.get('layer') || '1';
        const xmin = url.searchParams.get('xmin');
        const ymin = url.searchParams.get('ymin');
        const xmax = url.searchParams.get('xmax');
        const ymax = url.searchParams.get('ymax');
        const where = url.searchParams.get('where') || '1=1';
        const geom = JSON.stringify({ xmin: parseFloat(xmin), ymin: parseFloat(ymin), xmax: parseFloat(xmax), ymax: parseFloat(ymax) });
        const fields = 'WR_NUMBER,SOURCE_NAME,PURPOSES,MAX_FLOW_CFS,PERIOD_OF_DIVERSIONS,OWNERS,ENF_PRTY_DT_CHAR,URL_ABSTRACT,MAX_ACRES';
        const featureUrl = `https://gis.dnrc.mt.gov/arcgis/rest/services/WRD/WRQS/FeatureServer/${layer}/query?geometry=${encodeURIComponent(geom)}&geometryType=esriGeometryEnvelope&spatialRel=esriSpatialRelIntersects&inSR=4326&where=${encodeURIComponent(where)}&outFields=${fields}&f=geojson&resultRecordCount=500`;
        try {
          const r = await fetch(featureUrl, { headers: { 'User-Agent': 'RiverLine/1.0 (Ito Geospatial)' } });
          const body = await r.text();
          return new Response(body, {
            headers: {
              'Content-Type': 'application/geo+json',
              'Access-Control-Allow-Origin': '*',
              'Cache-Control': 'public, max-age=3600',
            },
          });
        } catch (_) {
          return new Response('{"type":"FeatureCollection","features":[]}', {
            status: 502,
            headers: { 'Content-Type': 'application/geo+json', 'Access-Control-Allow-Origin': '*' },
          });
        }
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
      // /gallatin and /gallatin/ both route to riverline/site/gallatin/
      const riverPath = path === '/' ? '/riverline/site/' : '/riverline/site' + path;
      return env.ASSETS.fetch(new Request(new URL(riverPath, url), request));
    }

    // Default: serve repo root (line.itogeospatial.com landing)
    return env.ASSETS.fetch(request);
  },
};
