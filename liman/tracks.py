"""Gemi izleri: ayrıntılı konumlar sınırlı süre saklanır, sadeleştirilmiş izler kalıcıdır.

Her gün arşivlenirken o gün açık denizde görülen ve takipteki gemilerin izi sadeleştirilip
'izler' tablosuna (kalıcı) ve günün arşiv klasörüne (izler.json, kanıt zincirine dahil) yazılır.
Harita bir seferin izini bu kalıcı izlerden ve henüz arşivlenmemiş son konumlardan birleştirir.
"""
from __future__ import annotations

import json

from .geo import simplify
from .util import day_bounds_utc, local_day, parse_iso

SPLIT_MIN = 120          # bu kadar dakikadan uzun sessizlik izi böler (haritada kesik çizgi)
TOL_ARCHIVE = 0.0006     # arşiv izi için sadeleştirme toleransı (derece, ~60 m)


def emin(t: str) -> int:
    """ISO zamanı dakika cinsinden Unix zamanına çevirir."""
    return int(parse_iso(t).timestamp() // 60)


def to_segments(points: list, split_min: int = SPLIT_MIN) -> list:
    segs, cur = [], []
    for p in points:
        if cur and p[2] - cur[-1][2] > split_min:
            segs.append(cur)
            cur = []
        cur.append(p)
    if cur:
        segs.append(cur)
    return segs


def _positions(con, mmsis, a: str, b: str) -> list:
    if not mmsis:
        return []
    q = ",".join("?" * len(mmsis))
    return [[round(r["lon"], 4), round(r["lat"], 4), emin(r["t"])] for r in con.execute(
        f"SELECT t, lat, lon FROM positions WHERE mmsi IN ({q}) AND t>=? AND t<=? ORDER BY t", (*mmsis, a, b))]


def build_day(cfg, con, day: str) -> dict:
    """Günün izlerini kalıcı tabloya yazar ve {mmsi: segmentler} döndürür."""
    a, b = day_bounds_utc(day, cfg.tz)
    ships = {r[0] for r in con.execute(
        "SELECT DISTINCT mmsi FROM positions WHERE port IS NULL AND t>=? AND t<?", (a, b))}
    ships |= {r[0] for r in con.execute(
        "SELECT mmsi FROM tracking WHERE start < ? AND coalesce(ended, until) >= ?", (b, a))}
    out = {}
    for m in sorted(ships):
        pts = [p for p in _positions(con, [m], a, b)]
        pts = [p for p in pts if p[2] < emin(b)]
        if not pts:
            continue
        segs = [simplify(s, TOL_ARCHIVE) for s in to_segments(pts)]
        out[str(m)] = segs
        con.execute("INSERT OR REPLACE INTO izler(mmsi, day, pts) VALUES(?,?,?)",
                    (m, day, json.dumps(segs, separators=(",", ":"))))
    con.commit()
    return out


def window(cfg, con, mmsis, t0: str, t1: str, tol: float = 0.003, keep_time: bool = False) -> list:
    """[t0, t1] aralığındaki iz segmentleri: kalıcı izler + henüz arşivlenmemiş konumlar."""
    if not mmsis or not t0 or not t1 or t1 < t0:
        return []
    m0, m1 = emin(t0), emin(t1)
    pts: dict[int, list] = {}
    q = ",".join("?" * len(mmsis))
    for r in con.execute(f"SELECT pts FROM izler WHERE mmsi IN ({q}) AND day>=? AND day<=?",
                         (*mmsis, local_day(t0, cfg.tz), local_day(t1, cfg.tz))):
        for seg in json.loads(r[0]):
            for p in seg:
                if m0 <= p[2] <= m1:
                    pts[p[2]] = p
    for p in _positions(con, mmsis, t0, t1):
        pts.setdefault(p[2], p)
    seq = [pts[k] for k in sorted(pts)]
    segs = [simplify(s, tol) for s in to_segments(seq)]
    if not keep_time:
        segs = [[[p[0], p[1]] for p in s] for s in segs]
    return [s for s in segs if s]
