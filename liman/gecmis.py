"""Geçmişe dönük tarama: Global Fishing Watch (GFW) API ile beyan tarihinden bugüne.

GFW, AIS verisinden liman ziyaretlerini (tüm gemi tipleri) ve AIS boşluklarını (tüm gemi tipleri)
üretip ücretsiz ve ticari olmayan kullanım için yayımlar. Bu modül:

  1. Hedef ülke (B) limanlarının alanında belirtilen tarihlerdeki tüm liman ziyaretlerini çeker.
  2. "Karanlık sefer" taraması işaretli A limanlarındaki ziyaretleri çeker.
  3. Bu gemilerin her birinin bütün liman ziyaretlerini ve AIS boşluklarını çeker.
  4. A ülkesinden çıkıp B ülkesine varan bacakları (doğrudan / ara duraklı / karanlık bacak) ve
     A'dan çıkıp karanlık bölgede uzun süre AIS kapatan seferleri bulur.

İş uzun sürebilir; her istek önbelleğe yazılır ve iş, süre bütçesi bitince kaldığı yerden devam eder.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .db import connect, db_path, get_meta, set_meta
from .geo import haversine_km
from .ulkeler import ISO3_AD
from .util import add_hours, hours_between, iso, now_utc

log = logging.getLogger("gecmis")
API = "https://gateway.api.globalfishingwatch.org/v3/events"
DS_PV = "public-global-port-visits-events:latest"
DS_GAP = "public-global-gaps-events:latest"
DS_PRESENCE = "public-global-presence:latest"
REPORT_API = "https://gateway.api.globalfishingwatch.org/v3/4wings/report"
# GFW gemi tipleri; "other_non_fishing" (tankerlerin çoğu bu sınıfta) atlanmamalı
SKIP_TYPES = {"fishing", "passenger", "gear", "support", "seismic_vessel", "seismic"}
# Ülke kodu yapılandırmada olmayan limanlar için Türkçe ülke adları (GFW ISO3 kullanır)
ULKE_ADLARI = ISO3_AD
# GFW liman adları ASCII; sık görülen Türk limanlarının doğru yazımı
TR_ADLAR = {
    "Aliaga": "Aliağa", "Ambarli": "Ambarlı", "Bandirma": "Bandırma", "Bartin": "Bartın", "Botas": "Botaş",
    "Canakkale": "Çanakkale", "Cesme": "Çeşme", "Derince": "Derince", "Diliskelesi": "Dilişkelesi", "Dortyol": "Dörtyol",
    "Eregli": "Ereğli", "Gulluk": "Güllük", "Haydarpasa": "Haydarpaşa", "Icdas": "İçdaş", "Isdemir": "İsdemir",
    "Iskenderun": "İskenderun", "Istanbul": "İstanbul", "Izmir": "İzmir", "Izmit": "İzmit", "Kapakli": "Kapaklı",
    "Karabiga": "Karabiga", "Tasucu": "Taşucu", "Tekirdag": "Tekirdağ", "Yumurtalik": "Yumurtalık",
}
CEYHAN = (36.875, 35.925)  # BTC ve Kerkük-Ceyhan terminalleri
CEYHAN_KM = 11  # GFW Ceyhan ziyaretlerini terminallerin 6-10 km güneyindeki demirleme noktalarına bağlıyor
# Neredeyse yalnızca ham petrol ve akaryakıt tankerlerinin uğradığı iskeleler (GFW demirleme yeri adı → Türkçe).
# Ceyhan'a uğrayan bir gemi bunlardan birine de uğruyorsa tanker olduğu rotasından anlaşılır.
PETROL_ISKELELERI = {
    "SIDI KERIR": "Sidi Kerir (SUMED boru hattı, Mısır)", "SARROCH": "Sarroch rafinerisi (İtalya)",
    "SANTA PANAGIA": "Santa Panagia petrol iskelesi (Sicilya)", "PRIOLO": "Priolo rafinerisi (Sicilya)",
    "MELILLI": "Melilli petrol iskelesi (Sicilya)", "MILAZZO": "Milazzo rafinerisi (Sicilya)",
    "SUPSA": "Supsa petrol terminali (Gürcistan)", "KULEVI": "Kulevi petrol terminali (Gürcistan)",
    "ES SIDER": "Es Sider petrol terminali (Libya)", "RAS LANUF": "Ras Lanuf petrol terminali (Libya)",
    "ZUEITINA": "Zueitina petrol terminali (Libya)", "BREGA": "Brega petrol terminali (Libya)",
    "MELLITAH": "Mellitah terminali (Libya)", "AGIOI THEODOROI": "Agioi Theodoroi rafinerisi (Yunanistan)",
    "OMISALJ": "Omišalj petrol terminali (Hırvatistan)", "LAVERA": "Lavéra petrol terminali (Fransa)",
    "OZEREYEVKA": "CPC petrol terminali (Rusya)", "SHESKHARIS": "Sheskharis petrol terminali (Rusya)",
    "TUTUNCIFTLIK": "Tüpraş İzmit rafinerisi", "SKIKDA": "Skikda petrol terminali (Cezayir)",
}
CLASS_LABELS = {
    "dogrudan": "Doğrudan",
    "aktarmali": "Ara limanlı",
    "karanlik_bacak": "Karanlık bacak (AIS boşluğu)",
    "karanlik_sefer": "Karanlık sefer (varış limanı kayıtsız)",
    "kiyida_bosaltma": "Limana girmeden kıyı açığında bekledi (olası şamandıra boşaltması)",
    "karanlik_acik": "AIS varış ülkesinin açıklarında kapalı (limana girişi kayıtsız)",
    "iz_hedef": "Konumu varış ülkesinin açıklarında ya da GPS karıştırmasının sahte konum noktasında (limana girişi kayıtsız)",
}


class Client:
    def __init__(self, token: str, pause: float = 0.25, limit: int | None = None):
        self.token = token
        self.pause = pause
        self.requests = 0
        self.limit = limit  # bu çalıştırmada en fazla kaç istek (GFW günlük sınırı için; bkz. gfw_sinir)

    def _req(self, method: str, url: str, body=None, ham: bool = False):
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(6):
            req = urllib.request.Request(url, data=data, method=method, headers={
                "Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                "User-Agent": "avvam (github.com/hakanul-barreyn/liman-izleme)"})
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    self.requests += 1
                    time.sleep(self.pause)
                    raw = r.read()
                    return raw if ham else json.loads(raw.decode())
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:500]
                if (e.code in (429, 500, 502, 503, 504) and attempt < 5) or (e.code == 524 and attempt < 1):
                    wait = int(e.headers.get("Retry-After") or 0) or 2 ** (attempt + 2)
                    log.warning("GFW %s, %ss bekleniyor", e.code, wait)
                    time.sleep(wait)
                    continue
                raise RuntimeError(f"GFW isteği başarısız ({e.code}): {detail}") from None
            except urllib.error.URLError as e:
                if attempt < 5:
                    time.sleep(2 ** (attempt + 2))
                    continue
                raise RuntimeError(f"GFW'ye ulaşılamadı: {e}") from None
        raise RuntimeError("GFW isteği tekrar tekrar başarısız oldu")

    def _pages(self, fetch) -> list[dict]:
        out, offset = [], 0
        while True:
            res = fetch(offset)
            entries = res.get("entries") or []
            out += entries
            nxt = res.get("nextOffset")
            total = res.get("total")
            if not entries or nxt is None or nxt <= offset or (total is not None and len(out) >= total):
                return out
            offset = nxt

    def presence(self, geometry: dict, start: str, end: str) -> list[dict]:
        """Bir alanda gün gün bulunan gemiler (4Wings AIS presence raporu, gemi kimliğine göre)."""
        q = urllib.parse.urlencode({"format": "JSON", "group-by": "VESSEL_ID", "temporal-resolution": "DAILY",
                                    "datasets[0]": DS_PRESENCE, "date-range": f"{start},{end}",
                                    "spatial-aggregation": "true"})
        # gövde: {"geojson": <GeoJSON nesnesi>} (metin değil). Önce FeatureCollection, reddedilirse yalın Polygon.
        fc = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {}, "geometry": geometry}]}
        try:
            raw = self._req("POST", f"{REPORT_API}?{q}", {"geojson": fc}, ham=True)
        except RuntimeError as e:
            if "(422)" not in str(e):
                raise
            raw = self._req("POST", f"{REPORT_API}?{q}", {"geojson": geometry}, ham=True)
        return _presence_entries(raw)

    def area_events(self, dataset: str, geometry: dict, start: str, end: str, extra: dict | None = None) -> list[dict]:
        body = {"datasets": [dataset], "startDate": start, "endDate": end, "geometry": geometry, **(extra or {})}
        return self._pages(lambda off: self._req("POST", f"{API}?offset={off}&limit=500", body))

    def vessel_events(self, dataset: str, vessel_id: str, start: str, end: str) -> list[dict]:
        def fetch(off):
            q = urllib.parse.urlencode({"datasets[0]": dataset, "vessels[0]": vessel_id, "start-date": start,
                                        "end-date": end, "limit": 500, "offset": off})
            return self._req("GET", f"{API}?{q}")
        return self._pages(fetch)


# --------------------------------------------------------------------------- yardımcılar
def _t(s: str | None) -> str | None:
    if not s:
        return None
    return s[:19] + "Z" if len(s) >= 19 else s


def slim(e: dict) -> dict:
    """Önbellek için gereksiz alanları atar."""
    v = e.get("vessel") or {}
    out = {"id": e.get("id"), "type": e.get("type"), "start": _t(e.get("start")), "end": _t(e.get("end")),
           "position": e.get("position"),
           "vessel": {k: v.get(k) for k in ("id", "name", "ssvid", "flag", "type")}}
    pv = e.get("port_visit") or e.get("portVisit")
    if pv:
        def anch(a):
            return {k: (a or {}).get(k) for k in ("name", "flag", "lat", "lon", "anchorageId", "topDestination")} if a else None
        out["port_visit"] = {"durationHrs": pv.get("durationHrs"), "confidence": pv.get("confidence"),
                             "startAnchorage": anch(pv.get("startAnchorage")),
                             "endAnchorage": anch(pv.get("endAnchorage"))}
    g = e.get("gap")
    if g:
        out["gap"] = {k: g.get(k) for k in ("durationHours", "distanceKm", "impliedSpeedKnots", "intentionalDisabling",
                                             "offPosition", "onPosition")}
    return out


def _presence_entries(raw: bytes) -> list[dict]:
    """Rapor yanıtı zip içinde JSON (ya da düz JSON); gemi-gün satırlarını sadeleştirir."""
    import io
    import zipfile
    if raw[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            name = next((n for n in z.namelist() if n.lower().endswith(".json")), None)
            data = json.loads(z.read(name).decode()) if name else {}
    else:
        data = json.loads(raw.decode() or "{}")
    rows: list[dict] = []

    def walk(x):
        if isinstance(x, dict):
            if "hours" in x and (x.get("vesselId") or x.get("vessel_id")):
                rows.append(x)
            else:
                for v in x.values():
                    walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    walk(data)
    return [{"vid": r.get("vesselId") or r.get("vessel_id"), "date": str(r.get("date") or "")[:10],
             "hours": r.get("hours"), "ad": r.get("shipName"), "m": r.get("mmsi"), "b": r.get("flag"),
             "tip": r.get("vesselType") or r.get("vessel_type")} for r in rows]


def geometry(area) -> dict:
    ring = [[round(lon, 5), round(lat, 5)] for lat, lon in area.outline()]
    if ring[0] != ring[-1]:
        ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


def chunks(start: str, end: str, days: int = 90) -> list[tuple[str, str]]:
    a = dt.date.fromisoformat(start)
    b = dt.date.fromisoformat(end)
    out = []
    while a < b:
        n = min(b, a + dt.timedelta(days=days))
        out.append((a.isoformat(), n.isoformat()))
        a = n
    return out


def _store(con, key: str, events: list[dict], ham: bool = False) -> list[dict]:
    data = events if ham else [slim(e) for e in events]
    con.execute("INSERT OR REPLACE INTO gfw_cache(key,data,fetched) VALUES(?,?,?)",
                (key, json.dumps(data, separators=(",", ":")), iso(now_utc())))
    con.commit()
    return data


def _cache_get(con, key):
    r = con.execute("SELECT data FROM gfw_cache WHERE key=?", (key,)).fetchone()
    return json.loads(r[0]) if r else None


# --------------------------------------------------------------------------- tarama
def target(con) -> dict | None:
    t = get_meta(con, "gecmis_hedef")
    return json.loads(t) if t else None


def set_target(con, start: str, end: str | None = None) -> dict:
    t = {"baslangic": start, "bitis": end or dt.date.today().isoformat()}
    set_meta(con, "gecmis_hedef", json.dumps(t))
    con.commit()
    return t


def erken_bas(cfg, t: dict) -> str:
    """Kayıtların başladığı gün: beyan tarihinden önceki erken dönem varsa onun başı (ör. 7 Ekim 2023)."""
    e = cfg.gecmis.get("erken_baslangic")
    return min(str(e), t["baslangic"]) if e else t["baslangic"]


def _imza(cfg, t: dict | None) -> str:
    """Taramanın kapsamı; ayarlar değişince (ör. gemi sınırı artınca) tamamlanmış tarama yeniden açılır."""
    targets = cfg.dest_countries()
    k = {"hedef": t, "sinir": cfg.gecmis["max_gemi_liman"], "erken": cfg.gecmis.get("erken_baslangic"),
         "varis": sorted(p.code for p in cfg.ports if p.country in targets and not p.approach),
         "karanlik": sorted(p.code for p in cfg.ports if p.retro_dark)}
    return hashlib.sha1(json.dumps(k, sort_keys=True).encode()).hexdigest()[:12]


def segments(t: dict, today: dt.date, lag: int = 3, step: int = 7) -> list[tuple[str, str]]:
    """Ana taramadan sonraki haftalık güncelleme dilimleri: 14 günlük, birbirinin 7 gününü örten pencereler.

    GFW verisi birkaç gün geç oluştuğu için bitişi bugünden en az `lag` gün önce olan dilimler taranır.
    """
    end0 = dt.date.fromisoformat(t["bitis"])
    out, k = [], 1
    while True:
        b = end0 + dt.timedelta(days=step * k)
        if b > today - dt.timedelta(days=lag):
            break
        out.append(((b - dt.timedelta(days=2 * step)).isoformat(), b.isoformat()))
        k += 1
    return out


class _Plan:
    """Görevleri sırayla yürütür; süre dolunca istek yapmayı bırakır ama kalan görevleri saymayı sürdürür."""

    def __init__(self, con, client, deadline):
        self.con, self.client, self.deadline = con, client, deadline
        self.done = self.total = 0
        self.out = client is None

    def _time_left(self) -> bool:
        lim = getattr(self.client, "limit", None)
        if self.out or (self.deadline is not None and time.time() > self.deadline) or \
                (lim is not None and self.client.requests >= lim):
            self.out = True
        return not self.out

    def area(self, key: str, fetch, ham: bool = False) -> list[dict] | None:
        """Alan sorgusunun sonucu (önbellekten ya da yeni istekle); süre yoksa None."""
        self.total += 1
        data = _cache_get(self.con, key)
        if data is None and self._time_left():
            sonuc = fetch()
            data = _store(self.con, key, sonuc, ham=ham) if sonuc is not None else None
        if data is not None:
            self.done += 1
        return data

    def ensure(self, key: str, fetch) -> None:
        """Gemi sorgusu: yalnızca önbellekte olması gerekir, içeriği burada okunmaz."""
        self.total += 1
        if self.con.execute("SELECT 1 FROM gfw_cache WHERE key=?", (key,)).fetchone():
            self.done += 1
        elif self._time_left():
            _store(self.con, key, fetch())
            self.done += 1


def offshore_zones(cfg) -> list:
    """Hedef ülkenin kıyı yaklaşma alanları (ör. İsrail kıyı açıkları)."""
    return [p for p in cfg.ports if p.approach and p.country in cfg.dest_countries()]


def iz_bolgeleri(cfg) -> list[tuple[str, str, dict]]:
    """Konum izi aranan bölgeler: (kod, tür, GeoJSON). 'IZK' varış ülkesinin açık denizi, 'IZS<n>' sahte konum noktaları."""
    from .geo import Area
    out = []
    box = cfg.th.get("hedef_acik_deniz")
    if box:
        (la0, lo0), (la1, lo1) = box
        out.append(("IZK", "acik", {"type": "Polygon", "coordinates": [[[lo0, la0], [lo1, la0], [lo1, la1], [lo0, la1], [lo0, la0]]]}))
    for i, n in enumerate(cfg.th.get("sahte_konum_noktalari") or []):
        out.append((f"IZS{i}", "sahte", geometry(Area({"merkez": n["merkez"], "yaricap_km": n.get("yaricap_km", 4)}))))
    return out


def _episodes(rows: list[dict], min_saat: float = 12) -> list[tuple[str, tuple]]:
    """Gemi-gün satırlarından ardışık günlerde en az min_saat bekleme dönemleri: (gemi, (ilk gün, son gün, saat, gemi))."""
    by: dict[str, list] = {}
    for r in rows:
        if r.get("vid") and r.get("date") and str(r.get("tip") or "").lower() not in SKIP_TYPES:
            by.setdefault(r["vid"], []).append(r)
    out = []
    for vid, rs in by.items():
        rs.sort(key=lambda r: r["date"])
        cur = None
        for r in rs + [None]:
            if r and cur and (dt.date.fromisoformat(r["date"]) - dt.date.fromisoformat(cur[1])).days <= 1:
                cur = (cur[0], r["date"], cur[2] + (r.get("hours") or 0), cur[3])
                continue
            if cur and cur[2] >= min_saat:
                out.append((vid, cur))
            cur = (r["date"], r["date"], r.get("hours") or 0, r) if r else None
    return out


def _vessels_in(evs: list[dict] | None, into: dict[str, dict]) -> None:
    for e in evs or []:
        v = e.get("vessel") or {}
        if v.get("id") and str(v.get("type") or "").lower() not in SKIP_TYPES:
            into.setdefault(v["id"], v)


def scan(cfg, con, client: Client | None, budget_min: float | None = None, today: dt.date | None = None) -> dict:
    """Önbellekte olmayan istekleri süre bütçesi içinde yapar; sonra sonuçları hesaplar.

    1) Ana tarama: hedef dönemde varış limanlarına uğrayan bütün gemiler ve karanlık sefer aranan
       limanlardan çıkan gemiler; her birinin dönem boyunca liman ziyaretleri ve AIS boşlukları.
    2) Güncelleme: ana dönemden sonraki her hafta için aynı sorgular, daha kısa pencereyle.
    """
    t = target(con)
    if not t:
        return {"durum": "hedef yok"}
    start, end = t["baslangic"], t["bitis"]
    today = today or now_utc().date()
    deadline = time.time() + budget_min * 60 if budget_min else None
    lookback = cfg.gecmis["onceki_gun"]
    v_start = (dt.date.fromisoformat(start) - dt.timedelta(days=lookback)).isoformat()
    targets = cfg.dest_countries()
    dest_ports = [p for p in cfg.ports if p.country in targets and not p.approach]
    dark_ports = [p for p in cfg.ports if p.retro_dark]
    pv_extra = {"confidences": ["3", "4"]}
    plan = _Plan(con, client, deadline)
    errors = False
    # öncelik grubu -> [tamamlanan, toplam] gemi sorgusu (-1 basın, 0 varış limanı, 1 Ceyhan ve kıyı açığı,
    # 2 varış limanı erken dönem, 3 Ceyhan erken dönem, 4-5 diğerleri)
    oncelik: dict[str, list[int]] = {}
    segs = segments(t, today)
    try:
        # 1) ana tarama
        vessel_ids: dict[str, dict] = {}
        partial = False
        ceyhan_ids: set = set()
        for ports, cap in ((dest_ports, None), (dark_ports, cfg.gecmis["max_gemi_liman"])):
            for p in ports:
                seen_here: dict[str, dict] = {}
                for a, b in chunks(start, end):
                    evs = plan.area(f"area_pv:{p.code}:{a}:{b}",
                                    lambda p=p, a=a, b=b: client.area_events(DS_PV, geometry(p.area), a, b, pv_extra))
                    partial |= evs is None
                    _vessels_in(evs, seen_here)
                    for e in evs or []:
                        pos = e.get("position") or {}
                        if pos.get("lat") is not None and haversine_km(pos["lat"], pos["lon"], *CEYHAN) <= CEYHAN_KM:
                            ceyhan_ids.add((e.get("vessel") or {}).get("id"))
                ids = list(seen_here)
                if cap and len(ids) > cap:
                    log.warning("%s: %d gemi bulundu, ilk %d tanesi taranacak", p.name, len(ids), cap)
                    ids = ids[:cap]
                for vid in ids:
                    vessel_ids.setdefault(vid, seen_here[vid])
            if ports is dest_ports:
                dest_ids = set(vessel_ids)
        # gemi sorguları öncelik sırasıyla: 0 varış limanlarına uğrayanlar, 1 Ceyhan petrol terminallerine uğrayanlar
        # ve hedef ülke kıyı açığında bekleyenler, 2-3 aynı gruplar erken dönemde, 4-5 diğerleri
        # basında adı geçen gemiler (gemiler.yaml, "basin") en önce: tespitlerin sağlaması onlarla yapılır
        from .tanker import _basin
        basin_ad = {str(b.get("ad") or "").upper() for b in _basin(cfg)} - {""}

        def basinda(v: dict) -> bool:
            return str((v or {}).get("name") or "").upper().strip() in basin_ad

        gorev: list[tuple] = []
        for i, vid in enumerate(vessel_ids):
            gorev.append(((-1 if basinda(vessel_ids[vid]) else 0 if vid in dest_ids else 1 if vid in ceyhan_ids else 4),
                          i, vid, v_start, end))
        if not partial:
            set_meta(con, "gecmis_gemiler", json.dumps(list(vessel_ids)))
        # 1b) erken dönem (ör. 7 Ekim 2023 – beyan tarihi): aynı sorgular, ayrı pencereyle
        e0 = erken_bas(cfg, t)
        if e0 < start:
            ew0 = (dt.date.fromisoformat(e0) - dt.timedelta(days=lookback)).isoformat()
            erken_ids: dict[str, dict] = {}
            dest_e: set = set()
            for ports in (dest_ports, dark_ports):
                for p in ports:
                    for a, b in chunks(e0, start):
                        evs = plan.area(f"area_pv:{p.code}:{a}:{b}",
                                        lambda p=p, a=a, b=b: client.area_events(DS_PV, geometry(p.area), a, b, pv_extra))
                        _vessels_in(evs, erken_ids)
                        for e in evs or []:
                            pos = e.get("position") or {}
                            if pos.get("lat") is not None and haversine_km(pos["lat"], pos["lon"], *CEYHAN) <= CEYHAN_KM:
                                ceyhan_ids.add((e.get("vessel") or {}).get("id"))
                if ports is dest_ports:
                    dest_e = set(erken_ids)
            for i, vid in enumerate(erken_ids):
                gorev.append(((-1 if basinda(erken_ids[vid]) else 2 if vid in dest_e else 3 if vid in ceyhan_ids else 5),
                              i, vid, ew0, start))

        def yurut(isler):
            for _p, _i, vid, w0, w1 in sorted(isler):
                say = oncelik.setdefault(str(_p), [0, 0])
                say[1] += 1
                once = plan.done
                for ds, kind in ((DS_PV, "v_pv"), (DS_GAP, "v_gap")):
                    plan.ensure(f"{kind}:{vid}:{w0}:{w1}",
                                lambda ds=ds, vid=vid, w0=w0, w1=w1: client.vessel_events(ds, vid, w0, w1))
                if plan.done - once == 2:
                    say[0] += 1
        # önce basındaki gemiler ve varış limanlarına uğrayanlar; sonra kıyı açığı sorguları; sonra kalanlar
        yurut([g for g in gorev if g[0] <= 0])
        gorev = [g for g in gorev if g[0] > 0]
        # 1c) hedef ülkenin kıyı açıkları: limana girmeden bekleyen gemiler (şamandıra boşaltması, aktarma).
        # Alan sorgusu az istek tutar; bekleyen gemilerin geçmişi Ceyhan gemileriyle aynı öncelikte alınır.
        son = (today - dt.timedelta(days=3)).isoformat()
        bilinen = {k.split(":")[1] for (k,) in con.execute("SELECT key FROM gfw_cache WHERE key LIKE 'v_pv:%'")}
        bilinen |= set(vessel_ids)
        def varlik(geom, a, b):
            try:
                return client.presence(geom, a, b)
            except RuntimeError as e:
                log.warning("AIS varlık sorgusu atlandı (%s – %s): %s", a, b, str(e)[:160])
                return None
        for z in offshore_zones(cfg):
            for a, b in chunks(erken_bas(cfg, t), son, days=30):
                evs = plan.area(f"pres:{z.code}:{a}:{b}",
                                lambda z=z, a=a, b=b: varlik(geometry(z.area), a, b), ham=True)
                for vid, (k0, k1, _h, _v) in _episodes(evs or []):
                    if vid in bilinen:
                        continue
                    w0 = (dt.date.fromisoformat(k0) - dt.timedelta(days=60)).isoformat()
                    w1 = (dt.date.fromisoformat(k1) + dt.timedelta(days=2)).isoformat()
                    gorev.append((1, -1, vid, w0, w1))
                    bilinen.add(vid)
        # 1d) konum izi: varış ülkesinin açık denizinde ya da GPS karıştırmasının sahte konum noktasında görünen gemiler.
        # Açık deniz kutusu kalabalık: 15 günlük dilimler. Zaman aşımına uğrayan dilim atlanır, sonraki çalıştırmada denenir.
        def iz_sorgu(geom, a, b):
            try:
                return client.presence(geom, a, b)
            except RuntimeError as e:
                log.warning("Konum izi sorgusu atlandı (%s – %s): %s", a, b, str(e)[:160])
                return None
        for kod, tur, geom in iz_bolgeleri(cfg):
            for a, b in chunks(erken_bas(cfg, t), son, days=15 if tur == "acik" else 30):
                plan.area(f"pres:{kod}:{a}:{b}", lambda geom=geom, a=a, b=b: iz_sorgu(geom, a, b), ham=True)
        yurut(gorev)
        # 2) haftalık güncelleme dilimleri
        dark_hist: list[set[str]] = []
        for a, b in segs:
            dest_here: dict[str, dict] = {}
            dark_here: dict[str, dict] = {}
            for ports, into in ((dest_ports, dest_here), (dark_ports, dark_here)):
                for p in ports:
                    _vessels_in(plan.area(f"area_pv:{p.code}:{a}:{b}",
                                          lambda p=p, a=a, b=b: client.area_events(DS_PV, geometry(p.area), a, b, pv_extra)),
                                into)
            # karanlık sefer haftalar sürebilir: önceki üç dilimde çıkan gemilerin boşlukları da güncellenir
            vs = set(dest_here) | set(dark_here)
            for h in dark_hist[-3:]:
                vs |= h
            dark_hist.append(set(dark_here))
            w0 = (dt.date.fromisoformat(a) - dt.timedelta(days=50)).isoformat()
            for vid in sorted(vs):
                for ds, kind in ((DS_PV, "v_pv"), (DS_GAP, "v_gap")):
                    plan.ensure(f"{kind}:{vid}:{w0}:{b}",
                                lambda ds=ds, vid=vid, w0=w0, b=b: client.vessel_events(ds, vid, w0, b))
    except RuntimeError as e:
        log.error("%s", e)
        errors = True
    complete = not plan.out and not errors
    n = compute(cfg, con)
    status = {"hedef": t, "tamam": complete, "imza": _imza(cfg, t), "gorev": [plan.done, plan.total], "kayit": n,
              "oncelik": oncelik,
              "dilim": len(segs), "son_dilim": segs[-1][1] if segs else None,
              "istek": client.requests if client else 0, "guncelleme": iso(now_utc())}
    set_meta(con, "gecmis_durum", json.dumps(status))
    con.commit()
    return status


# --------------------------------------------------------------------------- sonuç
def _visit_place(cfg, e: dict) -> tuple[str | None, str, str | None, float | None, float | None]:
    """(ülke kodu, liman adı, bizim liman kodumuz, enlem, boylam)"""
    pos = e.get("position") or {}
    pv = e.get("port_visit") or {}
    anc = pv.get("startAnchorage") or pv.get("endAnchorage") or {}
    lat, lon = pos.get("lat", anc.get("lat")), pos.get("lon", anc.get("lon"))
    c = cfg.country_from_iso3(anc.get("flag"))
    if lat is not None and lon is not None:
        code, _ = cfg.locate(lat, lon)
        if code and not cfg.port_by_code[code].approach:
            p = cfg.port_by_code[code]
            return p.country, p.name, code, lat, lon
        # liman alanımızın biraz dışındaki demirleme yerleri: aynı ülkedeki en yakın limanımız (40 km)
        best = None
        for p in cfg.ports:
            if p.approach or (c and p.country != c):
                continue
            d = haversine_km(lat, lon, *p.area.center)
            if d <= 40 and (best is None or d < best[0]):
                best = (d, p)
        if best:
            p = best[1]
            return p.country, p.name, p.code, lat, lon
    nm = (anc.get("name") or "").strip()
    flag = anc.get("flag") or ""
    ulke = cfg.country_name(c) if c else ULKE_ADLARI.get(flag, flag)
    if nm and not re.fullmatch(r"[A-Za-z]{3}-\d+", nm):  # "GRC-184" gibi adsız demirleme yerleri
        nm = " ".join(TR_ADLAR.get(w, w) for w in nm.title().split())
        name = f"{nm}, {ulke}" if ulke else nm
    elif nm:
        name = f"{ulke}, adsız demirleme yeri" if ulke else "Adsız demirleme yeri"
    else:
        name = f"{ulke} limanı" if ulke else "Bilinmeyen liman"
    return c, name, None, lat, lon


def _gap_info(g: dict) -> dict:
    gp = g.get("gap") or {}
    off = gp.get("offPosition") or g.get("position") or {}
    on = gp.get("onPosition") or {}
    dur = gp.get("durationHours")
    if dur is None and g.get("start") and g.get("end"):
        dur = hours_between(g["start"], g["end"])
    return {"eid": g.get("id"), "baslangic": g.get("start"), "bitis": g.get("end"), "saat": round(dur or 0, 1),
            "kapanis": [off.get("lat"), off.get("lon")], "acilis": [on.get("lat"), on.get("lon")],
            "mesafe_km": gp.get("distanceKm"), "kasitli": gp.get("intentionalDisabling")}


def _vessel_keys(con) -> dict[str, dict[str, list[str]]]:
    """gemi kimliği -> önbellekteki liman ziyareti ve AIS boşluğu sorgularının anahtarları (bütün pencereler)"""
    out: dict[str, dict[str, list[str]]] = {}
    for (key,) in con.execute("SELECT key FROM gfw_cache WHERE key LIKE 'v_pv:%' OR key LIKE 'v_gap:%'"):
        kind, vid = key.split(":")[:2]
        out.setdefault(vid, {"pv": [], "gap": []})["pv" if kind == "v_pv" else "gap"].append(key)
    return out


def _merged(con, keys: list[str]) -> list[dict]:
    """Aynı geminin farklı pencerelerdeki olayları; aynı olay bir kez."""
    seen: dict[str, dict] = {}
    for k in sorted(keys):
        for e in _cache_get(con, k) or []:
            seen.setdefault(e.get("id") or f"{e.get('type')}|{e.get('start')}", e)
    return list(seen.values())


def compute(cfg, con, *_eski) -> int:
    con.execute("DELETE FROM gecmis")
    con.execute("DELETE FROM dunya")
    hedef = cfg.dest_countries()
    # tarama sürerken de önbelleğe girmiş bütün gemiler, bütün pencereleriyle hesaba katılır
    vkeys = _vessel_keys(con)
    ids = sorted(vkeys)
    ceyhan: list[dict] = []
    end = "9999-12-31"  # güncelleme dilimleriyle dönem açık uçlu
    th = cfg.th
    max_h = th["guzergah_max_gun"] * 24
    dark_h = th["karanlik_sefer_saat"]
    dark_win = th["karanlik_sefer_gun"] * 24
    acik_h = th.get("hedef_acik_bosluk_saat") or 12
    max_mids = th["aktarma_max_liman"]
    via_h = th["aktarma_max_gun"] * 24
    direct_h = th["dogrudan_max_gun"] * 24
    t = target(con)
    period = f"{erken_bas(cfg, t)}T00:00:00Z" if t else ""
    # beyanı veren ülke (izlenen limanların ülkesi): dönem kuralı o ülkedeki uğrağa bakar
    home = {p.country for p in cfg.ports if p.role == "izlenen"}
    # ara liman sayılan ülkeler: yapılandırmadaki diğer ülkeler (Yunanistan, Bulgaristan, Mısır, Kıbrıs).
    # Başka bir ülkenin limanına uğrayan geminin yükü oradan gelmiş olabilir (ör. Ambarlı → Novorossiysk → Hayfa).
    aktarma = set(th.get("aktarma_ulkeleri") or []) or (set(cfg.countries) - home - cfg.dest_countries())
    # konum izi: gemi gemi, varış ülkesinin açık denizinde (acik) ve sahte konum noktalarında (sahte) görüldüğü günler
    iz_gun: dict[str, dict[str, dict[str, float]]] = {"acik": {}, "sahte": {}}
    for kod, tur, _g in iz_bolgeleri(cfg):
        for (key,) in con.execute("SELECT key FROM gfw_cache WHERE key LIKE ?", (f"pres:{kod}:%",)):
            for r in _cache_get(con, key) or []:
                if r.get("vid") and r.get("date") and (r.get("hours") or 0) > 0:
                    g = iz_gun[tur].setdefault(r["vid"], {})
                    g[r["date"]] = round(g.get(r["date"], 0) + (r.get("hours") or 0), 1)

    def izler(vid_, a_, b_):
        """a_ ile b_ arasında (gün) geminin iz günleri."""
        return {tur: sorted((gun_, h) for gun_, h in (iz_gun[tur].get(vid_) or {}).items() if a_[:10] <= gun_ <= b_[:10])
                for tur in ("acik", "sahte")}
    donus_h = (th.get("limansiz_donus_gun") or 20) * 24
    # hedef ülke kıyı açığındaki bekleme dönemleri, gemi gemi (Ceyhan çıkışlarıyla eşleştirmek için)
    acik: dict[str, list] = {}
    for z in offshore_zones(cfg):
        rows = []
        for (key,) in con.execute("SELECT key FROM gfw_cache WHERE key LIKE ?", (f"pres:{z.code}:%",)):
            rows += _cache_get(con, key) or []
        for vid_, (e0, e1, saat, _o) in _episodes(rows):
            acik.setdefault(vid_, []).append({"bas": e0, "son": e1, "saat": round(saat, 1)})
    petrol_lim: dict[str, list[str]] = {}
    n = 0
    for vid in ids:
        if not vkeys[vid]["pv"]:
            continue
        pvs = _merged(con, vkeys[vid]["pv"])
        gaps = _merged(con, vkeys[vid]["gap"])
        visits = []
        for e in sorted(pvs, key=lambda e: e["start"] or ""):
            if not e.get("start"):
                continue
            c, name, code, lat, lon = _visit_place(cfg, e)
            if code is None and lat is not None and cfg.in_transit_zone(lat, lon):
                continue  # boğaz geçişi için bekleme: liman uğrağı değil
            end = e["end"] or e["start"]
            prev = visits[-1] if visits else None
            if prev and prev["name"] == name and prev["c"] == c and hours_between(prev["end"], e["start"]) <= 72:
                # aynı limanda art arda iki kayıt (demirleme, sonra rıhtım): tek uğrak
                if end >= prev["end"]:
                    prev["eid_son"] = e.get("id")
                prev["end"] = max(prev["end"], end)
                continue
            pv_ = e.get("port_visit") or {}
            anc = pv_.get("startAnchorage") or pv_.get("endAnchorage") or {}
            visits.append({"c": c, "name": name, "code": code, "lat": lat, "lon": lon, "iso3": anc.get("flag"),
                           "anc": str(anc.get("name") or "").upper(), "start": e["start"], "end": end, "vessel": e["vessel"],
                           "eid": e.get("id")})
        gl = sorted((_gap_info(g) for g in gaps if g.get("start")), key=lambda g: g["baslangic"])
        # Ceyhan'a uğrayan gemi başka petrol iskelelerine de uğruyor mu? (tanker olduğunun rotadan kanıtı)
        if any(v["lat"] is not None and haversine_km(v["lat"], v["lon"], *CEYHAN) <= CEYHAN_KM for v in visits):
            pl = sorted({ad for v in visits for k, ad in PETROL_ISKELELERI.items() if k in v["anc"]})
            if pl:
                petrol_lim[vid] = pl
        # dünyadan hedef ülkeye: her varışın bir önceki uğrağı (hangi ülkeden geldi?)
        for i, v in enumerate(visits):
            if v["c"] not in hedef or v["start"] < period or (i and visits[i - 1]["c"] == v["c"]):
                continue
            pr = visits[i - 1] if i and hours_between(visits[i - 1]["end"], v["start"]) <= 45 * 24 else None
            vs_ = v["vessel"]
            con.execute("INSERT INTO dunya(vessel_id,ssvid,name,flag,vtype,origin,origin_iso3,o_lat,o_lon,t_dep,dest,t_arr) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (vid, vs_.get("ssvid"), vs_.get("name"), vs_.get("flag"), vs_.get("type"),
                         pr["name"] if pr else None, (pr.get("iso3") or ("TUR" if pr["c"] == "TR" else None)) if pr else None,
                         pr["lat"] if pr else None, pr["lon"] if pr else None, pr["end"] if pr else None,
                         v["name"], v["start"]))
        # Ceyhan petrol terminallerinden çıkışlar ve sonraki uğrak (nereye gittiler?)
        for i, v in enumerate(visits):
            if v["code"] and v["lat"] is not None and v["end"] >= period and \
                    haversine_km(v["lat"], v["lon"], *CEYHAN) <= CEYHAN_KM and v["end"] <= f"{end}T23:59:59Z":
                nx = visits[i + 1] if i + 1 < len(visits) else None
                kapali = [g for g in gl if v["end"] <= g["baslangic"] < (nx["start"] if nx else "9999")
                          and g["saat"] >= dark_h and g.get("kasitli") is not False]
                # tanker dosyaları için: sonraki uğraklar (45 gün), yoldaki AIS boşlukları, kıyı açığında bekleme
                bit = nx["start"] if nx else add_hours(v["end"], dark_win)
                sonra = [w for w in visits[i + 1:i + 6] if hours_between(v["end"], w["start"]) <= 45 * 24]
                bos = [{**g, "il": cfg.hedef_izi(*g["kapanis"]) or cfg.hedef_izi(*g["acilis"]),
                        "sahte": cfg.spoof_point(*g["kapanis"]) or cfg.spoof_point(*g["acilis"])}
                       for g in gl if v["end"] <= g["baslangic"] < bit and g["saat"] >= acik_h]
                bekle = [e for e in acik.get(vid, []) if v["end"][:10] <= e["bas"] <= bit[:10]]
                # Ceyhan'dan çıkıp hiçbir limana uğramadan Ceyhan'a dönüş: yükün boşaltıldığı yer kayıtsız
                donus = None
                if nx and nx["lat"] is not None and haversine_km(nx["lat"], nx["lon"], *CEYHAN) <= CEYHAN_KM and \
                        hours_between(v["end"], nx["start"]) <= donus_h:
                    donus = round(hours_between(v["end"], nx["start"]) / 24, 1)
                ceyhan.append({"vid": vid, "ad": v["vessel"].get("name"), "m": v["vessel"].get("ssvid"),
                               "t0": v["start"], "nokta": [round(v["lat"], 3), round(v["lon"], 3)],
                               "sonrakiler": [{"ad": w["name"], "c": w["c"], "giris": w["start"], "cikis": w["end"],
                                               "lat": w["lat"], "lon": w["lon"]} for w in sonra],
                               "bosluk": bos, "acik": bekle, "donus": donus, "iz": izler(vid, v["end"], bit),
                               "tip": v["vessel"].get("type"),
                               "b": v["vessel"].get("flag"), "t": v["end"], "sonraki": nx["name"] if nx else None,
                               "ulke": nx["c"] if nx else None, "t1": nx["start"] if nx else None,
                               "ulke_ad": (cfg.country_name(nx["c"]) if nx["c"] else
                                           re.sub(r"( limanı|, adsız demirleme yeri)$", "", nx["name"].split(", ")[-1])) if nx else None,
                               "karanlik": round(sum(g["saat"] for g in kapali), 1) or None})
        for (A, B) in cfg.directions:
            used = set()
            for i, v in enumerate(visits):
                if v["c"] != B:
                    continue
                mids, j = [], i - 1
                while j >= 0:
                    w = visits[j]
                    if hours_between(w["end"], v["start"]) > max_h or w["c"] == B:
                        j = -1
                        break
                    if w["c"] == A:
                        break
                    if w["c"] not in aktarma:
                        j = -1
                        break
                    mids.append(w)
                    j -= 1
                if j < 0:
                    continue
                o = visits[j]
                # ihracatta çıkış, ithalatta varış tarihi beyandan sonra olmalı
                if (o["end"] if A in home or B not in home else v["start"]) < period:
                    continue
                span = hours_between(o["end"], v["start"])
                if (mids and (len(mids) > max_mids or span > via_h)) or (not mids and span > direct_h):
                    continue  # bağ zayıf: çok fazla ara liman ya da çok uzun süre
                used.add(j)
                legs = [g for g in gl if o["end"] <= g["baslangic"] < v["start"] and g["saat"] >= th["ais_bosluk_saat"]]
                cls = "karanlik_bacak" if legs else ("aktarmali" if mids else "dogrudan")
                _insert(con, A, B, cls, vid, v["vessel"], o, v, None, list(reversed(mids)), legs)
                n += 1
            for i, o in enumerate(visits):
                if o["c"] != A or i in used or o["end"] < period:
                    continue
                nxt = visits[i + 1] if i + 1 < len(visits) else None
                if nxt and nxt["c"] == B:
                    continue
                lim = add_hours(o["end"], dark_win)
                if nxt and nxt["start"] < lim:
                    lim = nxt["start"]
                # AIS'i varış ülkesinin açıklarında kapatan ya da orada yeniden açan gemi (GFW "kasıtlı" saymasa da):
                # basında adı geçen Ceyhan tankerleri AIS'i yolda kapatıp Aşkelon'dan ayrılınca açıyor
                if B in hedef:
                    ac = [g for g in gl if o["end"] <= g["baslangic"] < lim and g["saat"] >= acik_h
                          and (cfg.hedef_izi(*g["kapanis"]) or cfg.hedef_izi(*g["acilis"]))]
                    if ac:
                        g = ac[0]
                        yer, tt = (g["acilis"], g["bitis"]) if cfg.hedef_izi(*g["acilis"]) else (g["kapanis"], g["baslangic"])
                        sp = cfg.spoof_point(*yer)
                        d = {"name": (f"{cfg.country_name(B)} yakınında, sahte konum: {sp} (AIS kapalıyken)" if sp else
                                      f"{cfg.country_name(B)} açıkları (AIS kapalıyken)"),
                             "c": B, "start": tt or g["baslangic"], "lat": yer[0], "lon": yer[1]}
                        _insert(con, A, B, "karanlik_acik", vid, o["vessel"], o, d, nxt, [], ac)
                        n += 1
                        continue
                    # AIS açıkken konum izi: gemi limana girmeden varış ülkesinin açık denizinde ya da sahte konum
                    # noktasında görüldü (GPS karıştırması limana girişin kaydını da bozabilir)
                    iz = izler(vid, o["end"], lim)
                    if iz["acik"] or iz["sahte"]:
                        gun0 = (iz["acik"] or iz["sahte"])[0][0]
                        sp = next((nm.get("ad") for nm in th.get("sahte_konum_noktalari") or []), None)
                        if iz["acik"]:
                            (la0, lo0), (la1, lo1) = th["hedef_acik_deniz"]
                            yer_ = ((la0 + la1) / 2, (lo0 + lo1) / 2)
                            ad_ = f"{cfg.country_name(B)} açıkları ({len(iz['acik'])} gün konum, limana girişi kayıtsız)"
                        else:
                            nm0 = (th.get("sahte_konum_noktalari") or [{}])[0]
                            yer_ = tuple(nm0.get("merkez") or (None, None))
                            ad_ = f"{cfg.country_name(B)} yakınında, sahte konum: {sp} ({len(iz['sahte'])} gün)"
                        d = {"name": ad_, "c": B, "start": f"{gun0}T00:00:00Z", "lat": yer_[0], "lon": yer_[1], "iz": iz}
                        _insert(con, A, B, "iz_hedef", vid, o["vessel"], o, d, nxt, [], [])
                        n += 1
                        continue
                # GFW'nin "kasıtlı kapatma" saydığı, liman yakınında olmayan uzun boşluklar
                legs = [g for g in gl if o["end"] <= g["baslangic"] < lim and g["saat"] >= dark_h
                        and g.get("kasitli") is not False
                        and None not in g["kapanis"] and cfg.in_dark_box(*g["kapanis"])
                        and not cfg.near_port(*g["kapanis"])]
                if legs:
                    _insert(con, A, B, "karanlik_sefer", vid, o["vessel"], o, None, nxt, [], legs)
                    n += 1
    n += _offshore(cfg, con, vkeys, period, home, aktarma, via_h, direct_h, max_mids)
    ceyhan.sort(key=lambda x: x["t"], reverse=True)
    set_meta(con, "ceyhan_cikislari", json.dumps(ceyhan, ensure_ascii=False))
    set_meta(con, "gemi_petrol_iskeleleri", json.dumps(petrol_lim, ensure_ascii=False))
    con.commit()
    return n


def _offshore(cfg, con, vkeys, period, home, aktarma, via_h, direct_h, max_mids) -> int:
    """Hedef ülke kıyı açığında limana girmeden bekleyen gemiler: bir önceki uğrağı ve (varsa) Türk limanı çıkışı."""
    n = 0
    for z in offshore_zones(cfg):
        rows = []
        for (key,) in con.execute("SELECT key FROM gfw_cache WHERE key LIKE ?", (f"pres:{z.code}:%",)):
            rows += _cache_get(con, key) or []
        clat, clon = z.area.center
        for vid, (e0, e1, saat, ornek) in _episodes(rows):
            t0, t1 = f"{e0}T00:00:00Z", f"{e1}T23:59:59Z"
            if t0 < period or vid not in vkeys:
                continue
            visits = []
            for e in sorted(_merged(con, vkeys[vid]["pv"]), key=lambda e: e.get("start") or ""):
                if not e.get("start"):
                    continue
                c, name, code, lat, lon = _visit_place(cfg, e)
                if code is None and lat is not None and cfg.in_transit_zone(lat, lon):
                    continue
                pv_ = e.get("port_visit") or {}
                visits.append({"c": c, "name": name, "code": code, "lat": lat, "lon": lon,
                               "iso3": (pv_.get("startAnchorage") or {}).get("flag"),
                               "start": e["start"], "end": e.get("end") or e["start"], "vessel": e.get("vessel") or {}})
            # aynı günlerde hedef ülkede liman ziyareti varsa bu bekleme liman sırasıdır
            if any(v["c"] == z.country and v["start"] <= add_hours(t1, 24) and v["end"] >= add_hours(t0, -24) for v in visits):
                continue
            onceki = [v for v in visits if v["end"] <= t0]
            vessel = {"name": ornek.get("ad"), "ssvid": ornek.get("m"), "flag": ornek.get("b"), "type": ornek.get("tip")}
            d = {"name": f"{cfg.country_name(z.country)} kıyı açıkları (limana girmeden, {round(saat)} saat)",
                 "c": z.country, "start": t0, "lat": clat, "lon": clon}
            pr = onceki[-1] if onceki and hours_between(onceki[-1]["end"], t0) <= 45 * 24 else None
            con.execute("INSERT INTO dunya(vessel_id,ssvid,name,flag,vtype,origin,origin_iso3,o_lat,o_lon,t_dep,dest,t_arr) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                        (vid, vessel["ssvid"], vessel["name"], vessel["flag"], vessel["type"],
                         pr["name"] if pr else None, (pr.get("iso3") or ("TUR" if pr["c"] == "TR" else None)) if pr else None,
                         pr["lat"] if pr else None, pr["lon"] if pr else None, pr["end"] if pr else None, d["name"], t0))
            # Türk limanından mı geldi? (ara limanlar aktarma ülkelerinde)
            mids, j = [], len(onceki) - 1
            while j >= 0:
                w = onceki[j]
                if w["c"] in home:
                    break
                if w["c"] not in aktarma or w["c"] == z.country:
                    j = -1
                    break
                mids.append(w)
                j -= 1
            if j < 0:
                continue
            o = onceki[j]
            span = hours_between(o["end"], t0)
            if o["end"] < period or (mids and (len(mids) > max_mids or span > via_h)) or (not mids and span > direct_h):
                continue
            for A in home:
                _insert(con, A, z.country, "kiyida_bosaltma", vid, vessel, o, d, None, list(reversed(mids)), [])
                n += 1
    return n


def _insert(con, A, B, cls, vid, vessel, o, d, nxt, mids, gaps):
    # kaynak: seferin dayandığı GFW olaylarının kimlikleri (çıkış ve varış liman ziyareti, ara uğraklar, AIS boşlukları)
    kaynak = {"cikis": o.get("eid_son") or o.get("eid"), "varis": d.get("eid") if d else None,
              "ara": [m.get("eid") for m in mids if m.get("eid")], "bosluk": [g.get("eid") for g in gaps if g.get("eid")]}
    if d and d.get("iz"):
        kaynak["iz"] = d["iz"]  # GFW AIS varlık verisinde iz günleri ve saatleri
    con.execute(
        """INSERT INTO gecmis(direction,cls,vessel_id,ssvid,name,flag,vtype,origin,origin_country,t_dep,dest,
           dest_country,t_arr,next_port,mids,gaps,o_lat,o_lon,d_lat,d_lon,kaynak)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (f"{A}>{B}", cls, vid, vessel.get("ssvid"), vessel.get("name"), vessel.get("flag"), vessel.get("type"),
         o["name"], o["c"], o["end"], d["name"] if d else None, d["c"] if d else None,
         d["start"] if d else (gaps[0]["bitis"] if gaps else None), nxt["name"] if nxt else None,
         json.dumps([{"liman": m["name"], "ulke": m["c"], "giris": m["start"], "cikis": m["end"],
                      "lat": m.get("lat"), "lon": m.get("lon")} for m in mids], ensure_ascii=False),
         json.dumps(gaps, ensure_ascii=False),
         o.get("lat"), o.get("lon"), d.get("lat") if d else None, d.get("lon") if d else None,
         json.dumps(kaynak, ensure_ascii=False)))


