"""Statik web sitesini üretir (GitHub Actions bunu GitHub Pages'e yükler)."""
from __future__ import annotations

import html
import json
import os
from urllib.parse import urlencode
from collections import Counter, defaultdict
from pathlib import Path

from . import proof
from .db import get_meta
from .routes import CLASS_LABELS, CLASS_ORDER, CLASS_SHORT, vessel_keys
from .util import SHIP_GROUP_LABELS, fmt_local, hazard_category, hours_between, iso, now_utc, ship_group

E = html.escape

CSS = """
:root{--bg:#f6f4ef;--panel:#fffdf8;--ink:#1b2430;--muted:#5d6876;--line:#dcd6ca;--accent:#0f5e7a;
--warn:#a4461c;--warn-bg:#fbeee6;--ok:#2f6b3a;--chip:#ece7dc;--mono:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}
@media (prefers-color-scheme:dark){:root{--bg:#11161c;--panel:#171e26;--ink:#e6e2d8;--muted:#9aa5b1;--line:#2b3542;
--accent:#6cc0dc;--warn:#f0a07a;--warn-bg:#2c1d16;--ok:#8fd19e;--chip:#222b36}}
*{box-sizing:border-box}html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.55 "Iowan Old Style","Palatino Linotype",Georgia,serif}
a{color:var(--accent)}
header.top{border-bottom:1px solid var(--line);background:var(--panel)}
.wrap{max-width:1080px;margin:0 auto;padding:0 16px}
.top .wrap{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 24px;padding-top:14px;padding-bottom:12px}
.brand{font-weight:700;font-size:20px;text-decoration:none;color:var(--ink);letter-spacing:.01em}
nav a{margin-right:16px;font:14px/1.4 system-ui,sans-serif;text-decoration:none;color:var(--muted)}
nav a.on{color:var(--ink);font-weight:600}
main{padding:28px 0 60px}
h1{font-size:30px;line-height:1.2;margin:0 0 8px}h2{font-size:21px;margin:36px 0 10px}h3{font-size:17px;margin:20px 0 6px}
.lede{color:var(--muted);max-width:720px;margin:0 0 20px}
.banner{background:var(--warn-bg);color:var(--warn);border:1px solid var(--warn);padding:10px 14px;border-radius:6px;
font:14px/1.45 system-ui,sans-serif;margin:0 0 20px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:10px;margin:14px 0}
.stat{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:12px 14px}
.stat b{display:block;font:600 26px/1.1 system-ui,sans-serif}.stat span{font:13px system-ui,sans-serif;color:var(--muted)}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:14px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:14px;min-width:0}
.card img{width:100%;height:auto;border-radius:4px;border:1px solid var(--line);display:block}
.tbl{overflow-x:auto;border:1px solid var(--line);border-radius:8px;background:var(--panel)}
table{border-collapse:collapse;width:100%;font:14px/1.4 system-ui,sans-serif}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line);vertical-align:top}
th{font-weight:600;color:var(--muted);font-size:12.5px;text-transform:uppercase;letter-spacing:.03em;white-space:nowrap}
tr:last-child td{border-bottom:0}
.chip{display:inline-block;background:var(--chip);border-radius:99px;padding:1px 9px;font:12.5px/1.6 system-ui,sans-serif;
margin:1px 4px 1px 0;white-space:nowrap}
.chip.w{background:var(--warn-bg);color:var(--warn)}
.mono{font-family:var(--mono);font-size:12.5px;word-break:break-all}
.muted{color:var(--muted)}.small{font-size:13.5px}
.quote{border-left:3px solid var(--accent);padding:6px 14px;margin:10px 0 18px;background:var(--panel)}
ul.basis{margin:4px 0 0;padding-left:18px;font-size:13px;color:var(--muted)}
footer{border-top:1px solid var(--line);padding:18px 0 40px;color:var(--muted);font:13px/1.5 system-ui,sans-serif}
@media (max-width:600px){h1{font-size:24px}th,td{padding:7px 8px}}
"""


def _page(cfg, title: str, body: str, depth: int, active: str = "") -> str:
    r = "../" * depth
    links = [("index.html", "Genel bakış", "home"), ("limanlar/index.html", "Limanlar", "ports"),
             ("gemiler/index.html", "Gemiler", "ships")]
    if cfg.directions:
        links.append(("beyan.html", "Beyan testi", "decl"))
    if getattr(cfg, "_has_gecmis", False):
        links.append(("gecmis.html", "Geçmiş tarama", "retro"))
    links += [("kanit.html", "Kanıt zinciri", "proof"), ("yontem.html", "Yöntem", "method")]
    nav = "".join(f'<a href="{r}{h}" class="{"on" if k == active else ""}">{E(t)}</a>' for h, t, k in links)
    gfw = (' · Geçmiş tarama: <a href="https://globalfishingwatch.org">Powered by Global Fishing Watch.</a>'
           if getattr(cfg, "_has_gecmis", False) else "")
    banner = ('<div class="banner"><b>Kurgusal demo.</b> Bu sayfadaki limanlar, ülkeler ve gemiler test için '
              'uydurulmuştur; gerçek bir olayı göstermez.</div>') if cfg.fictional else ""
    return f"""<!doctype html><html lang="tr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{E(title)} · {E(cfg.name)}</title><link rel="stylesheet" href="{r}stil.css"></head><body>
<header class="top"><div class="wrap"><a class="brand" href="{r}index.html">{E(cfg.name)}</a><nav>{nav}</nav></div></header>
<main><div class="wrap">{banner}{body}</div></main>
<footer><div class="wrap">Son güncelleme: {E(fmt_local(iso(now_utc()), cfg.tz))} ({E(cfg.tz)}) ·
Veri: AIS (aisstream.io) · Her günün dosyaları hash'lenip zincirlenir, bkz. <a href="{r}kanit.html">Kanıt zinciri</a>.
Bu sitedeki işaretler tespittir, hüküm değildir.{gfw}</div></footer></body></html>"""


