// Snowline webcams, shared by the map (index.html) and the Webcams page.
//
// Montana DOT: MDT's own camera API (app.mdt.mt.gov) blocks requests from
// Cloudflare, so the old /api/mdtcam proxy failed. The Montana 511 site serves
// the same images from a CDN at stable URLs that are overwritten in place
// (mt.cdn.iteris-atis.com/rwis_images/{camId}.jpg, station list in
// geojson/icons/metadata/icons.rwis.geojson). Browsers load them directly.
// Bearings come from each camera's description (North, Southwest, ...);
// roadway/underpass/lane views are left out. List checked 2026-10-14.
//
// FAA WeatherCams: the API answers only with a weathercams.faa.gov Referer,
// which a browser can't send, so /snow/api/faacam looks up the newest image
// and redirects to it. Sites with no current image were left out (2026-10-14).

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
  // ── Montana DOT (road weather stations, via the 511 image CDN) ──
  { name: 'MDT — Clancy (North)', lat: 46.4744, lon: -111.9798, bearing:   0, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/267111-00-02.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Clancy (South)', lat: 46.4744, lon: -111.9798, bearing: 180, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/267110-00-01.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Deep Creek (East)', lat: 46.3515, lon: -111.0668, bearing:  90, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564053-00-04.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Deep Creek (West)', lat: 46.3515, lon: -111.0668, bearing: 270, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564050-00-01.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Boulder Hill (Northeast)', lat: 46.3233, lon: -112.0689, bearing:  45, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/267030-00-01.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Boulder Hill (East)', lat: 46.3233, lon: -112.0689, bearing:  90, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/267031-00-02.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Boulder Hill (Southeast)', lat: 46.3233, lon: -112.0689, bearing: 135, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/267033-00-04.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Toston Bridge (Northeast)', lat: 46.1778, lon: -111.4433, bearing:  45, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564070-00-01.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Toston Bridge (Southeast)', lat: 46.1778, lon: -111.4433, bearing: 135, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564072-00-03.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Toston Bridge (West)', lat: 46.1778, lon: -111.4433, bearing: 270, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564074-00-05.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Boulder South (North)', lat: 46.135, lon: -111.9815, bearing:   0, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/267120-00-01.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Boulder South (East)', lat: 46.135, lon: -111.9815, bearing:  90, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/267122-00-03.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Harlowton South (Northeast)', lat: 46.1325, lon: -109.9169, bearing:  45, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/268130-00-01.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Harlowton South (Southeast Horizon)', lat: 46.1325, lon: -109.9169, bearing: 135, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/268131-00-02.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Harlowton South (Southwest)', lat: 46.1325, lon: -109.9169, bearing: 225, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/268133-00-04.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Harlowton South (West Horizon)', lat: 46.1325, lon: -109.9169, bearing: 270, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/268134-00-05.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Bridger Canyon (South)', lat: 45.8292, lon: -110.8827, bearing: 180, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564091-00-02.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Bridger Canyon (West Horizon)', lat: 45.8292, lon: -110.8827, bearing: 270, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564093-00-04.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Bozeman (East)', lat: 45.7435, lon: -111.1168, bearing:  90, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564110-00-01.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Bozeman (South Horizon)', lat: 45.7435, lon: -111.1168, bearing: 180, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564111-00-02.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Bozeman (West)', lat: 45.7435, lon: -111.1168, bearing: 270, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564113-00-04.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Springdale (Northeast)', lat: 45.7219, lon: -110.2486, bearing:  45, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564142-00-03.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Springdale (Southwest)', lat: 45.7219, lon: -110.2486, bearing: 225, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564140-00-01.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Reedpoint (East)', lat: 45.7101, lon: -109.5783, bearing:  90, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/263010-00-01.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Reedpoint (West)', lat: 45.7101, lon: -109.5783, bearing: 270, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/263012-00-03.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — East Livingston (South)', lat: 45.6854, lon: -110.5046, bearing: 180, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564031-00-02.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — East Livingston (Southwest)', lat: 45.6854, lon: -110.5046, bearing: 225, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564033-00-04.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — East Livingston (Northwest Horizon)', lat: 45.6854, lon: -110.5046, bearing: 315, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564034-00-05.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Bozeman Pass (East)', lat: 45.6668, lon: -110.804, bearing:  90, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564020-00-01.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Bozeman Pass (West)', lat: 45.6668, lon: -110.804, bearing: 270, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564023-00-04.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Livingston River Hill (Northeast)', lat: 45.6445, lon: -110.5541, bearing:  45, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564082-00-03.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Livingston River Hill (West)', lat: 45.6445, lon: -110.5541, bearing: 270, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564080-00-01.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Livingston River Hill (Northwest Horizon)', lat: 45.6445, lon: -110.5541, bearing: 315, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564083-00-04.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Norris Hill (Southwest)', lat: 45.4996, lon: -111.6962, bearing: 225, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564040-00-01.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Norris Hill (Northwest)', lat: 45.4996, lon: -111.6962, bearing: 315, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564042-00-03.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Karst (North)', lat: 45.3453, lon: -111.1726, bearing:   0, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564010-00-01.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Roscoe Hill (Southwest)', lat: 45.3386, lon: -109.4936, bearing: 225, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/263023-00-04.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Roscoe Hill (West)', lat: 45.3386, lon: -109.4936, bearing: 270, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/263021-00-02.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Roscoe Hill (Northwest)', lat: 45.3386, lon: -109.4936, bearing: 315, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/263020-00-01.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Big Sky Road (East)', lat: 45.2854, lon: -111.3727, bearing:  90, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564132-00-03.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Big Sky Road (Southeast Horizon)', lat: 45.2854, lon: -111.3727, bearing: 135, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564133-00-04.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Big Sky Road (West)', lat: 45.2854, lon: -111.3727, bearing: 270, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564130-00-01.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Gardiner (North)', lat: 45.1558, lon: -110.8223, bearing:   0, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564101-00-02.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Gardiner (South)', lat: 45.1558, lon: -110.8223, bearing: 180, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564103-00-04.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  { name: 'MDT — Gardiner (West Horizon)', lat: 45.1558, lon: -110.8223, bearing: 270, type: 'img', src: 'https://mt.cdn.iteris-atis.com/rwis_images/564100-00-01.jpg', link: 'https://www.511mt.net/', group: 'Montana DOT' },
  // ── FAA WeatherCams (aviation weather cameras; image looked up by our worker) ──
  { name: 'FAA — White Sulphur Springs Airport (East)', lat: 46.5029, lon: -110.9063, bearing:  65, type: 'faa', src: '13093', link: 'https://weathercams.faa.gov/map/846', group: 'FAA WeatherCams' },
  { name: 'FAA — White Sulphur Springs Airport (SouthEast)', lat: 46.5029, lon: -110.9063, bearing: 140, type: 'faa', src: '13094', link: 'https://weathercams.faa.gov/map/846', group: 'FAA WeatherCams' },
  { name: 'FAA — White Sulphur Springs Airport (SouthWest)', lat: 46.5029, lon: -110.9063, bearing: 225, type: 'faa', src: '13095', link: 'https://weathercams.faa.gov/map/846', group: 'FAA WeatherCams' },
  { name: 'FAA — White Sulphur Springs Airport (NorthWest)', lat: 46.5029, lon: -110.9063, bearing: 315, type: 'faa', src: '13092', link: 'https://weathercams.faa.gov/map/846', group: 'FAA WeatherCams' },
  { name: 'FAA — Three Forks (East)', lat: 45.8849, lon: -111.5632, bearing:  70, type: 'faa', src: '12384', link: 'https://weathercams.faa.gov/map/676', group: 'FAA WeatherCams' },
  { name: 'FAA — Three Forks (South)', lat: 45.8849, lon: -111.5632, bearing: 165, type: 'faa', src: '12385', link: 'https://weathercams.faa.gov/map/676', group: 'FAA WeatherCams' },
  { name: 'FAA — Three Forks (NorthWest)', lat: 45.8849, lon: -111.5632, bearing: 295, type: 'faa', src: '12383', link: 'https://weathercams.faa.gov/map/676', group: 'FAA WeatherCams' },
  { name: 'FAA — Bozeman Airport (North)', lat: 45.78, lon: -111.1446, bearing:   5, type: 'faa', src: '12052', link: 'https://weathercams.faa.gov/map/563', group: 'FAA WeatherCams' },
  { name: 'FAA — Bozeman Airport (SouthEast)', lat: 45.78, lon: -111.1446, bearing: 135, type: 'faa', src: '12053', link: 'https://weathercams.faa.gov/map/563', group: 'FAA WeatherCams' },
  { name: 'FAA — Bozeman Airport (SouthWest)', lat: 45.78, lon: -111.1446, bearing: 210, type: 'faa', src: '12054', link: 'https://weathercams.faa.gov/map/563', group: 'FAA WeatherCams' },
  { name: 'FAA — Bozeman Airport (West)', lat: 45.78, lon: -111.1446, bearing: 270, type: 'faa', src: '12055', link: 'https://weathercams.faa.gov/map/563', group: 'FAA WeatherCams' },
  { name: 'FAA — Livingston/Mission Field (NorthEast)', lat: 45.6969, lon: -110.4539, bearing:  25, type: 'faa', src: '13653', link: 'https://weathercams.faa.gov/map/987', group: 'FAA WeatherCams' },
  { name: 'FAA — Livingston/Mission Field (SouthEast)', lat: 45.6969, lon: -110.4539, bearing: 120, type: 'faa', src: '13654', link: 'https://weathercams.faa.gov/map/987', group: 'FAA WeatherCams' },
  { name: 'FAA — Livingston/Mission Field (SouthWest)', lat: 45.6969, lon: -110.4539, bearing: 210, type: 'faa', src: '13655', link: 'https://weathercams.faa.gov/map/987', group: 'FAA WeatherCams' },
  { name: 'FAA — Livingston/Mission Field (NorthWest)', lat: 45.6969, lon: -110.4539, bearing: 300, type: 'faa', src: '13656', link: 'https://weathercams.faa.gov/map/987', group: 'FAA WeatherCams' },
  { name: 'FAA — Bozeman Pass (North)', lat: 45.6671, lon: -110.8042, bearing:  12, type: 'faa', src: '11999', link: 'https://weathercams.faa.gov/map/549', group: 'FAA WeatherCams' },
  { name: 'FAA — Bozeman Pass (East)', lat: 45.6671, lon: -110.8042, bearing: 100, type: 'faa', src: '12000', link: 'https://weathercams.faa.gov/map/549', group: 'FAA WeatherCams' },
  { name: 'FAA — Bozeman Pass (SouthEast)', lat: 45.6671, lon: -110.8042, bearing: 145, type: 'faa', src: '12001', link: 'https://weathercams.faa.gov/map/549', group: 'FAA WeatherCams' },
  { name: 'FAA — Bozeman Pass (West)', lat: 45.6671, lon: -110.8042, bearing: 286, type: 'faa', src: '11998', link: 'https://weathercams.faa.gov/map/549', group: 'FAA WeatherCams' },
  { name: 'FAA — Columbus Airport (SouthEast)', lat: 45.6306, lon: -109.2363, bearing: 130, type: 'faa', src: '12183', link: 'https://weathercams.faa.gov/map/596', group: 'FAA WeatherCams' },
  { name: 'FAA — Columbus Airport (SouthWest)', lat: 45.6306, lon: -109.2363, bearing: 210, type: 'faa', src: '13003', link: 'https://weathercams.faa.gov/map/596', group: 'FAA WeatherCams' },
  { name: 'FAA — Columbus Airport (West)', lat: 45.6306, lon: -109.2363, bearing: 270, type: 'faa', src: '12182', link: 'https://weathercams.faa.gov/map/596', group: 'FAA WeatherCams' },
  { name: 'FAA — Madison Hill (North)', lat: 45.4909, lon: -111.6448, bearing:   0, type: 'faa', src: '13364', link: 'https://weathercams.faa.gov/map/918', group: 'FAA WeatherCams' },
  { name: 'FAA — Madison Hill (South)', lat: 45.4909, lon: -111.6448, bearing: 200, type: 'faa', src: '13365', link: 'https://weathercams.faa.gov/map/918', group: 'FAA WeatherCams' },
  { name: 'FAA — Madison Hill (West)', lat: 45.4909, lon: -111.6448, bearing: 255, type: 'faa', src: '13366', link: 'https://weathercams.faa.gov/map/918', group: 'FAA WeatherCams' },
  { name: 'FAA — Madison Hill (NorthWest)', lat: 45.4909, lon: -111.6448, bearing: 315, type: 'faa', src: '13367', link: 'https://weathercams.faa.gov/map/918', group: 'FAA WeatherCams' },
  { name: 'FAA — Red Lodge Airport (East)', lat: 45.1863, lon: -109.2537, bearing:  80, type: 'faa', src: '13081', link: 'https://weathercams.faa.gov/map/843', group: 'FAA WeatherCams' },
  { name: 'FAA — Red Lodge Airport (South)', lat: 45.1863, lon: -109.2537, bearing: 170, type: 'faa', src: '13082', link: 'https://weathercams.faa.gov/map/843', group: 'FAA WeatherCams' },
  { name: 'FAA — Red Lodge Airport (West)', lat: 45.1863, lon: -109.2537, bearing: 265, type: 'faa', src: '13083', link: 'https://weathercams.faa.gov/map/843', group: 'FAA WeatherCams' },
  { name: 'FAA — Red Lodge Airport (North)', lat: 45.1863, lon: -109.2537, bearing: 340, type: 'faa', src: '13080', link: 'https://weathercams.faa.gov/map/843', group: 'FAA WeatherCams' },
];

function camSrc(cam, ts) {
  if (cam.type === 'img')   return cam.src + '?t=' + ts;
  if (cam.type === 'proxy') return '/snow/api/camproxy?url=' + encodeURIComponent(cam.src) + '&t=' + ts;
  if (cam.type === 'faa')   return '/snow/api/faacam?id=' + cam.src + '&t=' + ts;
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
