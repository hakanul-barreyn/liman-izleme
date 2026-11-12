"""Statik web sitesi (GitHub Actions bunu GitHub Pages'e yükler).

Ana sayfa bir harita uygulamasıdır; veriyi veri/harita/*.json dosyalarından okur. Diğer sayfalar
sunucu tarafında üretilen hafif HTML'dir. Harita kütüphanesi (MapLibre) ve yazı tipi vendor/
klasörüne iş akışında indirilir; yoksa tarayıcı kütüphaneyi CDN'den yükler.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import shutil
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo

from . import harita, proof
from .db import get_meta
from .routes import CLASS_LABELS, vessel_keys
from .util import SHIP_GROUP_LABELS, hazard_category, iso, now_utc, parse_iso, ship_group

E = html.escape
WEB = Path(__file__).parent / "web"
ASSETS = ("stil.css", "ortak.js", "harita.js", "gemi.js")
AYLAR = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
NAV = [("index.html", "Harita", "harita"), ("beyan.html", "Beyan testi", "beyan"), ("gemiler/index.html", "Gemiler", "gemiler"),
       ("limanlar/index.html", "Limanlar", "limanlar"), ("gecmis.html", "Geçmiş tarama", "gecmis"),
       ("kanit.html", "Kanıt zinciri", "kanit"), ("yontem.html", "Yöntem", "yontem")]
TEMA = "<script>try{var t=localStorage.getItem('tema');if(t)document.documentElement.dataset.theme=t}catch(e){}</script>"
EVENT_LABELS = {"gap": "AIS sinyali kesildi", "stop": "Açık denizde uzun durdu", "sts": "Denizde başka bir gemiyle buluştu",
                "draught": "Limanda olmadan su çekimi değişti", "spoof": "Konum tutarsızlığı"}
OYNAT_SVG = '<svg viewBox="0 0 14 14" aria-hidden="true"><path d="M3 1.5v11l9-5.5z"/></svg>'


# --------------------------------------------------------------------------- yardımcılar
def _version() -> str:
    h = hashlib.sha256()
    for a in ASSETS:
        h.update((WEB / a).read_bytes())
    return h.hexdigest()[:10]


def _n(x) -> str:
    return f"{x:,}".replace(",", ".")


def _tarih(cfg, s, saat: bool = False) -> str:
    if not s:
        return "–"
    t = parse_iso(s).astimezone(ZoneInfo(cfg.tz))
    out = f"{t.day} {AYLAR[t.month - 1]} {t.year}"
    return f"{out}, {t:%H:%M}" if saat else out


def _ay(s: str) -> str:
    y, m = s[:7].split("-")
    return f"{AYLAR[int(m) - 1]} {y}"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _tbl(head: list[str], rows: list[list[str]], num: tuple = (), bos: str = "Henüz kayıt yok.") -> str:
    if not rows:
        return f'<p class="not">{E(bos)}</p>'
    th = "".join(f'<th{" class=sayi" if i in num else ""} scope="col">{E(h)}</th>' for i, h in enumerate(head))
    tr = "".join("<tr>" + "".join(f'<td{" class=sayi" if i in num else ""}>{c}</td>' for i, c in enumerate(r)) + "</tr>"
                 for r in rows)
    return f'<div class="tablo"><table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


def ham_url(day: str) -> str:
    """Ham veri GitHub Releases'ta tutuluyorsa onun adresi (LIMAN_HAM_URL içinde {gun} yer tutucusu)."""
    tpl = os.environ.get("LIMAN_HAM_URL")
    return tpl.format(gun=day) if tpl else f"arsiv/{day}/ham.jsonl.gz"


def _marka(cfg) -> tuple[str, str]:
    if ":" in cfg.name:
        a, b = cfg.name.split(":", 1)
        return a.strip(), b.strip()
    return cfg.name, ""


def _page(cfg, title: str, body: str, depth: int, active: str, *, app: bool = False, scripts=(), desc: str = "",
          head: str = "") -> str:
    r = "../" * depth
    v = cfg._surum
    nav = "".join(f'<a href="{r}{h}"{" aria-current=page" if k == active else ""}>{E(t)}</a>'
                  for h, t, k in NAV if (k != "gecmis" or cfg._has_gecmis) and (k != "beyan" or cfg.directions))
    ad, alt = _marka(cfg)
    kurgu = ('<div class="kurgu">Kurgusal deneme verisi: limanlar, ülkeler ve gemiler test için uydurulmuştur; '
             'gerçek bir olayı göstermez.</div>') if cfg.fictional else ""
    foot = "" if app else (
        f'<footer class="alt-bilgi">Veri: gemilerin yayınladığı AIS mesajları (<a href="https://aisstream.io">aisstream.io</a>). '
        f'Geçmiş tarama: <a href="https://globalfishingwatch.org">Powered by Global Fishing Watch.</a> '
        f'Harita: OpenFreeMap, OpenMapTiles, OpenStreetMap katkıcıları. Her günün kayıtları mühürlenir, bkz. '
        f'<a href="{r}kanit.html">Kanıt zinciri</a>. Sitedeki işaretler tespittir, hüküm değildir. '
        f'Son güncelleme: {E(_tarih(cfg, iso(now_utc()), True))}.</footer>')
    js = "".join(f'<script src="{r}assets/{s}?v={v}" defer></script>' for s in scripts)
    return (f'<!doctype html><html lang="tr"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">'
            f'<title>{E(title)} – {E(cfg.name)}</title><meta name="description" content="{E(desc or cfg.description)}">'
            f'<meta name="color-scheme" content="light dark">{TEMA}'
            f'<link rel="stylesheet" href="{r}assets/stil.css?v={v}">{head}</head>'
            f'<body class="{"uyg" if app else "icerik"}" data-tz="{E(cfg.tz)}"><a class="atla" href="#icerik">İçeriğe geç</a>'
            f'<header class="ust"><a class="marka" href="{r}index.html"><b>{E(ad)}</b>'
            f'{f"<span>{E(alt)}</span>" if alt else ""}</a><nav aria-label="Bölümler">{nav}</nav>'
            f'<button type="button" class="tema" id="tema">Gece</button></header>{kurgu}{body}{foot}'
            f'<script src="{r}assets/ortak.js?v={v}" defer></script>{js}</body></html>')


