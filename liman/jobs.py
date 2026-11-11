"""Zamanlanmış işler: saatlik analiz, günlük arşiv, site üretimi, GitHub'a gönderim."""
from __future__ import annotations

import datetime as dt
import hashlib
import logging
import subprocess
from zoneinfo import ZoneInfo

from . import anomaly, archive, routes, site, tracking, visits
from .db import connect, db_path
from .util import iso, local_day, now_utc

log = logging.getLogger("isler")


def hourly(cfg, now: str | None = None) -> dict:
    con = connect(db_path(cfg))
    try:
        now = now or iso(now_utc())
        n = visits.process(cfg, con, now)
        tracking.refresh(cfg, con, now)
        ev = anomaly.detect(cfg, con, now)
        r = routes.compute(cfg, con)
        site.build(cfg, con)
        return {"yeni_konum": n, "olaylar": ev, "beyan_hareketi": r}
    finally:
        con.close()


def pending_days(cfg, con, now: str) -> list[str]:
    today = local_day(now, cfg.tz)
    done = {r[0] for r in con.execute("SELECT day FROM archived_days")}
    first = con.execute("SELECT min(t) FROM positions").fetchone()[0]
    if not first:
        return []
    d = dt.date.fromisoformat(local_day(first, cfg.tz))
    end = dt.date.fromisoformat(today)
    out = []
    while d < end:
        s = d.isoformat()
        if s not in done:
            out.append(s)
        d += dt.timedelta(days=1)
    return out


def daily(cfg, now: str | None = None, push: bool | None = None) -> dict:
    now = now or iso(now_utc())
    hourly(cfg, now)
    con = connect(db_path(cfg))
    try:
        days = pending_days(cfg, con, now)
        for d in days:
            s = archive.build_day(cfg, con, d)
            log.info("Arşivlendi %s · gün hash'i %s", d, s["gun_hash"])
        site.build(cfg, con)
    finally:
        con.close()
    res = {"gunler": days, "ayar_degisti": False}
    if push if push is not None else cfg.pub.get("git_push"):
        res.update(git_publish(cfg, f"Arşiv: {', '.join(days)}" if days else "Site güncellemesi"))
    return res


def _config_hash(cfg) -> str:
    p = cfg.root / "config.yaml"
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else ""


def git_publish(cfg, message: str) -> dict:
    """Siteyi commit'ler, GitHub'daki değişiklikleri (ör. config.yaml düzenlemesi) çeker ve gönderir.
    Dönen sözlükteki 'ayar_degisti' True ise program yeni ayarlarla yeniden başlatılmalıdır."""
    root = cfg.root
    res = {"gonderildi": False, "ayar_degisti": False}

    def run(*args):
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=600)

    if run("rev-parse", "--is-inside-work-tree").returncode != 0:
        log.warning("Git deposu bulunamadı, gönderim atlandı")
        return res
    before = _config_hash(cfg)
    run("add", "-A", str(cfg.site_dir.relative_to(root)))
    if run("diff", "--cached", "--quiet").returncode != 0:
        c = run("commit", "-m", message)
        if c.returncode != 0:
            log.warning("Commit başarısız: %s", c.stderr.strip())
    pull = run("pull", "--rebase", "--autostash")
    if pull.returncode != 0:
        log.warning("GitHub'dan çekme başarısız: %s", pull.stderr.strip())
        run("rebase", "--abort")
    res["ayar_degisti"] = _config_hash(cfg) != before
    p = run("push")
    if p.returncode != 0:
        log.warning("Push başarısız: %s", p.stderr.strip())
    else:
        res["gonderildi"] = True
        log.info("GitHub'a gönderildi: %s", message)
    return res


def next_daily_run(cfg, after: dt.datetime) -> dt.datetime:
    hh, mm = map(int, cfg.pub.get("gunluk_saat", "00:05").split(":"))
    z = ZoneInfo(cfg.tz)
    local = after.astimezone(z)
    cand = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if cand <= local:
        cand += dt.timedelta(days=1)
    return cand.astimezone(dt.timezone.utc)
