"""Takip listesi: izlenen limana uğrayan her gemi takibe alınır."""
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


def on_visit_opened(cfg, con, visit: dict) -> None:
    port = cfg.port_by_code[visit["port"]]
    if port.role != "izlenen" or not _allowed(cfg, con, visit["mmsi"]):
        return
    until = add_hours(visit["t_in"], cfg.th["takip_gun"] * 24)
    con.execute(
        """INSERT INTO tracking(mmsi,start,until,visit_id,status) VALUES(?,?,?,?,'active')
           ON CONFLICT(mmsi) DO UPDATE SET until=max(tracking.until, excluded.until),
           visit_id=excluded.visit_id, status='active', ended=NULL, end_reason=NULL,
           start=CASE WHEN tracking.status='active' THEN tracking.start ELSE excluded.start END""",
        (visit["mmsi"], visit["t_in"], until, visit["id"]))


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
    start_visit = con.execute("SELECT port FROM visits WHERE id=?", (tr["visit_id"],)).fetchone()
    if not start_visit:
        return
    origin_c = cfg.port_by_code[start_visit["port"]].country
    here = cfg.port_by_code[v["port"]]
    if here.country != origin_c and here.role != "izlenen":
        con.execute("UPDATE tracking SET status='ended', ended=?, end_reason=? WHERE mmsi=?",
                    (v["t_out"], f"varış: {here.name}", v["mmsi"]))


def refresh(cfg, con, now: str) -> None:
    con.execute("UPDATE tracking SET status='ended', ended=until, end_reason='süre doldu' "
                "WHERE status='active' AND until < ?", (now,))
    for r in con.execute("SELECT mmsi FROM tracking WHERE status='active'").fetchall():
        if not _allowed(cfg, con, r["mmsi"]):
            con.execute("UPDATE tracking SET status='ended', ended=?, end_reason='gemi tipi filtre dışı' "
                        "WHERE mmsi=?", (now, r["mmsi"]))
    con.commit()


def active_mmsis(con) -> list[int]:
    """Canlı izlenecek gemiler; en yeni takipler öncelikli."""
    return [r["mmsi"] for r in con.execute(
        "SELECT mmsi FROM tracking WHERE status='active' ORDER BY start DESC")]
