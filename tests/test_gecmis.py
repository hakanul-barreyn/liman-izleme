"""Geçmiş tarama: GFW yanıtlarına benzeyen örnek verilerle sınıflandırma ve kaldığı yerden devam."""
import json

from liman import config, gecmis, site
from liman.db import connect, db_path

RAW = {
    "proje": {"kurgusal": True},
    "beyan": {"yonler": ["TR>IL"]},
    "ulkeler": {"TR": {"ad": "Türkiye"}, "IL": {"ad": "İsrail"}, "EG": {"ad": "Mısır"}},
    "limanlar": [
        {"kod": "CEY", "ad": "Ceyhan", "ulke": "TR", "rol": "izlenen", "merkez": [36.87, 35.93], "yaricap_km": 6,
         "gecmis_karanlik_tara": True},
        {"kod": "ASK", "ad": "Aşkelon", "ulke": "IL", "rol": "varis", "merkez": [31.67, 34.51], "yaricap_km": 7},
    ],
    "yayin": {"opentimestamps": False},
}


def pv(vid, name, flag, lat, lon, start, end, ssvid="111"):
    return {"id": f"{vid}-{start}", "type": "port_visit", "start": start + "T08:00:00.000Z", "end": end + "T08:00:00.000Z",
            "position": {"lat": lat, "lon": lon},
            "vessel": {"id": vid, "name": name, "ssvid": ssvid, "flag": "MLT", "type": "carrier"},
            "port_visit": {"durationHrs": 24, "confidence": 4,
                           "startAnchorage": {"name": name.upper(), "flag": flag, "lat": lat, "lon": lon}}}


def gap(vid, start, end, hours, lat, lon):
    return {"id": f"g-{vid}-{start}", "type": "gap", "start": start + "T00:00:00.000Z", "end": end + "T00:00:00.000Z",
            "position": {"lat": lat, "lon": lon}, "vessel": {"id": vid},
            "gap": {"durationHours": hours, "distanceKm": 400, "offPosition": {"lat": lat, "lon": lon},
                    "onPosition": {"lat": lat + 0.5, "lon": lon + 0.5}}}


class FakeClient:
    """Gerçek istek yapmaz; GFW'nin döndüreceği olayları taklit eder."""
    requests = 0

    def __init__(self):
        cey = (36.87, 35.93)
        ask = (31.67, 34.51)
        ps = (31.26, 32.30)
        self.v = {
            # V1: Ceyhan → Port Said → Aşkelon (ara duraklı)
            "V1": [pv("V1", "ceyhan", "TUR", *cey, "2025-01-01", "2025-01-03"),
                   pv("V1", "port said", "EGY", *ps, "2025-01-05", "2025-01-06"),
                   pv("V1", "ashkelon", "ISR", *ask, "2025-01-08", "2025-01-09")],
            # V2: Ceyhan'dan çıkar, Rodos açıklarında 60 saat AIS kapalı, Ceyhan'a döner (karanlık sefer)
            "V2": [pv("V2", "ceyhan", "TUR", *cey, "2025-02-01", "2025-02-02"),
                   pv("V2", "ceyhan", "TUR", *cey, "2025-02-12", "2025-02-13")],
            # V3: Ceyhan → Aşkelon, arada 30 saat AIS kapalı (karanlık bacak)
            "V3": [pv("V3", "ceyhan", "TUR", *cey, "2025-03-01", "2025-03-02"),
                   pv("V3", "ashkelon", "ISR", *ask, "2025-03-05", "2025-03-06")],
        }
        self.g = {"V2": [gap("V2", "2025-02-03", "2025-02-05", 60, 36.0, 28.5)],
                  "V3": [gap("V3", "2025-03-03", "2025-03-04", 30, 34.0, 33.0)]}

    def area_events(self, dataset, geometry, start, end, extra=None):
        self.requests += 1
        lon, lat = geometry["coordinates"][0][0]
        out = []
        for evs in self.v.values():
            for e in evs:
                if start <= e["start"][:10] < end and abs(e["position"]["lat"] - lat) < 0.2:
                    out.append(e)
        return out

    def vessel_events(self, dataset, vid, start, end):
        self.requests += 1
        return (self.v if "port-visits" in dataset else self.g).get(vid, [])


def test_retro_scan(tmp_path):
    cfg = config.Config(RAW, tmp_path)
    con = connect(db_path(cfg))
    gecmis.set_target(con, "2025-01-01", "2025-04-01")
    fake = FakeClient()
    # 1) çok kısa süre bütçesi: iş yarıda kalmalı
    st = gecmis.scan(cfg, con, fake, budget_min=-1)
    assert st["tamam"] is False
    # 2) bütçesiz: tamamlanmalı
    st = gecmis.scan(cfg, con, fake)
    assert st["tamam"] is True
    rows = {(r["vessel_id"], r["cls"]): dict(r) for r in con.execute("SELECT * FROM gecmis")}
    assert ("V1", "aktarmali") in rows and json.loads(rows[("V1", "aktarmali")]["mids"])[0]["ulke"] == "EG"
    assert ("V2", "karanlik_sefer") in rows and rows[("V2", "karanlik_sefer")]["dest"] is None
    assert ("V3", "karanlik_bacak") in rows
    assert len(rows) == 3
    # 3) tekrar çalıştırınca önbellekten okunmalı, yeni istek yapılmamalı
    before = fake.requests
    gecmis.scan(cfg, con, fake)
    assert fake.requests == before
    site.build(cfg, con)
    page = (cfg.site_dir / "gecmis.html").read_text()
    assert "Karanlık sefer" in page and "browser.dataspace.copernicus.eu" in page
