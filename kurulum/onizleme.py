"""Önizleme: siteyi yerelde sunar, gerçek tarayıcıda açar, ekran görüntüsü ve tarayıcı kayıtlarını _onizleme/ klasörüne yazar.

GitHub Actions'taki "Önizleme" iş akışı çalıştırır; sonuçlar 'onizleme' dalına gönderilir.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path("_onizleme")
OUT.mkdir(exist_ok=True)
SERVERS = {"gercek": ("site", 8001), "demo": ("demo/site", 8002)}


def db_ozet() -> dict:
    """Veritabanının kısa özeti: canlı katman boş kalırsa nedenini görmek için."""
    import sqlite3
    sys.path.insert(0, ".")
    from liman.config import load
    from liman.db import db_path
    path = db_path(load("config.yaml"))
    if not path.exists():
        return {"hata": f"{path} yok"}
    con = sqlite3.connect(path)
    q = lambda sql: [list(r) for r in con.execute(sql)]  # noqa: E731
    out = {
        "konum": q("SELECT count(*), sum(port IS NOT NULL), min(t), max(t) FROM positions"),
        "gemi": q("SELECT count(*) FROM vessels"),
        "ziyaret": q("SELECT port, count(*), sum(transit=1), sum(status='open') FROM visits GROUP BY port"),
        "takip": q("SELECT status, coalesce(end_reason,''), count(*) FROM tracking GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 20"),
        "sefer": q("SELECT direction, cls, count(*) FROM routes GROUP BY 1, 2"),
        "olay": q("SELECT kind, count(*) FROM events GROUP BY 1"),
        "gecmis": q("SELECT direction, cls, count(*), min(t_dep), max(t_arr) FROM gecmis GROUP BY 1, 2"),
        "iz": q("SELECT count(*), count(DISTINCT mmsi), min(day), max(day) FROM izler"),
        "gfw_onbellek": q("SELECT substr(key, 1, instr(key, ':') - 1), count(*) FROM gfw_cache GROUP BY 1"),
        "kesinti": q("SELECT conn, count(*), round(sum((julianday(coalesce(t_end, t_start)) - julianday(t_start)) * 24), 1) "
                     "FROM outages GROUP BY 1"),
        "meta": q("SELECT k, substr(v, 1, 300) FROM meta WHERE k LIKE 'gecmis%' OR k LIKE 'son%'"),
    }
    # tanı: İskenderun Körfezi alan sorgularında Ceyhan çevresindeki liman ziyaretleri
    import json as _j, math, collections
    def km(a, b, c, d):
        return 6371 * math.acos(min(1, math.sin(math.radians(a)) * math.sin(math.radians(c))
                                    + math.cos(math.radians(a)) * math.cos(math.radians(c)) * math.cos(math.radians(b - d))))
    yak, tip, nokta, gemi = collections.Counter(), collections.Counter(), collections.Counter(), set()
    for (data,) in con.execute("SELECT data FROM gfw_cache WHERE key LIKE 'area_pv:ISK:%'"):
        for e in _j.loads(data):
            pos = e.get("position") or {}
            if pos.get("lat") is None:
                continue
            dkm = km(pos["lat"], pos["lon"], 36.875, 35.925)
            yak[int(dkm // 2) * 2 if dkm < 20 else 99] += 1
            if dkm < 12:
                tip[str((e.get("vessel") or {}).get("type"))] += 1
                nokta[(round(pos["lat"], 2), round(pos["lon"], 2))] += 1
                gemi.add((e.get("vessel") or {}).get("id"))
    cached = {r[0].split(":")[1] for r in con.execute("SELECT key FROM gfw_cache WHERE key LIKE 'v_pv:%'")}
    out["ceyhan_tani"] = {"uzaklik_km": sorted(yak.items()), "tip": tip.most_common(8),
                          "nokta": [list(k) + [v] for k, v in nokta.most_common(10)],
                          "gemi": len(gemi), "gecmisi_alinan": len(gemi & cached)}
    try:
        out["tanker_tani"] = tanker_tani(con, cached)
    except Exception as e:  # noqa: BLE001
        out["tanker_tani"] = {"hata": repr(e)}
    con.close()
    return out


def tanker_tani(con, cached: set) -> dict:
    """Tanker dosyalarının sağlaması: basında adı geçen tankerler veride var mı, Ceyhan çıkışlarından sonra ne oldu?"""
    import json as _j, collections
    from liman.gecmis import CEYHAN
    from liman.geo import haversine_km
    isimler = {"KIMOLOS", "SEAVIGOUR", "NISSOS TINOS"}
    meta = dict(con.execute("SELECT k, v FROM meta WHERE k IN ('ceyhan_cikislari')").fetchall())
    cik = _j.loads(meta.get("ceyhan_cikislari") or "[]")
    out: dict = {"cikis": len(cik), "gemi": len({x["vid"] for x in cik})}
    ulke = collections.Counter(x.get("ulke") or "?" for x in cik)
    out["sonraki_ulke"] = ulke.most_common(15)
    bos = [g for x in cik for g in x.get("bosluk") or []]
    out["bosluk"] = {"cikis_bosluklu": sum(1 for x in cik if x.get("bosluk")), "bosluk": len(bos),
                     "il_kutusu": sum(1 for g in bos if g.get("il")),
                     "kasitli": collections.Counter(str(g.get("kasitli")) for g in bos).most_common(),
                     "saat_dagilim": collections.Counter(min(int((g.get("saat") or 0) // 24), 10) for g in bos).most_common()}
    out["acik_bekleme"] = sum(1 for x in cik if x.get("acik"))
    out["gecmis_sinif"] = [list(r) for r in con.execute(
        "SELECT cls, count(*), count(DISTINCT vessel_id) FROM gecmis WHERE direction='TR>IL' GROUP BY cls")]
    # basındaki adlar: alan sorgularında (Ceyhan'a uğrayanlar) ve gemi geçmişlerinde
    bul: dict = {}
    for key, data in con.execute("SELECT key, data FROM gfw_cache WHERE key LIKE 'area_pv:ISK:%' OR key LIKE 'v_pv:%'"):
        for e in _j.loads(data) or []:
            v = e.get("vessel") or {}
            n = (v.get("name") or "").upper().strip()
            if n not in isimler:
                continue
            b = bul.setdefault(n, {}).setdefault(v.get("id"), {"ssvid": v.get("ssvid"), "bayrak": v.get("flag"),
                                                                 "tip": v.get("type"), "ceyhan": set(), "gecmis": False})
            pos = e.get("position") or {}
            if pos.get("lat") is not None and haversine_km(pos["lat"], pos["lon"], *CEYHAN) <= 11:
                b["ceyhan"].add((e.get("start") or "")[:10])
            if key.startswith("v_pv:"):
                b["gecmis"] = True
    for n, vs in bul.items():
        for vid, b in vs.items():
            b["ceyhan"] = sorted(b["ceyhan"])
            b["gecmisi_alinan"] = vid in cached
            b["cikislar"] = [{k: x.get(k) for k in ("t", "sonraki", "ulke", "t1", "karanlik", "bosluk", "acik", "sonrakiler")}
                             for x in cik if x.get("vid") == vid][:12]
            b["kayitlar"] = [list(r) for r in con.execute(
                "SELECT cls, origin, t_dep, dest, t_arr, next_port FROM gecmis WHERE vessel_id=? ORDER BY t_dep", (vid,))]
            # bütün AIS boşlukları ve liman ziyaretleri (sıralı), geçmişi alınmışsa
            bos, zi = [], []
            for key, data in con.execute("SELECT key, data FROM gfw_cache WHERE key LIKE ? OR key LIKE ?",
                                         (f"v_gap:{vid}:%", f"v_pv:{vid}:%")):
                for e in _j.loads(data) or []:
                    if key.startswith("v_gap"):
                        g = e.get("gap") or {}
                        off, on = g.get("offPosition") or {}, g.get("onPosition") or {}
                        bos.append([e.get("start"), e.get("end"), g.get("durationHours"), off.get("lat"), off.get("lon"),
                                    on.get("lat"), on.get("lon"), g.get("intentionalDisabling")])
                    else:
                        a = ((e.get("port_visit") or {}).get("startAnchorage") or {})
                        zi.append([e.get("start"), e.get("end"), a.get("name"), a.get("flag"),
                                   (e.get("position") or {}).get("lat"), (e.get("position") or {}).get("lon")])
            b["bosluklar"] = sorted({tuple(x) for x in bos}, key=lambda x: x[0] or "")
            b["ziyaretler"] = sorted({tuple(x) for x in zi}, key=lambda x: x[0] or "")
    out["basindaki"] = bul
    out["basinda_bulunmayan"] = sorted(isimler - set(bul))
    return out


def ornekler(site: str) -> list[tuple[str, str]]:
    """Gerçek veriden seçili sefer ve hat süzgeci örnekleri."""
    from urllib.parse import quote
    f = Path(site, "veri", "harita", "seferler.json")
    if not f.exists():
        return []
    recs = [r for r in json.loads(f.read_text(encoding="utf-8"))["kayitlar"] if r.get("y") == "TR>IL"]
    out = []
    for aile, ad in (("karanlik", "gercek-secili-karanlik"), ("liman", "gercek-secili-aktarma"), ("dogrudan", "gercek-secili-dogrudan")):
        r = next((x for x in reversed(recs) if x["a"] == aile and (x.get("kp") or aile != "karanlik")), None)
        if r:
            out.append((ad, f"sec={r['id']}"))
    r = next((x for x in reversed(recs) if x["a"] == "liman" and x.get("ara")), None)
    if r:
        out.append(("gercek-hat", "hat=" + quote(f"{r['o']}>{r['ara'][0]}")))
    return out


def biggest_ship(site: str) -> str | None:
    files = sorted(Path(site, "veri", "gemi").glob("*.json"), key=lambda p: p.stat().st_size, reverse=True)
    return files[0].stem if files else None


def main() -> int:
    procs = [subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1", "--directory", d],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for d, port in SERVERS.values()]
    time.sleep(1.5)
    real_ship = biggest_ship("site")
    shots = [
        ("gercek-ozet", "gercek", "index.html", 1280, 2400, "light", False),
        ("gercek-ozet-mobil", "gercek", "index.html", 390, 2000, "light", True),
        ("gercek-ozet-koyu", "gercek", "index.html", 1280, 1000, "dark", False),
        ("gercek-rapor", "gercek", "rapor/index.html", 1280, 2600, "light", False),
        ("gercek-rapor-en", "gercek", "rapor/en.html", 1280, 1400, "light", False),
        ("gercek-masaustu", "gercek", "harita.html", 1440, 900, "light", False),
        ("gercek-koyu", "gercek", "harita.html", 1440, 900, "dark", False),
        ("gercek-gecmis", "gercek", "harita.html#k=g", 1440, 900, "light", False),
        ("gercek-mobil", "gercek", "harita.html", 390, 844, "light", True),
        ("demo-masaustu", "demo", "harita.html", 1440, 900, "light", False),
        ("demo-secili", "demo", "harita.html#sec=c4", 1440, 900, "light", False),
        ("gercek-mobil-koyu", "gercek", "harita.html", 390, 844, "dark", True),
        ("demo-gemi", "demo", "gemiler/imo9000003.html", 1280, 1100, "light", False),
        ("gercek-beyan", "gercek", "beyan.html", 1280, 1300, "light", False),
        ("gercek-yontem", "gercek", "yontem.html", 1280, 1800, "light", False),
        ("gercek-raporlar", "gercek", "raporlar/index.html", 1280, 1400, "light", False),
        ("gercek-raporlar-mobil", "gercek", "raporlar/index.html", 390, 1400, "light", True),
        ("gercek-dunya", "gercek", "raporlar/dunya.html", 1280, 2200, "light", False),
        ("gercek-limanlar", "gercek", "limanlar/index.html", 1280, 1300, "light", False),
        ("gercek-gecmis-sayfa", "gercek", "gecmis.html", 1280, 1100, "light", False),
    ]
    if real_ship:
        shots.append(("gercek-gemi", "gercek", f"gemiler/{real_ship}.html", 1280, 1100, "light", False))
    shots += [("gercek-tankerler", "gercek", "tankerler/index.html", 1280, 1800, "light", False),
              ("gercek-tankerler-mobil", "gercek", "tankerler/index.html", 390, 1400, "light", True)]
    tf = Path("site", "veri", "tankerler.json")
    if tf.exists():
        ds = json.loads(tf.read_text(encoding="utf-8"))
        if ds:
            shots.append(("gercek-tanker-dosya", "gercek", f"tankerler/{ds[0]['dosya']}.html", 1280, 1800, "light", False))
    for name, frag in ornekler("site"):
        shots.append((name, "gercek", f"harita.html#{frag}", 1440, 900, "light", False))
    report = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        for name, srv, path, w, h, scheme, mobile in shots:
            ctx = browser.new_context(viewport={"width": w, "height": h}, color_scheme=scheme, device_scale_factor=1,
                                      is_mobile=mobile, has_touch=mobile, locale="tr-TR", timezone_id="Europe/Istanbul")
            page = ctx.new_page()
            logs = []
            page.on("console", lambda m: logs.append(f"{m.type}: {m.text}"[:500]))
            page.on("pageerror", lambda e: logs.append(f"pageerror: {e}"[:800]))
            page.on("requestfailed", lambda r: logs.append(f"requestfailed: {r.url[:160]} {r.failure}"))
            url = f"http://127.0.0.1:{SERVERS[srv][1]}/{path}"
            t0 = time.time()
            try:
                page.goto(url, wait_until="load", timeout=60000)
                try:
                    page.wait_for_function("window.__haritaHazir || !document.querySelector('#harita, #gemi-harita')",
                                           timeout=25000)
                except Exception:  # noqa: BLE001
                    logs.append("harita 25 sn içinde hazır olmadı")
                page.wait_for_timeout(1500)
                timing = page.evaluate("""() => {const n = performance.getEntriesByType('navigation')[0];
                    return {dom: Math.round(n.domContentLoadedEventEnd), yuk: Math.round(n.loadEventEnd),
                            harita: window.__haritaHazir || null,
                            kaynak: performance.getEntriesByType('resource').length}}""")
            except Exception as e:  # noqa: BLE001
                timing = {"hata": str(e)[:300]}
            page.screenshot(path=str(OUT / f"{name}.png"))
            report[name] = {"url": url, "sure_sn": round(time.time() - t0, 1), "zaman": timing, "kayit": logs[:60]}
            ctx.close()
        browser.close()
    sizes = {str(f.relative_to("site")): f.stat().st_size for f in Path("site/veri/harita").glob("*.json")}
    sizes.update({str(f.relative_to("site")): f.stat().st_size for f in Path("site/vendor").rglob("*") if f.is_file()})
    report["_boyutlar"] = sizes
    try:
        report["_veritabani"] = db_ozet()
    except Exception as e:  # noqa: BLE001
        report["_veritabani"] = {"hata": str(e)[:300]}
    (OUT / "rapor.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    for pr in procs:
        pr.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
