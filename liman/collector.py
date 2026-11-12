"""aisstream.io'ya bağlanıp 7/24 veri toplar.

Bağlantı 1 (liman): tüm limanların çevresindeki kutulardan gelen her mesaj.
Bağlantı 2..n (takip): takipteki gemilerin MMSI listesi, tüm dünyada.
Kesintiler 'outages' tablosuna yazılır; böylece veri boşlukları gizlenmez.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

from .ais import MESSAGE_TYPES
from .tracking import active_mmsis
from .util import iso, now_utc

log = logging.getLogger("toplayici")
URL = "wss://stream.aisstream.io/v0/stream"


def port_boxes(cfg) -> list:
    margin = cfg.ais["liman_kenar_payi_km"]
    return [p.area.bbox(margin) for p in cfg.ports] + [a.bbox(0) for _, a in cfg.watch_areas]


class Collector:
    def __init__(self, cfg, con, ingestor):
        self.cfg = cfg
        self.con = con
        self.ing = ingestor
        self.key = os.environ.get(cfg.ais["anahtar_degiskeni"], "").strip()
        if not self.key:
            raise SystemExit(f"aisstream anahtarı yok: .env dosyasına {cfg.ais['anahtar_degiskeni']}=... ekle")
        self.track_chunks: list[list[int]] = []
        self._tasks: dict[str, asyncio.Task] = {}
        self.capacity = cfg.ais["takip_baglanti_sayisi"] * cfg.ais["mmsi_baglanti_basina"]
        self.overflow = 0

    # --- kesinti kaydı ---
    def _outage_open(self, conn: str, reason: str) -> int:
        cur = self.con.execute("INSERT INTO outages(conn,t_start,reason) VALUES(?,?,?)",
                               (conn, iso(now_utc()), reason))
        self.con.commit()
        return cur.lastrowid

    def _outage_close(self, oid: int) -> None:
        self.con.execute("UPDATE outages SET t_end=? WHERE id=?", (iso(now_utc()), oid))
        self.con.commit()

    async def _run_conn(self, name: str, subscription: dict) -> None:
        import websockets  # yalnızca gerçek toplamada gerekli

        backoff = 5
        outage = None
        silence = self.cfg.ais["sessizlik_dakika"] * 60
        while True:
            try:
                async with websockets.connect(URL, ping_interval=30, ping_timeout=60,
                                              max_size=2**22) as ws:
                    await ws.send(json.dumps({"APIKey": self.key, **subscription}))
                    log.info("%s bağlandı", name)
                    while True:
                        raw = await asyncio.wait_for(ws.recv(), timeout=silence)
                        msg = json.loads(raw)
                        if "error" in msg:
                            raise RuntimeError(f"aisstream hatası: {msg['error']}")
                        self.ing.handle(msg, name)
                        if outage:
                            self._outage_close(outage)
                            outage = None
                        backoff = 5
            except asyncio.CancelledError:
                if outage:
                    self._outage_close(outage)
                raise
            except Exception as e:  # noqa: BLE001
                reason = "sessizlik" if isinstance(e, asyncio.TimeoutError) else f"{type(e).__name__}: {e}"
                log.warning("%s koptu (%s), %ss sonra yeniden denenecek", name, reason, backoff)
                if outage is None:
                    outage = self._outage_open(name, reason[:300])
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 300)

    def _start(self, name: str, sub: dict) -> None:
        old = self._tasks.pop(name, None)
        if old:
            old.cancel()
        self._tasks[name] = asyncio.create_task(self._run_conn(name, sub))

    def refresh_tracking(self) -> None:
        mmsis = active_mmsis(self.con)
        self.overflow = max(0, len(mmsis) - self.capacity)
        mmsis = mmsis[: self.capacity]
        per = self.cfg.ais["mmsi_baglanti_basina"]
        chunks = [sorted(mmsis[i:i + per]) for i in range(0, len(mmsis), per)]
        for i in range(self.cfg.ais["takip_baglanti_sayisi"]):
            name = f"takip{i + 1}"
            new = chunks[i] if i < len(chunks) else []
            old = self.track_chunks[i] if i < len(self.track_chunks) else None
            if new == old:
                continue
            if not new:
                t = self._tasks.pop(name, None)
                if t:
                    t.cancel()
            else:
                self._start(name, {
                    "BoundingBoxes": [[[-90, -180], [90, 180]]],
                    "FiltersShipMMSI": [str(m) for m in new],
                    "FilterMessageTypes": MESSAGE_TYPES,
                })
        self.track_chunks = chunks
        if self.overflow:
            log.warning("Takip kapasitesi aşıldı: %d gemi canlı izlenemiyor", self.overflow)

    def start(self) -> None:
        self._start("liman", {"BoundingBoxes": port_boxes(self.cfg), "FilterMessageTypes": MESSAGE_TYPES})
        self.refresh_tracking()

    async def stop(self) -> None:
        for t in self._tasks.values():
            t.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