def _harita_head(r: str) -> str:
    return (f'<link rel="preload" href="{r}vendor/maplibre-gl.js" as="script">'
            f'<link rel="stylesheet" href="{r}vendor/maplibre-gl.css">'
            '<link rel="preconnect" href="https://tiles.openfreemap.org" crossorigin>')


def _draught(a, b) -> str:
    if a is None and b is None:
        return "–"
    s = f"{a if a is not None else '?'} → {b if b is not None else '?'} m"
    if a is not None and b is not None and abs(b - a) >= 0.5:
        s += f" ({'+' if b > a else ''}{round(b - a, 1)})"
    return s


def _isaret(cls: str) -> str:
    return f'<span class="isaret" style="--c:var(--c-{harita.FAMILY[cls]})">{E(harita.ALL_LABELS.get(cls, cls))}</span>'


# --------------------------------------------------------------------------- ana sayfa
def _manset(cfg, recs, y):
    a, b = y.split(">")
    sel = [r for r in recs if r["y"] == y]
    n = len(sel)
    dark = sum(1 for r in sel if r["a"] == "karanlik")
    ts = sorted(x for x in ((r.get("t1") or r.get("t0")) for r in sel) if x)
    head = f"{cfg.country_name(a)} limanlarından {cfg.country_name(b)} yönüne {_n(n)} sefer"
    if n:
        sub = f"{_tarih(cfg, ts[0])} ile {_tarih(cfg, ts[-1])} arasında, AIS kayıtlarına göre."
        if dark:
            sub += f" {_n(dark)} seferde gemi yolda sinyalini kapattı ya da varış limanı kayıtsız kaldı."
    else:
        sub = "Henüz sefer kaydı yok. Veri toplandıkça bu sayfa her saat güncellenir."
    return head, sub, sel


def _index(cfg, recs, meta) -> str:
    yonler = [f"{a}>{b}" for a, b in cfg.directions]
    y0 = yonler[0] if yonler else ""
    head, sub, sel = _manset(cfg, recs, y0) if y0 else (cfg.name, "Beyan testi kapalı; haritada takipteki gemiler görünür.", [])
    sayac = Counter(r["a"] for r in sel)
    aileler = "".join(
        f'<button type="button" class="sinif" data-a="{k}" aria-pressed="true" style="--c:var(--c-{k})">'
        f'<span class="cizgi"></span><b>{E(harita.FAMILY_LABELS[k])}</b><span class="sayi">{_n(sayac.get(k, 0))}</span>'
        f'<small>{E(harita.FAMILY_NOTES[k])}</small></button>' for k in harita.FAMILY_ORDER)
    yon_btn = "".join(f'<button type="button" data-y="{E(y)}" aria-pressed="{str(i == 0).lower()}">'
                      f'{E(cfg.country_name(y.split(">")[0]))} → {E(cfg.country_name(y.split(">")[1]))}</button>'
                      for i, y in enumerate(yonler))
    son = sorted(sel, key=lambda r: r.get("t1") or r.get("t0") or "", reverse=True)[:30]
    satirlar = "".join(
        f'<li><button type="button" class="satir" data-id="{r["id"]}" style="--c:var(--c-{r["a"]})">'
        f'<span class="serit{" g" if r["s"] == "g" else ""}"></span><b>{E(r.get("n") or "Adı bilinmiyor")}</b>'
        f'<time>{E(_tarih(cfg, r.get("t1") or r.get("t0")))}</time>'
        f'<span class="rota">{E(r.get("o") or "")} → {E(r.get("d") or "varış kayıtsız")}</span></button></li>' for r in son)
    hedef = json.loads(get_meta(cfg._con, "gecmis_hedef", "null") or "null")
    ts = sorted(x for x in ((r.get("t1") or r.get("t0")) for r in recs) if x)
    isaretler = [{"gun": str(a["gun"])[:10], "etiket": a["etiket"]}
                 for a in cfg.declaration.get("aciklamalar") or [] if a.get("gun") and a.get("etiket")]
    ayar = {"kok": "", "surum": cfg._surum, "yonler": yonler or [""], "isaretler": isaretler,
            "baslangic": (hedef or {}).get("baslangic") or (ts[0][:10] if ts else iso(now_utc())[:10])}
    kaynak = Counter(r["s"] for r in sel)
    body = f'''<main class="uygulama" id="icerik">
<aside class="panel" id="panel" aria-label="Seferler">
  <div class="panel-bas"><button type="button" class="cekme" id="cekme" aria-expanded="false" aria-controls="panel">
    <span class="gizli">Listeyi aç ya da kapat</span></button>
    <h1 class="manset" id="manset">{E(head)}</h1><p class="manset-alt" id="manset-alt">{E(sub)}</p></div>
  <div class="panel-govde">
    <div class="kontrol">
      {f'<div class="dugmeler" role="group" aria-label="Yön">{yon_btn}</div>' if len(yonler) > 1 else ""}
      <div class="siniflar" id="siniflar" role="group" aria-label="Sefer türleri">{aileler}</div>
      <div class="dugmeler" role="group" aria-label="Kaynak">
        <button type="button" data-k="c" aria-pressed="true">Canlı kayıt <span class="sayi">{_n(kaynak.get("c", 0))}</span></button>
        <button type="button" data-k="g" aria-pressed="true">Geçmiş tarama <span class="sayi">{_n(kaynak.get("g", 0))}</span></button></div>
      <label class="ara"><span class="gizli">Gemi ara</span><input type="search" id="ara" placeholder="Gemi adı, IMO ya da MMSI" autocomplete="off"></label>
      <div class="hat" id="hat" hidden></div>
    </div>
    <div id="liste"><ul class="liste">{satirlar}</ul></div>
    <div id="detay" hidden></div>
    <footer class="panel-alt">Renk sefer türünü, kavisli çizginin kalınlığı o hattaki sefer sayısını gösterir. Kavisli çizgi
    çıkış ve varış limanlarını bağlar, gerçek güzergâhı göstermez; ince düz çizgi bu sitenin kaydettiği gerçek AIS izidir.
    Yeşil daireler ara limanlardır, büyüklükleri oraya uğrayan sefer sayısıdır. Macenta noktalı çizgi AIS sinyalinin kesildiği
    aralıktır. Bir hatta ya da ara limana tıklarsan yalnızca oradan geçen seferler listelenir ve bütün bacakları çizilir.<br><br>
    Veri: AIS (aisstream.io). Geçmiş tarama: <a href="https://globalfishingwatch.org">Powered by Global Fishing Watch.</a>
    Harita: OpenFreeMap, OpenStreetMap. Son güncelleme: {E(_tarih(cfg, meta["olusturma"], True))}.
    <a href="kanit.html">Kanıt zinciri</a>, <a href="yontem.html">yöntem</a>.</footer>
  </div>
</aside>
<section class="harita" aria-label="Harita">
  <div id="harita"></div>
  <div class="katmanlar yuzer" role="group" aria-label="Katmanlar">
    <label><input type="checkbox" name="canli" checked> Takipteki gemiler</label>
    <label><input type="checkbox" name="olay"> Açık deniz olayları</label>
    <label><input type="checkbox" name="sahte"> Sahte konumlar</label></div>
  <div class="zaman yuzer"><button type="button" class="oynat" id="oynat" aria-label="Geçmişi oynat">{OYNAT_SVG}</button>
    <svg class="cizelge" id="cizelge" role="img" aria-label="Aylara göre sefer sayısı. Bir ayı seçmek için tıkla, aralık seçmek için sürükle."></svg>
    <button type="button" class="tumu" id="tumu">Tüm dönem</button></div>
  <div class="ipucu" id="ipucu" hidden></div>
  <div class="harita-mesaj yuzer" id="harita-mesaj" hidden></div>
</section>
</main>
<script id="ayar" type="application/json">{json.dumps(ayar, ensure_ascii=False)}</script>'''
    return _page(cfg, "Harita", body, 0, "harita", app=True, scripts=("harita.js",), head=_harita_head(""),
                 desc=f"{head}. {sub}")


