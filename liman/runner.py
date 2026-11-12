"""Her şeyi tek süreçte çalıştırır: toplayıcı + saatlik ve günlük işler."""
from __future__ import annotations

import asyncio
import logging
import signal

from . import jobs, tracking, visits
from .collector import Collector
from .db import connect, db_path, get_meta, set_meta
from .ingest import Ingestor
from .util import iso, now_utc, parse_iso

log = logging.getLogger("calistir")


async def main(cfg, minutes: float | None = None) -> int:
    """minutes verilirse (GitHub Actions modu) o kadar dakika toplar ve durur;
    saatlik/günlük işleri çağıran taraf ayrıca çalıştırır."""
    if not cfg.ports:
        raise SystemExit("config.yaml içinde hiç liman yok. Önce limanları ekle.")
    con = connect(db_path(cfg))
    # Program kapalıyken geçen süreyi kesinti olarak kaydet
    last = get_meta(con, "last_alive")
    if last and (now_utc() - parse_iso(last)).total_seconds() > 120:
        reason = "çalıştırmalar arası boşluk" if minutes else "program kapalıydı"
        con.execute("INSERT INTO outages(conn,t_start,t_end,reason) VALUES('tumu',?,?,?)",
                    (last, iso(now_utc()), reason))
        con.commit()
    ing = Ingestor(cfg, con)
    col = Collector(cfg, con, ing)
    col.start()
    stop = asyncio.Event()
    restart = {"evet": False}
    loop = asyncio.get_running_loop()
    for s in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(s, stop.set)
        except NotImplementedError:  # Windows
            pass

    async def flusher():
        while True:
            await asyncio.sleep(5)
            ing.flush()
            set_meta(con, "last_alive", iso(now_utc()))
            con.commit()

    async def refresher():
        # Limana yeni giren gemiler 10 dakika içinde canlı takibe alınsın
        while True:
            await asyncio.sleep(600)
            try:
                ing.flush()
                visits.process(cfg, con)
                tracking.refresh(cfg, con, iso(now_utc()))
                col.refresh_tracking()
            except Exception:  # noqa: BLE001
                log.exception("Takip yenileme hatası")

    async def timer():
        await asyncio.sleep(minutes * 60)
        stop.set()

    async def hourly():
        every = cfg.pub.get("site_guncelleme_dakika", 60) * 60
        while True:
            await asyncio.sleep(every)
            try:
                ing.flush()
                r = await asyncio.to_thread(jobs.hourly, cfg)
                col.refresh_tracking()
                log.info("Saatlik iş: %s · %d mesaj alındı · takip kapasitesi dışı: %d", r, ing.count, col.overflow)
            except Exception:  # noqa: BLE001
                log.exception("Saatlik iş hatası")

    async def daily():
        while True:
            nxt = jobs.next_daily_run(cfg, now_utc())
            await asyncio.sleep(max(1, (nxt - now_utc()).total_seconds()))
            try:
                ing.flush()
                res = await asyncio.to_thread(jobs.daily, cfg)
                col.refresh_tracking()
                log.info("Günlük iş tamam: %s", res)
                if res.get("ayar_degisti"):
                    log.info("config.yaml GitHub'da değişmiş; yeni ayarlarla yeniden başlatılıyor")
                    restart["evet"] = True
                    stop.set()
            except Exception:  # noqa: BLE001
                log.exception("Günlük iş hatası")

    loops = (flusher, refresher, timer) if minutes else (flusher, refresher, hourly, daily)
    tasks = [asyncio.create_task(x()) for x in loops]
    log.info("Çalışıyor. %d liman izleniyor. Durdurmak için Ctrl+C.", len(cfg.ports))
    await stop.wait()
    log.info("Durduruluyor… %d AIS mesajı alındı, %d kaydedildi; takipte %d gemi (kapasite dışı %d)",
             ing.count, ing.kept, len(tracking.active_mmsis(con)), col.overflow)
    for t in tasks:
        t.cancel()
    await col.stop()
    ing.close()
    set_meta(con, "last_alive", iso(now_utc()))
    con.commit()
    con.close()
    return 3 if restart["evet"] else 0
