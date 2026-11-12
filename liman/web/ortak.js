/* Avvam – ortak yardımcılar (harita ve gemi sayfası birlikte kullanır). */
(function () {
  'use strict';
  const LI = (window.LI = window.LI || {});
  const MAPLIBRE = '5.24.0';
  const STYLE_URL = 'https://tiles.openfreemap.org/styles/positron';
  const doc = document.documentElement;

  LI.esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  LI.tz = document.body.dataset.tz || 'Europe/Istanbul';
  LI.azHareket = matchMedia('(prefers-reduced-motion: reduce)').matches;

  const fmtCache = {};
  LI.tarih = function (v, saat) {
    if (v == null || v === '') return '–';
    const key = saat ? 's' : 'g';
    if (!fmtCache[key]) {
      const o = { day: 'numeric', month: 'short', year: 'numeric', timeZone: LI.tz };
      if (saat) { o.hour = '2-digit'; o.minute = '2-digit'; }
      fmtCache[key] = new Intl.DateTimeFormat('tr-TR', o);
    }
    return fmtCache[key].format(typeof v === 'number' ? new Date(v) : new Date(v));
  };
  LI.sayi = (n) => new Intl.NumberFormat('tr-TR').format(n);

  /* ---------- tema ---------- */
  LI.tema = () => doc.dataset.theme || (matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
  LI.renk = (ad) => getComputedStyle(doc).getPropertyValue(ad).trim();
  function temaDugmesi() {
    const b = document.getElementById('tema');
    if (!b) return;
    const yaz = () => { b.textContent = LI.tema() === 'dark' ? 'Gündüz' : 'Gece'; b.setAttribute('aria-label', LI.tema() === 'dark' ? 'Açık temaya geç' : 'Koyu temaya geç'); };
    yaz();
    b.addEventListener('click', () => {
      const yeni = LI.tema() === 'dark' ? 'light' : 'dark';
      doc.dataset.theme = yeni;
      try { localStorage.setItem('tema', yeni); } catch (e) { /* depolama kapalı olabilir */ }
      yaz();
      document.dispatchEvent(new CustomEvent('tema'));
    });
    matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => {
      if (!doc.dataset.theme) { yaz(); document.dispatchEvent(new CustomEvent('tema')); }
    });
  }
  temaDugmesi();

  /* ---------- harita kütüphanesi ---------- */
  function yukle(src) {
    return new Promise((ok, hata) => {
      const s = document.createElement('script');
      s.src = src; s.async = true; s.onload = ok; s.onerror = hata;
      document.head.appendChild(s);
    });
  }
  let kutuphane = null;
  LI.maplibre = function (kok) {
    if (!kutuphane) {
      kutuphane = (async () => {
        if (window.maplibregl) return window.maplibregl;
        try {
          await yukle(kok + 'vendor/maplibre-gl.js');
        } catch (e) {
          const l = document.createElement('link');
          l.rel = 'stylesheet';
          l.href = `https://cdn.jsdelivr.net/npm/maplibre-gl@${MAPLIBRE}/dist/maplibre-gl.css`;
          document.head.appendChild(l);
          await yukle(`https://cdn.jsdelivr.net/npm/maplibre-gl@${MAPLIBRE}/dist/maplibre-gl.js`);
        }
        if (!window.maplibregl) throw new Error('harita kütüphanesi yüklenemedi');
        return window.maplibregl;
      })();
    }
    return kutuphane;
  };

  /* ---------- altlık harita: OpenFreeMap Positron, seyir haritası renklerine boyanır ---------- */
  const ALTLIK = {
    light: { land: '#efece4', land2: '#e7e3d8', sea: '#e4eef3', shore: '#9cb2c3', road: '#ddd7c8', border: '#b3ad9d',
             label: '#5e6b78', seaLabel: '#7393aa', halo: '#f4f2ec' },
    dark: { land: '#17222d', land2: '#1b2733', sea: '#0c1824', shore: '#2f4558', road: '#233140', border: '#3f5264',
            label: '#8b9cac', seaLabel: '#55738d', halo: '#0c1824' },
  };
  let hamStil = null;
  LI.stil = async function () {
    const c = ALTLIK[LI.tema()];
    if (!hamStil) {
      hamStil = fetch(STYLE_URL).then((r) => { if (!r.ok) throw new Error(r.status); return r.json(); }).catch(() => null);
    }
    const s = await hamStil;
    if (!s) {
      return { version: 8, glyphs: 'https://tiles.openfreemap.org/fonts/{fontstack}/{range}.pbf', sources: {},
               layers: [{ id: 'background', type: 'background', paint: { 'background-color': c.sea } }], yedek: true };
    }
    return boya(JSON.parse(JSON.stringify(s)), c);
  };
  const AD = ['coalesce', ['get', 'name:tr'], ['get', 'name:latin'], ['get', 'name']];
  function boya(s, c) {
    const yeni = [];
    for (const L of s.layers) {
      const id = L.id.toLowerCase();
      L.paint = L.paint || {}; L.layout = L.layout || {};
      if (L.type === 'background') {
        L.paint['background-color'] = c.land;
      } else if (L.type === 'fill') {
        delete L.paint['fill-pattern'];
        if (/water|ocean|sea|lake|river/.test(id)) { L.paint['fill-color'] = c.sea; L.paint['fill-opacity'] = 1; L.paint['fill-outline-color'] = c.sea; }
        else if (/building/.test(id)) L.layout.visibility = 'none';
        else { L.paint['fill-color'] = c.land2; L.paint['fill-opacity'] = 0.5; delete L.paint['fill-outline-color']; }
      } else if (L.type === 'line') {
        if (/waterway|river|stream|canal/.test(id)) L.paint['line-color'] = c.shore;
        else if (/boundary|admin/.test(id)) L.paint['line-color'] = c.border;
        else { L.paint['line-color'] = c.road; L.paint['line-opacity'] = 0.7; }
      } else if (L.type === 'symbol') {
        if (/poi|shield|housenum|road|highway|rail|transit|aerodrome|airport|oneway|street|path|bridge|tunnel/.test(id)) {
          L.layout.visibility = 'none';
        } else {
          if (L.layout['text-field']) L.layout['text-field'] = AD;
          const deniz = /water|ocean|sea|marine|bay|gulf|strait/.test(id);
          L.paint['text-color'] = deniz ? c.seaLabel : c.label;
          L.paint['text-halo-color'] = c.halo;
          L.paint['text-halo-width'] = 1.2;
        }
      } else if (L.type === 'fill-extrusion' || L.type === 'hillshade' || L.type === 'raster' || L.type === 'heatmap') {
        L.layout.visibility = 'none';
      }
      yeni.push(L);
      if (L.type === 'fill' && /^water$/.test(L.id)) {
        // seyir haritası gibi kıyı çizgisi
        yeni.push({ id: 'kiyi-cizgisi', type: 'line', source: L.source, 'source-layer': L['source-layer'],
                    filter: L.filter, paint: { 'line-color': c.shore, 'line-width': ['interpolate', ['linear'], ['zoom'], 3, 0.4, 8, 0.9, 12, 1.3] } });
      }
    }
    s.layers = yeni;
    return s;
  }

  /* ---------- harita çizim yardımcıları ---------- */
  LI.yay = function (a, b, n, k) {
    n = n || 24;
    k = k == null ? 0.16 : k;
    const dx = b[0] - a[0], dy = b[1] - a[1];
    if (!dx && !dy) return [a, b];
    // kavis güneybatıya doğru: Doğu Akdeniz'de kıyılar doğu ve kuzeyde, deniz batı ve güneyde kalır;
    // böylece aynı iki liman arasındaki gidiş ve dönüş de aynı yana kavis yapar
    let nx = -dy, ny = dx;
    if (-nx - ny < 0) { nx = -nx; ny = -ny; }
    const cx = (a[0] + b[0]) / 2 + nx * k, cy = (a[1] + b[1]) / 2 + ny * k;
    const out = [];
    for (let i = 0; i <= n; i++) {
      const t = i / n, u = 1 - t;
      out.push([u * u * a[0] + 2 * u * t * cx + t * t * b[0], u * u * a[1] + 2 * u * t * cy + t * t * b[1]]);
    }
    return out;
  };
  LI.sinirlar = function (coords) {
    let a = 180, b = 90, c = -180, d = -90;
    for (const p of coords) { if (p[0] < a) a = p[0]; if (p[1] < b) b = p[1]; if (p[0] > c) c = p[0]; if (p[1] > d) d = p[1]; }
    return a <= c ? [[a, b], [c, d]] : null;
  };
  LI.okResmi = function (map, ad, renk, kenar) {
    const s = 40, cv = document.createElement('canvas');
    cv.width = cv.height = s;
    const g = cv.getContext('2d');
    g.beginPath(); g.moveTo(s / 2, 4); g.lineTo(s - 10, s - 6); g.lineTo(s / 2, s - 13); g.lineTo(10, s - 6); g.closePath();
    g.lineJoin = 'round'; g.lineWidth = 4; g.strokeStyle = kenar; g.stroke(); g.fillStyle = renk; g.fill();
    const img = g.getImageData(0, 0, s, s);
    if (map.hasImage(ad)) map.updateImage(ad, img); else map.addImage(ad, img, { pixelRatio: 2 });
  };

  /* ---------- uydu görüntüsü bağlantısı (Copernicus Browser) ---------- */
  LI.uydu = function (lat, lon, t0, t1, radar) {
    const q = new URLSearchParams({ zoom: 12, lat: lat.toFixed(4), lng: lon.toFixed(4), themeId: 'DEFAULT-THEME',
      datasetId: radar ? 'S1_CDAS_IW_VVVH' : 'S2_L2A_CDAS', fromTime: `${t0.slice(0, 10)}T00:00:00.000Z`,
      toTime: `${t1.slice(0, 10)}T23:59:59.999Z` });
    return `https://browser.dataspace.copernicus.eu/?${q}`;
  };
  LI.json = (url) => fetch(url).then((r) => { if (!r.ok) throw new Error(`${url}: ${r.status}`); return r.json(); });
})();