# --------------------------------------------------------------------------- beyan
def _aylik(recs, y):
    sel = [r for r in recs if r["y"] == y]
    cnt = Counter(((r.get("t1") or r.get("t0") or "")[:7], r["a"]) for r in sel)
    months = sorted({m for m, _ in cnt if m}, reverse=True)
    rows = []
    for m in months:
        vals = [cnt.get((m, k), 0) for k in harita.FAMILY_ORDER]
        rows.append([E(_ay(m))] + [_n(v) if v else "–" for v in vals] + [f"<b>{_n(sum(vals))}</b>"])
    return rows


def _beyan(cfg, recs, live_routes, port_name) -> str:
    d = cfg.declaration
    b = ['<main class="sayfa" id="icerik"><header><h1>Beyan testi</h1><p class="giris">Resmî açıklamalar ve AIS kayıtlarına '
         'göre gerçekleşen gemi hareketleri yan yana. Sayılar gemi hareketidir; yükün kendisi yalnızca dayanaklarıyla '
         'birlikte “muhtemel” olarak verilir.</p></header>']
    if d.get("metin"):
        b.append(f'<blockquote class="alinti"><p>{E(d["metin"])}</p><footer>{E(d.get("tarih") or "")} {E(d.get("kaynak") or "")}</footer></blockquote>')
    for a in d.get("aciklamalar") or []:
        src = E(a.get("kaynak") or "kaynak")
        if a.get("url"):
            src = f'<a href="{E(a["url"])}" rel="noopener">{src}</a>'
        b.append(f'<blockquote class="alinti"><p>“{E(a.get("metin", ""))}”</p><footer>{E(a.get("kim") or "")}, '
                 f'{E(a.get("tarih") or "")}. Kaynak: {src}</footer></blockquote>')
    if d.get("karsi_gorus"):
        b.append(f'<h2>Resmî yanıtlar ve karşı görüş</h2><p>{E(d["karsi_gorus"])}</p>')
    head = ["Ay"] + [harita.FAMILY_LABELS[k] for k in harita.FAMILY_ORDER] + ["Toplam"]
    for (A, B) in cfg.directions:
        y = f"{A}>{B}"
        b.append(f'<h2>{E(cfg.country_name(A))} → {E(cfg.country_name(B))}</h2>'
                 f'<p class="not">Canlı kayıt ve geçmiş tarama birlikte. Ayrıntılar ve uydu bağlantıları için '
                 f'<a href="index.html#y={E(y)}">haritada aç</a>.</p>')
        b.append(_tbl(head, _aylik(recs, y), num=(1, 2, 3, 4, 5)))
        rows = []
        for r in [x for x in live_routes if x["direction"] == y][:60]:
            rows.append([f'<a href="gemiler/{E(r["vkey"])}.html">{E(r["name"])}</a>',
                         f'{E(port_name.get(r["origin_port"], r["origin_port"]))}<br><span class="not">{E(_tarih(cfg, r["t_dep"]))}</span>',
                         (f'{E(port_name.get(r["dest_port"], r["dest_port"]))}<br><span class="not">{E(_tarih(cfg, r["t_arr"]))}</span>'
                          if r["dest_port"] else '<span class="uyari">Kayıtsız</span>'),
                         _isaret(r["cls"]), f'<a href="index.html#sec=c{r["id"]}">Haritada</a>'])
        b.append("<h3>Canlı kayıttaki son seferler</h3>" + _tbl(["Gemi", "Çıkış", "Varış", "Tür", ""], rows,
                                                                 bos="Canlı kayıtta henüz sefer yok."))
    b.append("</main>")
    return _page(cfg, "Beyan testi", "".join(b), 0, "beyan")


