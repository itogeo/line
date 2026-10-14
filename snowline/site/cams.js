// Snowline webcams, shared by the map (index.html) and the Webcams page.
//
// Montana DOT cameras were removed on 2026-10-14: MDT blocks requests from
// Cloudflare (our image proxy runs there). Its camera API answered from a
// home connection but returned 502 to the worker, and the image host served
// an HTML block page. The browser can't call the API directly (no CORS).

// bearing = degrees clockwise from north (direction camera is pointing)
const WEBCAMS = [
  // ── Bozeman Area ──────────────────────────────────────────────────
  { name: 'KBZK — Bozeman Stadium',       lat: 45.6655, lon: -111.0620, bearing:   0, type: 'proxy',  src: 'https://mediaassets.kbzk.com/kbzk/bozemanStadium.jpg', link: 'https://www.kbzk.com/weather/weather-cameras-travel-watch', group: 'Bozeman Area' },
  { name: 'BZN Airport — Taxiway F Live', lat: 45.7775, lon: -111.1527, bearing:  45, type: 'iframe', src: 'https://video.nest.com/embedded/live/6Bfv8C4CVw?autoplay=0', link: 'https://video.nest.com/live/6Bfv8C4CVw', group: 'Bozeman Area' },

  // ── Bridger Bowl ──────────────────────────────────────────────────
  // Coordinates from OSM lift/parking data; cameras spread base→ridge
  { name: 'Bridger Bowl — Parking Lot',   lat: 45.8166, lon: -110.8935, bearing: 175, type: 'img',   src: 'https://webcam-images.s3-us-west-1.amazonaws.com/parking_lot.jpg',  link: 'https://bridgerbowl.com/weather/webcams', group: 'Bridger Bowl' },
  { name: 'Bridger Bowl — Apron',         lat: 45.8177, lon: -110.8977, bearing: 200, type: 'img',   src: 'https://webcam-images.s3-us-west-1.amazonaws.com/apron.jpg',          link: 'https://bridgerbowl.com/weather/webcams', group: 'Bridger Bowl' },
  { name: 'Bridger Bowl — Ridge East',    lat: 45.8355, lon: -110.8995, bearing: 100, type: 'img',   src: 'https://webcam-images.s3-us-west-1.amazonaws.com/RidgeEast.jpg',      link: 'https://bridgerbowl.com/weather/webcams', group: 'Bridger Bowl' },
  { name: 'Bridger Bowl — Alpine Lift',   lat: 45.8290, lon: -110.9219, bearing: 215, type: 'img',   src: 'https://webcam-images.s3-us-west-1.amazonaws.com/alpine_lift.jpg',   link: 'https://bridgerbowl.com/weather/webcams', group: 'Bridger Bowl' },
  { name: 'Bridger Bowl — Red Chair Live', lat: 45.8255, lon: -110.9140, bearing: 200, type: 'iframe', src: 'https://www.youtube.com/embed/playlist?list=PLtlKPoVnCL8k1uFuXB5id3Tvz1BC2yX-B&rel=0&modestbranding=1&playsinline=1', link: 'https://bridgerbowl.com/weather/webcams', group: 'Bridger Bowl' },

  // ── Big Sky ───────────────────────────────────────────────────────
  { name: 'Big Sky — Lone Peak',          lat: 45.2855, lon: -111.4016, bearing: 185, type: 'img',   src: 'https://img.youtube.com/vi/6iW7bdSavUo/maxresdefault.jpg',            link: 'https://bigskyresort.com/the-mountain/web-cams', group: 'Big Sky' },
  { name: 'Big Sky — Everett 8800',       lat: 45.2870, lon: -111.3980, bearing: 200, type: 'img',   src: 'https://img.youtube.com/vi/dMr-Jt_K3Cc/maxresdefault.jpg',            link: 'https://bigskyresort.com/the-mountain/web-cams', group: 'Big Sky' },

  // ── Cooke City ────────────────────────────────────────────────────
  // YouTube thumbnail shown; click ↗ to open live stream
  { name: 'Cooke City — Town Cam',        lat: 45.0197, lon: -109.9337, bearing: 270, type: 'img',   src: 'https://img.youtube.com/vi/hzcsPl8MtXU/maxresdefault.jpg',            link: 'https://www.youtube.com/watch?v=hzcsPl8MtXU', group: 'Cooke City' },

  // ── Yellowstone NPS ───────────────────────────────────────────────
  { name: 'West Yellowstone — Gate Out',  lat: 44.6573, lon: -111.0946, bearing: 270, type: 'proxy', src: 'https://www.nps.gov/webcams-yell/west_gate.jpg',                      link: 'https://www.nps.gov/yell/learn/photosmultimedia/webcams.htm', group: 'Yellowstone NPS' },
  { name: 'West Yellowstone — Into Park', lat: 44.6578, lon: -111.0940, bearing:  90, type: 'proxy', src: 'https://www.nps.gov/webcams-yell/west_into.jpg',                      link: 'https://www.nps.gov/yell/learn/photosmultimedia/webcams.htm', group: 'Yellowstone NPS' },
  { name: 'Mammoth — Electric Peak',      lat: 44.9734, lon: -110.7043, bearing: 315, type: 'proxy', src: 'https://www.nps.gov/webcams-yell/mammoth_electric.jpg',               link: 'https://www.nps.gov/yell/learn/photosmultimedia/webcams.htm', group: 'Yellowstone NPS' },
  { name: 'Mammoth — North Arch',         lat: 44.9750, lon: -110.7038, bearing:   0, type: 'proxy', src: 'https://www.nps.gov/webcams-yell/mammoth_arch.jpg',                   link: 'https://www.nps.gov/yell/learn/photosmultimedia/webcams.htm', group: 'Yellowstone NPS' },
  { name: 'Mammoth — Travertine',         lat: 44.9766, lon: -110.6972, bearing: 180, type: 'proxy', src: 'https://www.nps.gov/webcams-yell/mammoth_parade.jpg',                 link: 'https://www.nps.gov/yell/learn/photosmultimedia/webcams.htm', group: 'Yellowstone NPS' },
  { name: 'Mt Washburn — SW',             lat: 44.7979, lon: -110.4342, bearing: 225, type: 'proxy', src: 'https://www.nps.gov/webcams-yell/washburn_sw.jpg',                    link: 'https://www.nps.gov/yell/learn/photosmultimedia/webcams.htm', group: 'Yellowstone NPS' },
  { name: 'Mt Washburn — NE',             lat: 44.8072, lon: -110.4489, bearing:  45, type: 'proxy', src: 'https://www.nps.gov/webcams-yell/washburn_ne.jpg',                    link: 'https://www.nps.gov/yell/learn/photosmultimedia/webcams.htm', group: 'Yellowstone NPS' },
  { name: 'East Entrance — Out of Park',  lat: 44.3876, lon: -110.0054, bearing:  90, type: 'proxy', src: 'https://www.nps.gov/webcams-yell/east_out.jpg',                       link: 'https://www.nps.gov/yell/learn/photosmultimedia/webcams.htm', group: 'Yellowstone NPS' },
  { name: 'East Entrance — Into Park',    lat: 44.3880, lon: -110.0050, bearing: 270, type: 'proxy', src: 'https://www.nps.gov/webcams-yell/east_in.jpg',                        link: 'https://www.nps.gov/yell/learn/photosmultimedia/webcams.htm', group: 'Yellowstone NPS' },
];