def run(cfg, start: str | None, end: str | None, budget_min: float | None, istek: int | None = None) -> dict:
    from . import gfw_sinir
    con = connect(db_path(cfg))
    try:
        if start:
            set_target(con, start, end)
        if not target(con):
            return {"durum": "hedef yok (ilk çalıştırmada --baslangic ver)"}
        token = os.environ.get(cfg.gecmis["anahtar_degiskeni"], "").strip()
        st = json.loads(get_meta(con, "gecmis_durum", "{}") or "{}")
        t = target(con)
        guncel = st.get("imza") == _imza(cfg, t) and st.get("dilim") == len(segments(t, now_utc().date()))
        if st.get("tamam") and not start and (guncel or not token):
            # tarama bitti ve yeni dilim yok: yalnızca önbellekten yeniden hesapla (kurallar değişmiş olabilir)
            st["kayit"] = compute(cfg, con)
            set_meta(con, "gecmis_durum", json.dumps(st))
            con.commit()
            return {"durum": "tamamlandı", **st}
        client = None
        if token:
            hak = gfw_sinir.hak(con, istek or cfg.gecmis.get("istek_siniri") or 1500)
            log.info("GFW istek hakkı: %d (son 24 saatte %d istek)", hak, gfw_sinir.son24(con))
            client = Client(token, limit=hak)
        else:
            log.warning("GFW anahtarı yok (%s); yalnızca önbellekteki veriler işlenecek", cfg.gecmis["anahtar_degiskeni"])
        try:
            return scan(cfg, con, client, budget_min)
        finally:
            if client:
                gfw_sinir.yaz(con, client.requests)
    finally:
        con.close()
