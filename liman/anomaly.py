"""Takipteki gemilerin izlerinde şüpheli durumları işaretler.

gap      : açık denizde uzun AIS sessizliği (toplayıcı kesintisi değilse)
stop     : liman dışında uzun süre durma
sts      : iki geminin açık denizde yan yana durması (olası gemiden gemiye aktarma)
draught  : liman ziyareti olmadan su çekiminde büyük değişim
Bunlar tespittir, hüküm değildir.
"""
from __future__ import annotations

import json
from collections import defaultdict

from . import tracking
from .geo import haversine_km
from .util import add_hours, hours_between, parse_iso

KINDS = ("gap", "stop", "sts", "draught")


def outage_hours(con, a: str, b: str) -> float:
    """[a, b] aralığında bizim toplayıcımızın veri almadığı toplam süre (saat, çakışmalar birleştirilerek)."""
    iv = []
    for r in con.execute("SELECT t_start, coalesce(t_end, ?) t_end FROM outages WHERE t_start < ? "
                         "AND coalesce(t_end, ?) > ?", (b, b, b, a)):
        iv.append((max(r["t_start"], a), min(r["t_end"], b)))
    iv.sort()
    total, cur = 0.0, None
    for s0, e0 in iv:
        if cur and s0 <= cur[1]:
            cur = (cur[0], max(cur[1], e0))
        else:
            if cur:
                total += hours_between(*cur)
            cur = (s0, e0)
    if cur:
        total += hours_between(*cur)
    return total


def _draught_at(con, mmsi: int, t: str):
    r = con.execute("SELECT draught FROM statics WHERE mmsi=? AND t<=? AND draught IS NOT NULL "
                    "ORDER BY t DESC LIMIT 1", (mmsi, t)).fetchone()
    return r[0] if r else None


def _insert(con, kind, mmsi, mmsi2, t0, t1, lat, lon, detail):
    con.execute("INSERT INTO events(kind,mmsi,mmsi2,t_start,t_end,lat,lon,detail) VALUES(?,?,?,?,?,?,?,?)",
                (kind, mmsi, mmsi2, t0, t1, lat, lon, json.dumps(detail, ensure_ascii=False)))