# --------------------------------------------------------------------------- gemiler
def _gemi(cfg, con, key, mmsis, vessels, tracking, port_name, names) -> str:
    main = max(mmsis, key=lambda m: (vessels.get(m) or {}).get("last_seen") or "")
    vs = vessels.get(main) or {}
    q = ",".join("?" * len(mmsis))
    tr = next((tracking[m] for m in mmsis if m in tracking), None)
    group = ship_group(vs.get("type"))
    hz = hazard_category(vs.get("type"))
    routes = [dict(r) for r in con.execute(
        f"SELECT * FROM routes WHERE mmsi IN ({q}) OR via_mmsi IN ({q}) ORDER BY t_dep DESC", (*mmsis, *mmsis))]
    visits = [dict(v) for v in con.execute(
        f"SELECT * FROM visits WHERE mmsi IN ({q}) AND (transit IS NOT 1 OR status='open') ORDER BY t_in DESC LIMIT 300", mmsis)]
    evs = [dict(e) for e in con.execute(
        f"SELECT * FROM events WHERE (mmsi IN ({q}) OR mmsi2 IN ({q})) AND kind != 'spoof' ORDER BY t_start DESC LIMIT 300",
        (*mmsis, *mmsis))]
    spoofs = con.execute(f"SELECT count(*) FROM events WHERE mmsi IN ({q}) AND kind='spoof'", mmsis).fetchone()[0]
    hist = json.loads(vs.get("history") or "[]")
    ad = vs.get("name") or f"MMSI {main}"
    takip = "–"
    if tr:
        takip = (f"{'Takipte' if tr['status'] == 'active' else 'Takip bitti'}, {_tarih(cfg, tr['start'])} – "
                 f"{_tarih(cfg, tr['ended'] or tr['until'])}" + (f" ({tr['end_reason']})" if tr.get("end_reason") else ""))
    kim = [("IMO", vs.get("imo") or "–"), ("MMSI", ", ".join(map(str, mmsis))), ("Çağrı işareti", vs.get("callsign") or "–"),
           ("Tip", SHIP_GROUP_LABELS[group] + (f", tehlikeli yük kat. {hz}" if hz else "")),
           ("Boy", f"{vs['length']:.0f} m" if vs.get("length") else "–"),
           ("Son beyan edilen varış", vs.get("dest") or "–"), ("Takip", takip)]
    b = [f'<main class="sayfa" id="icerik"><header><h1>{E(ad)}</h1><p class="giris">{E(SHIP_GROUP_LABELS[group])}. '
         f'{_n(len(routes))} sefer kaydı, {_n(len(visits))} liman ziyareti, {_n(len(evs))} açık deniz olayı.'
         f'{f" {_n(spoofs)} konum tutarsızlığı (olası GPS karıştırma) analizden çıkarıldı." if spoofs else ""}</p></header>',
         '<dl class="kimlik-tablo">' + "".join(
             f'<div{" class=genis" if k == "Takip" else ""}><dt>{E(k)}</dt><dd>{E(str(v))}</dd></div>' for k, v in kim) + "</dl>",
         f'<h2>Geçmiş</h2><div class="mini-harita" id="gemi-harita" data-kok="../" data-anahtar="{E(key)}" data-surum="{cfg._surum}">'
         '<div class="harita-ic"></div></div><div class="oynatici"><button type="button" class="eylem" id="gemi-oynat">Oynat</button>'
         '<input type="range" id="kaydir" aria-label="Zaman"><output id="an" for="kaydir"></output></div>'
         '<p class="not">Kalın çizgi seçili ana kadar geçilen yolu, ince çizgi bütün izi gösterir. Macenta kesik çizgi AIS '
         'sinyalinin kesildiği aralıktır. Daireler uğradığı limanlardır.</p>']
    if routes:
        rows = [[f'{E(port_name.get(r["origin_port"], r["origin_port"]))}<br><span class="not">{E(_tarih(cfg, r["t_dep"]))}</span>',
                 (f'{E(port_name.get(r["dest_port"], r["dest_port"]))}<br><span class="not">{E(_tarih(cfg, r["t_arr"]))}</span>'
                  if r["dest_port"] else '<span class="uyari">Kayıtsız</span>'),
                 _isaret(r["cls"]) + (f'<br><span class="not">Yükü veren: {E(r["via_name"])}</span>'
                                       if r["via_mmsi"] and r["mmsi"] in mmsis else ""),
                 f'{E(r["cargo"] or "–")}<br><span class="not">güven: {E(r["cargo_conf"] or "–")}</span>',
                 f'<a href="../index.html#sec=c{r["id"]}">Haritada</a>'] for r in routes]
        b.append("<h2>Seferler</h2>" + _tbl(["Çıkış", "Varış", "Tür", "Muhtemel yük", ""], rows))
    b.append("<h2>Liman ziyaretleri</h2>" + _tbl(["Liman", "Giriş", "Çıkış", "Terminal", "Su çekimi", "Beyan edilen varış"], [
        [E(port_name.get(v["port"], v["port"])), E(_tarih(cfg, v["t_in"], True)),
         E(_tarih(cfg, v["t_out"], True)) if v["t_out"] else "Limanda", E(v["terminal"] or "–"),
         E(_draught(v["draught_in"], v["draught_out"])), E(v["dest_out"] or "–")] for v in visits]))
    if evs:
        rows = []
        for e in evs:
            d = json.loads(e["detail"] or "{}")
            other = e["mmsi2"] if e["mmsi"] in mmsis else e["mmsi"]
            extra = f", {names.get(other) or other} ile" if e["kind"] == "sts" else ""
            rows.append([f'<span class="{"uyari" if e["kind"] == "gap" else ""}">{E(EVENT_LABELS.get(e["kind"], e["kind"]))}</span>',
                         E(_tarih(cfg, e["t_start"], True)), E(_tarih(cfg, e["t_end"], True)),
                         E(f'{d.get("saat", "–")} saat{extra}')])
        b.append("<h2>Açık deniz olayları</h2>" + _tbl(["Olay", "Başlangıç", "Bitiş", "Ayrıntı"], rows))
    if hist:
        b.append("<h2>Kimlik değişiklikleri</h2>" + _tbl(["Zaman", "Alan", "Eski", "Yeni"], [
            [E(_tarih(cfg, h["t"], True)), E(h["alan"]), E(str(h["eski"])), E(str(h["yeni"]))] for h in hist]))
    b.append("</main>")
    return _page(cfg, ad, "".join(b), 1, "gemiler", scripts=("gemi.js",), head=_harita_head("../"),
                 desc=f"{ad}: AIS izi, liman ziyaretleri ve seferleri.")


