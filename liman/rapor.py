"""Raporlar: hedef ülkeye giden gemilerin gemi gemi listesi, aylık raporlar ve CSV dosyaları.

raporlar/index.html             ilk yön (ör. Türkiye → İsrail): bütün gemiler ve her birinin seferleri
raporlar/<yön>.html             diğer yönler (ör. il-tr.html)
raporlar/<yön>-<YYYY-AA>.html   aylık rapor: o ay varan seferler, gemi gemi
raporlar/<yön>-gemiler.csv      gemi listesi
raporlar/<yön>-seferler.csv     bütün seferler
"""
from __future__ import annotations

import csv
import io
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote
from zoneinfo import ZoneInfo

from . import harita
from .ulkeler import bayrak
from .util import parse_iso

KISA_AY = ["Oca", "Şub", "Mar", "Nis", "May", "Haz", "Tem", "Ağu", "Eyl", "Eki", "Kas", "Ara"]


def slug(y: str) -> str:
    return y.replace(">", "-").lower()


def sayfa(directions: list[str], y: str) -> str:
    return "index.html" if y == directions[0] else f"{slug(y)}.html"


def _zaman(r: dict) -> str:
    return r.get("t1") or r.get("t0") or ""


def _yerel(cfg, s: str):
    return parse_iso(s).astimezone(ZoneInfo(cfg.tz))


def _kisa(cfg, s: str | None, yil: bool = True) -> str:
    if not s:
        return "?"
    t = _yerel(cfg, s)
    return f"{t.day} {KISA_AY[t.month - 1]}" + (f" {t.year}" if yil else "")


def _aralik(cfg, a: str | None, b: str | None) -> str:
    if not a or not b:
        return _kisa(cfg, a or b)
    ta, tb = _yerel(cfg, a), _yerel(cfg, b)
    return f"{_kisa(cfg, a, ta.year != tb.year)} – {_kisa(cfg, b)}"


def _rota(r: dict) -> str:
    return " → ".join([r.get("o") or "?", *(r.get("ara") or []), r.get("d") or "varış kayıtsız"])


def ships(recs: list[dict], y: str, vessels: dict, m2k: dict, pages: set[str], bilgi=None) -> list[dict]:
    """Bir yöndeki seferleri gemi gemi toplar (gemi = MMSI; yoksa ad)."""
    by: dict = defaultdict(list)
    for r in recs:
        if r["y"] == y:
            by[r.get("m") or f"ad:{r.get('n')}"].append(r)
    out = []
    for key, rs in by.items():
        rs.sort(key=_zaman, reverse=True)
        mmsi = key if isinstance(key, int) else None
        v = vessels.get(mmsi) or {}
        imo = next((r["imo"] for r in rs if r.get("imo")), None) or v.get("imo")
        flag = next((r["b"] for r in rs if r.get("b")), None)
        page = next((r["g"] for r in rs if r.get("g")), None) or (m2k.get(mmsi) if mmsi else None)
        hat = Counter((r.get("o") or "?", r.get("d") or "varış kayıtsız") for r in rs)
        ek = bilgi(mmsi, imo) if bilgi else {}
        imo = imo or ek.get("imo")
        out.append({**ek,
            "ad": rs[0].get("n") or (f"MMSI {mmsi}" if mmsi else "Adı bilinmiyor"),
            "adlar": sorted({r.get("n") for r in rs if r.get("n")} - {rs[0].get("n")}),
            "mmsi": mmsi, "imo": imo, "bayrak": bayrak(flag, mmsi), "flag3": flag,
            "sayfa": page if page in pages else None,
            "n": len(rs), "aile": Counter(r["a"] for r in rs),
            "ilk": _zaman(rs[-1]), "son": _zaman(rs[0]),
            "hatlar": hat.most_common(), "seferler": rs,
        })
    out.sort(key=lambda s: (-s["n"], s["ad"]))
    return out


def _harita_link(directions, r) -> str:
    y = "" if r["y"] == directions[0] else f"y={quote(r['y'])}&"
    return f"../index.html#{y}sec={r['id']}"


def _sefer_li(cfg, E, directions, r) -> str:
    link = f'<a href="{_harita_link(directions, r)}">Haritada</a>' if r["id"][0] in "cg" else "<span></span>"
    return (f'<li><span class="t">{E(_aralik(cfg, r.get("t0"), r.get("t1")))}</span>'
            f'<span class="r">{E(_rota(r))}</span>'
            f'<em class="{r["a"]}">{E(r.get("etiket") or harita.ALL_LABELS.get(r["k"], r["k"]))}</em>'
            f'{link}</li>')