def detect(cfg, con, now: str) -> dict:
    th = cfg.th
    win = add_hours(now, -24 * th["anomali_pencere_gun"])
    # uzun karanlık seferler haftalar sürebilir: boşluğun başı için geriye daha uzun bakılır
    ctx = add_hours(win, -24 * max(1, th.get("karanlik_sefer_gun", 30)))
    # bitişi pencere içinde kalan olaylar yeniden hesaplanır
    con.execute(f"DELETE FROM events WHERE kind IN ({','.join('?' * len(KINDS))}) AND coalesce(t_end, t_start) >= ?",
                (*KINDS, win))
    counts = defaultdict(int)
    stop_kn = th["durma_hizi_knot"]

    mmsis = [r[0] for r in con.execute(
        "SELECT DISTINCT mmsi FROM positions WHERE port IS NULL AND t >= ?", (ctx,))]
    # AIS boşluğu yalnızca takip sırasında anlamlıdır: takipte olmayan gemiyi zaten dinlemiyoruz
    tracked = {r["mmsi"]: (r["start"], r["ended"] or r["until"]) for r in con.execute(
        "SELECT mmsi, start, until, ended FROM tracking")}
    for mmsi in mmsis:
        rows = con.execute("SELECT t,lat,lon,sog,port FROM positions WHERE mmsi=? AND t>=? ORDER BY t",
                           (mmsi, ctx)).fetchall()
        # --- AIS boşlukları ---
        for a, b in zip(rows, rows[1:]):
            h = hours_between(a["t"], b["t"])
            if h < th["ais_bosluk_saat"] or b["t"] < win:
                continue
            span = tracked.get(mmsi)
            if not span or not (span[0] <= a["t"] and b["t"] <= add_hours(span[1], 24)):
                continue
            if cfg.near_port(a["lat"], a["lon"]) or cfg.near_port(b["lat"], b["lon"]):
                continue
            ours = outage_hours(con, a["t"], b["t"])
            if h - ours < th["ais_bosluk_saat"]:
                continue  # sessizliğin çoğu bizim toplayıcımızın kesintisi; geminin suçu değil
            dist = haversine_km(a["lat"], a["lon"], b["lat"], b["lon"])
            _insert(con, "gap", mmsi, None, a["t"], b["t"], (a["lat"] + b["lat"]) / 2, (a["lon"] + b["lon"]) / 2, {
                "saat": round(h, 1), "mesafe_km": round(dist, 1),
                "ortalama_hiz_knot": round(dist / 1.852 / h, 1) if h else None,
                "baslangic": [a["lat"], a["lon"]], "bitis": [b["lat"], b["lon"]],
                "draft_once": _draught_at(con, mmsi, a["t"]),
                "draft_sonra": _draught_at(con, mmsi, add_hours(b["t"], 1)),
                "bizim_kesinti_saat": round(ours, 1),
            })
            counts["gap"] += 1
        # --- liman dışı duraklar ---
        run = []
        for r in rows + [None]:
            still = r is not None and r["port"] is None and r["sog"] is not None and r["sog"] < stop_kn
            if still and (not run or hours_between(run[-1]["t"], r["t"]) <= 2):
                run.append(r)
                continue
            if run and hours_between(run[0]["t"], run[-1]["t"]) >= th["durak_sure_saat"] and run[-1]["t"] >= win:
                lat = sum(x["lat"] for x in run) / len(run)
                lon = sum(x["lon"] for x in run) / len(run)
                _insert(con, "stop", mmsi, None, run[0]["t"], run[-1]["t"], lat, lon, {
                    "saat": round(hours_between(run[0]["t"], run[-1]["t"]), 1),
                    "draft_once": _draught_at(con, mmsi, run[0]["t"]),
                    "draft_sonra": _draught_at(con, mmsi, add_hours(run[-1]["t"], 1)),
                })
                counts["stop"] += 1
            run = [r] if still else []

    # --- su çekimi değişimi (liman ziyareti olmadan) ---
    for mmsi in mmsis:
        st = con.execute("SELECT t, draught FROM statics WHERE mmsi=? AND t>=? AND draught IS NOT NULL ORDER BY t",
                         (mmsi, ctx)).fetchall()
        for a, b in zip(st, st[1:]):
            if b["t"] < win or abs(b["draught"] - a["draught"]) < th["draft_degisim_m"]:
                continue
            in_port = con.execute(
                "SELECT 1 FROM visits WHERE mmsi=? AND transit IS NOT 1 AND t_in <= ? AND coalesce(t_out,'9999') >= ?",
                (mmsi, b["t"], a["t"])).fetchone()
            if in_port:
                continue
            p = con.execute("SELECT lat,lon FROM positions WHERE mmsi=? AND t<=? ORDER BY t DESC LIMIT 1",
                            (mmsi, b["t"])).fetchone()
            _insert(con, "draught", mmsi, None, a["t"], b["t"], p["lat"] if p else None, p["lon"] if p else None,
                    {"once": a["draught"], "sonra": b["draught"], "fark": round(b["draught"] - a["draught"], 1)})
            counts["draught"] += 1

    # --- gemiden gemiye aktarma (STS) ---
    bucket_s = 600
    buckets: dict[int, dict[int, tuple]] = defaultdict(dict)
    for r in con.execute("SELECT mmsi,t,lat,lon,sog FROM positions WHERE port IS NULL AND t>=? AND sog IS NOT NULL "
                         "AND sog < ? ORDER BY t", (add_hours(win, -12), stop_kn)):
        b = int(parse_iso(r["t"]).timestamp()) // bucket_s
        buckets[b][r["mmsi"]] = (r["lat"], r["lon"], r["t"])
    pairs: dict[tuple, list] = defaultdict(list)
    lim_km = th["sts_mesafe_m"] / 1000

    def takipte(m, t):
        sp = tracked.get(m)
        return bool(sp) and sp[0] <= t <= add_hours(sp[1], 24)

    # Yalnızca takipteki (izlenen limandan çıkmış) bir geminin karıştığı buluşmalar: demirleme
    # yerlerinde yan yana bekleyen yerel tekneler ve yakıt mavnaları buluşma sayılmaz.
    for b, ships in buckets.items():
        items = list(ships.items())
        ilgili = [k for k, (m, p) in enumerate(items) if takipte(m, p[2])]
        ilgili_set = set(ilgili)
        for i in ilgili:
            for j in range(len(items)):
                if j == i or (j in ilgili_set and j < i):
                    continue
                (m1, p1), (m2, p2) = items[i], items[j]
                if haversine_km(p1[0], p1[1], p2[0], p2[1]) <= lim_km:
                    key = (min(m1, m2), max(m1, m2))
                    pairs[key].append((b, (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2, min(p1[2], p2[2])))
    for (m1, m2), hits in pairs.items():
        hits.sort()
        seg = [hits[0]]
        for h in hits[1:] + [None]:
            if h is not None and h[0] - seg[-1][0] <= 3:
                seg.append(h)
                continue
            dur_h = (seg[-1][0] - seg[0][0] + 1) * bucket_s / 3600
            if dur_h >= th["sts_sure_saat"]:
                lat = sum(x[1] for x in seg) / len(seg)
                lon = sum(x[2] for x in seg) / len(seg)
                if cfg.near_port(lat, lon, th.get("sts_liman_km", 10)):
                    seg = [h] if h is not None else []
                    continue
                t0 = seg[0][3]
                t1 = add_hours(t0, dur_h)
                if t1 < win:
                    seg = [h] if h is not None else []
                    continue
                _insert(con, "sts", m1, m2, t0, t1, lat, lon, {
                    "saat": round(dur_h, 1),
                    "draft_1": [_draught_at(con, m1, t0), _draught_at(con, m1, add_hours(t1, 2))],
                    "draft_2": [_draught_at(con, m2, t0), _draught_at(con, m2, add_hours(t1, 2))],
                })
                counts["sts"] += 1
                # takipli bir gemiyle buluşan gemi de takibe alınır
                act = {r["mmsi"] for r in con.execute(
                    "SELECT mmsi FROM tracking WHERE status='active' AND mmsi IN (?,?)", (m1, m2))}
                for me, other in ((m1, m2), (m2, m1)):
                    if me in act and other not in act:
                        if tracking.add_partner(cfg, con, other, t0, f"denizde buluşma: {me}"):
                            counts["yeni_takip"] += 1
            seg = [h] if h is not None else []
    con.commit()
    return dict(counts)