def _gemiler(cfg, con, keys, vessels, tracking) -> str:
    counts = Counter()
    for r in con.execute("SELECT vkey, via_vkey FROM routes"):
        counts[r["vkey"]] += 1
        if r["via_vkey"]:
            counts[r["via_vkey"]] += 1
    rows = []
    for key, mmsis in keys.items():
        main = max(mmsis, key=lambda m: (vessels.get(m) or {}).get("last_seen") or "")
        vs = vessels.get(main) or {}
        tr = next((tracking[m] for m in mmsis if m in tracking), None)
        active = bool(tr and tr["status"] == "active")
        rows.append((active, vs.get("last_seen") or "", [
            f'<a href="{E(key)}.html">{E(vs.get("name") or "MMSI " + str(main))}</a>', E(str(vs.get("imo") or "–")),
            E(", ".join(map(str, mmsis))), E(SHIP_GROUP_LABELS[ship_group(vs.get("type"))]),
            _n(counts.get(key, 0)) if counts.get(key) else "–", "Takipte" if active else "–",
            E(_tarih(cfg, vs.get("last_seen")))]))
    rows.sort(key=lambda x: (x[0], x[1]), reverse=True)
    body = ('<main class="sayfa" id="icerik"><header><h1>Gemiler</h1><p class="giris">Takip edilen, bir sefere ya da açık '
            'deniz olayına karışan gemiler. Gemiler IMO numarasıyla tanınır; adı veya MMSI numarası değişse de aynı sayfada '
            'kalır.</p></header><p><label class="ara"><span class="gizli">Gemi ara</span><input type="search" id="gemi-ara" '
            'placeholder="Gemi adı, IMO ya da MMSI" autocomplete="off"></label></p>'
            + _tbl(["Gemi", "IMO", "MMSI", "Tip", "Sefer", "Durum", "Son görülme"], [r[2] for r in rows], num=(4,),
                   bos="Henüz takip edilen gemi yok.")
            + '<script>document.getElementById("gemi-ara").addEventListener("input",function(){var q=this.value.toLocaleLowerCase("tr");'
              'document.querySelectorAll("tbody tr").forEach(function(r){r.hidden=q&&r.textContent.toLocaleLowerCase("tr").indexOf(q)<0})})'
              '</script></main>')
    return _page(cfg, "Gemiler", body, 1, "gemiler")