function camSrc(cam, ts) {
  if (cam.type === 'img')   return cam.src + '?t=' + ts;
  if (cam.type === 'proxy') return '/snow/api/camproxy?url=' + encodeURIComponent(cam.src) + '&t=' + ts;
  return '';
}

// Viewshed fan icon (tip = camera, fan = direction it points) and a plain
// dot for cameras without a bearing. Call once per map before adding layers.
function addCamIcons(map) {
// ── Viewshed icon: tip at bottom-center, fan extends upward (= bearing 0°)
  // icon-anchor:'bottom' pins the tip to the map coordinate; icon-rotate sweeps the fan.
  const W = 48, H = 52;
  const offscreen = document.createElement('canvas');
  offscreen.width = W; offscreen.height = H;
  const ctx = offscreen.getContext('2d');
  ctx.clearRect(0, 0, W, H);

  const tipX = W / 2, tipY = H - 5;
  const fov  = Math.PI / 2.8; // ~64° field of view
  const len  = H - 10;

  // Fan fill
  ctx.beginPath();
  ctx.moveTo(tipX, tipY);
  const a1 = -Math.PI / 2 - fov / 2;
  const a2 = -Math.PI / 2 + fov / 2;
  ctx.arc(tipX, tipY, len, a1, a2);
  ctx.closePath();
  ctx.fillStyle = 'rgba(255, 112, 67, 0.28)';
  ctx.fill();

  // Fan outline edges only (no arc stroke — cleaner)
  ctx.beginPath();
  ctx.moveTo(tipX + Math.cos(a1) * len, tipY + Math.sin(a1) * len);
  ctx.lineTo(tipX, tipY);
  ctx.lineTo(tipX + Math.cos(a2) * len, tipY + Math.sin(a2) * len);
  ctx.strokeStyle = 'rgba(255, 112, 67, 0.75)';
  ctx.lineWidth = 1.5;
  ctx.stroke();

  // Solid dot at tip (camera position)
  ctx.beginPath();
  ctx.arc(tipX, tipY, 4.5, 0, Math.PI * 2);
  ctx.fillStyle = '#FF7043';
  ctx.fill();
  ctx.strokeStyle = 'rgba(0,0,0,0.45)';
  ctx.lineWidth = 1;
  ctx.stroke();

  map.addImage('cam-viewshed', ctx.getImageData(0, 0, W, H));

  // Fallback dot-only icon for cams without bearing
  const dW = 16, dH = 16;
  const dc = document.createElement('canvas');
  dc.width = dW; dc.height = dH;
  const dctx = dc.getContext('2d');
  dctx.beginPath();
  dctx.arc(dW / 2, dH / 2, 5.5, 0, Math.PI * 2);
  dctx.fillStyle = '#FF7043';
  dctx.fill();
  dctx.strokeStyle = 'rgba(0,0,0,0.4)';
  dctx.lineWidth = 1;
  dctx.stroke();
  map.addImage('cam-dot', dctx.getImageData(0, 0, dW, dH));
}
