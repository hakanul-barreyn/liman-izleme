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
    # AIS'te tanker olarak bilinen gemi: iskelesi bilinmeyen petrol seferleri raporu bozmamalı
    con.execute("INSERT OR REPLACE INTO vessels(mmsi, name, type) VALUES(111, 'ORNEK', 80)")
    con.execute("UPDATE gecmis SET o_lat=36.2, o_lon=30.4 WHERE vessel_id='V3'")  # iskele olmayan bir nokta
    con.commit()
    site.HATALAR.clear()
    site.build(cfg, con)
    assert not site.HATALAR
    assert "İskele kayıtsız" in (cfg.site_dir / "raporlar" / "tr-il-petrol.html").read_text()
    page = (cfg.site_dir / "gecmis.html").read_text()
    assert "Geçmiş tarama" in page and "Powered by Global Fishing Watch" in page
    data = json.loads((cfg.site_dir / "veri" / "harita" / "seferler.json").read_text())
    rec = {r["id"]: r for r in data["kayitlar"]}
    dark = [r for r in rec.values() if r["k"] == "karanlik_sefer"][0]
    assert dark["s"] == "g" and dark["kp"] and dark["w"][0] == [35.93, 36.87] and "d" not in dark
    via = [r for r in rec.values() if r["k"] == "aktarmali"][0]
    assert len(via["w"]) == 3 and via["ara"]
    # raporlar: gemi gemi liste, aylık rapor ve CSV
    rd = cfg.site_dir / "raporlar"
    rp = (rd / "index.html").read_text()
    # örnek gemilerin hepsi aynı MMSI'yi (111) taşıyor: gemiler MMSI ile gruplanır
    assert rp.count('<details class="gemi"') == 1 and "1 gemi, 3 sefer" in rp
    assert (rd / "tr-il-seferler.csv").read_bytes().startswith("\ufeff".encode())
    assert list(rd.glob("tr-il-2025-0*.html"))
    # dünyadan İsrail'e: her varış önceki uğrağıyla
    dp = (rd / "dunya.html").read_text()
    assert "Mısır" in dp and (rd / "dunya-egy.html").exists() and (rd / "dunya-seferler.csv").exists()


def test_guncelleme_bogaz_ve_donem(tmp_path):
    """Ana dönemden sonraki haftalık dilimler yeni seferleri bulur; boğaz demirlemesi ve dönem öncesi çıkış elenir."""
    import datetime as dt
    cfg = config.Config(RAW, tmp_path)
    con = connect(db_path(cfg))
    gecmis.set_target(con, "2025-01-01", "2025-04-01")
    fake = FakeClient()
    cey, ask, bogaz = (36.87, 35.93), (31.67, 34.51), (41.236, 29.118)
    fake.v = {
        # V4: ana dönemden sonra Ceyhan → Aşkelon
        "V4": [pv("V4", "ceyhan", "TUR", *cey, "2025-05-01", "2025-05-02"),
               pv("V4", "ashkelon", "ISR", *ask, "2025-05-04", "2025-05-05")],
        # V5: Karadeniz'den gelip İstanbul Boğazı girişinde bekler, sonra Aşkelon (Türk ihracatı değil)
        "V5": [pv("V5", "rumelifeneri", "TUR", *bogaz, "2025-02-01", "2025-02-02"),
               pv("V5", "ashkelon", "ISR", *ask, "2025-02-05", "2025-02-06")],
        # V6: beyandan önce çıkmış, sonra varmış
        "V6": [pv("V6", "ceyhan", "TUR", *cey, "2024-12-27", "2024-12-28"),
               pv("V6", "ashkelon", "ISR", *ask, "2025-01-02", "2025-01-03")],
    }
    fake.g = {}
    st = gecmis.scan(cfg, con, fake, today=dt.date(2025, 6, 1))
    assert st["tamam"] is True and st["dilim"] >= 8
    rows = {(r["vessel_id"], r["cls"]) for r in con.execute("SELECT * FROM gecmis")}
    assert rows == {("V4", "dogrudan")}
    # aynı olay birden çok pencerede gelse de bir kez sayılır
    assert con.execute("SELECT count(*) FROM gecmis").fetchone()[0] == 1
    # yeni dilim yoksa yeniden çalıştırmada istek yapılmaz
    before = fake.requests
    gecmis.scan(cfg, con, fake, today=dt.date(2025, 6, 1))
    assert fake.requests == before


def test_kiyi_acigi_bosaltma(tmp_path):
    """Limana girmeden İsrail kıyı açığında bekleyen tanker, Ceyhan çıkışıyla eşleşir."""
    import copy
    import datetime as dt
    raw = copy.deepcopy(RAW)
    raw["limanlar"].append({"kod": "ILK", "ad": "İsrail kıyı yaklaşma alanı", "ulke": "IL", "rol": "varis", "yaklasma": True,
                            "alan": [[31.9, 34.6], [31.9, 34.2], [31.5, 34.2], [31.5, 34.6]]})
    cfg = config.Config(raw, tmp_path)
    con = connect(db_path(cfg))
    gecmis.set_target(con, "2025-01-01", "2025-04-01")
    fake = FakeClient()
    fake.v = {"V8": [pv("V8", "ceyhan", "TUR", 36.87, 35.93, "2025-02-01", "2025-02-02")]}
    fake.g = {}
    fake.presence = lambda geometry, a, b: [
        {"vid": "V8", "date": d, "hours": 20, "ad": "TANKER X", "m": "538000001", "b": "MHL", "tip": "other_non_fishing"}
        for d in ("2025-02-05", "2025-02-06") if a <= d < b]
    st = gecmis.scan(cfg, con, fake, today=dt.date(2025, 4, 10))
    assert st["tamam"] is True
    rows = [dict(r) for r in con.execute("SELECT * FROM gecmis WHERE cls='kiyida_bosaltma'")]
    assert len(rows) == 1 and rows[0]["origin"] == "Ceyhan" and rows[0]["name"] == "TANKER X"
    assert con.execute("SELECT count(*) FROM dunya WHERE dest LIKE '%kıyı açıkları%'").fetchone()[0] == 1
