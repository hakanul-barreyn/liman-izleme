"""Kurgusal uçtan uca deneme. Gerçek hiçbir liman, ülke veya gemi kullanılmaz.

Senaryo (XX = 'X ülkesi', YY = 'Y ülkesi', ZZ = üçüncü ülke; koordinatlar açık denizde uydurmadır):
  ATLAS   tanker  XX-1'de yükler, varış 'FOR ORDERS' yazar, doğrudan YY-1'e gidip boşaltır   → doğrudan + varış beyanı farklı
  BORA    kargo   XX-2'de yükler, ZZ-1'e uğrar, sonra YY-1'e gider                          → ara duraklı
  CEREN   tanker  XX-1'de yükler, açık denizde 10 saat AIS kapatır, YY-1'de boşaltır          → karanlık bacak
  DENIZ   tanker  XX-3'te yükler, açık denizde EFES ile 6 saat yan yana durur, boşalır        → denizde buluşma
  EFES    tanker  XX-2'ye boş uğrar, DENIZ'den yük alır, YY-1'de boşaltır                    → dolaylı + denizde buluşma
  FENER   kargo   XX-1 alanından durmadan geçer, bir kez sahte konum yayınlar                → ziyaret sayılmaz + konum tutarsızlığı
  GOKCE   tanker  XX-1'de yükler, varış ZZ-1 yazar, açık denizde ~2 gün AIS kapatır, su çekimi düşmüş
                  olarak döner, ZZ-1'e uğrar                                                   → karanlık sefer
  HAZAL   kargo   XX-2'de yükler, YY kıyı alanına girer, hiçbir limana girmeden sinyali kesilir  → kıyıda AIS kapandı
"""
from __future__ import annotations

import datetime as dt
import json
import math
import shutil
from pathlib import Path

import yaml

from . import config, jobs, proof
from .db import connect, db_path
from .ingest import Ingestor
from .util import UTC, iso

DEMO_CONFIG = {
    "proje": {"ad": "Avvam (demo)", "kurgusal": True, "saat_dilimi": "Europe/Istanbul",
              "aciklama": "Kurgusal verilerle sistemin nasıl çalıştığını gösteren deneme sitesi."},
    "beyan": {"aktif": True, "yonler": ["XX>YY"], "tarih": "2026-10-01", "kaynak": "Kurgusal açıklama",
              "metin": "X ülkesinden Y ülkesine hiçbir gemi gönderilmemektedir.",
              "karsi_gorus": "Kurgusal örnek: X hükümeti, limanlarından geçen yükün alıcısını kendisinin belirlemediğini söylüyor."},
    "ulkeler": {"XX": {"ad": "X ülkesi", "varis_anahtarlari": ["XLAND"]},
                "YY": {"ad": "Y ülkesi", "varis_anahtarlari": ["YLAND", "YY-1"]},
                "ZZ": {"ad": "Z ülkesi", "varis_anahtarlari": ["ZLAND", "ZZ-1"]}},
    "limanlar": [
        {"kod": "XX1", "ad": "XX-1 Rafineri Limanı", "ulke": "XX", "rol": "izlenen", "merkez": [14.0, 60.0], "yaricap_km": 6,
         "terminaller": [{"ad": "Petrol iskelesi", "yuk": "sivi_dokme", "merkez": [14.0, 60.02], "yaricap_km": 1.5}]},
        {"kod": "XX2", "ad": "XX-2 Konteyner Limanı", "ulke": "XX", "rol": "izlenen", "merkez": [14.6, 61.2], "yaricap_km": 6,
         "terminaller": [{"ad": "Genel rıhtım", "yuk": "genel_kargo", "merkez": [14.6, 61.2], "yaricap_km": 1.5}]},
        {"kod": "XX3", "ad": "XX-3 Dökme Yük Limanı", "ulke": "XX", "rol": "izlenen", "merkez": [13.2, 60.4], "yaricap_km": 6,
         "terminaller": [{"ad": "Akaryakıt iskelesi", "yuk": "sivi_dokme", "merkez": [13.2, 60.4], "yaricap_km": 1.5}]},
        {"kod": "YY1", "ad": "YY-1 Ana Liman", "ulke": "YY", "rol": "varis", "merkez": [10.0, 66.0], "yaricap_km": 7,
         "terminaller": [{"ad": "Boşaltma iskelesi", "yuk": "sivi_dokme", "merkez": [10.0, 66.0], "yaricap_km": 1.5}]},
        {"kod": "ZZ1", "ad": "ZZ-1 Aktarma Limanı", "ulke": "ZZ", "rol": "varis", "merkez": [12.0, 64.0], "yaricap_km": 6},
        {"kod": "YYK", "ad": "YY kıyı yaklaşma alanı", "ulke": "YY", "rol": "varis", "yaklasma": True,
         "alan": [[10.6, 65.4], [10.6, 66.6], [9.4, 66.6], [9.4, 65.4]]},
    ],
    "esikler": {"anomali_pencere_gun": 12, "karanlik_bolge": [[8.5, 58.0], [16.5, 68.5]]},
    "yayin": {"opentimestamps": False},
}

