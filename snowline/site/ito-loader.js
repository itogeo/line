// Ito Geospatial loading mark: the logo with the satellite circling its orbit
// (the same path as the logo on itogeospatial.com, looped and faster).
//
// Any page that includes this script gets a small mark in the bottom corner
// whenever it has been waiting on data for more than a moment. It counts
// in-flight fetch() calls, so nothing else needs wiring up. Pages can also
// drop the mark anywhere with itoMark() (e.g. a full-screen loader).

(function () {
  const css = `
  .ito-mark { position: relative; display: inline-block; width: 45.64px; height: 36px; flex: none;
    transform: scale(var(--ito-scale, 1)); transform-origin: center; }
  .ito-mark img.ito-mark-base { height: 36px; width: auto; display: block; }
  .ito-mark img.ito-mark-sat {
    position: absolute; left: 0; top: 0; width: 14.74px; height: auto;
    offset-path: path("M 35.29 9.71 A 22.67 11.97 12.9 0 0 10.59 25.96 A 22.67 11.97 12.9 0 0 35.29 9.71");
    offset-anchor: 6.15px 9.71px; offset-rotate: 0deg; offset-distance: 0%;
    animation: ito-orbit-loop 1.1s linear infinite;
  }
  @keyframes ito-orbit-loop { from { offset-distance: 0%; } to { offset-distance: 100%; } }
  @supports not (offset-path: path("M 0 0")) { .ito-mark img.ito-mark-sat { left: 29.14px; top: 0; } }
  @media (prefers-reduced-motion: reduce) { .ito-mark img.ito-mark-sat { animation-duration: 3s; } }
  .ito-busy { position: fixed; right: var(--ito-busy-right, 16px); bottom: var(--ito-busy-bottom, 16px); z-index: 9000;
    padding: 8px 10px; border-radius: 10px; background: rgba(10, 18, 30, 0.85); border: 1px solid rgba(255,255,255,0.08);
    box-shadow: 0 4px 16px rgba(0,0,0,0.35); opacity: 0; transition: opacity 0.2s; pointer-events: none; }
  .ito-busy.on { opacity: 1; }`;
  const style = document.createElement('style');
  style.textContent = css;
  document.head.appendChild(style);

  window.itoMark = function (scale) {
    const m = document.createElement('span');
    m.className = 'ito-mark';
    if (scale) m.style.setProperty('--ito-scale', scale);
    m.setAttribute('role', 'img');
    m.setAttribute('aria-label', 'Loading');
    m.innerHTML = '<img class="ito-mark-base" src="/snow/img/ito-base.png" alt="">'
      + '<img class="ito-mark-sat" src="/snow/img/ito-sat.png" alt="">';
    return m;
  };

  // Corner mark while any fetch is in flight (shown after 250 ms, so quick
  // loads don't flicker).
  let busy = 0, timer = null, badge = null;
  function update() {
    if (busy > 0 && !timer && !(badge && badge.classList.contains('on'))) {
      timer = setTimeout(() => {
        timer = null;
        if (busy <= 0) return;
        // A page's own full-screen loader is already showing the mark.
        if (document.querySelector('.loader-wrap:not(.hidden)')) { timer = null; setTimeout(update, 300); return; }
        if (!badge) {
          badge = document.createElement('div');
          badge.className = 'ito-busy';
          badge.title = 'Loading';
          badge.appendChild(window.itoMark());
          document.body.appendChild(badge);
        }
        badge.classList.add('on');
      }, 250);
    } else if (busy <= 0) {
      clearTimeout(timer); timer = null;
      if (badge) badge.classList.remove('on');
    }
  }
  const realFetch = window.fetch.bind(window);
  const track = p => { busy++; update(); return p.finally(() => { busy--; update(); }); };
  window.fetch = function (...args) {
    return track(realFetch(...args).then(r => {
      // Reading the body (a big JSON file) counts as loading too.
      for (const m of ['json', 'text', 'arrayBuffer', 'blob']) {
        const read = r[m].bind(r);
        r[m] = () => track(read());
      }
      return r;
    }));
  };
})();