def _satir(cfg, E, directions, s: dict, top: int) -> str:
    kimlik = [f"{s['bayrak']} bayraklı" if s["bayrak"] else None,
              f"IMO {s['imo']}" if s["imo"] else None, f"MMSI {s['mmsi']}" if s["mmsi"] else None,
              s["firma"][0]["ad"] if s.get("firma") else None]
    bar = "".join(f'<i class="{a}" style="width:{100 * s["aile"][a] / top:.2f}%"></i>'
                  for a in harita.FAMILY_ORDER if s["aile"].get(a))
    hat = ", ".join(f"{E(a)} → {E(b)}" + (f" <small>({n})</small>" if len(s["hatlar"]) > 1 else "")
                    for (a, b), n in s["hatlar"][:2])
    if len(s["hatlar"]) > 2:
        hat += f', <small>{len(s["hatlar"]) - 2} hat daha</small>'
    ailesi = ", ".join(f'{harita.FAMILY_LABELS[a].lower()} {s["aile"][a]}' for a in harita.FAMILY_ORDER if s["aile"].get(a))
    baglanti = ([f'<a href="../index.html#q={quote(str(s["mmsi"] or s["ad"]))}">Haritada bütün seferleri</a>']
                if any(r["id"][0] in "cg" for r in s["seferler"]) else [])
    if s["sayfa"]:
        baglanti.append(f'<a href="../gemiler/{E(s["sayfa"])}.html">Gemi sayfası</a>')
    eski = f' Önceki adları: {E(", ".join(s["adlar"]))}.' if s["adlar"] else ""
    ara = " ".join(filter(None, [s["ad"], *s["adlar"], str(s["mmsi"] or ""), str(s["imo"] or ""), s["bayrak"],
                                 *[f["ad"] for f in s.get("firma") or []]]))
    return (f'<details class="gemi" data-n="{s["n"]}" data-son="{E(s["son"])}" data-ad="{E(s["ad"])}" '
            f'data-ara="{E(ara.lower())}"><summary>'
            f'<span class="ad"><b>{E(s["ad"])}</b><small>{E(", ".join(filter(None, kimlik)))}</small></span>'
            f'<span class="adet"><span class="bar" aria-hidden="true">{bar}</span><b>{s["n"]}</b></span>'
            f'<span class="son"><small>Son sefer </small>{E(_kisa(cfg, s["son"]))}</span>'
            f'<span class="rota-ozet">{hat}</span></summary>'
            f'<div class="govde">{_kunye(E, s)}<p>{s["n"]} sefer: {E(ailesi)}. İlk sefer {E(_kisa(cfg, s["ilk"]))}.{eski} '
            f'{" ".join(baglanti)}</p><ol class="seferler">'
            + "".join(_sefer_li(cfg, E, directions, r) for r in s["seferler"]) + "</ol></div></details>")


def dis_baglantilar(s: dict) -> list[tuple[str, str]]:
    """Geminin herkese açık takip sitelerindeki sayfaları."""
    out = []
    if s.get("mmsi"):
        out.append(("MarineTraffic", f"https://www.marinetraffic.com/en/ais/details/ships/mmsi:{s['mmsi']}"))
    elif s.get("imo"):
        out.append(("MarineTraffic", f"https://www.marinetraffic.com/en/ais/details/ships/imo:{s['imo']}"))
    if s.get("imo"):
        out.append(("VesselFinder", f"https://www.vesselfinder.com/vessels/details/{s['imo']}"))
    if s.get("mmsi"):
        out.append(("MyShipTracking", f"https://www.myshiptracking.com/vessels/mmsi-{s['mmsi']}"))
    if s.get("vid"):
        out.append(("Global Fishing Watch", f"https://globalfishingwatch.org/map/vessel/{s['vid']}"))
    return out


def _kunye(E, s: dict) -> str:
    parts = []
    foto = (s.get("foto") or [None])[0]
    if foto and foto.get("kucuk"):
        lis = E(foto.get("lisans") or "serbest lisans")
        if foto.get("lisans_url"):
            lis = f'<a href="{E(foto["lisans_url"])}" rel="noopener">{lis}</a>'
        parts.append(f'<figure class="gemi-foto"><a href="{E(foto.get("sayfa") or foto["kucuk"])}" rel="noopener">'
                     f'<img src="{E(foto["kucuk"])}" alt="{E(s["ad"])}" loading="lazy" decoding="async"></a>'
                     f'<figcaption>Fotoğraf: {E(foto.get("yazar") or "bilinmiyor")}, {lis}, '
                     f'<a href="{E(foto.get("sayfa") or "")}" rel="noopener">Wikimedia Commons</a></figcaption></figure>')
    if s.get("firma"):
        fs = "; ".join(f'{E(f["ad"])}' + (f' ({E(f["not"])})' if f.get("not") else "") for f in s["firma"])
        kay = s["firma"][0].get("kaynak")
        kay = (f' <span class="not">Kaynak: <a href="{E(kay)}" rel="noopener">bağlantı</a></span>' if kay and kay.startswith("http")
               else f' <span class="not">Kaynak: {E(kay)}</span>' if kay else "")
        parts.append(f'<p class="firma"><b>Firma:</b> {fs}.{kay}</p>')
    else:
        parts.append('<p class="firma"><b>Firma:</b> açık kayıtlarda bulunamadı; aşağıdaki sitelerden bakılabilir.</p>')
    dl = dis_baglantilar(s)
    if dl:
        parts.append('<p class="dis">' + "".join(f'<a href="{E(u)}" rel="noopener" target="_blank">{E(n)}</a>' for n, u in dl)
                     + "</p>")
    return f'<div class="kunye">{"".join(parts)}</div>'