# --------------------------------------------------------------------------- limanlar
def _limanlar(cfg, con, days, keys) -> None:
    out = cfg.site_dir
    counts = Counter(r[0] for r in con.execute("SELECT port FROM visits WHERE transit IS NOT 1"))

    def map_day(code):
        for d in days:
            if (out / "arsiv" / d / f"{code}.png").exists():
                return d
        return None

    figs = []
    for p in cfg.ports:
        if p.role != "izlenen":
            continue
        md = map_day(p.code)
        img = (f'<img src="../arsiv/{md}/{p.code}.png" alt="{E(p.name)} limanındaki gemi izleri, {E(md)}" loading="lazy" '
               f'width="880" height="660">' if md else "")
        figs.append(f'<figure><a href="{p.code}.html">{img}</a><figcaption><a href="{p.code}.html"><b>{E(p.name)}</b></a>'
                    f'<span>{_n(counts.get(p.code, 0))} ziyaret{f", son harita {E(_tarih(cfg, md + "T12:00:00Z"))}" if md else ""}</span>'
                    '</figcaption></figure>')
    rol = {"izlenen": "İzlenen: uğrayan her gemi takibe alınır", "varis": "Varış kontrolü"}
    rows = [[f'<a href="{p.code}.html">{E(p.name)}</a>', E(cfg.country_name(p.country)),
             E("Kıyı yaklaşma alanı" if p.approach else rol.get(p.role, p.role)), _n(counts.get(p.code, 0))] for p in cfg.ports]
    body = ('<main class="sayfa" id="icerik"><header><h1>Limanlar</h1><p class="giris">İzlenen limanlara uğrayan her gemi '
            'takibe alınır. Diğer limanlar ve kıyı alanı, takipteki gemilerin nereye vardığını kaydetmek için dinlenir.'
            '</p></header>' + (f'<div class="limanlar">{"".join(figs)}</div>' if figs else "")
            + "<h2>Bütün alanlar</h2>" + _tbl(["Liman", "Ülke", "Rol", "Ziyaret"], rows, num=(3,)) + "</main>")
    _write(out / "limanlar" / "index.html", _page(cfg, "Limanlar", body, 1, "limanlar"))
    names = {r["mmsi"]: r["name"] for r in con.execute("SELECT mmsi, name FROM vessels")}
    m2k, _ = vessel_keys(con)
    for p in cfg.ports:
        md = map_day(p.code)
        vis = [dict(v) for v in con.execute(
            "SELECT * FROM visits WHERE port=? AND (transit IS NOT 1 OR status='open') ORDER BY t_in DESC LIMIT 200", (p.code,))]
        vrows = []
        for v in vis:
            k = m2k.get(v["mmsi"], f"mmsi{v['mmsi']}")
            label = E(names.get(v["mmsi"]) or f"MMSI {v['mmsi']}")
            vrows.append([f'<a href="../gemiler/{E(k)}.html">{label}</a>' if k in keys else label,
                          E(_tarih(cfg, v["t_in"], True)), E(_tarih(cfg, v["t_out"], True)) if v["t_out"] else "Limanda",
                          E(v["terminal"] or "–"), E(_draught(v["draught_in"], v["draught_out"])), E(v["dest_out"] or "–")])
        arch = [[E(d), f'<a href="../arsiv/{d}/{p.code}.csv">CSV</a>, <a href="../arsiv/{d}/{p.code}.json">JSON</a>'
                 + (f', <a href="../arsiv/{d}/{p.code}.png">harita</a>' if (out / "arsiv" / d / f"{p.code}.png").exists() else "")]
                for d in days[:120]]
        terms = ", ".join(t.name for t in p.terminals) or "tanımlı değil"
        img = (f'<p><img src="../arsiv/{md}/{p.code}.png" alt="{E(p.name)} limanındaki gemi izleri, {E(md)}" width="880" '
               f'height="660" style="max-width:100%;height:auto;border:1px solid var(--rule);border-radius:8px"></p>') if md else ""
        body = (f'<main class="sayfa" id="icerik"><header><h1>{E(p.name)}</h1><p class="giris">{E(cfg.country_name(p.country))}. '
                f'{E("Kıyı yaklaşma alanı" if p.approach else rol.get(p.role, p.role))}. Terminaller: {E(terms)}.</p></header>'
                f'{img}<h2>Son ziyaretler</h2>'
                + _tbl(["Gemi", "Giriş", "Çıkış", "Terminal", "Su çekimi", "Beyan edilen varış"], vrows)
                + "<h2>Günlük arşiv</h2>" + _tbl(["Gün", "Dosyalar"], arch, bos="Henüz arşivlenmiş gün yok.") + "</main>")
        _write(out / "limanlar" / f"{p.code}.html", _page(cfg, p.name, body, 1, "limanlar"))


# --------------------------------------------------------------------------- geçmiş, kanıt, yöntem
def _gecmis(cfg, recs, st) -> str:
    t = st.get("hedef") or {}
    done, total = st.get("gorev") or [0, 0]
    pct = int(100 * done / total) if total else 0
    prog = ("Tarama tamamlandı." if st.get("tamam") else
            f"Tarama sürüyor: {_n(done)} / {_n(total)} sorgu tamamlandı. Her saatlik çalıştırmada kaldığı yerden devam eder.")
    retro = [r for r in recs if r["s"] == "g"]
    bas = _tarih(cfg, t["baslangic"] + "T12:00:00Z") if t.get("baslangic") else "?"
    bit = _tarih(cfg, t["bitis"] + "T12:00:00Z") if t.get("bitis") else "?"
    b = [f'<main class="sayfa" id="icerik"><header><h1>Geçmiş tarama</h1><p class="giris">{E(bas)} ile {E(bit)} arası. '
         'Global Fishing Watch’ın AIS verisinden ürettiği liman ziyaretleri ve AIS boşlukları üzerinden yapılır.</p></header>',
         f'<p>{E(prog)}</p><div class="ilerleme" role="progressbar" aria-valuenow="{pct}" aria-valuemin="0" aria-valuemax="100">'
         f'<i style="width:{pct}%"></i></div>',
         '<p class="not"><a href="https://globalfishingwatch.org">Powered by Global Fishing Watch.</a> Veri lisansı CC BY-NC 4.0, '
         'ticari olmayan kullanım. Bu kayıtlar GFW’nin hesapladığı olaylara dayanır ve bu sitenin kanıt zincirinde ham verisi '
         'yoktur; her kaydın uydu bağlantılarıyla elle doğrulanması önerilir.</p>',
         '<p class="eylemler"><a class="eylem ana" href="index.html#k=g">Geçmiş taramayı haritada gör</a>'
         '<a class="eylem" href="veri/gecmis.json">Bütün kayıtlar (JSON)</a></p>']
    head = ["Ay"] + [harita.FAMILY_LABELS[k] for k in harita.FAMILY_ORDER] + ["Toplam"]
    for (A, B) in cfg.directions:
        b.append(f"<h2>{E(cfg.country_name(A))} → {E(cfg.country_name(B))}</h2>"
                 + _tbl(head, _aylik(retro, f"{A}>{B}"), num=(1, 2, 3, 4, 5), bos="Henüz kayıt yok."))
    b.append("</main>")
    return _page(cfg, "Geçmiş tarama", "".join(b), 0, "gecmis")