STS_POINT = (12.3, 62.6)


class Ship:
    def __init__(self, mmsi, imo, name, typ, length, lat, lon, t, draught, dest):
        self.mmsi, self.imo, self.name, self.typ, self.length = mmsi, imo, name, typ, length
        self.lat, self.lon, self.t = lat, lon, t
        self.draught, self.dest = draught, dest
        self.dark = False
        self.msgs: list[dict] = []
        self._last_static = None

    def _pos(self, sog):
        if self.dark:
            return
        self.msgs.append({"MessageType": "PositionReport", "MetaData": {
            "MMSI": self.mmsi, "ShipName": self.name, "latitude": self.lat, "longitude": self.lon,
            "time_utc": self.t.strftime("%Y-%m-%d %H:%M:%S.000000 +0000 UTC")},
            "Message": {"PositionReport": {"UserID": self.mmsi, "Latitude": self.lat, "Longitude": self.lon,
                                           "Sog": sog, "Cog": 0, "NavigationalStatus": 1 if sog < 1 else 0}}})
        if self._last_static is None or (self.t - self._last_static).total_seconds() >= 2 * 3600:
            self.static()

    def static(self):
        if self.dark:
            return
        self._last_static = self.t
        self.msgs.append({"MessageType": "ShipStaticData", "MetaData": {
            "MMSI": self.mmsi, "ShipName": self.name, "time_utc": self.t.strftime("%Y-%m-%d %H:%M:%S.000000 +0000 UTC")},
            "Message": {"ShipStaticData": {"UserID": self.mmsi, "ImoNumber": self.imo, "Name": self.name,
                                           "CallSign": f"D{self.mmsi % 10000}", "Type": self.typ,
                                           "Dimension": {"A": self.length * 0.8, "B": self.length * 0.2, "C": 15, "D": 15},
                                           "MaximumStaticDraught": self.draught, "Destination": self.dest}}})

    def sail(self, lat, lon, knots=12, step_min=6):
        dist_km = math.hypot((lat - self.lat) * 111.32, (lon - self.lon) * 111.32 * math.cos(math.radians(self.lat)))
        hours = dist_km / (knots * 1.852)
        n = max(1, int(hours * 60 / step_min))
        lat0, lon0 = self.lat, self.lon
        for i in range(1, n + 1):
            self.t += dt.timedelta(hours=hours / n)
            self.lat = lat0 + (lat - lat0) * i / n
            self.lon = lon0 + (lon - lon0) * i / n
            self._pos(knots)
        return self

    def stay(self, hours, step_min=6, new_draught=None, new_dest=None):
        n = max(1, int(hours * 60 / step_min))
        for i in range(n):
            self.t += dt.timedelta(minutes=step_min)
            if i == n // 2 and new_draught is not None:
                self.draught = new_draught
                self.static()
            self._pos(0.1)
        if new_dest is not None:
            self.dest = new_dest
            self.static()
        return self

    def until(self, t):
        h = (t - self.t).total_seconds() / 3600
        if h > 0:
            self.stay(h)
        return self

    def spoof(self, lat, lon):
        """Tek bir sahte konum yayınla (GPS karıştırma örneği)."""
        self.t += dt.timedelta(minutes=1)
        real = (self.lat, self.lon)
        self.lat, self.lon = lat, lon
        self._pos(12)
        self.lat, self.lon = real
        return self

    def go_dark(self, on=True):
        self.dark = on
        return self


