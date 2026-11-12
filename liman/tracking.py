"""Takip listesi: izlenen limana uğrayan her gemi takibe alınır.

Aynı anda canlı izlenebilecek gemi sayısı sınırlı olduğu için her takibe bir öncelik verilir:
tankerler, varış noktası şüpheli olanlar (FOR ORDERS, Mısır, Kıbrıs, hedef ülke vb.), daha önce
hedef ülkeye gitmiş olanlar ve denizde takipli bir gemiyle buluşanlar önce izlenir.
"""
from __future__ import annotations

from .util import add_hours, ship_group


def _allowed(cfg, con, mmsi: int) -> bool:
    v = con.execute("SELECT type, length FROM vessels WHERE mmsi=?", (mmsi,)).fetchone()
    types = cfg.ship_filter.get("tipler") or []
    if v is None:
        return "bilinmiyor" in types or not types
    if types and ship_group(v["type"]) not in types:
        return False
    min_len = cfg.ship_filter.get("min_boy_m") or 0
    if min_len and v["length"] and v["length"] < min_len:
        return False
    return True


def priority(cfg, con, mmsi: int) -> int:
    v = con.execute("SELECT type, dest FROM vessels WHERE mmsi=?", (mmsi,)).fetchone()
    p = 0
    if v:
        g = ship_group(v["type"])
        p += 2 if g == "tanker" else 1 if g == "kargo" else 0
        if cfg.dest_has_keyword(v["dest"], cfg.ais.get("oncelikli_varis")):
            p += 3
    targets = cfg.dest_countries()
    if targets:
        codes = [p_.code for p_ in cfg.ports if p_.country in targets]
        if codes:
            q = ",".join("?" * len(codes))
            if con.execute(f"SELECT 1 FROM visits WHERE mmsi=? AND port IN ({q}) LIMIT 1", (mmsi, *codes)).fetchone():
                p += 3
    return p


def on_visit_opened(cfg, con, visit: dict) -> None:
    port = cfg.port_by_code[visit["port"]]
    if port.role != "izlenen" or not _allowed(cfg, con, visit["mmsi"]):
        return
    until = add_hours(visit["t_in"], cfg.th["takip_gun"] * 24)
    con.execute(
        """INSERT INTO tracking(mmsi,start,until,visit_id,status,prio) VALUES(?,?,?,?,'active',?)
           ON CONFLICT(mmsi) DO UPDATE SET until=max(tracking.until, excluded.until),
           visit_id=excluded.visit_id, status='active', ended=NULL, end_reason=NULL,
           prio=max(coalesce(tracking.prio,0), excluded.prio),
           start=CASE WHEN tracking.status='active' THEN tracking.start ELSE excluded.start END""",
        (visit["mmsi"], visit["t_in"], until, visit["id"], priority(cfg, con, visit["mmsi"])))


def add_partner(cfg, con, mmsi: int, t: str, reason: str) -> bool:
    """Denizde takipli bir gemiyle buluşan gemiyi de takibe al."""
    row = con.execute("SELECT status FROM tracking WHERE mmsi=?", (mmsi,)).fetchone()
    if row and row["status"] == "active":
        return False
    until = add_hours(t, cfg.th["takip_gun"] * 24)
    con.execute(
        """INSERT INTO tracking(mmsi,start,until,visit_id,status,prio,end_reason) VALUES(?,?,?,NULL,'active',9,?)
           ON CONFLICT(mmsi) DO UPDATE SET start=excluded.start, until=excluded.until, visit_id=NULL,
           status='active', prio=9, ended=NULL, end_reason=excluded.end_reason""",
        (mmsi, t, until, reason))
    return True


def on_visit_closed(cfg, con, visit_id: int) -> None:
    v = con.execute("SELECT * FROM visits WHERE id=?", (visit_id,)).fetchone()
    tr = con.execute("SELECT * FROM tracking WHERE mmsi=?", (v["mmsi"],)).fetchone()
    if not tr:
        return
    if v["transit"] and tr["visit_id"] == visit_id and tr["status"] == "active":
        # Limandan sadece geçti: takibe hiç alınmamış sayılır
        con.execute("DELETE FROM tracking WHERE mmsi=?", (v["mmsi"],))
        return
    if v["transit"] or tr["status"] != "active" or tr["visit_id"] == visit_id:
        return
    here = cfg.port_by_code[v["port"]]
    if here.role == "izlenen" or here.approach:
        return
    targets = cfg.dest_countries()
    if targets:
        # Beyan testi açıkken ara ülkelerde takip bitmez; yalnızca hedef ülkeye varınca biter
        if here.country in targets:
            con.execute("UPDATE tracking SET status='ended', ended=?, end_reason=? WHERE mmsi=?",
                        (v["t_out"], f"varış: {here.name}", v["mmsi"]))
        return
    start_visit = con.execute("SELECT port FROM visits WHERE id=?", (tr["visit_id"],)).fetchone() \
        if tr["visit_id"] else None
    if not start_visit:
        return
    if here.country != cfg.port_by_code[start_visit["port"]].country:
        con.execute("UPDATE tracking SET status='ended', ended=?, end_reason=? WHERE mmsi=?",
                    (v["t_out"], f"varış: {here.name}", v["mmsi"]))


def refresh(cfg, con, now: str) -> None:
    con.execute("UPDATE tracking SET status='ended', ended=until, end_reason='süre doldu' "
                "WHERE status='active' AND until < ?", (now,))
    for r in con.execute("SELECT mmsi, prio FROM tracking WHERE status='active'").fetchall():
        if (r["prio"] or 0) < 9 and not _allowed(cfg, con, r["mmsi"]):
            con.execute("UPDATE tracking SET status='ended', ended=?, end_reason='gemi tipi filtre dışı' "
                        "WHERE mmsi=?", (now, r["mmsi"]))
            continue
        if (r["prio"] or 0) < 9:
            con.execute("UPDATE tracking SET prio=? WHERE mmsi=?", (priority(cfg, con, r["mmsi"]), r["mmsi"]))
    con.commit()


def active_mmsis(con) -> list[int]:
    """Canlı izlenecek gemiler; önceliği yüksek ve en yeni takipler önce."""
    return [r["mmsi"] for r in con.execute(
        "SELECT mmsi FROM tracking WHERE status='active' ORDER BY coalesce(prio,0) DESC, start DESC")]
