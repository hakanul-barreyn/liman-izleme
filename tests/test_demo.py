"""Uçtan uca test: kurgusal senaryo beklenen sonuçları üretmeli."""
import sqlite3

from liman import ais, config, demo, proof
from liman.geo import Area, haversine_km


def test_parse_position():
    m = {"MessageType": "PositionReport",
         "MetaData": {"MMSI": 123456789, "ShipName": "TEST@@", "time_utc": "2026-11-06 03:12:00.123456789 +0000 UTC"},
         "Message": {"PositionReport": {"Latitude": 41.0, "Longitude": 29.0, "Sog": 0.2, "Cog": 360, "NavigationalStatus": 5}}}
    p = ais.parse(m)
    assert p["t"] == "2026-11-06T03:12:00Z" and p["lat"] == 41.0 and p["cog"] is None and p["name"] == "TEST"


def test_parse_invalid_position():
    m = {"MessageType": "PositionReport", "MetaData": {"MMSI": 1},
         "Message": {"PositionReport": {"Latitude": 91, "Longitude": 181}}}
    assert ais.parse(m) is None


def test_area():
    a = Area({"merkez": [10, 20], "yaricap_km": 5})
    assert a.contains(10.01, 20.01) and not a.contains(10.2, 20)
    poly = Area({"alan": [[0, 0], [0, 1], [1, 1], [1, 0]]})
    assert poly.contains(0.5, 0.5) and not poly.contains(1.5, 0.5)
    assert 110 < haversine_km(0, 0, 1, 0) < 112


def test_end_to_end(tmp_path):
    assert demo.run(tmp_path / "demo") == 0
    cfg = config.load(tmp_path / "demo" / "config.yaml")
    con = sqlite3.connect(cfg.data_dir / "liman.db")
    con.row_factory = sqlite3.Row
    routes = {(r["name"], r["cls"]): r for r in con.execute("SELECT * FROM routes")}
    assert ("DEMO ATLAS", "dogrudan") in routes and routes[("DEMO ATLAS", "dogrudan")]["masked"] == 1
    assert ("DEMO BORA", "aktarmali") in routes
    assert ("DEMO CEREN", "karanlik_bacak") in routes
    assert ("DEMO EFES", "denizde_aktarma") in routes
    assert routes[("DEMO EFES", "dolayli_sts")]["via_name"] == "DEMO DENIZ"
    assert routes[("DEMO ATLAS", "dogrudan")]["cargo_conf"] == "yüksek"
    fener = con.execute("SELECT transit FROM visits v JOIN vessels s USING(mmsi) WHERE s.name='DEMO FENER'").fetchone()
    assert fener["transit"] == 1
    assert con.execute("SELECT count(*) FROM tracking WHERE mmsi=999000006").fetchone()[0] == 0

    # Arşivdeki bir dosyayı değiştirmek doğrulamayı bozmalı
    day = "2026-11-02"
    assert proof.verify(cfg, day)[0]
    f = cfg.site_dir / "arsiv" / day / "XX1.csv"
    f.write_text(f.read_text() + "sahte satir\n")
    assert not proof.verify(cfg, day)[0]


def test_destination_match(tmp_path):
    cfg = config.Config({"ulkeler": {"TR": {"varis_anahtarlari": ["TURKEY"]}}}, tmp_path)
    assert cfg.destination_matches("TR IST", "TR") is False
    assert cfg.destination_matches("TRIST", "TR") is True
    assert cfg.destination_matches("ISTANBUL TURKEY", "TR") is True
    assert cfg.destination_matches(None, "TR") is None