def scenario(start: dt.datetime) -> list[dict]:
    T = lambda h: start + dt.timedelta(hours=h)  # noqa: E731
    ships = []
    a = Ship(999000001, 9000001, "DEMO ATLAS", 80, 250, 14.4, 59.6, T(0), 9.0, "XX-1")
    a.sail(14.0, 60.02).stay(20, new_draught=15.2, new_dest="FOR ORDERS").sail(10.0, 66.0).stay(18, new_draught=9.1, new_dest="XLAND").sail(9.0, 67.5)
    ships.append(a)
    b = Ship(999000002, 9000002, "DEMO BORA", 70, 180, 15.0, 61.0, T(6), 7.0, "XX-2")
    b.sail(14.6, 61.2).stay(12, new_draught=10.0, new_dest="ZZ-1").sail(12.0, 64.0).stay(10, new_dest="YY-1").sail(10.0, 66.0).stay(12, new_draught=7.0, new_dest="ZLAND").sail(10.5, 67.5)
    ships.append(b)
    c = Ship(999000003, 9000003, "DEMO CEREN", 80, 230, 14.3, 59.7, T(20), 8.5, "XX-1")
    c.sail(14.0, 60.02).stay(16, new_draught=14.0, new_dest="YY-1 YLAND").sail(12.6, 62.0)
    c.go_dark().sail(11.0, 64.4).go_dark(False).sail(10.0, 66.0).stay(14, new_draught=8.6).sail(9.2, 66.8)
    ships.append(c)
    meet = T(60)
    d = Ship(999000004, 9000004, "DEMO DENIZ", 80, 240, 13.5, 60.0, T(4), 9.0, "XX-3")
    d.sail(13.2, 60.4).stay(18, new_draught=14.8, new_dest="ZLAND").sail(*STS_POINT).until(meet).stay(6, new_draught=9.5).sail(13.0, 58.0)
    ships.append(d)
    e = Ship(999000005, 9000005, "DEMO EFES", 80, 230, 15.0, 61.5, T(8), 8.0, "XX-2")
    e.sail(14.6, 61.2).stay(8, new_dest="OMAN").sail(STS_POINT[0] + 0.002, STS_POINT[1] + 0.002).until(meet).stay(6, new_draught=13.5).sail(10.0, 66.0).stay(16, new_draught=8.0).sail(9.0, 64.5)
    ships.append(e)
    f = Ship(999000006, 9000006, "DEMO FENER", 70, 150, 14.3, 59.8, T(30), 6.0, "ZLAND")
    f.sail(14.0, 60.05, knots=13).spoof(2.0, 75.0).sail(13.7, 60.2, knots=13)
    ships.append(f)
    g = Ship(999000007, 9000007, "DEMO GOKCE", 80, 245, 14.4, 59.5, T(40), 9.2, "XX-1")
    g.sail(14.0, 60.02).stay(18, new_draught=15.0, new_dest="ZZ-1").sail(12.0, 62.5)
    g.go_dark().sail(10.5, 65.0).stay(20).sail(12.2, 62.4)
    g.draught = 9.0
    g.go_dark(False).sail(12.0, 64.0).stay(10).sail(13.0, 63.0)
    ships.append(g)
    h = Ship(999000008, 9000008, "DEMO HAZAL", 70, 190, 15.0, 61.6, T(50), 7.5, "XX-2")
    h.sail(14.6, 61.2).stay(14, new_draught=11.0, new_dest="ZLAND").sail(10.45, 65.6)
    ships.append(h)
    msgs = [m for s in ships for m in s.msgs]
    msgs.sort(key=lambda m: m["MetaData"]["time_utc"])
    return msgs