def _kanit(cfg, chain) -> str:
    rows = [[E(c["gun"]), f'<span class="kod">{c["gun_hash"]}</span>', f'<span class="kod">{c["kayit_hash"][:16]}…</span>',
             "var" if c.get("opentimestamps") else "yok",
             f'<a href="arsiv/{c["gun"]}/MANIFEST.sha256">manifest</a>, <a href="arsiv/{c["gun"]}/ozet.json">özet</a>, '
             f'<a href="arsiv/{c["gun"]}/izler.json">izler</a>, <a href="{ham_url(c["gun"])}">ham veri</a>'
             + (f', <a href="arsiv/{c["gun"]}/MANIFEST.sha256.ots">damga</a>' if c.get("opentimestamps") else "")]
            for c in reversed(chain)]
    body = ('<main class="sayfa" id="icerik"><header><h1>Kanıt zinciri</h1><p class="giris">Her gün bittiğinde o günün bütün '
            'dosyaları (ham AIS mesajları, ziyaret listeleri, gemi izleri, haritalar, olaylar) tek tek SHA-256 ile özetlenir. '
            'Bu listenin özeti “gün hash’i”dir. Her gün bir önceki günün kaydına bağlanır; geçmişteki tek bir bayt değişirse '
            'zincir kırılır. Gün hash’i ayrıca Bitcoin blok zincirine damgalanır (OpenTimestamps).</p></header>'
            '<h2>Bir günü kendin doğrula</h2><ol class="adim-liste">'
            '<li>Günün klasöründeki dosyaları, <code>MANIFEST.sha256</code> dosyasını ve “ham veri” bağlantısındaki '
            '<code>ham.jsonl.gz</code> dosyasını aynı klasöre indir.</li>'
            '<li>Klasörde <code>sha256sum -c MANIFEST.sha256</code> çalıştır; her satır OK olmalı.</li>'
            '<li><code>sha256sum MANIFEST.sha256</code> sonucu aşağıdaki gün hash’iyle aynı olmalı.</li>'
            '<li>Damga varsa <code>ots verify MANIFEST.sha256.ots</code> ile Bitcoin kaydını kontrol et.</li></ol>'
            '<p>Zincirin tamamı: <a href="kanit/zincir.jsonl">zincir.jsonl</a></p>'
            + _tbl(["Gün", "Gün hash’i (SHA-256)", "Zincir kaydı", "Bitcoin damgası", "Dosyalar"], rows,
                   bos="Henüz arşivlenmiş gün yok. İlk gün, gece yarısından sonraki ilk çalıştırmada mühürlenir.")
            + "</main>")
    return _page(cfg, "Kanıt zinciri", body, 0, "kanit")


def _yontem(cfg) -> str:
    th = cfg.th
    body = f'''<main class="sayfa" id="icerik"><header><h1>Yöntem ve sınırlar</h1><p class="giris">Bu site gemilerin kendi
yayınladığı AIS mesajlarını toplar, liman ziyaretlerini ve açık denizdeki davranışları kurala dayalı olarak sınıflandırır.
Kurallar aşağıda; aynı veriden herkes aynı sonuca ulaşabilir.</p></header>
<h2>Veri</h2><p>AIS mesajları <a href="https://aisstream.io">aisstream.io</a> üzerinden toplanır. Kaydedilen her mesaj
değiştirilmeden günlük ham dosyaya yazılır; aynı geminin çok sık tekrarlanan konumları seyreltilir. Limanların çevresindeki
bütün gemiler ve takipteki gemiler dünyanın her yerinde dinlenir. Toplayıcının veri alamadığı süreler kesinti olarak kaydedilir.</p>
<h2>Ziyaret ve takip</h2><p>Bir gemi liman alanına girip en az {th["ziyaret_min_dakika"]} dakika kalır ve bu sürede en az bir kez
durursa ziyaret sayılır. İzlenen limana uğrayan her gemi {th["takip_gun"]} gün boyunca ya da hedef ülkeye varana kadar izlenir.
Denizde takipli bir gemiyle buluşan gemi de takibe alınır.</p>
<h2>Sefer türleri</h2><p>Haritadaki renkler dört aileyi gösterir:</p><ul>
<li><span class="isaret" style="--c:var(--c-dogrudan)"><b>Doğrudan</b></span>: çıkış limanından arada başka limana uğramadan varış.</li>
<li><span class="isaret" style="--c:var(--c-liman)"><b>Ara limanlı</b></span>: arada üçüncü bir ülkenin limanına ya da açık denizde uzun durağa uğradı.</li>
<li><span class="isaret" style="--c:var(--c-sts)"><b>Gemiden gemiye</b></span>: yolda başka bir gemiyle {th["sts_mesafe_m"]} m’den yakın ve
duruk hâlde en az {th["sts_sure_saat"]} saat kaldı; ya da çıkış limanından gelen gemi yükünü denizde başka bir gemiye verdi ve o gemi varış ülkesine gitti.</li>
<li><span class="isaret" style="--c:var(--c-karanlik)"><b>AIS kapatılmış</b></span>: yolda en az {th["ais_bosluk_saat"]} saat sinyal yok
(karanlık bacak); hedef ülkenin kıyı alanına girip hiçbir limana uğramadan en az {th["yaklasma_sessizlik_saat"]} saat sinyal vermedi
(kıyıda kayboldu); ya da varış ülkesinde hiç kaydı yok ama izlenen deniz bölgesinde en az {th["karanlik_sefer_saat"]} saat AIS boşluğu
var (karanlık sefer).</li></ul>
<p>Haritada düz çizgi bu sitenin kaydettiği gerçek AIS izidir. Kesik çizgi geçmiş taramadaki limanlar arası bağlantıdır; gerçek
güzergâhı göstermez. Macenta noktalı çizgi AIS sinyalinin kesildiği aralıktır; boş macenta daire sinyalin kesildiği, dolu daire
yeniden geldiği yerdir.</p>
<h2>Konum tutarsızlıkları</h2><p>Geminin konumu bir önceki kayda göre fiziksel olarak imkânsız bir hızla (60 knot üstü) sıçrarsa
bu konum GPS karıştırma ya da sahte konum sayılır: ham arşive yazılır ama analizde kullanılmaz.</p>
<h2>Muhtemel yük</h2><p>Gemi tipi, yanaştığı terminal ve limanlardaki su çekimi değişiminden çıkarılır; dayanakları her
seferde listelenir. Üç ya da daha fazla dayanak uyuşuyorsa güven “yüksek”, iki ise “orta”, biri ise “düşük”tür. Su çekimini
mürettebat elle girer ve güncellenmeyebilir. Konteyner gemilerinin içeriği bu yöntemle bilinemez.</p>
<h2>Uydu görüntüleri</h2><p>Şüpheli seferlerde hedef ülke limanlarının o tarihlerdeki Sentinel-1 (radar) ve Sentinel-2 (optik)
görüntülerine bağlantı verilir. Uydular bir noktadan genellikle birkaç günde bir geçer; her tarih için görüntü olmayabilir.
Görüntülerin incelenmesi elle yapılmalıdır.</p>
<h2>Sınırlar</h2><ul><li>AIS’i tamamen kapalı olan ya da sahte konum yayınlayan gemiler görülmez; açık denizde alıcı kapsaması zayıf olabilir.</li>
<li>Kayıtlar gemi hareketini gösterir; yükün sahibini, satıcısını ya da ticaretin hukuki durumunu göstermez.</li>
<li>Bu sitedeki işaretler tespittir, hüküm değildir.</li></ul></main>'''
    return _page(cfg, "Yöntem", body, 0, "yontem")


