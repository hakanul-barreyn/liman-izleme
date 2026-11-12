"""Haritanın okuduğu JSON dosyaları.

veri/harita/alanlar.json   limanlar, kıyı alanı, dinleme alanları, karanlık sefer bölgesi (GeoJSON)
veri/harita/seferler.json  canlı kayıttan ve geçmiş taramadan bütün tespitler (kısa alan adlarıyla)
veri/harita/canli.json     takipteki gemilerin son konumu ve son 48 saatlik izi
veri/harita/olaylar.json   açık denizdeki olaylar ve son 3 günün sahte konumları
veri/gemi/<anahtar>.json   bir geminin bütün izi (zamanlı), ziyaretleri ve olayları
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from . import tracks
from .config import CARGO_LABELS
from .geo import haversine_km
from .gecmis import CLASS_LABELS as RETRO_LABELS
from .routes import CLASS_LABELS, vessel_keys
from .util import SHIP_GROUP_LABELS, add_hours, iso, now_utc, ship_group

FAMILY = {"dogrudan": "dogrudan", "dogrudan_izlenmedi": "dogrudan", "aktarmali": "liman",
          "denizde_aktarma": "sts", "dolayli_sts": "sts",
          "karanlik_bacak": "karanlik", "kiyida_kayboldu": "karanlik", "karanlik_sefer": "karanlik"}
FAMILY_LABELS = {"dogrudan": "Doğrudan", "liman": "Ara limanlı", "sts": "Gemiden gemiye",
                 "karanlik": "AIS kapatılmış"}
FAMILY_NOTES = {"dogrudan": "Arada başka limana uğramadan",
                "liman": "Üçüncü bir ülkenin limanı üzerinden",
                "sts": "Açık denizde başka bir gemiyle buluşma",
                "karanlik": "Yolda sinyal kesildi, kıyıda kayboldu veya varış kayıtsız"}
FAMILY_ORDER = ["dogrudan", "liman", "sts", "karanlik"]
ALL_LABELS = {**RETRO_LABELS, **CLASS_LABELS}


def _ll(lat, lon, n: int = 3):
    if lat is None or lon is None:
        return None
    return [round(lon, n), round(lat, n)]


def _clean(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in (None, "", [], {})}


def _dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


# --------------------------------------------------------------------------- alanlar
def zones(cfg) -> dict:
    dest = cfg.dest_countries()
    feats = []
    for p in cfg.ports:
        ring = [[round(lon, 4), round(lat, 4)] for lat, lon in p.area.outline()]
        if ring[0] != ring[-1]:
            ring.append(ring[0])
        feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
                      "properties": _clean({"tur": "yaklasma" if p.approach else ("izlenen" if p.role == "izlenen"
                                                                                  else ("hedef" if p.country in dest else "ara")),
                                            "kod": p.code, "ad": p.name, "ulke": p.country,
                                            "ulke_ad": cfg.country_name(p.country),
                                            "merkez": _ll(*p.area.center, 4)})})
    for name, area in cfg.watch_areas:
        ring = [[round(lon, 4), round(lat, 4)] for lat, lon in area.outline()]
        feats.append({"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [ring]},
                      "properties": {"tur": "dinleme", "ad": name, "merkez": _ll(*area.center, 4)}})
    (la0, lo0), (la1, lo1) = cfg.dark_box
    feats.append({"type": "Feature", "properties": {"tur": "karanlik", "ad": "Karanlık sefer arama bölgesi"},
                  "geometry": {"type": "Polygon", "coordinates": [[[lo0, la0], [lo1, la0], [lo1, la1], [lo0, la1], [lo0, la0]]]}})
    return {"type": "FeatureCollection", "features": feats}


# --------------------------------------------------------------------------- seferler
def _port_by_name(cfg):
    return {p.name: p for p in cfg.ports}


CEYHAN = (36.875, 35.925)  # BTC ve Kerkük-Ceyhan terminalleri


def cfg_home(cfg) -> set[str]:
    return {p.country for p in cfg.ports if p.role == "izlenen"}


def voyages(cfg, con) -> list[dict]:
    out = []
    pmap = cfg.port_by_code
    pname = _port_by_name(cfg)
    _, k2m = vessel_keys(con)
    vessels = {r["mmsi"]: dict(r) for r in con.execute("SELECT * FROM vessels")}
    ev = {r["id"]: dict(r) for r in con.execute("SELECT * FROM events WHERE kind IN ('gap','sts','stop')")}
    for r in con.execute("SELECT * FROM routes ORDER BY t_arr"):
        r = dict(r)
        flags = json.loads(r["flags"] or "{}")
        mids = json.loads(r["mids"] or "[]")
        o = pmap.get(r["origin_port"])
        d = pmap.get(r["dest_port"]) if r["dest_port"] else None
        mm = k2m.get(r["vkey"]) or [r["mmsi"]]
        evs = [ev[i] for i in json.loads(r["evts"] or "[]") if i in ev]
        if r["via_mmsi"]:
            giver = k2m.get(r["via_vkey"]) or [r["via_mmsi"]]
            meet = next((e for e in evs if e["kind"] == "sts"), None)
            ts = meet["t_start"] if meet else r["t_dep"]
            segs = tracks.window(cfg, con, giver, r["t_dep"], ts) + tracks.window(cfg, con, mm, ts, r["t_arr"])
        else:
            segs = tracks.window(cfg, con, mm, r["t_dep"], r["t_arr"])
        kp, sts = [], []
        for e in evs:
            det = json.loads(e["detail"] or "{}")
            if e["kind"] == "gap" and det.get("baslangic") and det.get("bitis"):
                a, b = det["baslangic"], det["bitis"]
                kp.append([round(a[1], 3), round(a[0], 3), round(b[1], 3), round(b[0], 3), det.get("saat"),
                           e["t_start"], e["t_end"]])
            elif e["kind"] == "sts" and e["lat"] is not None:
                sts.append([round(e["lon"], 3), round(e["lat"], 3), e["t_start"], e["t_end"], det.get("saat")])
        w = [_ll(*o.area.center)] if o else []
        for x in mids:
            if x.get("konum"):
                w.append([x["konum"][1], x["konum"][0]])
            elif x.get("liman") in pname:
                w.append(_ll(*pname[x["liman"]].area.center))
        if d:
            w.append(_ll(*d.area.center))
        v = vessels.get(r["mmsi"]) or {}
        tv = con.execute("SELECT terminal FROM visits WHERE port=? AND t_out=? AND terminal IS NOT NULL LIMIT 1",
                         (r["origin_port"], r["t_dep"])).fetchone()
        ter = tv[0] if tv else None
        sv = cfg.terminal_cargo(r["origin_port"], ter) == "sivi_dokme" if ter else False
        tk = ship_group(v.get("type")) == "tanker"
        rec = {"ter": ter, "sv": 1 if (sv or tk) else None, "tk": 1 if tk else None, "id": f"c{r['id']}", "s": "c", "y": r["direction"], "k": r["cls"], "a": FAMILY[r["cls"]],
               "n": r["name"], "m": r["mmsi"], "imo": v.get("imo"),
               "tip": SHIP_GROUP_LABELS[ship_group(v.get("type"))],
               "o": o.name if o else r["origin_port"], "oc": o.country if o else None, "t0": r["t_dep"],
               "d": d.name if d else None, "dc": d.country if d else None, "t1": r["t_arr"],
               "ara": [x["liman"] for x in mids], "at": [[x.get("giris"), x.get("cikis")] for x in mids],
               "w": [p for p in w if p], "iz": [s for s in segs if len(s) >= 2], "kp": kp, "sts": sts,
               "yuk": r["cargo"], "gv": r["cargo_conf"], "dy": json.loads(r["cargo_basis"] or "[]"),
               "vb": flags.get("varis_beyani"), "vt": r["dest_text"], "g": r["vkey"],
               "sz": flags.get("sessizlik_saat"), "ks": flags.get("karanlik_saat"),
               "dd": flags.get("draft_dustu") or None, "sl": flags.get("sonraki_liman")}
        if r["via_mmsi"]:
            rec["via"] = _clean({"n": r["via_name"], "m": r["via_mmsi"], "g": r["via_vkey"]})
        out.append(_clean(rec))
    for r in con.execute("SELECT * FROM gecmis ORDER BY t_arr"):
        r = dict(r)
        gaps = json.loads(r["gaps"] or "[]")
        mids = json.loads(r["mids"] or "[]")
        w = [_ll(r.get("o_lat"), r.get("o_lon"))] + [_ll(m.get("lat"), m.get("lon")) for m in mids]
        if r["dest"]:
            w.append(_ll(r.get("d_lat"), r.get("d_lon")))
        elif gaps and None not in gaps[0]["kapanis"]:
            w.append(_ll(*gaps[0]["kapanis"]))
        kp = [[round(g["kapanis"][1], 3), round(g["kapanis"][0], 3), round(g["acilis"][1], 3), round(g["acilis"][0], 3),
               g.get("saat"), g.get("baslangic"), g.get("bitis")]
              for g in gaps if None not in g.get("kapanis", [None]) and None not in g.get("acilis", [None])]
        try:
            mmsi = int(r["ssvid"]) if r["ssvid"] else None
        except ValueError:
            mmsi = r["ssvid"]
        # Türk tarafındaki uğrağın terminali (ihracatta çıkış, ithalatta varış)
        home = r["origin_country"] in cfg_home(cfg)
        la, lo = (r.get("o_lat"), r.get("o_lon")) if home else (r.get("d_lat"), r.get("d_lon"))
        ter = cfg.locate(la, lo)[1] if la is not None and lo is not None else None
        tcode = cfg.locate(la, lo)[0] if ter else None
        sv = cfg.terminal_cargo(tcode, ter) == "sivi_dokme" if ter else False
        vt = (vessels.get(mmsi) or {}).get("type") if isinstance(mmsi, int) else None
        tk = ship_group(vt) == "tanker" if vt else False
        if not ter and la is not None and r["origin_country"] in cfg_home(cfg) and haversine_km(la, lo, *CEYHAN) <= 11:
            ter = "Ceyhan terminalleri ve demirleme alanı"
        out.append(_clean({"ter": ter, "sv": 1 if (sv or tk) else None, "tk": 1 if tk else None,
                           "yuk": CARGO_LABELS["sivi_dokme"] if (sv or tk) else None,
                           "gv": ("yüksek" if sv and tk else "orta") if (sv or tk) else None,
                           "dy": [x for x in [f"{'Çıkış' if home else 'Varış'} terminali: {ter} (yalnızca sıvı dökme yük iskelesi)" if sv else None,
                                              "Gemi AIS'te kendini tanker olarak bildiriyor" if tk else None] if x] or None,
                           "id": f"g{r['id']}", "s": "g", "y": r["direction"], "k": r["cls"], "a": FAMILY[r["cls"]],
                           "n": r["name"], "m": mmsi, "b": r["flag"], "tip": "Tanker (AIS)" if tk else r["vtype"],
                           "o": r["origin"], "oc": r["origin_country"], "t0": r["t_dep"],
                           "d": r["dest"], "dc": r["dest_country"], "t1": r["t_arr"],
                           "ara": [m["liman"] for m in mids], "at": [[m.get("giris"), m.get("cikis")] for m in mids],
                           "w": [p for p in w if p], "kp": kp,
                           "sl": r["next_port"]}))
    return out


# --------------------------------------------------------------------------- canlı
def live(cfg, con, now: str) -> list[dict]:
    m2k, _ = vessel_keys(con)
    out = []
    for r in con.execute("""SELECT t.mmsi, t.prio, t.start, v.name, v.type, v.dest FROM tracking t
                            LEFT JOIN vessels v USING(mmsi) WHERE t.status='active'"""):
        last = con.execute("SELECT t, lat, lon, sog, cog FROM positions WHERE mmsi=? ORDER BY t DESC LIMIT 1",
                           (r["mmsi"],)).fetchone()
        if not last:
            continue
        segs = tracks.window(cfg, con, [r["mmsi"]], add_hours(now, -48), now, tol=0.002)
        out.append(_clean({"m": r["mmsi"], "n": r["name"] or f"MMSI {r['mmsi']}", "g": m2k.get(r["mmsi"]),
                           "tip": SHIP_GROUP_LABELS[ship_group(r["type"])], "vt": r["dest"],
                           "p": _ll(last["lat"], last["lon"], 4), "c": last["cog"], "h": last["sog"],
                           "t": last["t"], "pr": r["prio"], "iz": [s for s in segs if len(s) >= 2]}))
    return out


def events(cfg, con, now: str) -> dict:
    names = {r["mmsi"]: r["name"] for r in con.execute("SELECT mmsi, name FROM vessels")}
    ev = []
    for e in con.execute("SELECT * FROM events WHERE kind IN ('gap','stop','sts','draught') AND lat IS NOT NULL "
                         "ORDER BY t_start DESC LIMIT 3000"):
        d = json.loads(e["detail"] or "{}")
        ev.append(_clean({"k": e["kind"], "m": e["mmsi"], "n": names.get(e["mmsi"]), "m2": e["mmsi2"],
                          "n2": names.get(e["mmsi2"]) if e["mmsi2"] else None, "t0": e["t_start"], "t1": e["t_end"],
                          "p": _ll(e["lat"], e["lon"]), "s": d.get("saat")}))
    spoof = [[round(e["lon"], 3), round(e["lat"], 3)] for e in con.execute(
        "SELECT lat, lon FROM events WHERE kind='spoof' AND t_start >= ? ORDER BY t_start DESC LIMIT 2000",
        (add_hours(now, -72),))]
    total = con.execute("SELECT count(*) FROM events WHERE kind='spoof'").fetchone()[0]
    return {"olaylar": ev, "sahte": spoof, "sahte_toplam": total}


# --------------------------------------------------------------------------- gemi
def relevant_keys(con) -> dict[str, list[int]]:
    """Kendi sayfası olacak gemiler: takip edilmiş, bir sefere veya olaya karışmış olanlar."""
    m2k, k2m = vessel_keys(con)
    mm = {r[0] for r in con.execute(
        "SELECT mmsi FROM tracking WHERE coalesce(end_reason,'') != 'gemi tipi filtre dışı'")}
    mm |= {r[0] for r in con.execute("SELECT mmsi FROM routes")}
    mm |= {r[0] for r in con.execute("SELECT via_mmsi FROM routes WHERE via_mmsi IS NOT NULL")}
    mm |= {r[0] for r in con.execute("SELECT mmsi FROM events WHERE kind != 'spoof'")}
    mm |= {r[0] for r in con.execute("SELECT mmsi2 FROM events WHERE mmsi2 IS NOT NULL")}
    keys = defaultdict(set)
    for m in mm:
        if m is None:
            continue
        k = m2k.get(m, f"mmsi{m}")
        keys[k] |= set(k2m.get(k, [m])) | {m}
    return {k: sorted(v) for k, v in keys.items()}


def ship(cfg, con, key: str, mmsis: list[int], now: str) -> dict:
    segs = tracks.window(cfg, con, mmsis, "2000-01-01T00:00:00Z", now, tol=0.0012, keep_time=True)
    q = ",".join("?" * len(mmsis))
    visits = []
    for v in con.execute(f"SELECT * FROM visits WHERE mmsi IN ({q}) AND (transit IS NOT 1 OR status='open') "
                         "ORDER BY t_in", mmsis):
        p = cfg.port_by_code.get(v["port"])
        if p:
            visits.append(_clean({"l": p.name, "k": p.code, "u": p.country, "p": _ll(*p.area.center),
                                  "t0": v["t_in"], "t1": v["t_out"]}))
    evs = []
    for e in con.execute(f"SELECT * FROM events WHERE (mmsi IN ({q}) OR mmsi2 IN ({q})) AND kind != 'spoof' "
                         "ORDER BY t_start", (*mmsis, *mmsis)):
        d = json.loads(e["detail"] or "{}")
        item = {"k": e["kind"], "t0": e["t_start"], "t1": e["t_end"], "p": _ll(e["lat"], e["lon"]), "s": d.get("saat")}
        if e["kind"] == "gap" and d.get("baslangic") and d.get("bitis"):
            item["a"] = _ll(*d["baslangic"])
            item["b"] = _ll(*d["bitis"])
        evs.append(_clean(item))
    routes = [f"c{r[0]}" for r in con.execute(
        f"SELECT id FROM routes WHERE mmsi IN ({q}) OR via_mmsi IN ({q})", (*mmsis, *mmsis))]
    return {"anahtar": key, "iz": segs, "ziyaretler": visits, "olaylar": evs, "seferler": routes}


# --------------------------------------------------------------------------- hepsi
def build(cfg, con, out: Path, recs: list | None = None) -> dict:
    now = iso(now_utc())
    d = out / "veri" / "harita"
    recs = voyages(cfg, con) if recs is None else recs
    meta = {"olusturma": now,
            "siniflar": ALL_LABELS,
            "aileler": [{"kod": k, "ad": FAMILY_LABELS[k], "not": FAMILY_NOTES[k]} for k in FAMILY_ORDER],
            "yonler": [f"{a}>{b}" for a, b in cfg.directions],
            "ulkeler": {c: cfg.country_name(c) for c in {*cfg.countries, *[p.country for p in cfg.ports]}},
            "hedef": sorted(cfg.dest_countries())}
    _dump(d / "seferler.json", {**meta, "kayitlar": recs})
    _dump(d / "alanlar.json", zones(cfg))
    _dump(d / "canli.json", {"olusturma": now, "gemiler": live(cfg, con, now)})
    _dump(d / "olaylar.json", events(cfg, con, now))
    keys = relevant_keys(con)
    gdir = out / "veri" / "gemi"
    gdir.mkdir(parents=True, exist_ok=True)
    for key, mmsis in keys.items():
        _dump(gdir / f"{key}.json", ship(cfg, con, key, mmsis, now))
    return {"kayit": len(recs), "gemi": len(keys)}