def run(base: Path | None = None) -> int:
    base = (base or Path.cwd() / "demo").resolve()
    if base.exists():
        shutil.rmtree(base)
    base.mkdir(parents=True)
    (base / "config.yaml").write_text(yaml.safe_dump(DEMO_CONFIG, allow_unicode=True, sort_keys=False), encoding="utf-8")
    cfg = config.load(base / "config.yaml")
    con = connect(db_path(cfg))
    ing = Ingestor(cfg, con)
    start = dt.datetime(2026, 11, 1, 0, 0, tzinfo=UTC)
    msgs = scenario(start)
    # bir de toplayıcı kesintisi örneği
    con.execute("INSERT INTO outages(conn,t_start,t_end,reason) VALUES('liman',?,?,'örnek: ağ bağlantısı koptu')",
                (iso(start + dt.timedelta(hours=100)), iso(start + dt.timedelta(hours=100, minutes=20))))
    last_hour = None
    for m in msgs:
        p = ing.handle(m, "liman")
        if p is None:
            continue
        hour = p["t"][:13]
        if last_hour and hour != last_hour and hour.endswith(("00", "06", "12", "18")):
            ing.flush()
            jobs.hourly(cfg, now=p["t"])
        last_hour = hour
    ing.close()
    end = msgs[-1]["MetaData"]["time_utc"][:19].replace(" ", "T") + "Z"
    final = iso(dt.datetime.strptime(end, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) + dt.timedelta(days=1, hours=1))
    days = jobs.daily(cfg, now=final, push=False)["gunler"]
    con.close()
    con = connect(db_path(cfg))
    print(f"\n{len(msgs)} kurgusal AIS mesajı işlendi. Arşivlenen günler: {', '.join(days)}")
    print("\nZiyaretler:")
    for v in con.execute("SELECT v.port, s.name, v.t_in, v.t_out, v.transit, v.terminal, v.draught_in, v.draught_out "
                         "FROM visits v JOIN vessels s USING(mmsi) ORDER BY v.t_in"):
        print(f"  {v['port']:4s} {v['name']:12s} {v['t_in']} → {v['t_out']}  geçiş={v['transit']} "
              f"terminal={v['terminal']} draft {v['draught_in']}→{v['draught_out']}")
    print("\nOlaylar:")
    for e in con.execute("SELECT kind, mmsi, mmsi2, t_start, t_end FROM events ORDER BY t_start"):
        print(f"  {e['kind']:8s} {e['mmsi']} {e['mmsi2'] or ''} {e['t_start']} → {e['t_end']}")
    print("\nBeyan testi:")
    for r in con.execute("SELECT * FROM routes ORDER BY t_arr"):
        print(f"  {r['name']:12s} {r['origin_port']}→{r['dest_port']} sınıf={r['cls']} varış_farklı={r['masked']} "
              f"yük={r['cargo']} ({r['cargo_conf']}) {('veren=' + r['via_name']) if r['via_name'] else ''}")
    ok_all = True
    for d in days:
        ok, _ = proof.verify(cfg, d)
        ok_all &= ok
    print("\nKanıt zinciri doğrulaması:", "tamam" if ok_all else "HATA")
    print(f"Site: {cfg.site_dir / 'index.html'}")
    con.close()
    return 0 if ok_all else 1