def _share_drafts(cfg, routes, chain, port_name) -> list[dict]:
    """Paylaşım için hazır metinler (otomatik gönderilmez)."""
    out = []
    if chain:
        c = chain[-1]
        out.append({"tur": "gunluk_ozet", "gun": c["gun"],
                    "metin": f"{cfg.name}: {c['gun']} arşivi mühürlendi.\nGün hash'i: {c['gun_hash'][:16]}…"})
    for r in routes[:20]:
        out.append({"tur": "beyan_hareketi", "id": r["id"], "metin": (
            f"{r['name']}: {port_name.get(r['origin_port'])} ({_tarih(cfg, r['t_dep'])}) → "
            f"{port_name.get(r['dest_port']) or 'varış limanı kayıtsız (AIS kapalı)'} ({_tarih(cfg, r['t_arr'])})\n"
            f"Tür: {CLASS_LABELS[r['cls']]}\nMuhtemel yük: {r['cargo']} (güven: {r['cargo_conf']})\n"
            "Bu bir tespittir, hüküm değildir.")})
    return out


# --------------------------------------------------------------------------- hepsi
def build(cfg, con) -> None:
    out = cfg.site_dir
    out.mkdir(parents=True, exist_ok=True)
    cfg._surum = _version()
    cfg._con = con
    gecmis_state = json.loads(get_meta(con, "gecmis_durum", "{}") or "{}")
    cfg._has_gecmis = bool(gecmis_state) or con.execute("SELECT 1 FROM gecmis LIMIT 1").fetchone() is not None
    assets = out / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    for a in ASSETS:
        shutil.copyfile(WEB / a, assets / a)
    (out / "_headers").unlink(missing_ok=True)

    recs = harita.voyages(cfg, con)
    meta = {"olusturma": iso(now_utc())}
    harita.build(cfg, con, out, recs=recs)
    port_name = {p.code: p.name for p in cfg.ports}
    days = sorted([r["day"] for r in con.execute("SELECT day FROM archived_days")], reverse=True)
    chain = proof.read_chain(cfg)
    live_routes = [dict(r) for r in con.execute("SELECT * FROM routes ORDER BY t_arr DESC")]

    _write(out / "index.html", _index(cfg, recs, meta))
    if cfg.directions:
        _write(out / "beyan.html", _beyan(cfg, recs, live_routes, port_name))
    else:
        (out / "beyan.html").unlink(missing_ok=True)
    vessels = {r["mmsi"]: dict(r) for r in con.execute("SELECT * FROM vessels")}
    names = {m: v.get("name") for m, v in vessels.items()}
    tracking = {r["mmsi"]: dict(r) for r in con.execute("SELECT * FROM tracking")}
    keys = harita.relevant_keys(con)
    gdir = out / "gemiler"
    if gdir.exists():
        for f in gdir.glob("*.html"):
            if f.stem != "index" and f.stem not in keys:
                f.unlink()
    for key, mmsis in keys.items():
        _write(gdir / f"{key}.html", _gemi(cfg, con, key, mmsis, vessels, tracking, port_name, names))
    _write(gdir / "index.html", _gemiler(cfg, con, keys, vessels, tracking))
    _limanlar(cfg, con, days, keys)
    if cfg._has_gecmis:
        _write(out / "gecmis.html", _gecmis(cfg, recs, gecmis_state))
        _write(out / "veri" / "gecmis.json", json.dumps(
            [dict(r) for r in con.execute("SELECT * FROM gecmis ORDER BY t_arr DESC")], ensure_ascii=False))
    _write(out / "kanit.html", _kanit(cfg, chain))
    _write(out / "yontem.html", _yontem(cfg))
    _write(out / "veri" / "guzergahlar.json", json.dumps(live_routes, ensure_ascii=False))
    _write(out / "veri" / "olaylar.json", json.dumps(
        [dict(e) for e in con.execute("SELECT * FROM events WHERE kind != 'spoof' ORDER BY t_start DESC")], ensure_ascii=False))
    _write(out / "veri" / "paylasim_taslaklari.json", json.dumps(
        _share_drafts(cfg, live_routes, chain, port_name), ensure_ascii=False, indent=1))