def _csv(rows: list[list]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerows(rows)
    return ("﻿" + buf.getvalue()).encode("utf-8")


ARAC = '''<script>(function(){
var liste=document.getElementById("gemi-liste"),ara=document.getElementById("rapor-ara"),say=document.getElementById("rapor-say");
var hepsi=[].slice.call(liste.querySelectorAll("details.gemi")),zaman=null;
function goster(){var q=ara.value.trim().toLocaleLowerCase("tr"),n=0;
hepsi.forEach(function(d){var u=!q||d.dataset.ara.indexOf(q)>=0||d.textContent.toLocaleLowerCase("tr").indexOf(q)>=0;d.hidden=!u;if(u)n++});
say.textContent=q?n+" gemi bulundu":hepsi.length+" gemi";}
ara.addEventListener("input",function(){clearTimeout(zaman);zaman=setTimeout(goster,120)});
document.querySelectorAll("[data-sirala]").forEach(function(b){b.addEventListener("click",function(){
var k=b.dataset.sirala;document.querySelectorAll("[data-sirala]").forEach(function(x){x.setAttribute("aria-pressed",String(x===b))});
hepsi.sort(function(a,c){if(k==="ad")return a.dataset.ad.localeCompare(c.dataset.ad,"tr");
if(k==="son")return c.dataset.son.localeCompare(a.dataset.son);return c.dataset.n-a.dataset.n||a.dataset.ad.localeCompare(c.dataset.ad,"tr")});
hepsi.forEach(function(d){liste.appendChild(d)});});});
goster();})();</script>'''


def build(cfg, con, recs: list[dict], out: Path) -> None:
    from .routes import vessel_keys
    from .db import get_meta
    from .site import E, _ay, _n, _page, _tarih, _tbl, _write
    home = {p.country for p in cfg.ports if p.role == "izlenen"}

    directions = [f"{a}>{b}" for a, b in cfg.directions]
    rdir = out / "raporlar"
    if rdir.exists():
        for f in rdir.iterdir():
            if f.is_file():
                f.unlink()
    if not directions:
        _write(rdir / "index.html", _page(cfg, "Raporlar", '<main class="sayfa" id="icerik"><h1>Raporlar</h1>'
                                          '<p class="not">Beyan testi kapalı; rapor yok.</p></main>', 1, "raporlar"))
        return
    vessels = {r["mmsi"]: dict(r) for r in con.execute("SELECT mmsi, imo, name FROM vessels")}
    from . import gemi_bilgi
    m2vid = {}
    for ssvid, vid in con.execute("SELECT ssvid, vessel_id FROM gecmis WHERE vessel_id IS NOT NULL GROUP BY ssvid, vessel_id"):
        try:
            m2vid.setdefault(int(ssvid), vid)
        except (TypeError, ValueError):
            pass
    elle = gemi_bilgi.elle(cfg)

    def bilgi(mmsi, imo):
        vid = m2vid.get(mmsi)
        k = (gemi_bilgi.oku(con, f"gkimlik:{vid}") if vid else None) or {}
        imo = str(imo or k.get("imo") or "") or None
        e = elle.get(str(imo)) or elle.get(str(mmsi)) or {}
        firma = []
        if e.get("firma"):
            firma.append({"ad": e["firma"], "not": e.get("rol"), "kaynak": e.get("kaynak") or "elle girildi"})
        else:
            sah = sorted(k.get("sahipler") or [], key=lambda o: o.get("son") or "9999", reverse=True)
            firma = [{"ad": o["ad"], "not": "sicildeki sahip", "kaynak": "Global Fishing Watch"} for o in sah[:2]]
        return {"vid": vid, "imo": imo, "firma": firma, "foto": (gemi_bilgi.oku(con, f"foto:{imo}") if imo else None) or []}
    m2k, _ = vessel_keys(con)
    pages = {f.stem for f in (out / "gemiler").glob("*.html")}
    legend = "".join(f'<span class="isaret" style="--c:var(--c-{k})">{E(harita.FAMILY_LABELS[k])}</span>'
                     for k in harita.FAMILY_ORDER)
    # dünyadan hedef ülkeye: geçmiş taramadaki bütün varışlar ve bir önceki uğrak
    dunya = [dict(r) for r in con.execute("SELECT * FROM dunya ORDER BY t_arr DESC")]
    hedef_ad = ", ".join(cfg.country_name(c) for c in sorted(cfg.dest_countries()))

    def dunya_sekme(aktif):
        if not dunya:
            return ""
        return f'<a href="dunya.html"{" aria-current=page" if aktif else ""}>Dünya → {E(hedef_ad)}</a>'

    for y in directions:
        A, B = y.split(">")
        a_ad, b_ad = cfg.country_name(A), cfg.country_name(B)
        sl = slug(y)
        sh = ships(recs, y, vessels, m2k, pages, bilgi)
        sel = [r for r in recs if r["y"] == y]
        top = max((s["n"] for s in sh), default=1)
        ts = sorted(_zaman(r) for r in sel if _zaman(r))
        yon = dunya_sekme(False) + "".join(f'<a href="{sayfa(directions, x)}"{" aria-current=page" if x == y else ""}>'
                      f'{E(cfg.country_name(x.split(">")[0]))} → {E(cfg.country_name(x.split(">")[1]))}</a>' for x in directions)
        aylar = defaultdict(list)
        for r in sel:
            if _zaman(r):
                aylar[_zaman(r)[:7]].append(r)
        ay_li = "".join(f'<li><a href="{sl}-{m}.html"><b>{E(_ay(m))}</b>'
                        f'<span>{_n(len(rs))} sefer, {_n(len({x.get("m") or x.get("n") for x in rs}))} gemi</span></a></li>'
                        for m, rs in sorted(aylar.items(), reverse=True))
        donem = f"{_tarih(cfg, ts[0])} ile {_tarih(cfg, ts[-1])} arasında" if ts else ""
        petrol = [r for r in sel if r.get("sv")]
        ceyhan = [r for r in petrol if (r.get("ter") or "").startswith("Ceyhan")]
        gemi_say = lambda rs: len({x.get("m") or x.get("n") for x in rs})  # noqa: E731
        petrol_not = ""
        if petrol:
            petrol_not = (f'<p class="petrol-ozet">Bunların <b>{_n(len(petrol))} seferi ({_n(gemi_say(petrol))} gemi)</b> '
                          f'petrol tankeri ya da petrol iskelesinden; <b>{_n(len(ceyhan))} seferi ({_n(gemi_say(ceyhan))} gemi)</b> '
                          f'Ceyhan petrol terminallerinden (BTC ve Kerkük-Ceyhan). <a href="{sl}-petrol.html">Petrol tankerleri raporu</a></p>')

        # Ceyhan'dan çıkan bütün gemiler: sonraki uğrak (yalnızca beyanı veren ülkeden çıkan yönde)
        ceyhan_html = ""
        cik = json.loads(get_meta(con, "ceyhan_cikislari", "[]") or "[]") if A in home else []
        if cik:
            from .ulkeler import ulke_adi
            anah = lambda x: x.get("ulke_ad") or (cfg.country_name(x["ulke"]) if x.get("ulke") else "?")  # noqa: E731
            say = Counter(x.get("ulke") for x in cik)
            ulk = Counter(anah(x) for x in cik)
            satir = []
            for c, n in ulk.most_common():
                ad_ = "Sonraki uğrak kayıtsız" if c == "?" else c
                satir.append([f"<b>{E(ad_)}</b>" if c in (b_ad, "?") else E(ad_), _n(n),
                              _n(len({x["vid"] for x in cik if anah(x) == c}))])
            dikkat = [x for x in cik if x.get("ulke") in (B, None) or x.get("karanlik")]
            drows = [[f'<b>{E(x.get("ad") or "?")}</b><br><span class="not">{E(ulke_adi(x.get("b")))}, MMSI {E(str(x.get("m") or "?"))}</span>',
                      f'<span class="tarih">{E(_kisa(cfg, x["t"]))}</span>',
                      E(x.get("sonraki") or "kayıt yok") + (f'<br><span class="not tarih">{E(_kisa(cfg, x.get("t1")))}</span>' if x.get("t1") else ""),
                      f'<span class="uyari">{E(str(x["karanlik"]).replace(".", ","))} saat</span>' if x.get("karanlik") else "–"]
                     for x in dikkat[:300]]
            ceyhan_html = (f'<h2>Ceyhan’dan çıkan gemiler nereye gitti?</h2><p class="not">Geçmiş taramada Ceyhan '
                           'terminallerine (BTC, Kerkük-Ceyhan) ya da önlerindeki demirleme alanına (11 km) uğrayıp ayrılan '
                           f'{_n(len(cik))} sefer ve her birinin bir sonraki uğrağı. GFW bu ziyaretleri terminallerin birkaç km '
                           'güneyindeki demirleme noktalarına bağlıyor; bu alanda Sugözü ve gübre iskelelerine gelen kuru yük '
                           'gemileri de bulunabilir. Tarama sürdükçe sayı artar.</p>'
                           + _tbl(["Sonraki uğrak", "Sefer", "Gemi"], satir, num=(1, 2))
                           + (f'<h3>{E(b_ad)}’e giden, sonraki uğrağı kayıtsız ya da yolda AIS’i kapanan seferler</h3>'
                              + _tbl(["Gemi", "Ceyhan’dan çıkış", "Sonraki uğrak", "AIS kapalı"], drows) if drows else ""))
        if cik and A in home:
            petrol_not = (petrol_not[:-4] if petrol_not else '<p class="petrol-ozet">') + (
                f' Ceyhan terminalleri çevresinden taranan {_n(len(cik))} çıkıştan {_n(say.get(B, 0))} tanesi doğrudan {E(b_ad)}’e gitti.'
                + ("" if petrol else f' <a href="{sl}-petrol.html">Petrol tankerleri raporu</a>') + '</p>')

        def liste(sh_):
            top_ = max((x["n"] for x in sh_), default=1)
            return (f'<div class="arac"><label class="ara"><span class="gizli">Gemi ya da liman ara</span>'
                    '<input type="search" id="rapor-ara" placeholder="Gemi adı, IMO, MMSI, bayrak, firma ya da liman" autocomplete="off"></label>'
                    '<div class="dugmeler" role="group" aria-label="Sıralama"><button type="button" data-sirala="n" aria-pressed="true">'
                    'Sefer sayısı</button><button type="button" data-sirala="son" aria-pressed="false">Son sefer</button>'
                    '<button type="button" data-sirala="ad" aria-pressed="false">Ad</button></div>'
                    f'<output id="rapor-say" aria-live="polite">{_n(len(sh_))} gemi</output></div>'
                    f'<p class="lejant">{legend}</p>'
                    '<div class="gemi-liste" id="gemi-liste"><div class="gemi-bas" aria-hidden="true"><span>Gemi</span>'
                    '<span>Sefer</span><span>Son sefer</span><span>Başlıca hat</span></div>'
                    + "".join(_satir(cfg, E, directions, x, top_) for x in sh_) + "</div>" + (ARAC if sh_ else ""))

        body = (f'<main class="sayfa rapor" id="icerik"><header><h1>Raporlar</h1>'
                f'<p class="giris">{E(a_ad)} limanlarından {E(b_ad)} limanlarına doğrudan ya da dolaylı giden gemiler, '
                'gemi gemi. Bir gemiye tıklayınca bütün seferleri açılır.</p></header>'
                + (f'<nav class="dugmeler yon" aria-label="Yön">{yon}</nav>' if len(directions) > 1 or dunya else "")
                + f'<h2 class="rapor-baslik">{_n(len(sh))} gemi, {_n(len(sel))} sefer</h2>'
                f'<p class="not">{E(donem)}{", " if donem else ""}canlı kayıt ve geçmiş tarama birlikte. Varış ayına göre '
                f'<a href="#aylik">aylık raporlar</a> sayfanın sonunda.</p>{petrol_not}'
                f'<p class="eylemler"><a class="eylem ana" href="{sl}-seferler.html">Bütün seferler tek listede</a>'
                f'<a class="eylem" href="{sl}-gemiler.csv" download>Gemi listesi (CSV)</a>'
                f'<a class="eylem" href="{sl}-seferler.csv" download>Bütün seferler (CSV)</a></p>'
                + (liste(sh) if sh else '<p class="not">Henüz sefer yok.</p>')
                + (f'<section id="aylik"><h2>Aylık raporlar</h2><p class="not">Aylar varış tarihine göre.</p>'
                   f'<ul class="aylar">{ay_li}</ul></section>' if ay_li else "")
                + "</main>")
        _write(rdir / sayfa(directions, y), _page(cfg, "Raporlar", body, 1, "raporlar",
                                                   desc=f"{a_ad} limanlarından {b_ad} limanlarına giden {len(sh)} gemi, {len(sel)} sefer."))

        def sefer_satiri(r):
            mm = r.get("m")
            ter = f'<br><span class="not">{E(r["ter"])}</span>' if r.get("ter") and r.get("oc") == A else ""
            return [
                f'<b>{E(r.get("n") or "Adı bilinmiyor")}</b><br><span class="not">{E(bayrak(r.get("b"), mm))}{", MMSI " + str(mm) if mm else ""}</span>',
                f'{E(r.get("o") or "?")}{ter}<br><span class="not tarih">{E(_kisa(cfg, r.get("t0")))}</span>',
                E(", ".join(r.get("ara") or [])) or "–",
                (f'{E(r["d"])}<br><span class="not tarih">{E(_kisa(cfg, r.get("t1")))}</span>' if r.get("d")
                 else '<span class="uyari">Kayıtsız</span>'),
                f'<span class="isaret" style="--c:var(--c-{r["a"]})">{E(harita.ALL_LABELS.get(r["k"], r["k"]))}</span>',
                f'<a href="{_harita_link(directions, r)}">Haritada</a>']
        bas = ["Gemi", "Çıkış", "Ara liman", "Varış", "Tür", ""]
        yol = f'<p class="yol"><a href="{sayfa(directions, y)}">Raporlar</a>, {E(a_ad)} → {E(b_ad)}</p>'

        # bütün seferler tek listede
        ara_kutu = ('<div class="arac"><label class="ara"><span class="gizli">Sefer ara</span><input type="search" id="tablo-ara" '
                    'placeholder="Gemi, liman, bayrak ya da tür" autocomplete="off"></label><output id="tablo-say"></output></div>')
        tablo_js = ('<script>(function(){var a=document.getElementById("tablo-ara"),o=document.getElementById("tablo-say"),'
                    'r=[].slice.call(document.querySelectorAll("tbody tr")),z;function g(){var q=a.value.trim().toLocaleLowerCase("tr"),n=0;'
                    'r.forEach(function(t){var u=!q||t.textContent.toLocaleLowerCase("tr").indexOf(q)>=0;t.hidden=!u;if(u)n++});'
                    'o.textContent=n+" sefer"}a.addEventListener("input",function(){clearTimeout(z);z=setTimeout(g,120)});g()})();</script>')
        hepsi = sorted(sel, key=lambda r: r.get("t0") or _zaman(r), reverse=True)
        _write(rdir / f"{sl}-seferler.html", _page(cfg, "Bütün seferler", (
            f'<main class="sayfa rapor" id="icerik"><header>{yol}<h1>Bütün seferler</h1>'
            f'<p class="giris">{E(a_ad)} limanlarından {E(b_ad)} limanlarına {_n(len(sel))} sefer, {_n(len(sh))} gemi. '
            'En yeni çıkış en üstte.</p></header>' + ara_kutu + _tbl(bas, [sefer_satiri(r) for r in hepsi]) + tablo_js
            + "</main>"), 1, "raporlar", desc=f"{a_ad} limanlarından {b_ad} limanlarına bütün seferler."))

        # petrol tankerleri
        if petrol or ceyhan_html:
            sh_p = ships(petrol, y, vessels, m2k, pages, bilgi)
            ter_say = Counter(r.get("ter") for r in petrol)
            ter_rows = [[E(t), _n(n), _n(gemi_say([r for r in petrol if r.get("ter") == t]))] for t, n in ter_say.most_common()]
            _write(rdir / f"{sl}-petrol.html", _page(cfg, "Petrol tankerleri", (
                f'<main class="sayfa rapor" id="icerik"><header>{yol}<h1>Petrol ve akaryakıt tankerleri</h1>'
                f'<p class="giris">{E(a_ad)} tarafında petrol ya da akaryakıt iskelesine yanaşan ya da AIS’te kendini tanker '
                f'olarak bildiren ve {E(b_ad)} limanlarına giden {_n(len(sh_p))} gemi, {_n(len(petrol))} sefer. Yükün türü '
                '(ham petrol, akaryakıt, kimyasal) AIS verisinden kesin bilinemez.</p></header>'
                '<p class="not">Ceyhan’daki BTC (Bakü-Tiflis-Ceyhan) ve Kerkük-Ceyhan terminalleri birbirine bir iki kilometre '
                'uzaklıkta; AIS konumuyla ayırt edilemedikleri için birlikte sayılır. Geçmiş taramada geminin tipi bilinmez; '
                'tip, gemi canlı kayıtta bir kez görüldüğünde öğrenilir. Bu yüzden liste zamanla uzar.</p>'
                + ceyhan_html
                + (f'<h2>{E(b_ad)}’e giden petrol tankerleri</h2>' + _tbl(["İskele", "Sefer", "Gemi"], ter_rows, num=(1, 2))
                   + liste(sh_p) + "<h2>Seferler</h2>"
                   + _tbl(bas, [sefer_satiri(r) for r in sorted(petrol, key=lambda r: r.get("t0") or "", reverse=True)])
                   if petrol else f'<h2>{E(b_ad)}’e giden petrol tankerleri</h2><p class="not">Şimdilik kayıt yok.</p>')
                + "</main>"), 1, "raporlar", desc=f"{a_ad} petrol iskelelerinden {b_ad} limanlarına {len(petrol)} sefer."))

        # aylık raporlar
        sirali = sorted(aylar)
        for i, m in enumerate(sirali):
            rs = sorted(aylar[m], key=lambda r: r.get("t0") or _zaman(r))
            onceki = f'<a href="{sl}-{sirali[i - 1]}.html">{E(_ay(sirali[i - 1]))}</a>' if i else "<span></span>"
            sonraki = f'<a href="{sl}-{sirali[i + 1]}.html">{E(_ay(sirali[i + 1]))}</a>' if i + 1 < len(sirali) else ""
            rows = [sefer_satiri(r) for r in rs]
            n_gemi = len({x.get("m") or x.get("n") for x in rs})
            mbody = (f'<main class="sayfa rapor" id="icerik"><header><p class="yol"><a href="{sayfa(directions, y)}">Raporlar</a>'
                     f', {E(a_ad)} → {E(b_ad)}</p><h1>{E(_ay(m))}</h1>'
                     f'<p class="giris">{E(a_ad)} limanlarından {E(b_ad)} limanlarına {_n(len(rs))} sefer, {_n(n_gemi)} gemi. '
                     'Varış tarihine göre; satırlar çıkış tarihine göre sıralı.</p></header>'
                     f'<nav class="ay-gecis" aria-label="Aylar">{onceki}{sonraki}</nav>'
                     + _tbl(bas, rows) + "</main>")
            _write(rdir / f"{sl}-{m}.html", _page(cfg, f"{_ay(m)} raporu", mbody, 1, "raporlar",
                                                   desc=f"{_ay(m)}: {a_ad} limanlarından {b_ad} limanlarına {len(rs)} sefer."))

        # CSV
        (rdir / f"{sl}-gemiler.csv").write_bytes(_csv(
            [["Gemi", "Önceki adları", "MMSI", "IMO", "Bayrak", "Firma", "MarineTraffic", "Sefer", *[harita.FAMILY_LABELS[k] for k in harita.FAMILY_ORDER],
              "İlk sefer (varış)", "Son sefer (varış)", "Başlıca hat"]]
            + [[s["ad"], ", ".join(s["adlar"]), s["mmsi"] or "", s["imo"] or "", s["bayrak"],
                "; ".join(f["ad"] for f in s.get("firma") or []), (dis_baglantilar(s) or [("", "")])[0][1], s["n"],
                *[s["aile"].get(k, 0) for k in harita.FAMILY_ORDER], s["ilk"], s["son"],
                f'{s["hatlar"][0][0][0]} → {s["hatlar"][0][0][1]}' if s["hatlar"] else ""] for s in sh]))
        (rdir / f"{sl}-seferler.csv").write_bytes(_csv(
            [["Gemi", "MMSI", "IMO", "Bayrak", "Tür", "Çıkış limanı", "Çıkış tarihi", "Ara limanlar", "Varış limanı",
              "Varış tarihi", "Türk tarafındaki terminal", "Kaynak", "Kayıt"]]
            + [[r.get("n") or "", r.get("m") or "", r.get("imo") or "", bayrak(r.get("b"), r.get("m")),
                harita.ALL_LABELS.get(r["k"], r["k"]), r.get("o") or "", r.get("t0") or "", ", ".join(r.get("ara") or []),
                r.get("d") or "", r.get("t1") or "", r.get("ter") or "", "Canlı kayıt" if r["s"] == "c" else "Geçmiş tarama (GFW)", r["id"]]
               for r in sorted(sel, key=lambda r: r.get("t0") or "")]))

    if dunya:
        _dunya(cfg, con, dunya, directions, rdir, vessels, m2k, pages, bilgi, legend, hedef_ad, dunya_sekme)


def _dunya(cfg, con, dunya, directions, rdir, vessels, m2k, pages, bilgi, legend, hedef_ad, dunya_sekme):
    from .site import E, _n, _page, _tarih, _tbl, _write
    from .ulkeler import ulke_adi
    recs = []
    for r in dunya:
        try:
            m = int(r["ssvid"]) if r["ssvid"] else None
        except ValueError:
            m = None
        recs.append({"id": f"d{r['id']}", "s": "g", "y": "DUNYA", "k": "dunya", "a": "dogrudan", "etiket": "Varış",
                     "n": r["name"], "m": m, "b": r["flag"], "o": r["origin"] or "önceki uğrak kayıtsız",
                     "oc3": r["origin_iso3"], "t0": r["t_dep"], "d": r["dest"], "t1": r["t_arr"]})
    yon = dunya_sekme(True) + "".join(f'<a href="{sayfa(directions, x)}">{E(cfg.country_name(x.split(">")[0]))} → '
                                      f'{E(cfg.country_name(x.split(">")[1]))}</a>' for x in directions)
    ulk = defaultdict(list)
    for r in recs:
        ulk[r["oc3"] or "?"].append(r)
    gsay = lambda rs: len({x.get("m") or x.get("n") for x in rs})  # noqa: E731
    ts = sorted(r["t1"] for r in recs if r["t1"])
    satir = []
    for c, rs in sorted(ulk.items(), key=lambda kv: -len(kv[1])):
        ad = "Önceki uğrak kayıtsız (45 gün içinde)" if c == "?" else (ulke_adi(c) or c)
        link = f'<a href="dunya-{c.lower()}.html">{E(ad)}</a>' if c != "?" else E(ad)
        satir.append([link, _n(len(rs)), _n(gsay(rs)), f"%{100 * len(rs) / len(recs):.1f}".replace(".", ",")])
    limanlar = Counter((r["o"], r["oc3"]) for r in recs if r["oc3"])
    lrows = [[E(o), E(ulke_adi(c) or c), _n(n)] for (o, c), n in limanlar.most_common(30)]
    body = (f'<main class="sayfa rapor" id="icerik"><header><h1>Raporlar</h1>'
            f'<p class="giris">Dünyanın her yerinden {E(hedef_ad)} limanlarına gelen gemiler ve her varıştan önceki son uğrak. '
            'Global Fishing Watch liman ziyaretlerinden; bir ülkeye tıklayınca o ülkeden gelen gemiler gemi gemi açılır.</p></header>'
            f'<nav class="dugmeler yon" aria-label="Yön">{yon}</nav>'
            f'<h2 class="rapor-baslik">{_n(gsay(recs))} gemi, {_n(len(recs))} varış, {_n(len([c for c in ulk if c != "?"]))} ülkeden</h2>'
            f'<p class="not">{E(_tarih(cfg, ts[0]) if ts else "")} ile {E(_tarih(cfg, ts[-1]) if ts else "")} arasında. '
            'Tarama yalnızca hedef ülke limanlarına uğrayan gemileri kapsar; liman dışı (açık deniz şamandırası) boşaltmalar ve '
            'AIS’i kapalı gelişler görünmez.</p>'
            '<p class="eylemler"><a class="eylem" href="dunya-seferler.csv" download>Bütün varışlar (CSV)</a></p>'
            '<h2>Geldikleri ülke</h2>' + _tbl(["Önceki uğrak ülkesi", "Varış", "Gemi", "Pay"], satir, num=(1, 2, 3))
            + '<h2>En sık son uğrak limanları</h2>' + _tbl(["Liman", "Ülke", "Varış"], lrows, num=(2,)) + "</main>")
    _write(rdir / "dunya.html", _page(cfg, "Dünyadan " + hedef_ad, body, 1, "raporlar",
                                      desc=f"Dünyadan {hedef_ad} limanlarına {len(recs)} varış."))
    for c, rs in ulk.items():
        if c == "?":
            continue
        sh = ships(rs, "DUNYA", vessels, m2k, pages, bilgi)
        top = max((x["n"] for x in sh), default=1)
        ad = ulke_adi(c) or c
        b = (f'<main class="sayfa rapor" id="icerik"><header><p class="yol"><a href="dunya.html">Dünya → {E(hedef_ad)}</a></p>'
             f'<h1>{E(ad)} → {E(hedef_ad)}</h1><p class="giris">Son uğrağı {E(ad)} olan {_n(len(rs))} varış, {_n(len(sh))} gemi. '
             'Bir gemiye tıklayınca bütün varışları açılır.</p></header>'
             '<div class="arac"><label class="ara"><span class="gizli">Gemi ara</span><input type="search" id="rapor-ara" '
             'placeholder="Gemi adı, IMO, MMSI, bayrak, firma ya da liman" autocomplete="off"></label>'
             '<div class="dugmeler" role="group" aria-label="Sıralama"><button type="button" data-sirala="n" aria-pressed="true">'
             'Varış sayısı</button><button type="button" data-sirala="son" aria-pressed="false">Son varış</button>'
             '<button type="button" data-sirala="ad" aria-pressed="false">Ad</button></div>'
             f'<output id="rapor-say" aria-live="polite">{_n(len(sh))} gemi</output></div>'
             '<div class="gemi-liste" id="gemi-liste"><div class="gemi-bas" aria-hidden="true"><span>Gemi</span>'
             '<span>Varış</span><span>Son varış</span><span>Başlıca hat</span></div>'
             + "".join(_satir(cfg, E, directions, x, top) for x in sh) + "</div>" + ARAC + "</main>")
        _write(rdir / f"dunya-{c.lower()}.html", _page(cfg, f"{ad} → {hedef_ad}", b, 1, "raporlar"))
    (rdir / "dunya-seferler.csv").write_bytes(_csv(
        [["Gemi", "MMSI", "Bayrak", "GFW tipi", "Önceki uğrak", "Önceki uğrak ülkesi", "Çıkış", "Varış limanı", "Varış"]]
        + [[r["name"] or "", r["ssvid"] or "", ulke_adi(r["flag"]), r["vtype"] or "", r["origin"] or "",
            ulke_adi(r["origin_iso3"]) if r["origin_iso3"] else "", r["t_dep"] or "", r["dest"] or "", r["t_arr"] or ""]
           for r in dunya]))
