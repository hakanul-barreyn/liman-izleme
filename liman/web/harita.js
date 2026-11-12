/* Liman İzleme – ana harita: seferler, zaman çizelgesi ve geçmiş oynatma. */
(function () {
  'use strict';
  const LI = window.LI;
  const $ = (s, el) => (el || document).querySelector(s);
  const esc = LI.esc;
  const ayar = JSON.parse($('#ayar').textContent);
  const KOK = ayar.kok || '';
  const S = ayar.surum ? `?v=${ayar.surum}` : '';

  /* ---------- durum ---------- */
  const durum = {
    y: ayar.yonler[0], aile: new Set(), kaynak: new Set(['c', 'g']), q: '', t: null, sec: null, limit: 80,
    katman: { canli: true, olay: false, sahte: false },
  };
  let VERI = null, KAYIT = [], ID = new Map(), AILE = [], ALAN = null, CANLI = null, OLAY = null;
  let harita = null, haritaHazir = false, popup = null, oynatici = null;

  const ay = (iso) => { const d = new Date(iso); return d.getUTCFullYear() * 12 + d.getUTCMonth(); };
  const ayKodu = (i) => `${Math.floor(i / 12)}-${String((i % 12) + 1).padStart(2, '0')}`;
  const ayCoz = (s) => { const [y, m] = s.split('-').map(Number); return y * 12 + m - 1; };
  const AYLAR = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];
  const ayAd = (i, kisa) => `${kisa ? AYLAR[i % 12].slice(0, 3) : AYLAR[i % 12]} ${Math.floor(i / 12)}`;
  const zaman = (r) => r.t1 || r.t0;
  const ulke = (k) => (VERI && VERI.ulkeler[k]) || k;

  /* ---------- adres çubuğu ---------- */
  function hashOku() {
    const p = new URLSearchParams(location.hash.slice(1));
    if (p.get('y') && ayar.yonler.includes(p.get('y'))) durum.y = p.get('y');
    if (p.get('a')) durum.aile = new Set(p.get('a').split(',').filter(Boolean));
    if (p.get('k')) durum.kaynak = new Set(p.get('k').split(',').filter((x) => x === 'c' || x === 'g'));
    if (p.get('q')) durum.q = p.get('q');
    if (p.get('t')) {
      const [a, b] = p.get('t').split('_');
      const t = [ayCoz(a), ayCoz(b || a)];
      durum.t = t.every(Number.isFinite) ? [Math.min(...t), Math.max(...t)] : null;
    }
    if (p.get('sec')) durum.sec = p.get('sec');
  }
  function hashYaz() {
    const p = new URLSearchParams();
    if (durum.y !== ayar.yonler[0]) p.set('y', durum.y);
    if (durum.aile.size !== AILE.length) p.set('a', [...durum.aile].join(','));
    if (durum.kaynak.size !== 2) p.set('k', [...durum.kaynak].join(','));
    if (durum.q) p.set('q', durum.q);
    if (durum.t) p.set('t', `${ayKodu(durum.t[0])}_${ayKodu(durum.t[1])}`);
    if (durum.sec) p.set('sec', durum.sec);
    const h = p.toString();
    history.replaceState(null, '', h ? `#${h}` : location.pathname + location.search);
  }

  /* ---------- süzme ---------- */
  function aramaUyar(r) {
    if (!durum.q) return true;
    const q = durum.q.toLocaleLowerCase('tr');
    return (r.n || '').toLocaleLowerCase('tr').includes(q) || String(r.m || '').includes(q) || String(r.imo || '').includes(q);
  }
  const temel = (r) => r.y === durum.y && durum.kaynak.has(r.s) && aramaUyar(r);
  const zamanda = (r) => !durum.t || (r._ay >= durum.t[0] && r._ay <= durum.t[1]);
  const uyar = (r) => temel(r) && durum.aile.has(r.a) && zamanda(r);

  /* ---------- panel ---------- */
  function manset(list) {
    const [A, B] = durum.y.split('>');
    const n = list.length;
    const karanlik = list.filter((r) => r.a === 'karanlik').length;
    $('#manset').textContent = `${ulke(A)} limanlarından ${ulke(B)} yönüne ${LI.sayi(n)} sefer`;
    let donem;
    if (durum.t) {
      donem = durum.t[0] === durum.t[1] ? `${ayAd(durum.t[0])} içinde` : `${ayAd(durum.t[0])} ile ${ayAd(durum.t[1])} arasında`;
    } else if (n) {
      const ts = list.map(zaman).filter(Boolean).sort();
      donem = `${LI.tarih(ts[0])} ile ${LI.tarih(ts[ts.length - 1])} arasında`;
    } else donem = '';
    let alt = n ? `${donem}, AIS kayıtlarına göre.` : 'Seçili filtrelerle eşleşen sefer yok. Filtreleri genişlet ya da tüm dönemi seç.';
    if (karanlik) alt += ` ${LI.sayi(karanlik)} seferde gemi yolda sinyalini kapattı ya da varış limanı kayıtsız kaldı.`;
    $('#manset-alt').textContent = alt;
  }

  function aileler() {
    const kutu = $('#siniflar');
    const sayac = {};
    for (const r of KAYIT) if (temel(r) && zamanda(r)) sayac[r.a] = (sayac[r.a] || 0) + 1;
    kutu.innerHTML = AILE.map((f) => `<button type="button" class="sinif" data-a="${f.kod}" aria-pressed="${durum.aile.has(f.kod)}"
      style="--c:var(--c-${f.kod})"><span class="cizgi"></span><b>${esc(f.ad)}</b><span class="sayi">${LI.sayi(sayac[f.kod] || 0)}</span>
      <small>${esc(f.not)}</small></button>`).join('');
  }

  function satir(r) {
    const rota = `${esc(r.o)} → ${r.d ? esc(r.d) : 'varış kayıtsız'}`;
    return `<li><button type="button" class="satir" data-id="${r.id}" style="--c:var(--c-${r.a})">
      <span class="serit${r.s === 'g' ? ' g' : ''}"></span><b>${esc(r.n || 'Adı bilinmiyor')}</b>
      <time datetime="${esc(zaman(r))}">${LI.tarih(zaman(r))}</time><span class="rota">${rota}</span></button></li>`;
  }

  function liste(list) {
    const kutu = $('#liste');
    if (!list.length) { kutu.innerHTML = '<p class="bos">Bu filtrelerle sefer yok.</p>'; return; }
    const sirali = list.slice().sort((a, b) => (zaman(b) || '').localeCompare(zaman(a) || ''));
    const goster = sirali.slice(0, durum.limit);
    kutu.innerHTML = `<ul class="liste">${goster.map(satir).join('')}</ul>` +
      (sirali.length > goster.length ? `<button type="button" class="daha" id="daha">${LI.sayi(sirali.length - goster.length)} sefer daha göster</button>` : '');
  }

  function uygula(opts) {
    opts = opts || {};
    const list = KAYIT.filter(uyar);
    manset(list);
    aileler();
    if (!durum.sec) liste(list);
    cizelge();
    haritaSuz();
    if (!opts.hashYok) hashYaz();
  }

  /* ---------- sefer ayrıntısı ---------- */
  function adimlar(r) {
    const out = [];
    out.push(`<li><b>Çıkış: ${esc(r.o)}</b><span>${LI.tarih(r.t0, true)}${r.oc ? `, ${esc(ulke(r.oc))}` : ''}</span></li>`);
    for (const x of r.ara || []) out.push(`<li><b>Ara liman: ${esc(x)}</b></li>`);
    for (const s of r.sts || []) out.push(`<li><b>Denizde başka bir gemiyle buluştu</b><span>${LI.tarih(s[2], true)}${s[4] ? `, ${s[4]} saat yan yana` : ''}</span></li>`);
    for (const k of r.kp || []) {
      out.push(`<li class="kapali"><b>AIS sinyali kesildi</b><span>${LI.tarih(k[5], true)}, ${k[1].toFixed(2)}° K ${k[0].toFixed(2)}° D</span></li>`);
      out.push(`<li class="acik"><b>AIS sinyali yeniden geldi</b><span>${LI.tarih(k[6], true)}${k[4] ? `, ${String(k[4]).replace('.', ',')} saat sonra` : ''}</span></li>`);
    }
    if (r.k === 'kiyida_kayboldu') {
      out.push(`<li class="bilinmez"><b>${esc(r.d || 'Kıyı alanı')}: sinyal kesildi</b><span>${LI.tarih(r.t1, true)}${r.sz ? `, ardından ${String(r.sz).replace('.', ',')} saat sessizlik` : ''}. Hiçbir limanda kaydı yok.</span></li>`);
    } else if (r.d) {
      out.push(`<li><b>Varış: ${esc(r.d)}</b><span>${LI.tarih(r.t1, true)}${r.dc ? `, ${esc(ulke(r.dc))}` : ''}</span></li>`);
    } else {
      out.push(`<li class="bilinmez"><b>Varış limanı kayıtsız</b><span>${r.sl ? `Sonraki kayıtlı liman: ${esc(r.sl)}` : 'Sonraki liman kaydı yok'}</span></li>`);
    }
    return `<ol class="adimlar">${out.join('')}</ol>`;
  }

  function uyduBlok(r) {
    const k = (r.kp || [])[0];
    const t0 = k ? k[5] : r.t0, t1 = k ? k[6] : r.t1;
    if (!t0 || !t1) return '';
    const yerler = [];
    if (ALAN) for (const f of ALAN.features) if (f.properties.tur === 'hedef' && f.properties.merkez) yerler.push([f.properties.ad, f.properties.merkez]);
    if (k) yerler.push(['Sinyalin kesildiği nokta', [k[0], k[1]]]);
    if (!yerler.length) return '';
    return `<div class="blok"><h3>Uydu görüntüsü, ${LI.tarih(t0)} – ${LI.tarih(t1)}</h3>
      <p class="not">Sentinel-1 radar bulut ve geceden etkilenmez; Sentinel-2 optik görüntü bulutsuz günlerde işe yarar.</p>
      <div class="uydu">${yerler.map(([ad, p]) => `<span>${esc(ad)}</span>
        <a href="${esc(LI.uydu(p[1], p[0], t0, t1, true))}" target="_blank" rel="noopener">Radar</a>
        <a href="${esc(LI.uydu(p[1], p[0], t0, t1, false))}" target="_blank" rel="noopener">Optik</a>`).join('')}</div></div>`;
  }

  function detay(id) {
    const r = ID.get(id);
    const kutu = $('#detay');
    if (!r) { kapat(); return; }
    const [, B] = r.y.split('>');
    const kimlik = [r.tip, r.b ? `${r.b} bayraklı` : null, r.imo ? `IMO ${r.imo}` : null, r.m ? `MMSI ${r.m}` : null].filter(Boolean).join(', ');
    let beyan = '';
    if (r.vb === 'farkli') beyan = `<div class="blok"><h3>Beyan edilen varış</h3><p class="dikkat">Gemi çıkarken AIS'e “${esc(r.vt)}” yazdı. Bu, ${esc(ulke(B))} limanlarını göstermiyor.</p></div>`;
    else if (r.vb === 'bos') beyan = '<div class="blok"><h3>Beyan edilen varış</h3><p>Gemi çıkarken AIS\'te varış noktası boştu.</p></div>';
    let yuk = '';
    if (r.yuk) yuk = `<div class="blok"><h3>Muhtemel yük: ${esc(r.yuk)}</h3><p class="not">Güven: ${esc(r.gv || '–')}. Kesin yük bilgisi değildir; dayanakları:</p>
      <ul>${(r.dy || []).map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div>`;
    const via = r.via ? `<p class="kimlik">Yükü denizde veren gemi: ${r.via.g ? `<a href="${KOK}gemiler/${esc(r.via.g)}.html">${esc(r.via.n)}</a>` : esc(r.via.n)}</p>` : '';
    const kaynak = r.s === 'c'
      ? 'Kaynak: bu sitenin kendi AIS kaydı. Ham mesajlar her gün mühürlenir, bkz. <a href="kanit.html">Kanıt zinciri</a>.'
      : 'Kaynak: Global Fishing Watch liman ziyareti ve AIS boşluğu verisi (geçmiş tarama). Rota çizgisi gerçek güzergâhı değil, limanlar arası bağlantıyı gösterir.';
    kutu.innerHTML = `<div class="detay"><button type="button" class="geri" id="geri">← Listeye dön</button>
      <h2>${esc(r.n || 'Adı bilinmiyor')}</h2><p class="kimlik">${esc(kimlik)}</p>${via}
      <span class="rozet" style="--c:var(--c-${r.a})">${esc((VERI.siniflar || {})[r.k] || r.k)}</span>
      ${adimlar(r)}${beyan}${yuk}${uyduBlok(r)}
      <div class="eylemler">${r.g ? `<a class="eylem ana" href="${KOK}gemiler/${esc(r.g)}.html">Geminin tüm geçmişi</a>` : ''}
        <button type="button" class="eylem" id="kopyala">Bağlantıyı kopyala</button></div>
      <p class="kaynak">${kaynak}</p></div>`;
    kutu.hidden = false;
    $('#liste').hidden = true;
    $('.kontrol').hidden = true;
    $('.panel-govde').scrollTop = 0;
    $('#panel').classList.add('acik');
    $('#cekme').setAttribute('aria-expanded', 'true');
    haritaSec(r);
  }
  function kapat() {
    durum.sec = null;
    $('#detay').hidden = true;
    $('#liste').hidden = false;
    $('.kontrol').hidden = false;
    haritaSec(null);
    uygula();
  }

  /* ---------- zaman çizelgesi ---------- */
  let cizim = null;
  function cizelge() {
    const svg = $('#cizelge');
    if (!svg || !KAYIT.length) return;
    const W = svg.clientWidth || 600, H = svg.clientHeight || 58;
    const ilk = Math.min(ay(ayar.baslangic || zaman(KAYIT[0])), ...KAYIT.filter((r) => r.y === durum.y).map((r) => r._ay));
    const son = ay(new Date().toISOString());
    const N = Math.max(1, son - ilk + 1);
    const sayac = new Array(N).fill(0);
    for (const r of KAYIT) if (temel(r) && durum.aile.has(r.a) && r._ay >= ilk && r._ay <= son) sayac[r._ay - ilk]++;
    const ust = Math.max(1, ...sayac);
    const altBos = 15, padX = 2, bw = Math.min(40, (W - padX * 2) / N), gap = bw > 6 ? 2 : 1;
    const h = (v) => (v ? Math.max(2, ((H - altBos - 4) * v) / ust) : 0);
    let s = `<line class="taban" x1="0" x2="${W}" y1="${H - altBos + 0.5}" y2="${H - altBos + 0.5}"/>`;
    if (durum.t) {
      const x0 = padX + (durum.t[0] - ilk) * bw, x1 = padX + (durum.t[1] - ilk + 1) * bw;
      s += `<rect class="secim" x="${x0}" y="0" width="${Math.max(0, x1 - x0)}" height="${H - altBos}"/>`;
    }
    for (let i = 0; i < N; i++) {
      const v = sayac[i];
      if (!v) continue;
      const x = padX + i * bw + gap / 2, w = Math.max(1, bw - gap), yy = H - altBos - h(v), r = Math.min(2, w / 2);
      const sec = !durum.t || (i + ilk >= durum.t[0] && i + ilk <= durum.t[1]);
      s += `<path class="cubuk${sec ? ' sec' : ''}" d="M${x},${H - altBos}V${yy + r}Q${x},${yy} ${x + r},${yy}H${x + w - r}Q${x + w},${yy} ${x + w},${yy + r}V${H - altBos}Z"/>`;
    }
    const adim = bw < 14 ? 12 : bw < 28 ? 6 : 3;
    for (let i = 0; i < N; i++) {
      const m = (i + ilk) % 12;
      if (i === 0 || m === 0 || (adim < 12 && m % adim === 0)) {
        const x = padX + i * bw + 1;
        const etiket = m === 0 || i === 0 ? ayAd(i + ilk, true) : AYLAR[m].slice(0, 3);
        if (x < W - 40) s += `<text class="eksen" x="${x}" y="${H - 2}">${etiket}</text>`;
      }
    }
    svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    svg.innerHTML = s;
    cizim = { ilk, N, bw, padX, sayac };
  }
  function cizelgeEtkilesim() {
    const svg = $('#cizelge'), ip = $('#ipucu');
    let bas = null, oynadi = false;
    const idx = (e) => {
      const b = svg.getBoundingClientRect();
      const i = Math.floor((e.clientX - b.left - cizim.padX) / cizim.bw);
      return Math.max(0, Math.min(cizim.N - 1, i));
    };
    svg.addEventListener('pointerdown', (e) => { if (!cizim) return; bas = idx(e); oynadi = false; svg.setPointerCapture(e.pointerId); });
    svg.addEventListener('pointermove', (e) => {
      if (!cizim) return;
      const i = idx(e);
      const b = svg.getBoundingClientRect(), kap = svg.closest('.harita').getBoundingClientRect();
      ip.hidden = false;
      ip.textContent = `${ayAd(i + cizim.ilk)}: ${LI.sayi(cizim.sayac[i])} sefer`;
      ip.style.left = `${b.left - kap.left + cizim.padX + (i + 0.5) * cizim.bw}px`;
      ip.style.top = `${b.top - kap.top}px`;
      if (bas !== null && i !== bas) {
        oynadi = true;
        durum.t = [Math.min(bas, i) + cizim.ilk, Math.max(bas, i) + cizim.ilk];
        durum.limit = 80; uygula();
      }
    });
    svg.addEventListener('pointerleave', () => { ip.hidden = true; });
    svg.addEventListener('pointerup', (e) => {
      if (bas === null) return;
      if (!oynadi) {
        const m = bas + cizim.ilk;
        durum.t = durum.t && durum.t[0] === m && durum.t[1] === m ? null : [m, m];
        durum.limit = 80; uygula();
      }
      bas = null;
    });
  }
  function oynat() {
    const b = $('#oynat');
    if (oynatici) { clearInterval(oynatici); oynatici = null; b.innerHTML = OYNAT; b.setAttribute('aria-label', 'Geçmişi oynat'); return; }
    if (!cizim) return;
    let i = durum.t && durum.t[0] === durum.t[1] && durum.t[0] < cizim.ilk + cizim.N - 1 ? durum.t[0] - cizim.ilk : 0;
    b.innerHTML = DURDUR; b.setAttribute('aria-label', 'Durdur');
    const adim = () => {
      if (i >= cizim.N) { oynat(); return; }
      durum.t = [i + cizim.ilk, i + cizim.ilk];
      uygula({ hashYok: true });
      i++;
    };
    adim();
    oynatici = setInterval(adim, LI.azHareket ? 1600 : 900);
  }
  const OYNAT = '<svg viewBox="0 0 14 14" aria-hidden="true"><path d="M3 1.5v11l9-5.5z"/></svg>';
  const DURDUR = '<svg viewBox="0 0 14 14" aria-hidden="true"><path d="M3 2h3v10H3zM8 2h3v10H8z"/></svg>';

  /* ---------- harita ---------- */
  function renkler() {
    const r = (n) => LI.renk(n);
    return { ink: r('--ink'), ink2: r('--ink-2'), ink3: r('--ink-3'), paper: r('--paper'), magenta: r('--magenta'),
             aile: ['match', ['get', 'a'], 'dogrudan', r('--c-dogrudan'), 'liman', r('--c-liman'), 'sts', r('--c-sts'), r('--c-karanlik')] };
  }
  function ozellikler() {
    const cizgi = [], bosluk = [], nokta = [];
    for (const r of KAYIT) {
      const p = { id: r.id, y: r.y, s: r.s, a: r.a, ay: r._ay };
      if (r.iz && r.iz.length) {
        cizgi.push({ type: 'Feature', properties: { ...p, tur: 'iz' }, geometry: { type: 'MultiLineString', coordinates: r.iz } });
        for (let i = 1; i < r.iz.length; i++) {
          const a = r.iz[i - 1][r.iz[i - 1].length - 1], b = r.iz[i][0];
          cizgi.push({ type: 'Feature', properties: { ...p, tur: 'bos' }, geometry: { type: 'LineString', coordinates: [a, b] } });
        }
        const ilk = r.iz[0][0];
        if (r.w && r.w[0] && (Math.abs(r.w[0][0] - ilk[0]) > 0.05 || Math.abs(r.w[0][1] - ilk[1]) > 0.05)) {
          cizgi.push({ type: 'Feature', properties: { ...p, tur: 'bos' }, geometry: { type: 'LineString', coordinates: [r.w[0], ilk] } });
        }
      } else if (r.w && r.w.length >= 2) {
        let c = [];
        for (let i = 1; i < r.w.length; i++) c = c.concat(LI.yay(r.w[i - 1], r.w[i]).slice(i > 1 ? 1 : 0));
        cizgi.push({ type: 'Feature', properties: { ...p, tur: 'yay' }, geometry: { type: 'LineString', coordinates: c } });
      }
      for (const k of r.kp || []) {
        bosluk.push({ type: 'Feature', properties: p, geometry: { type: 'LineString', coordinates: [[k[0], k[1]], [k[2], k[3]]] } });
        nokta.push({ type: 'Feature', properties: { ...p, tur: 'kapandi' }, geometry: { type: 'Point', coordinates: [k[0], k[1]] } });
        nokta.push({ type: 'Feature', properties: { ...p, tur: 'acildi' }, geometry: { type: 'Point', coordinates: [k[2], k[3]] } });
      }
      for (const s of r.sts || []) nokta.push({ type: 'Feature', properties: { ...p, tur: 'bulusma' }, geometry: { type: 'Point', coordinates: [s[0], s[1]] } });
      const son = r.iz && r.iz.length ? r.iz[r.iz.length - 1][r.iz[r.iz.length - 1].length - 1] : (r.w || [])[r.w ? r.w.length - 1 : 0];
      if (son) nokta.push({ type: 'Feature', properties: { ...p, tur: r.d && r.k !== 'kiyida_kayboldu' ? 'varis' : 'kayip' }, geometry: { type: 'Point', coordinates: son } });
    }
    const fc = (f) => ({ type: 'FeatureCollection', features: f });
    return { cizgi: fc(cizgi), bosluk: fc(bosluk), nokta: fc(nokta) };
  }
  function canliOzellik() {
    const n = [], iz = [];
    for (const g of (CANLI && CANLI.gemiler) || []) {
      if (!g.p) continue;
      n.push({ type: 'Feature', properties: { m: g.m, n: g.n, g: g.g || '', c: g.c || 0, t: g.t, vt: g.vt || '', tip: g.tip || '' }, geometry: { type: 'Point', coordinates: g.p } });
      if (g.iz && g.iz.length) iz.push({ type: 'Feature', properties: { m: g.m }, geometry: { type: 'MultiLineString', coordinates: g.iz } });
    }
    return { nokta: { type: 'FeatureCollection', features: n }, iz: { type: 'FeatureCollection', features: iz } };
  }
  function olayOzellik() {
    const o = [], s = [];
    for (const e of (OLAY && OLAY.olaylar) || []) if (e.p) o.push({ type: 'Feature', properties: { k: e.k, n: e.n || '', n2: e.n2 || '', t0: e.t0, s: e.s || 0 }, geometry: { type: 'Point', coordinates: e.p } });
    for (const p of (OLAY && OLAY.sahte) || []) s.push({ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: p } });
    return { olay: { type: 'FeatureCollection', features: o }, sahte: { type: 'FeatureCollection', features: s } };
  }
  function alanEtiketleri() {
    const f = [];
    for (const z of (ALAN && ALAN.features) || []) if (z.properties.merkez) f.push({ type: 'Feature', properties: z.properties, geometry: { type: 'Point', coordinates: z.properties.merkez } });
    return { type: 'FeatureCollection', features: f };
  }
  const FONT = ['Noto Sans Regular'];
  const FONT_B = ['Noto Sans Bold'];
  function katmanlariKur(yedek) {
    const c = renkler();
    const m = harita;
    const oz = ozellikler(), cz = canliOzellik(), ol = olayOzellik();
    m.addSource('alan', { type: 'geojson', data: ALAN || { type: 'FeatureCollection', features: [] } });
    m.addSource('alan-etiket', { type: 'geojson', data: alanEtiketleri() });
    m.addSource('sefer', { type: 'geojson', data: oz.cizgi, tolerance: 0.2 });
    m.addSource('bosluk', { type: 'geojson', data: oz.bosluk });
    m.addSource('nokta', { type: 'geojson', data: oz.nokta });
    m.addSource('canli', { type: 'geojson', data: cz.nokta });
    m.addSource('canli-iz', { type: 'geojson', data: cz.iz });
    m.addSource('olay', { type: 'geojson', data: ol.olay });
    m.addSource('sahte', { type: 'geojson', data: ol.sahte });
    LI.okResmi(m, 'gemi', c.ink, c.paper);
    const tur = (...t) => ['in', ['get', 'tur'], ['literal', t]];
    m.addLayer({ id: 'alan-dolgu', type: 'fill', source: 'alan', filter: tur('izlenen', 'hedef', 'yaklasma'),
      paint: { 'fill-color': ['match', ['get', 'tur'], 'yaklasma', c.magenta, c.ink], 'fill-opacity': ['match', ['get', 'tur'], 'yaklasma', 0.05, 'hedef', 0.07, 0.09] } });
    m.addLayer({ id: 'alan-cizgi', type: 'line', source: 'alan', filter: tur('izlenen', 'hedef', 'ara'),
      paint: { 'line-color': ['match', ['get', 'tur'], 'ara', c.ink3, c.ink2], 'line-width': ['match', ['get', 'tur'], 'ara', 0.6, 1] } });
    m.addLayer({ id: 'alan-kesik', type: 'line', source: 'alan', filter: tur('dinleme', 'karanlik'),
      paint: { 'line-color': c.ink3, 'line-width': 0.8, 'line-dasharray': [4, 3] } });
    m.addLayer({ id: 'alan-yaklasma', type: 'line', source: 'alan', filter: tur('yaklasma'),
      paint: { 'line-color': c.magenta, 'line-width': 1.2, 'line-dasharray': [3, 2] } });
    m.addLayer({ id: 'canli-iz', type: 'line', source: 'canli-iz', layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': c.ink3, 'line-width': 1, 'line-opacity': 0.8 } });
    m.addLayer({ id: 'yay', type: 'line', source: 'sefer', filter: ['==', ['get', 'tur'], 'yay'], layout: { 'line-cap': 'round' },
      paint: { 'line-color': c.aile, 'line-width': ['interpolate', ['linear'], ['zoom'], 4, 1, 8, 1.8], 'line-opacity': 0.75, 'line-dasharray': [3, 2] } });
    m.addLayer({ id: 'iz-zemin', type: 'line', source: 'sefer', filter: ['==', ['get', 'tur'], 'iz'], layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': c.paper, 'line-width': 4.5, 'line-opacity': 0.9 } });
    m.addLayer({ id: 'iz', type: 'line', source: 'sefer', filter: ['==', ['get', 'tur'], 'iz'], layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': c.aile, 'line-width': 2.2 } });
    m.addLayer({ id: 'bos', type: 'line', source: 'sefer', filter: ['==', ['get', 'tur'], 'bos'],
      paint: { 'line-color': c.ink3, 'line-width': 1.2, 'line-dasharray': [0.6, 2.2] } });
    m.addLayer({ id: 'bosluk', type: 'line', source: 'bosluk', paint: { 'line-color': c.magenta, 'line-width': 2, 'line-dasharray': [1, 1.6] } });
    m.addLayer({ id: 'secili-zemin', type: 'line', source: 'sefer', filter: ['==', ['get', 'id'], ''], layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': c.paper, 'line-width': 8 } });
    m.addLayer({ id: 'secili', type: 'line', source: 'sefer', filter: ['==', ['get', 'id'], ''], layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: { 'line-color': c.aile, 'line-width': 4 } });
    m.addLayer({ id: 'secili-bosluk', type: 'line', source: 'bosluk', filter: ['==', ['get', 'id'], ''],
      paint: { 'line-color': c.magenta, 'line-width': 3, 'line-dasharray': [1, 1.4] } });
    m.addLayer({ id: 'nokta', type: 'circle', source: 'nokta', paint: {
      'circle-radius': ['match', ['get', 'tur'], 'kapandi', 4.5, 'acildi', 3.5, 'kayip', 5, 'bulusma', 4.5, 3.5],
      'circle-color': ['match', ['get', 'tur'], 'kapandi', c.paper, 'kayip', c.paper, 'acildi', c.magenta, 'bulusma', LI.renk('--c-sts'), c.aile],
      'circle-stroke-color': ['match', ['get', 'tur'], 'kapandi', c.magenta, 'kayip', c.magenta, c.paper],
      'circle-stroke-width': ['match', ['get', 'tur'], 'kapandi', 2, 'kayip', 2, 1.5] } });
    m.addLayer({ id: 'olay', type: 'circle', source: 'olay', layout: { visibility: durum.katman.olay ? 'visible' : 'none' }, paint: {
      'circle-radius': 4, 'circle-color': ['match', ['get', 'k'], 'gap', c.magenta, 'sts', LI.renk('--c-sts'), c.ink3],
      'circle-stroke-color': c.paper, 'circle-stroke-width': 1.5 } });
    m.addLayer({ id: 'sahte', type: 'circle', source: 'sahte', layout: { visibility: durum.katman.sahte ? 'visible' : 'none' },
      paint: { 'circle-radius': 1.8, 'circle-color': c.ink3, 'circle-opacity': 0.6 } });
    m.addLayer({ id: 'canli', type: 'symbol', source: 'canli', layout: {
      visibility: durum.katman.canli ? 'visible' : 'none', 'icon-image': 'gemi', 'icon-size': ['interpolate', ['linear'], ['zoom'], 4, 0.55, 9, 0.85],
      'icon-rotate': ['get', 'c'], 'icon-rotation-alignment': 'map', 'icon-allow-overlap': true,
      ...(yedek ? {} : { 'text-field': ['step', ['zoom'], '', 7, ['get', 'n']], 'text-font': FONT, 'text-size': 11, 'text-offset': [0, 1.3], 'text-anchor': 'top', 'text-optional': true }) },
      paint: yedek ? {} : { 'text-color': c.ink2, 'text-halo-color': c.paper, 'text-halo-width': 1.2 } });
    m.setLayoutProperty('canli-iz', 'visibility', durum.katman.canli ? 'visible' : 'none');
    if (!yedek) {
      m.addLayer({ id: 'alan-etiket-ara', type: 'symbol', source: 'alan-etiket', filter: tur('yaklasma', 'ara'), minzoom: 5.5,
        layout: { 'text-field': ['get', 'ad'], 'text-font': FONT, 'text-size': 10.5, 'text-max-width': 9, 'text-optional': true },
        paint: { 'text-color': ['match', ['get', 'tur'], 'yaklasma', c.magenta, c.ink3], 'text-halo-color': c.paper, 'text-halo-width': 1.4 } });
      m.addLayer({ id: 'alan-etiket', type: 'symbol', source: 'alan-etiket', filter: tur('izlenen', 'hedef'), minzoom: 4.5,
        layout: { 'text-field': ['get', 'ad'], 'text-font': FONT_B, 'text-size': 12, 'text-max-width': 9, 'text-optional': true },
        paint: { 'text-color': c.ink, 'text-halo-color': c.paper, 'text-halo-width': 1.4 } });
    }
    // tıklama alanı çizgilerden geniş olsun
    m.addLayer({ id: 'vurgu', type: 'line', source: 'sefer', filter: ['in', ['get', 'tur'], ['literal', ['iz', 'yay']]], paint: { 'line-color': '#000', 'line-opacity': 0, 'line-width': 14 } });
    haritaSuz();
    if (durum.sec && ID.get(durum.sec)) haritaSec(ID.get(durum.sec));
  }

  function suzgec() {
    const f = ['all', ['==', ['get', 'y'], durum.y], ['in', ['get', 's'], ['literal', [...durum.kaynak]]], ['in', ['get', 'a'], ['literal', [...durum.aile]]]];
    if (durum.t) f.push(['>=', ['get', 'ay'], durum.t[0]], ['<=', ['get', 'ay'], durum.t[1]]);
    if (durum.q) f.push(['in', ['get', 'id'], ['literal', KAYIT.filter(uyar).map((r) => r.id)]]);
    return f;
  }
  function haritaSuz() {
    if (!haritaHazir) return;
    const f = suzgec();
    const tur = (x) => [...f, ['==', ['get', 'tur'], x]];
    harita.setFilter('yay', tur('yay'));
    harita.setFilter('iz-zemin', tur('iz'));
    harita.setFilter('iz', tur('iz'));
    harita.setFilter('bos', tur('bos'));
    harita.setFilter('vurgu', [...f, ['in', ['get', 'tur'], ['literal', ['iz', 'yay']]]]);
    harita.setFilter('bosluk', f);
    harita.setFilter('nokta', f);
    const sec = !!durum.sec;
    harita.setPaintProperty('iz', 'line-opacity', sec ? 0.25 : 1);
    harita.setPaintProperty('yay', 'line-opacity', sec ? 0.18 : 0.75);
    harita.setPaintProperty('bosluk', 'line-opacity', sec ? 0.25 : 1);
    harita.setPaintProperty('nokta', 'circle-opacity', sec ? 0.25 : 1);
    harita.setPaintProperty('nokta', 'circle-stroke-opacity', sec ? 0.25 : 1);
  }
  function haritaSec(r) {
    if (!haritaHazir) return;
    const id = r ? r.id : '';
    harita.setFilter('secili-zemin', ['==', ['get', 'id'], id]);
    harita.setFilter('secili', ['==', ['get', 'id'], id]);
    harita.setFilter('secili-bosluk', ['==', ['get', 'id'], id]);
    haritaSuz();
    if (!r) return;
    let pts = [];
    for (const s of r.iz || []) pts = pts.concat(s);
    pts = pts.concat(r.w || []);
    for (const k of r.kp || []) pts.push([k[0], k[1]], [k[2], k[3]]);
    const b = LI.sinirlar(pts);
    if (b) {
      const dar = innerWidth <= 860;
      harita.fitBounds(b, { padding: dar ? { top: 40, bottom: 120, left: 30, right: 30 } : { top: 70, bottom: 110, left: 60, right: 60 },
        maxZoom: 8, duration: LI.azHareket ? 0 : 700 });
    }
  }

  function etkilesim() {
    const m = harita;
    popup = new window.maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10, maxWidth: '260px' });
    const goster = (e, html) => { m.getCanvas().style.cursor = 'pointer'; popup.setLngLat(e.lngLat).setHTML(html).addTo(m); };
    const gizle = () => { m.getCanvas().style.cursor = ''; popup.remove(); };
    m.on('mousemove', 'vurgu', (e) => {
      const r = ID.get(e.features[0].properties.id);
      if (r) goster(e, `<b>${esc(r.n || '?')}</b>${esc(r.o)} → ${r.d ? esc(r.d) : 'varış kayıtsız'}<br>${LI.tarih(zaman(r))}`);
    });
    m.on('mouseleave', 'vurgu', gizle);
    m.on('click', 'vurgu', (e) => { const id = e.features[0].properties.id; durum.sec = id; detay(id); hashYaz(); });
    m.on('mousemove', 'canli', (e) => {
      const p = e.features[0].properties;
      goster(e, `<b>${esc(p.n)}</b>Takipte, ${esc(p.tip)}<br>Son konum: ${LI.tarih(p.t, true)}${p.vt ? `<br>Beyan edilen varış: ${esc(p.vt)}` : ''}`);
    });
    m.on('mouseleave', 'canli', gizle);
    m.on('click', 'canli', (e) => { const g = e.features[0].properties.g; if (g) location.href = `${KOK}gemiler/${g}.html`; });
    const OLAYAD = { gap: 'AIS sinyali kesildi', stop: 'Açık denizde uzun durdu', sts: 'Denizde iki gemi buluştu', draught: 'Limanda olmadan su çekimi değişti' };
    m.on('mousemove', 'olay', (e) => {
      const p = e.features[0].properties;
      goster(e, `<b>${esc(OLAYAD[p.k] || p.k)}</b>${esc(p.n)}${p.n2 ? ` ve ${esc(p.n2)}` : ''}<br>${LI.tarih(p.t0, true)}${p.s ? `, ${p.s} saat` : ''}`);
    });
    m.on('mouseleave', 'olay', gizle);
  }

  async function haritaKur() {
    const mesaj = $('#harita-mesaj');
    let ml;
    try {
      ml = await LI.maplibre(KOK);
    } catch (e) {
      mesaj.hidden = false;
      mesaj.textContent = 'Harita bu tarayıcıda açılamadı. Seferlerin listesi panelde duruyor.';
      return;
    }
    const stil = await LI.stil();
    const dar = innerWidth <= 860;
    try {
      harita = new ml.Map({ container: 'harita', style: stil, bounds: dar ? [[26, 30.5], [36.5, 41]] : [[23.5, 29.8], [37.5, 41.8]],
        fitBoundsOptions: { padding: dar ? 10 : { top: 40, bottom: 100, left: 20, right: 20 } }, attributionControl: false,
        dragRotate: false, pitchWithRotate: false, touchPitch: false, renderWorldCopies: false, fadeDuration: 0 });
    } catch (e) {
      mesaj.hidden = false;
      mesaj.textContent = 'Harita açılamadı: tarayıcın WebGL desteklemiyor olabilir. Seferlerin listesi panelde duruyor.';
      return;
    }
    harita.touchZoomRotate.disableRotation();
    harita.addControl(new ml.NavigationControl({ showCompass: false }), 'top-right');
    harita.addControl(new ml.AttributionControl({ compact: true, customAttribution: 'Veri: AIS (aisstream.io), Global Fishing Watch' }), 'bottom-right');
    if (stil.yedek) { mesaj.hidden = false; mesaj.textContent = 'Altlık harita yüklenemedi; seferler kıyı çizgisi olmadan gösteriliyor.'; }
    harita.on('load', async () => {
      await verilerHazir;
      katmanlariKur(stil.yedek);
      haritaHazir = true;
      etkilesim();
      haritaSuz();
      if (durum.sec && ID.get(durum.sec)) haritaSec(ID.get(durum.sec));
      harita.once('idle', () => { window.__haritaHazir = Math.round(performance.now()); });
    });
    document.addEventListener('tema', async () => {
      const yeni = await LI.stil();
      haritaHazir = false;
      harita.setStyle(yeni, { diff: false });
      harita.once('style.load', () => { katmanlariKur(yeni.yedek); haritaHazir = true; haritaSuz(); if (durum.sec) haritaSec(ID.get(durum.sec)); });
    });
  }

  /* ---------- açılış ---------- */
  hashOku();
  const kutuphaneHazir = LI.maplibre(KOK).catch(() => null);
  const verilerHazir = Promise.all([
    LI.json(`${KOK}veri/harita/seferler.json${S}`),
    LI.json(`${KOK}veri/harita/alanlar.json${S}`).catch(() => null),
    LI.json(`${KOK}veri/harita/canli.json${S}`).catch(() => null),
  ]).then(([v, a, c]) => {
    VERI = v; ALAN = a; CANLI = c;
    AILE = v.aileler;
    if (!durum.aile.size) durum.aile = new Set(AILE.map((f) => f.kod));
    KAYIT = v.kayitlar;
    for (const r of KAYIT) { r._ay = ay(zaman(r) || r.t0 || '2024-01-01'); ID.set(r.id, r); }
    uygula({ hashYok: true });
    if (durum.sec && ID.get(durum.sec)) detay(durum.sec);
  }).catch((e) => {
    $('#liste').innerHTML = `<p class="bos">Veriler yüklenemedi (${esc(e.message)}). Sayfayı yenile.</p>`;
  });
  kutuphaneHazir.then(() => haritaKur());

  /* ---------- denetimler ---------- */
  document.addEventListener('click', (e) => {
    const t = e.target.closest('button');
    if (!t) return;
    if (t.matches('.satir')) { durum.sec = t.dataset.id; detay(durum.sec); hashYaz(); }
    else if (t.id === 'geri') kapat();
    else if (t.id === 'daha') { durum.limit += 200; uygula(); }
    else if (t.matches('.sinif')) {
      const a = t.dataset.a;
      if (durum.aile.has(a)) { if (durum.aile.size > 1) durum.aile.delete(a); } else durum.aile.add(a);
      durum.limit = 80; uygula();
    } else if (t.matches('[data-y]')) {
      durum.y = t.dataset.y; durum.limit = 80;
      document.querySelectorAll('[data-y]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.y === durum.y)));
      uygula();
    } else if (t.matches('[data-k]')) {
      const k = t.dataset.k;
      if (durum.kaynak.has(k)) { if (durum.kaynak.size > 1) durum.kaynak.delete(k); } else durum.kaynak.add(k);
      document.querySelectorAll('[data-k]').forEach((b) => b.setAttribute('aria-pressed', String(durum.kaynak.has(b.dataset.k))));
      durum.limit = 80; uygula();
    } else if (t.id === 'oynat') oynat();
    else if (t.id === 'tumu') { if (oynatici) oynat(); durum.t = null; uygula(); }
    else if (t.id === 'kopyala') {
      const yaz = () => { t.textContent = 'Bağlantı kopyalandı'; setTimeout(() => { t.textContent = 'Bağlantıyı kopyala'; }, 2000); };
      if (navigator.clipboard) navigator.clipboard.writeText(location.href).then(yaz, () => prompt('Bağlantı:', location.href));
      else prompt('Bağlantı:', location.href);
    } else if (t.id === 'cekme') {
      const p = $('#panel');
      const acik = p.classList.toggle('acik');
      t.setAttribute('aria-expanded', String(acik));
    }
  });
  document.querySelectorAll('[data-y]').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.y === durum.y)));
  document.querySelectorAll('[data-k]').forEach((b) => b.setAttribute('aria-pressed', String(durum.kaynak.has(b.dataset.k))));
  const ara = $('#ara');
  ara.value = durum.q;
  let araZaman = null;
  ara.addEventListener('input', () => {
    clearTimeout(araZaman);
    araZaman = setTimeout(() => { durum.q = ara.value.trim(); durum.limit = 80; if (durum.sec) kapat(); else uygula(); }, 160);
  });
  document.querySelectorAll('.katmanlar input').forEach((inp) => {
    inp.checked = !!durum.katman[inp.name];
    inp.addEventListener('change', async () => {
      durum.katman[inp.name] = inp.checked;
      if ((inp.name === 'olay' || inp.name === 'sahte') && !OLAY) {
        OLAY = await LI.json(`${KOK}veri/harita/olaylar.json${S}`).catch(() => ({ olaylar: [], sahte: [] }));
        if (haritaHazir) { const o = olayOzellik(); harita.getSource('olay').setData(o.olay); harita.getSource('sahte').setData(o.sahte); }
      }
      if (!haritaHazir) return;
      const v = inp.checked ? 'visible' : 'none';
      if (inp.name === 'canli') { harita.setLayoutProperty('canli', 'visibility', v); harita.setLayoutProperty('canli-iz', 'visibility', v); }
      else harita.setLayoutProperty(inp.name, 'visibility', v);
    });
  });
  cizelgeEtkilesim();
  if (window.ResizeObserver) new ResizeObserver(() => cizelge()).observe($('#cizelge'));
  addEventListener('keydown', (e) => { if (e.key === 'Escape' && durum.sec) kapat(); });
})();
