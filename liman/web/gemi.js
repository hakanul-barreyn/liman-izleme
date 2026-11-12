/* Avvam – gemi sayfası: bütün iz ve zaman kaydırıcısıyla geçmiş oynatma. */
(function () {
  'use strict';
  const LI = window.LI;
  const $ = (s) => document.querySelector(s);
  const kutu = $('#gemi-harita');
  if (!kutu) return;
  const KOK = kutu.dataset.kok || '';
  const S = kutu.dataset.surum ? `?v=${kutu.dataset.surum}` : '';
  const ANAHTAR = kutu.dataset.anahtar;
  const kaydir = $('#kaydir'), cikti = $('#an'), dugme = $('#gemi-oynat');
  let V = null, harita = null, hazir = false, oyna = null;
  let noktalar = [];   // [boylam, enlem, dakika] düz liste, segment sınırlarıyla
  let sinirlar = [];   // her noktanın segment indeksi

  function hazirla() {
    noktalar = []; sinirlar = [];
    (V.iz || []).forEach((seg, i) => { for (const p of seg) { noktalar.push(p); sinirlar.push(i); } });
  }
  function kesit(t) {
    // t (dakika) anına kadar olan iz, son nokta ara değerlenir
    const segs = [];
    let cur = null, son = null, sonSeg = -1;
    for (let i = 0; i < noktalar.length; i++) {
      const p = noktalar[i];
      if (p[2] > t) {
        if (cur && sinirlar[i] === sonSeg && son) {
          const k = (t - son[2]) / Math.max(1, p[2] - son[2]);
          const ara = [son[0] + (p[0] - son[0]) * k, son[1] + (p[1] - son[1]) * k];
          cur.push(ara); son = [ara[0], ara[1], t];
        }
        break;
      }
      if (sinirlar[i] !== sonSeg) { cur = []; segs.push(cur); sonSeg = sinirlar[i]; }
      cur.push([p[0], p[1]]); son = p;
    }
    return { segs: segs.filter((s) => s.length >= 2), son };
  }
  function ciz(t) {
    if (!hazir) return;
    const { segs, son } = kesit(t);
    harita.getSource('gecilen').setData({ type: 'FeatureCollection', features: segs.length ? [{ type: 'Feature', properties: {}, geometry: { type: 'MultiLineString', coordinates: segs } }] : [] });
    harita.getSource('konum').setData({ type: 'FeatureCollection', features: son ? [{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: [son[0], son[1]] } }] : [] });
    cikti.textContent = LI.tarih(t * 60000, true);
  }
  function renk(n) { return LI.renk(n); }
  function katmanlar(yedek) {
    const m = harita, c = { ink: renk('--ink'), ink3: renk('--ink-3'), paper: renk('--paper'), magenta: renk('--magenta') };
    const tum = { type: 'FeatureCollection', features: (V.iz || []).length ? [{ type: 'Feature', properties: {}, geometry: { type: 'MultiLineString', coordinates: V.iz.map((s) => s.map((p) => [p[0], p[1]])) } }] : [] };
    const bos = [], dur = [];
    for (const e of V.olaylar || []) {
      if (e.k === 'gap' && e.a && e.b) bos.push({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: [e.a, e.b] } });
      else if (e.p) dur.push({ type: 'Feature', properties: { k: e.k }, geometry: { type: 'Point', coordinates: e.p } });
    }
    const zy = (V.ziyaretler || []).filter((z) => z.p).map((z) => ({ type: 'Feature', properties: { l: z.l }, geometry: { type: 'Point', coordinates: z.p } }));
    m.addSource('tum', { type: 'geojson', data: tum });
    m.addSource('gecilen', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    m.addSource('konum', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
    m.addSource('bosluk', { type: 'geojson', data: { type: 'FeatureCollection', features: bos } });
    m.addSource('olay', { type: 'geojson', data: { type: 'FeatureCollection', features: dur } });
    m.addSource('ziyaret', { type: 'geojson', data: { type: 'FeatureCollection', features: zy } });
    m.addLayer({ id: 'tum', type: 'line', source: 'tum', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': c.ink3, 'line-width': 1.2, 'line-opacity': 0.6 } });
    m.addLayer({ id: 'bosluk', type: 'line', source: 'bosluk', paint: { 'line-color': c.magenta, 'line-width': 2, 'line-dasharray': [1, 1.6] } });
    m.addLayer({ id: 'gecilen-zemin', type: 'line', source: 'gecilen', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': c.paper, 'line-width': 5 } });
    m.addLayer({ id: 'gecilen', type: 'line', source: 'gecilen', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': c.ink, 'line-width': 2.4 } });
    m.addLayer({ id: 'olay', type: 'circle', source: 'olay', paint: { 'circle-radius': 4, 'circle-color': ['match', ['get', 'k'], 'sts', renk('--c-sts'), c.ink3], 'circle-stroke-color': c.paper, 'circle-stroke-width': 1.5 } });
    m.addLayer({ id: 'ziyaret', type: 'circle', source: 'ziyaret', paint: { 'circle-radius': 5, 'circle-color': c.paper, 'circle-stroke-color': c.ink, 'circle-stroke-width': 2 } });
    if (!yedek) m.addLayer({ id: 'ziyaret-ad', type: 'symbol', source: 'ziyaret', layout: { 'text-field': ['get', 'l'], 'text-font': ['Noto Sans Bold'], 'text-size': 11.5, 'text-offset': [0, 1.1], 'text-anchor': 'top', 'text-optional': true }, paint: { 'text-color': c.ink, 'text-halo-color': c.paper, 'text-halo-width': 1.4 } });
    m.addLayer({ id: 'konum', type: 'circle', source: 'konum', paint: { 'circle-radius': 6, 'circle-color': c.ink, 'circle-stroke-color': c.paper, 'circle-stroke-width': 2.5 } });
    hazir = true;
    ciz(Number(kaydir.value));
  }
  function oynat() {
    if (oyna) { cancelAnimationFrame(oyna); oyna = null; dugme.textContent = 'Oynat'; return; }
    const a = Number(kaydir.min), b = Number(kaydir.max);
    if (Number(kaydir.value) >= b) kaydir.value = a;
    dugme.textContent = 'Durdur';
    const sure = LI.azHareket ? 6000 : 20000;
    let bas = null; const bas0 = Number(kaydir.value);
    const adim = (zaman) => {
      if (bas === null) bas = zaman;
      const v = Math.min(b, bas0 + ((zaman - bas) / sure) * (b - a));
      kaydir.value = v; ciz(v);
      if (v < b) oyna = requestAnimationFrame(adim); else { oyna = null; dugme.textContent = 'Oynat'; }
    };
    oyna = requestAnimationFrame(adim);
  }

  (async () => {
    try { V = await LI.json(`${KOK}veri/gemi/${ANAHTAR}.json${S}`); } catch (e) { kutu.innerHTML = '<p class="harita-mesaj yuzer">İz verisi yüklenemedi.</p>'; return; }
    hazirla();
    if (!noktalar.length) { kutu.innerHTML = '<p class="harita-mesaj yuzer">Bu gemi için açık denizde kayıtlı iz yok; yalnızca liman ziyaretleri var.</p>'; $('.oynatici').hidden = true; return; }
    kaydir.min = noktalar[0][2]; kaydir.max = noktalar[noktalar.length - 1][2]; kaydir.step = 10; kaydir.value = kaydir.max;
    cikti.textContent = LI.tarih(Number(kaydir.max) * 60000, true);
    let ml;
    try { ml = await LI.maplibre(KOK); } catch (e) { kutu.innerHTML = '<p class="harita-mesaj yuzer">Harita bu tarayıcıda açılamadı.</p>'; return; }
    const stil = await LI.stil();
    const b = LI.sinirlar(noktalar.concat((V.ziyaretler || []).map((z) => z.p).filter(Boolean)));
    try {
      harita = new ml.Map({ container: kutu.querySelector('.harita-ic'), style: stil, bounds: b, fitBoundsOptions: { padding: 40, maxZoom: 9 },
        attributionControl: false, dragRotate: false, pitchWithRotate: false, fadeDuration: 0 });
    } catch (e) { kutu.innerHTML = '<p class="harita-mesaj yuzer">Harita açılamadı: tarayıcın WebGL desteklemiyor olabilir.</p>'; return; }
    harita.addControl(new ml.NavigationControl({ showCompass: false }), 'top-right');
    harita.addControl(new ml.AttributionControl({ compact: true }), 'bottom-right');
    harita.on('load', () => { katmanlar(stil.yedek); harita.once('idle', () => { window.__haritaHazir = Math.round(performance.now()); }); });
    document.addEventListener('tema', async () => {
      const yeni = await LI.stil(); hazir = false;
      harita.setStyle(yeni, { diff: false });
      harita.once('style.load', () => katmanlar(yeni.yedek));
    });
  })();
  kaydir.addEventListener('input', () => ciz(Number(kaydir.value)));
  dugme.addEventListener('click', oynat);
})();
