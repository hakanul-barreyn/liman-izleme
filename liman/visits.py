"""Konum kayıtlarından liman ziyaretlerini (giriş/çıkış) çıkarır. Artımlı çalışır."""
from __future__ import annotations

from . import tracking
from .db import get_meta, set_meta
from .util import add_hours, hours_between


def _latest_static(con, mmsi: int, field: str, before: str):
    r = con.execute(
        f"SELECT {field} FROM statics WHERE mmsi=? AND t<=? AND {field} IS NOT NULL ORDER BY t DESC LIMIT 1",
        (mmsi, before)).fetchone()
    return r[0] if r else None


def _first_static_after(con, mmsi: int, field: str, after: str, until: str):
    r = con.execute(
        f"SELECT {field} FROM statics WHERE mmsi=? AND t>=? AND t<=? AND {field} IS NOT NULL ORDER BY t LIMIT 1",
        (mmsi, after, until)).fetchone()
    return r[0] if r else None


def _close(cfg, con, v, t_out: str) -> None:
    th = cfg.th
    dur_min = hours_between(v["t_in"], t_out) * 60
    transit = int(dur_min < th["ziyaret_min_dakika"] or not v["stopped"])
    # su çekimi: girişte ilk bilinen değer, çıkışta son bilinen değer
    d_in = _latest_static(con, v["mmsi"], "draught", add_hours(v["t_in"], 0.5))
    if d_in is None:
        d_in = _first_static_after(con, v["mmsi"], "draught", v["t_in"], t_out)
    d_out = _latest_static(con, v["mmsi"], "draught", add_hours(t_out, 0.5))
    dest = _latest_static(con, v["mmsi"], "dest", add_hours(t_out, 0.5))
    term = con.execute(
        """SELECT terminal, count(*) n FROM positions WHERE mmsi=? AND port=? AND t BETWEEN ? AND ?
           AND terminal IS NOT NULL AND sog IS NOT NULL AND sog < ? GROUP BY terminal ORDER BY n DESC LIMIT 1""",
        (v["mmsi"], v["port"], v["t_in"], t_out, th["durma_hizi_knot"])).fetchone()
    con.execute(
        """UPDATE visits SET t_out=?, status='closed', transit=?, draught_in=?, draught_out=?,
           terminal=?, dest_out=? WHERE id=?""",
        (t_out, transit, d_in, d_out, term["terminal"] if term else None, dest, v["id"]))
    tracking.on_visit_closed(cfg, con, v["id"])


def process(cfg, con, now: str | None = None) -> int:
    """Yeni konumları işler; açık ziyaretleri günceller, süresi dolanları kapatır."""
    th = cfg.th
    tol_h = th["cikis_tolerans_dakika"] / 60
    merge_h = th["ziyaret_birlestirme_saat"]
    stop_kn = th["durma_hizi_knot"]
    cursor = int(get_meta(con, "visit_cursor", 0))
    open_v = {r["mmsi"]: dict(r) for r in con.execute("SELECT * FROM visits WHERE status='open'")}
    latest = get_meta(con, "visit_latest_t", "")
    n = 0
    rows = con.execute("SELECT id,mmsi,t,port,sog FROM positions WHERE id>? ORDER BY id", (cursor,))
    for r in rows:
        n += 1
        cursor = r["id"]
        t = r["t"]
        if t > latest:
            latest = t
        v = open_v.get(r["mmsi"])
        stopped = r["sog"] is not None and r["sog"] < stop_kn
        if r["port"]:
            if v and v["port"] == r["port"]:
                if t > v["last_in"]:
                    v["last_in"] = t
                if stopped:
                    v["stopped"] = 1
                con.execute("UPDATE visits SET last_in=?, stopped=? WHERE id=?", (v["last_in"], v["stopped"], v["id"]))
                continue
            if v:
                _close(cfg, con, v, v["last_in"])
                open_v.pop(r["mmsi"])
            # kısa bir sessizlikten sonra aynı limana dönüş: önceki ziyareti yeniden aç
            prev = con.execute(
                "SELECT * FROM visits WHERE mmsi=? AND port=? AND status='closed' ORDER BY t_out DESC LIMIT 1",
                (r["mmsi"], r["port"])).fetchone()
            if prev and prev["t_out"] and 0 <= hours_between(prev["t_out"], t) <= merge_h:
                con.execute("UPDATE visits SET status='open', t_out=NULL, last_in=?, stopped=max(stopped,?) WHERE id=?",
                            (t, int(stopped), prev["id"]))
                open_v[r["mmsi"]] = dict(con.execute("SELECT * FROM visits WHERE id=?", (prev["id"],)).fetchone())
            else:
                cur = con.execute(
                    "INSERT INTO visits(mmsi,port,t_in,last_in,stopped,status) VALUES(?,?,?,?,?,'open')",
                    (r["mmsi"], r["port"], t, t, int(stopped)))
                open_v[r["mmsi"]] = dict(con.execute("SELECT * FROM visits WHERE id=?", (cur.lastrowid,)).fetchone())
                tracking.on_visit_opened(cfg, con, open_v[r["mmsi"]])
        elif v and hours_between(v["last_in"], t) > tol_h:
            _close(cfg, con, v, v["last_in"])
            open_v.pop(r["mmsi"])
    # Uzun süredir limandan ses gelmeyen gemilerin ziyaretini kapat
    ref = now or latest
    for mmsi, v in list(open_v.items()):
        if ref and hours_between(v["last_in"], ref) > tol_h:
            _close(cfg, con, v, v["last_in"])
    set_meta(con, "visit_cursor", cursor)
    set_meta(con, "visit_latest_t", latest)
    con.commit()
    return n