def _tbl(head: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return '<p class="muted small">Henüz kayıt yok.</p>'
    th = "".join(f"<th>{E(h)}</th>" for h in head)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tbl"><table><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table></div>'


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _draught(a, b) -> str:
    if a is None and b is None:
        return "–"
    s = f"{a if a is not None else '?'} → {b if b is not None else '?'} m"
    if a is not None and b is not None and abs(b - a) >= 0.5:
        s += f' <span class="chip{" w" if b > a else ""}">{"+" if b > a else ""}{round(b - a, 1)}</span>'
    return s


EVENT_LABELS = {"gap": "AIS boşluğu", "stop": "Liman dışı durak", "sts": "Denizde buluşma",
                "draught": "Limansız su çekimi değişimi", "spoof": "Konum tutarsızlığı"}


def sat_link(lat: float, lon: float, t0: str, t1: str, radar: bool = False, zoom: int = 12) -> str:
    """Copernicus Browser'da konumu ve tarih aralığını açan bağlantı (Sentinel-1 radar / Sentinel-2 optik)."""
    q = urlencode({"zoom": zoom, "lat": round(lat, 4), "lng": round(lon, 4), "themeId": "DEFAULT-THEME",
                   "datasetId": "S1_CDAS_IW_VVVH" if radar else "S2_L2A_CDAS",
                   "fromTime": f"{t0[:10]}T00:00:00.000Z", "toTime": f"{t1[:10]}T23:59:59.999Z"})
    return f"https://browser.dataspace.copernicus.eu/?{q}"


def sat_links(cfg, t0: str, t1: str, points=()) -> str:
    """Hedef ülke limanları (ve verilen noktalar) için o tarih aralığında uydu görüntüsü bağlantıları."""
    if not t0 or not t1:
        return ""
    items = list(points)
    targets = cfg.dest_countries()
    items += [(p.name, p.area.center) for p in cfg.ports
              if p.country in targets and not p.approach and p.role == "varis"]
    parts = []
    for name, (lat, lon) in items[:8]:
        parts.append(f"{E(name)} <a href='{E(sat_link(lat, lon, t0, t1, True))}' target='_blank' rel='noopener'>radar</a>/"
                     f"<a href='{E(sat_link(lat, lon, t0, t1))}' target='_blank' rel='noopener'>optik</a>")
    return "<div class='small muted'>Uydu görüntüsü (" + E(t0[:10]) + " – " + E(t1[:10]) + "): " + " · ".join(parts) + "</div>"


def _event_text(e: dict, names: dict) -> str:
    d = json.loads(e["detail"] or "{}")
    if e["kind"] == "gap":
        return (f"{d.get('saat')} saat sinyal yok, bu sürede {d.get('mesafe_km')} km yer değiştirdi "
                f"(ort. {d.get('ortalama_hiz_knot')} knot). Su çekimi: {d.get('draft_once')} → {d.get('draft_sonra')} m")
    if e["kind"] == "stop":
        return f"{d.get('saat')} saat açık denizde durdu. Su çekimi: {d.get('draft_once')} → {d.get('draft_sonra')} m"
    if e["kind"] == "sts":
        return (f"{E(names.get(e['mmsi'], str(e['mmsi'])))} ile {E(names.get(e['mmsi2'], str(e['mmsi2'])))} "
                f"{d.get('saat')} saat boyunca 500 m'den yakın durdu. Su çekimleri: {d.get('draft_1')} / {d.get('draft_2')}")
    if e["kind"] == "draught":
        return f"Liman ziyareti olmadan su çekimi {d.get('once')} → {d.get('sonra')} m"
    if e["kind"] == "spoof":
        return (f"Konum bir önceki kayda göre {d.get('km')} km sıçradı (görünen hız {d.get('gorunen_hiz_knot') or '∞'} knot). "
                "GPS karıştırma veya sahte konum olabilir; bu konum analizde kullanılmadı.")
    return ""


def ham_url(day: str) -> str:
    """Ham veri GitHub Releases'ta tutuluyorsa onun adresi (LIMAN_HAM_URL içinde {gun} yer tutucusu)."""
    tpl = os.environ.get("LIMAN_HAM_URL")
    return tpl.format(gun=day) if tpl else f"arsiv/{day}/ham.jsonl.gz"


def build(cfg, con) -> None:
    out = cfg.site_dir
    out.mkdir(parents=True, exist_ok=True)
    gecmis_rows = [dict(r) for r in con.execute("SELECT * FROM gecmis ORDER BY t_arr DESC")]
    gecmis_state = json.loads(get_meta(con, "gecmis_durum", "{}") or "{}")
    cfg._has_gecmis = bool(gecmis_rows or gecmis_state)
    _write(out / "stil.css", CSS)
    tz = cfg.tz
    m2k, k2m = vessel_keys(con)
    vessels = {r["mmsi"]: dict(r) for r in con.execute("SELECT * FROM vessels")}
    names = {m: (v["name"] or f"MMSI {m}") for m, v in vessels.items()}
    port_name = {p.code: p.name for p in cfg.ports}
    days = sorted([r["day"] for r in con.execute("SELECT day FROM archived_days")], reverse=True)

    def map_day(code):
        for d in days:
            try:
                oz = json.loads((out / "arsiv" / d / "ozet.json").read_text(encoding="utf-8"))
                if oz["limanlar"].get(code, {}).get("ziyaret"):
                    return d
            except (OSError, ValueError, KeyError):
                continue
        return days[0] if days else None
    chain = proof.read_chain(cfg)
    tracking = {r["mmsi"]: dict(r) for r in con.execute("SELECT * FROM tracking")}
    visits = [dict(v) for v in con.execute("SELECT * FROM visits WHERE transit IS NOT 1 OR status='open' ORDER BY t_in DESC")]
    routes = [dict(r) for r in con.execute("SELECT * FROM routes ORDER BY t_arr DESC")]
    events = [dict(e) for e in con.execute("SELECT * FROM events ORDER BY t_start DESC")]
    outages = [dict(o) for o in con.execute("SELECT * FROM outages ORDER BY t_start DESC LIMIT 50")]

    def vlink(mmsi, depth):
        k = m2k.get(mmsi, f"mmsi{mmsi}")
        return f'<a href="{"../" * depth}gemiler/{k}.html">{E(names.get(mmsi, str(mmsi)))}</a>'

    # ---------- Genel bakış ----------
    active_tr = sum(1 for t in tracking.values() if t["status"] == "active")
    stats = [(len({v["mmsi"] for v in visits}), "farklı gemi limanlara uğradı"),
             (active_tr, "gemi şu an takipte"),
             (sum(1 for e in events if e["kind"] != "spoof"), "işaretlenen olay"),
             (len(days), "arşivlenmiş gün")]
    if cfg.directions:
        stats.insert(2, (len(routes), "beyanla çelişen hareket"))
    body = [f"<h1>{E(cfg.name)}</h1><p class='lede'>{E(cfg.description)}</p>",
            "<div class='stats'>" + "".join(f"<div class='stat'><b>{n}</b><span>{E(t)}</span></div>" for n, t in stats) + "</div>"]
    if cfg.directions and routes:
        body.append("<h2>Beyan testi: son hareketler</h2>")
        body.append(_route_table(cfg, routes[:8], vlink, port_name, 0))
        body.append('<p class="small"><a href="beyan.html">Tüm hareketler ve aylık rapor →</a></p>')
    body.append("<h2>Limanlar</h2><div class='cards'>")
    for p in cfg.ports:
        img = ""
        md = map_day(p.code)
        if md:
            img = (f'<a href="limanlar/{p.code}.html"><img src="arsiv/{md}/{p.code}.png" alt="{E(p.name)} haritası, {md}" '
                   f'loading="lazy"></a><p class="small muted">Gemi görülen son gün: {md}</p>')
        n_vis = sum(1 for v in visits if v["port"] == p.code)
        role = "İzlenen liman" if p.role == "izlenen" else "Varış kontrol limanı"
        body.append(f"<div class='card'><h3><a href='limanlar/{p.code}.html'>{E(p.name)}</a></h3>"
                    f"<p class='small muted'>{E(cfg.country_name(p.country))} · {role} · {n_vis} ziyaret</p>{img}</div>")
    body.append("</div>")
    if events:
        body.append("<h2>Son işaretler</h2>")
        body.append(_tbl(["Tür", "Gemi", "Başlangıç", "Ayrıntı"], [
            [f'<span class="chip w">{EVENT_LABELS[e["kind"]]}</span>', vlink(e["mmsi"], 0),
             E(fmt_local(e["t_start"], tz)), _event_text(e, names)]
            for e in [x for x in events if x["kind"] != "spoof"][:10]]))
    if outages:
        body.append("<h2>Veri kesintileri</h2><p class='small muted'>Toplayıcının veri alamadığı süreler. "
                    "Bu aralıklarda olan hareketler kayıtlarda görünmez.</p>")
        body.append(_tbl(["Bağlantı", "Başlangıç", "Bitiş", "Sebep"], [
            [E(o["conn"]), E(fmt_local(o["t_start"], tz)), E(fmt_local(o["t_end"], tz)) if o["t_end"] else "sürüyor",
             E(o["reason"] or "")] for o in outages[:10]]))
    _write(out / "index.html", _page(cfg, "Genel bakış", "".join(body), 0, "home"))

    # ---------- Limanlar ----------
    cards = []
    for p in cfg.ports:
        pv = [v for v in visits if v["port"] == p.code]
        rows = [[vlink(v["mmsi"], 1), E(fmt_local(v["t_in"], tz)),
                 E(fmt_local(v["t_out"], tz)) if v["t_out"] else "<span class='chip'>limanda</span>",
                 E(v["terminal"] or "–"), _draught(v["draught_in"], v["draught_out"]), E(v["dest_out"] or "–")]
                for v in pv[:200]]
        arch = [[E(d), f'<a href="../arsiv/{d}/{p.code}.png">harita</a> · <a href="../arsiv/{d}/{p.code}.csv">CSV</a> · '
                       f'<a href="../arsiv/{d}/{p.code}.json">JSON</a>'] for d in days]
        md = map_day(p.code)
        img = f'<img src="../arsiv/{md}/{p.code}.png" alt="{E(p.name)} haritası, {md}"><p class="small muted">{md}</p>' if md else ""
        terms = ", ".join(f"{E(t.name)} ({E(t.cargo)})" for t in p.terminals) or "tanımlı değil"
        b = (f"<h1>{E(p.name)}</h1><p class='lede'>{E(cfg.country_name(p.country))} · "
             f"{'İzlenen liman: uğrayan her gemi takibe alınır.' if p.role == 'izlenen' else 'Varış kontrol limanı: buraya varan gemiler kaydedilir.'}"
             f"<br><span class='small'>Terminaller: {terms}</span></p>"
             f"<div class='card'>{img}</div><h2>Ziyaretler</h2>"
             + _tbl(["Gemi", "Giriş", "Çıkış", "Terminal", "Su çekimi", "Beyan edilen varış"], rows)
             + "<h2>Günlük arşiv</h2>" + _tbl(["Gün", "Dosyalar"], arch))
        _write(out / "limanlar" / f"{p.code}.html", _page(cfg, p.name, b, 1, "ports"))
        cards.append([f"<a href='{p.code}.html'>{E(p.name)}</a>", E(cfg.country_name(p.country)),
                      "İzlenen" if p.role == "izlenen" else "Varış kontrol", str(len(pv))])
    _write(out / "limanlar" / "index.html", _page(cfg, "Limanlar", "<h1>Limanlar</h1>" + _tbl(
        ["Liman", "Ülke", "Rol", "Ziyaret"], cards), 1, "ports"))

    # ---------- Gemiler ----------
    keys = defaultdict(set)
    for v in visits:
        keys[m2k.get(v["mmsi"], f"mmsi{v['mmsi']}")].add(v["mmsi"])
    for r in routes:
        keys[r["vkey"]].add(r["mmsi"])
    list_rows = []
    for key, mmsis in sorted(keys.items()):
        mm = sorted(set(mmsis) | set(k2m.get(key, [])))
        main = max(mm, key=lambda m: vessels.get(m, {}).get("last_seen") or "")
        vs = vessels.get(main, {})
        tr = next((tracking[m] for m in mm if m in tracking), None)
        vvis = [v for v in visits if v["mmsi"] in mm]
        vevs = [e for e in events if e["mmsi"] in mm or e["mmsi2"] in mm]
        vroutes = [r for r in routes if r["mmsi"] in mm or r["via_mmsi"] in mm]
        group = ship_group(vs.get("type"))
        hz = hazard_category(vs.get("type"))
        hist = json.loads(vs.get("history") or "[]")
        ident = [["Ad", E(vs.get("name") or "–")], ["IMO", E(str(vs.get("imo") or "–"))],
                 ["MMSI", E(", ".join(map(str, mm)))], ["Çağrı işareti", E(vs.get("callsign") or "–")],
                 ["Tip", E(SHIP_GROUP_LABELS[group]) + (f" · tehlikeli yük kat. {E(hz)}" if hz else "")],
                 ["Boy", f"{vs.get('length'):.0f} m" if vs.get("length") else "–"],
                 ["Son beyan edilen varış", E(vs.get("dest") or "–")],
                 ["Takip", (f"{'Aktif' if tr['status'] == 'active' else 'Bitti'} · {E(fmt_local(tr['start'], tz))} → "
                            f"{E(fmt_local(tr['ended'] or tr['until'], tz))}"
                            + (f" ({E(tr['end_reason'])})" if tr.get('end_reason') else "")) if tr else "–"]]
        b = [f"<h1>{E(vs.get('name') or 'MMSI ' + str(main))}</h1>",
             "<div class='tbl'><table><tbody>" + "".join(f"<tr><th>{k}</th><td>{v}</td></tr>" for k, v in ident) + "</tbody></table></div>"]
        if hist:
            b.append("<h2>Kimlik değişiklikleri</h2>" + _tbl(["Zaman", "Alan", "Eski", "Yeni"], [
                [E(fmt_local(h["t"], tz)), E(h["alan"]), E(str(h["eski"])), E(str(h["yeni"]))] for h in hist]))
        if vroutes:
            b.append("<h2>Beyanla ilgili hareketler</h2>" + _route_table(cfg, vroutes, vlink, port_name, 1, detail=True))
        b.append("<h2>Liman ziyaretleri</h2>" + _tbl(["Liman", "Giriş", "Çıkış", "Terminal", "Su çekimi", "Beyan edilen varış"], [
            [E(port_name.get(v["port"], v["port"])), E(fmt_local(v["t_in"], tz)),
             E(fmt_local(v["t_out"], tz)) if v["t_out"] else "limanda", E(v["terminal"] or "–"),
             _draught(v["draught_in"], v["draught_out"]), E(v["dest_out"] or "–")] for v in vvis]))
        if vevs:
            b.append("<h2>İşaretler</h2>" + _tbl(["Tür", "Başlangıç", "Bitiş", "Konum", "Ayrıntı"], [
                [f'<span class="chip w">{EVENT_LABELS[e["kind"]]}</span>', E(fmt_local(e["t_start"], tz)),
                 E(fmt_local(e["t_end"], tz)), f'<span class="mono">{e["lat"]:.3f}, {e["lon"]:.3f}</span>' if e["lat"] is not None else "–",
                 _event_text(e, names)] for e in vevs]))
        _write(out / "gemiler" / f"{key}.html", _page(cfg, vs.get("name") or key, "".join(b), 1, "ships"))
        list_rows.append((tr is not None and tr["status"] == "active", vs.get("last_seen") or "",
                          [f"<a href='{key}.html'>{E(vs.get('name') or 'MMSI ' + str(main))}</a>",
                           E(str(vs.get("imo") or "–")), E(SHIP_GROUP_LABELS[group]), str(len(vvis)),
                           "<span class='chip'>takipte</span>" if tr and tr["status"] == "active" else "",
                           str(len(vroutes)) if vroutes else "", E(fmt_local(vs.get("last_seen"), tz))]))
    list_rows.sort(key=lambda x: (x[0], x[1]), reverse=True)
    _write(out / "gemiler" / "index.html", _page(cfg, "Gemiler", "<h1>Gemiler</h1><p class='lede'>Limanlara uğrayan "
           "ve takip edilen tüm gemiler. Gemiler IMO numarasıyla tanınır; ad veya MMSI değişirse aynı sayfada kalır.</p>"
           + _tbl(["Gemi", "IMO", "Tip", "Ziyaret", "Durum", "Beyan hareketi", "Son görülme"], [r[2] for r in list_rows]),
           1, "ships"))

    # ---------- Beyan testi ----------
    if cfg.directions:
        d = cfg.declaration
        b = ["<h1>Beyan testi</h1>"]
        if d.get("metin"):
            b.append(f"<div class='quote'>{E(d['metin'])}<div class='small muted'>{E(d.get('tarih') or '')} "
                     f"{('· ' + E(d['kaynak'])) if d.get('kaynak') else ''}</div></div>")
        for a in d.get("aciklamalar") or []:
            src = E(a.get("kaynak") or "")
            if a.get("url"):
                src = f"<a href='{E(a['url'])}' rel='noopener'>{src or 'kaynak'}</a>"
            b.append(f"<div class='quote'>“{E(a.get('metin', ''))}”<div class='small muted'>{E(a.get('kim') or '')} · "
                     f"{E(a.get('tarih') or '')} · {src}</div></div>")
        if d.get("karsi_gorus"):
            b.append(f"<h3>Resmî yanıtlar ve karşı görüş</h3><p class='small'>{E(d['karsi_gorus'])}</p>")
        b.append("<p class='lede'>Aşağıdaki tablolar, beyanda adı geçen ülkelerin limanları arasında AIS kayıtlarına "
                 "göre gerçekleşen gemi hareketlerini gösterir. Sayılar gemi hareketidir; yükün kendisi yalnızca "
                 "dayanaklarıyla birlikte 'muhtemel' olarak verilir.</p>")
        for (A, B) in cfg.directions:
            dr = [r for r in routes if r["direction"] == f"{A}>{B}"]
            months = sorted({r["t_arr"][:7] for r in dr}, reverse=True)
            cnt = Counter((r["t_arr"][:7], r["cls"]) for r in dr)
            b.append(f"<h2>{E(cfg.country_name(A))} → {E(cfg.country_name(B))}</h2>")
            b.append(_tbl(["Ay"] + [CLASS_SHORT[c] for c in CLASS_ORDER] + ["Toplam"], [
                [E(m)] + [str(cnt.get((m, c), 0) or "–") for c in CLASS_ORDER] + [f"<b>{sum(cnt.get((m, c), 0) for c in CLASS_ORDER)}</b>"]
                for m in months]))
            b.append("<p class='small muted'>Doğrudan*: çıkış ve varış kayıtlı, ara güzergâh izlenemedi. "
                     "Sınıfların tanımı <a href='yontem.html'>Yöntem</a> sayfasında.</p>")
            b.append("<h3>Hareketler</h3>" + _route_table(cfg, dr, vlink, port_name, 0, detail=True))
        _write(out / "beyan.html", _page(cfg, "Beyan testi", "".join(b), 0, "decl"))

    # ---------- Geçmiş tarama (Global Fishing Watch) ----------
    if cfg._has_gecmis:
        _write(out / "gecmis.html", _page(cfg, "Geçmiş tarama", _gecmis_body(cfg, gecmis_rows, gecmis_state), 0, "retro"))
        _write(out / "veri" / "gecmis.json", json.dumps(gecmis_rows, ensure_ascii=False, indent=1))

    # ---------- Kanıt zinciri ----------
    rows = [[E(c["gun"]), f'<span class="mono">{c["gun_hash"]}</span>', f'<span class="mono">{c["kayit_hash"][:16]}…</span>',
             "evet" if c.get("opentimestamps") else "hayır",
             f'<a href="arsiv/{c["gun"]}/MANIFEST.sha256">manifest</a> · <a href="arsiv/{c["gun"]}/ozet.json">özet</a>'
             f' · <a href="{ham_url(c["gun"])}">ham veri</a>'
             + (f' · <a href="arsiv/{c["gun"]}/MANIFEST.sha256.ots">.ots</a>' if c.get("opentimestamps") else "")]
            for c in reversed(chain)]
    b = ("<h1>Kanıt zinciri</h1><p class='lede'>Her gün bittiğinde o günün bütün dosyaları (ham AIS mesajları, ziyaret "
         "listeleri, haritalar, olaylar) tek tek SHA-256 ile hash'lenir. Bu listenin hash'i 'gün hash'idir'. Her gün bir "
         "önceki günün kaydına bağlanır; geçmişteki tek bir bayt değişirse zincir kırılır. OpenTimestamps açıksa gün hash'i "
         "Bitcoin blok zincirine damgalanır ve dosyanın o tarihte var olduğu bağımsız olarak kanıtlanır.</p>"
         "<h2>Nasıl doğrularım?</h2><ol class='small'>"
         "<li>Bir günün klasöründen dosyaları, <span class='mono'>MANIFEST.sha256</span> dosyasını ve 'ham veri' bağlantısındaki "
         "<span class='mono'>ham.jsonl.gz</span> dosyasını aynı klasöre indir.</li>"
         "<li>Linux/Mac'te klasörde <span class='mono'>sha256sum -c MANIFEST.sha256</span> çalıştır; her satır OK olmalı.</li>"
         "<li><span class='mono'>sha256sum MANIFEST.sha256</span> sonucu aşağıdaki gün hash'iyle aynı olmalı.</li>"
         "<li>Damga varsa <span class='mono'>ots verify MANIFEST.sha256.ots</span> ile Bitcoin kaydını kontrol et.</li>"
         "<li>Ham veri <span class='mono'>ham.jsonl.gz</span> dosyasındadır; harita ve tablolar bundan yeniden üretilebilir.</li></ol>"
         f"<p class='small'>Zincirin tamamı: <a href='kanit/zincir.jsonl'>zincir.jsonl</a></p>"
         + _tbl(["Gün", "Gün hash'i (SHA-256)", "Zincir kaydı", "Bitcoin damgası", "Dosyalar"], rows))
    _write(out / "kanit.html", _page(cfg, "Kanıt zinciri", b, 0, "proof"))

    # ---------- Yöntem ----------
    th = cfg.th
    b = f"""<h1>Yöntem ve sınırlar</h1>
<h2>Veri</h2><p>Gemilerin kendi yayınladığı AIS mesajları <a href="https://aisstream.io">aisstream.io</a> üzerinden 7/24 toplanır.
Her mesaj değiştirilmeden günlük ham dosyaya yazılır. Limanların çevresindeki tüm gemiler ve takipteki gemiler dinlenir.</p>
<h2>Ziyaret</h2><p>Bir gemi liman alanına girip en az {th['ziyaret_min_dakika']} dakika kalır ve bu sürede en az bir kez durursa
(hız &lt; {th['durma_hizi_knot']} knot) ziyaret sayılır. Durmadan geçenler sayılmaz. Gemiden {th['cikis_tolerans_dakika']} dakika
ses gelmezse çıkmış kabul edilir.</p>
<h2>Takip</h2><p>İzlenen bir limana uğrayan her gemi {th['takip_gun']} gün boyunca dünya genelinde izlenir. Beyan testi
açıkken takip ara ülkelerde bitmez; yalnızca hedef ülkeye varınca veya süre dolunca biter. Aynı anda izlenebilecek gemi sayısı
sınırlı olduğundan tankerler, varış beyanı şüpheli olanlar, daha önce hedef ülkeye gitmiş olanlar ve denizde takipli bir gemiyle
buluşan gemiler önceliklidir. Denizde takipli bir gemiyle buluşan gemi de otomatik olarak takibe alınır.</p>
<h2>İşaretler</h2><ul>
<li><b>AIS boşluğu:</b> limanlardan {th['liman_uzaklik_km']} km'den uzakta {th['ais_bosluk_saat']} saatten uzun sinyal yok.
Bizim toplayıcımızın kapalı olduğu süreler hariç tutulur. Açık denizde alıcı kapsaması zayıf olabilir; boşluk tek başına
AIS'in kapatıldığını kanıtlamaz.</li>
<li><b>Liman dışı durak:</b> liman dışında {th['durak_sure_saat']} saatten uzun durma.</li>
<li><b>Denizde buluşma:</b> iki takipli gemi {th['sts_mesafe_m']} m'den yakın ve duruk hâlde {th['sts_sure_saat']} saatten uzun.
Yalnızca iki gemi de izleniyorsa görülebilir.</li>
<li><b>Limansız su çekimi değişimi:</b> liman ziyareti olmadan su çekiminde {th['draft_degisim_m']} m'den büyük değişim.</li>
<li><b>Konum tutarsızlığı:</b> geminin konumu bir önceki kayda göre fiziksel olarak imkânsız bir hızla (60 knot üstü) sıçradı.
GPS karıştırma veya sahte konum yayını olabilir. Bu konumlar ham arşive yazılır ama analizde kullanılmaz.</li></ul>
<h2>Beyan testi sınıfları</h2><ul>
<li><b>Doğrudan:</b> A ülkesi limanından çıkış, kesintisiz izleme, B ülkesi limanına varış.</li>
<li><b>Doğrudan (ara güzergâh izlenemedi):</b> çıkış ve varış kayıtlı, ara yol izlenemedi.</li>
<li><b>Ara duraklı:</b> arada üçüncü bir limana veya açık denizde uzun durağa uğradı.</li>
<li><b>Karanlık bacak:</b> yol sırasında AIS boşluğu var.</li>
<li><b>Denizde buluşma:</b> yol sırasında başka bir gemiyle yan yana durdu.</li>
<li><b>Dolaylı:</b> A'dan çıkan gemi denizde başka bir gemiyle buluştu; o gemi B'ye vardı.</li>
<li><b>Hedef ülke kıyısında AIS kapandı:</b> gemi B ülkesinin kıyı yaklaşma alanına girdi, hiçbir limanda kaydı yok ve ardından en az
{th['yaklasma_sessizlik_saat']} saat sinyal vermedi.</li>
<li><b>Karanlık sefer:</b> gemi A'dan çıktı, B'de hiçbir kaydı yok, ama izlenen deniz bölgesinde en az {th['karanlik_sefer_saat']} saat
AIS boşluğu var. Boşluktan sonra su çekimi düştüyse yük boşaltılmış olabilir. Bu sınıftaki kayıtlar için hedef ülke limanlarının
o tarihlerdeki uydu görüntülerine bağlantı verilir; görüntülerin incelenmesi elle yapılmalıdır.</li></ul>
<p>Bir hareket {th['guzergah_max_gun']} günden uzun sürdüyse sayılmaz. <b>Varış beyanı farklı</b> işareti, gemi A'dan çıkarken
AIS'e yazdığı varış noktasının B ülkesini göstermediği anlamına gelir.</p>
<h2>Muhtemel yük</h2><p>Gemi tipi, yanaştığı terminal ve limanlardaki su çekimi değişiminden çıkarılır; dayanakları her
harekette listelenir. Üç veya daha fazla dayanak uyuşuyorsa güven 'yüksek', iki ise 'orta', biri ise 'düşük'tür.
Su çekimi mürettebatın elle girdiği bir değerdir ve güncellenmeyebilir. Konteyner gemilerinin içeriği bu yöntemle bilinemez.</p>
<h2>Uydu bağlantıları</h2><p>Bağlantılar Copernicus Browser'ı ilgili konum ve tarih aralığında açar. Sentinel-1 (radar) bulut ve
geceden etkilenmez, gemiler parlak noktalar olarak görünür; Sentinel-2 (optik) bulutsuz günlerde gerçek renkli görüntü verir.
Uydular bir noktadan genellikle birkaç günde bir geçer; her tarih için görüntü olmayabilir. Tarayıcı açıldığında katman seçmek
gerekebilir.</p>
<h2>Sınırlar</h2><ul><li>AIS'i tamamen kapalı olan veya sahte konum yayınlayan gemiler görülmez.</li>
<li>Kayıtlar gemi hareketini gösterir; ticaretin yasal olup olmadığı hakkında hüküm vermez.</li>
<li>Veri kesintileri ana sayfada ve her günün arşivinde (<span class='mono'>kesintiler.json</span>) yayımlanır.</li></ul>"""
    _write(out / "yontem.html", _page(cfg, "Yöntem", b, 0, "method"))

    # ---------- Ham JSON dışa aktarım + paylaşım taslakları ----------
    _write(out / "veri" / "guzergahlar.json", json.dumps(routes, ensure_ascii=False, indent=1))
    _write(out / "veri" / "olaylar.json", json.dumps(events, ensure_ascii=False, indent=1))
    _write(out / "veri" / "paylasim_taslaklari.json", json.dumps(_share_drafts(cfg, routes, days, chain, port_name),
                                                                  ensure_ascii=False, indent=1))
    _write(out / "_headers", "/arsiv/*\n  Cache-Control: public, max-age=31536000, immutable\n")


def _route_table(cfg, routes, vlink, port_name, depth, detail=False) -> str:
    tz = cfg.tz
    rows = []
    for r in routes:
        flags = json.loads(r["flags"] or "{}")
        chips = [f'<span class="chip{" w" if r["cls"] != "dogrudan_izlenmedi" else ""}">{E(CLASS_LABELS[r["cls"]])}</span>']
        if flags.get("karanlik_saat"):
            chips.append(f'<span class="chip w">{flags["karanlik_saat"]} saat AIS kapalı</span>')
        if flags.get("draft_dustu"):
            chips.append('<span class="chip w">Sonra su çekimi düştü</span>')
        if flags.get("sessizlik_saat"):
            chips.append(f'<span class="chip w">Kıyıda {flags["sessizlik_saat"]} saat sessizlik</span>')
        if r["masked"]:
            chips.append(f'<span class="chip w">Varış beyanı farklı: {E(r["dest_text"] or "")}</span>')
        elif flags.get("varis_beyani") == "bos":
            chips.append('<span class="chip">Varış beyanı boş</span>')
        via = ""
        if r["via_mmsi"]:
            via = f"<div class='small muted'>Yükü veren: {vlink(r['via_mmsi'], depth)}</div>"
        mids = json.loads(r["mids"] or "[]")
        mid = "<div class='small muted'>Ara: " + ", ".join(E(m["liman"]) for m in mids) + "</div>" if mids and detail else ""
        sat = ""
        if detail and r["cls"] in ("karanlik_sefer", "kiyida_kayboldu", "karanlik_bacak", "denizde_aktarma", "dolayli_sts"):
            sat = sat_links(cfg, r["t_dep"], r["t_arr"])
        if r["dest_port"]:
            dest = f"{E(port_name.get(r['dest_port'], r['dest_port']))}<div class='small muted'>{E(fmt_local(r['t_arr'], tz))}</div>"
        else:
            nxt = flags.get("sonraki_liman")
            dest = ("<i>Bilinmiyor</i><div class='small muted'>AIS yeniden açıldı: " + E(fmt_local(r["t_arr"], tz))
                    + (f"<br>Sonraki kayıtlı liman: {E(nxt)}" if nxt else "") + "</div>")
        cargo = f"{E(r['cargo'] or '–')} <span class='chip'>güven: {E(r['cargo_conf'] or '–')}</span>"
        if detail:
            cargo += "<ul class='basis'>" + "".join(f"<li>{E(x)}</li>" for x in json.loads(r["cargo_basis"] or "[]")) + "</ul>"
        rows.append([vlink(r["mmsi"], depth) + via,
                     f"{E(port_name.get(r['origin_port'], r['origin_port']))}<div class='small muted'>{E(fmt_local(r['t_dep'], tz))}</div>",
                     dest, "".join(chips) + mid + sat, cargo])
    return _tbl(["Gemi", "Çıkış", "Varış", "Sınıf", "Muhtemel yük"], rows)


def _share_drafts(cfg, routes, days, chain, port_name) -> list[dict]:
    """Tweet veya başka paylaşımlar için hazır metinler (otomatik gönderilmez)."""
    out = []
    if chain:
        c = chain[-1]
        out.append({"tur": "gunluk_ozet", "gun": c["gun"],
                    "metin": f"{cfg.name} · {c['gun']} arşivi mühürlendi.\nGün hash'i: {c['gun_hash'][:16]}…"})
    for r in routes[:20]:
        out.append({"tur": "beyan_hareketi", "id": r["id"], "metin": (
            f"{r['name']}: {port_name.get(r['origin_port'])} ({fmt_local(r['t_dep'], cfg.tz)[:10]}) → "
            f"{port_name.get(r['dest_port']) or 'varış limanı kayıtsız (AIS kapalı)'} ({fmt_local(r['t_arr'], cfg.tz)[:10]})\n"
            f"Sınıf: {CLASS_LABELS[r['cls']]}\nMuhtemel yük: {r['cargo']} (güven: {r['cargo_conf']})\n"
            "Bu bir tespittir, hüküm değildir.")})
    return out


def _gecmis_body(cfg, rows, st) -> str:
    from .gecmis import CLASS_LABELS as GL
    tz = cfg.tz
    t = st.get("hedef") or {}
    done, total = (st.get("gorev") or [0, 0])
    prog = ("Tarama tamamlandı." if st.get("tamam") else
            f"Tarama sürüyor: {done} / {total} sorgu tamam. Her saatlik çalıştırmada kaldığı yerden devam eder.")
    b = [f"<h1>Geçmiş tarama</h1><p class='lede'>{E(t.get('baslangic', '?'))} – {E(t.get('bitis', '?'))} arası. Kaynak: "
         "<a href='https://globalfishingwatch.org'>Global Fishing Watch</a> liman ziyareti ve AIS boşluğu verileri "
         "(AIS'ten üretilmiş, ticari olmayan kullanım için açık veri). " + E(prog) + "</p>",
         "<p class='small'><a href='https://globalfishingwatch.org'>Powered by Global Fishing Watch.</a> "
         "Veri lisansı: CC BY-NC 4.0, ticari olmayan kullanım.</p>"
         "<p class='small muted'>Bu sayfa canlı arşivden ayrıdır: kayıtlar GFW'nin hesapladığı olaylara dayanır, bu sitenin "
         "kanıt zincirinde ham verisi yoktur. Her kaydın uydu bağlantılarıyla elle doğrulanması önerilir.</p>"]
    for (A, B) in cfg.directions:
        dr = [r for r in rows if r["direction"] == f"{A}>{B}"]
        b.append(f"<h2>{E(cfg.country_name(A))} → {E(cfg.country_name(B))}</h2>")
        months = sorted({(r["t_arr"] or r["t_dep"] or "")[:7] for r in dr}, reverse=True)
        cnt = Counter(((r["t_arr"] or r["t_dep"] or "")[:7], r["cls"]) for r in dr)
        b.append(_tbl(["Ay"] + list(GL.values()) + ["Toplam"], [
            [E(m)] + [str(cnt.get((m, c), 0) or "–") for c in GL] + [f"<b>{sum(cnt.get((m, c), 0) for c in GL)}</b>"]
            for m in months]))
        trs = []
        for r in dr:
            gaps = json.loads(r["gaps"] or "[]")
            mids = json.loads(r["mids"] or "[]")
            chips = f'<span class="chip w">{E(GL[r["cls"]])}</span>'
            for g in gaps[:3]:
                chips += f'<span class="chip w">{g["saat"]} saat AIS kapalı</span>'
            extra = ("<div class='small muted'>Ara: " + ", ".join(E(m["liman"]) for m in mids) + "</div>") if mids else ""
            pts = [("Kapanış noktası", tuple(g["kapanis"])) for g in gaps[:1] if None not in g["kapanis"]]
            t0 = gaps[0]["baslangic"] if gaps else r["t_dep"]
            t1 = gaps[0]["bitis"] if gaps else r["t_arr"]
            sat = sat_links(cfg, t0, t1, pts) if (gaps or r["cls"] != "dogrudan") else ""
            dest = (f"{E(r['dest'])}<div class='small muted'>{E(fmt_local(r['t_arr'], tz))}</div>" if r["dest"] else
                    "<i>Bilinmiyor</i><div class='small muted'>AIS yeniden açıldı: " + E(fmt_local(r["t_arr"], tz))
                    + (f"<br>Sonraki liman: {E(r['next_port'])}" if r["next_port"] else "") + "</div>")
            trs.append([f"{E(r['name'] or '?')}<div class='small muted'>MMSI {E(str(r['ssvid'] or '?'))} · "
                        f"{E(r['flag'] or '?')} · {E(r['vtype'] or '?')}</div>",
                        f"{E(r['origin'])}<div class='small muted'>{E(fmt_local(r['t_dep'], tz))}</div>",
                        dest, chips + extra + sat])
        b.append("<h3>Kayıtlar</h3>" + _tbl(["Gemi", "Çıkış", "Varış", "Sınıf ve ayrıntı"], trs))
    return "".join(b)
