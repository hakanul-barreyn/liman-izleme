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
from .util import add_hours, hours_between, iso, now_utc

log = logging.getLogger("gecmis")
API = "https://gateway.api.globalfishingwatch.org/v3/events"
DS_PV = "public-global-port-visits-events:latest"
DS_GAP = "public-global-gaps-events:latest"
SKIP_TYPES = ("fishing", "passenger", "gear", "support", "seismic")
# Ülke kodu yapılandırmada olmayan limanlar için Türkçe ülke adları (GFW ISO3 kullanır)
ULKE_ADLARI = {
    "ALB": "Arnavutluk", "ARE": "BAE", "AZE": "Azerbaycan", "BEL": "Belçika", "BGR": "Bulgaristan", "BHR": "Bahreyn",
    "CHN": "Çin", "CYP": "Kıbrıs", "DEU": "Almanya", "DZA": "Cezayir", "EGY": "Mısır", "ESP": "İspanya", "FRA": "Fransa",
    "GBR": "Birleşik Krallık", "GEO": "Gürcistan", "GRC": "Yunanistan", "HRV": "Hırvatistan", "IND": "Hindistan",
    "IRN": "İran", "IRQ": "Irak", "ISR": "İsrail", "ITA": "İtalya", "JOR": "Ürdün", "KWT": "Kuveyt", "LBN": "Lübnan",
    "LBY": "Libya", "MAR": "Fas", "MLT": "Malta", "MNE": "Karadağ", "NLD": "Hollanda", "OMN": "Umman", "PAK": "Pakistan",
    "PRT": "Portekiz", "QAT": "Katar", "ROU": "Romanya", "RUS": "Rusya", "SAU": "Suudi Arabistan", "SVN": "Slovenya",
    "SYR": "Suriye", "TUN": "Tunus", "TUR": "Türkiye", "UKR": "Ukrayna", "USA": "ABD", "XXX": "X ülkesi",
}
# GFW liman adları ASCII; sık görülen Türk limanlarının doğru yazımı
TR_ADLAR = {
    "Aliaga": "Aliağa", "Ambarli": "Ambarlı", "Bandirma": "Bandırma", "Bartin": "Bartın", "Botas": "Botaş",
    "Canakkale": "Çanakkale", "Cesme": "Çeşme", "Derince": "Derince", "Diliskelesi": "Dilişkelesi", "Dortyol": "Dörtyol",
    "Eregli": "Ereğli", "Gulluk": "Güllük", "Haydarpasa": "Haydarpaşa", "Icdas": "İçdaş", "Isdemir": "İsdemir",
    "Iskenderun": "İskenderun", "Istanbul": "İstanbul", "Izmir": "İzmir", "Izmit": "İzmit", "Kapakli": "Kapaklı",
    "Karabiga": "Karabiga", "Tasucu": "Taşucu", "Tekirdag": "Tekirdağ", "Yumurtalik": "Yumurtalık",
}
CLASS_LABELS = {
    "dogrudan": "Doğrudan",
    "aktarmali": "Ara duraklı",
    "karanlik_bacak": "Karanlık bacak (AIS boşluğu)",
    "karanlik_sefer": "Karanlık sefer (varış limanı kayıtsız)",
}


class Client:
    def __init__(self, token: str, pause: float = 0.25):
        self.token = token
        self.pause = pause
        self.requests = 0

    def _req(self, method: str, url: str, body=None) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        for attempt in range(6):
            req = urllib.request.Request(url, data=data, method=method, headers={
                "Authorization": f"Bearer {self.token}", "Content-Type": "application/json",
                "User-Agent": "liman-izleme"})
            try:
                with urllib.request.urlopen(req, timeout=180) as r:
                    self.requests += 1
                    time.sleep(self.pause)
                    return json.loads(r.read().decode())
            except urllib.error.HTTPError as e:
                detail = e.read().decode(errors="replace")[:500]
                if e.code in (429, 500, 502, 503, 504) and attempt < 5:
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


def _store(con, key: str, events: list[dict]) -> list[dict]:
    data = [slim(e) for e in events]
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


def _imza(cfg, t: dict | None) -> str:
    """Taramanın kapsamı; ayarlar değişince (ör. gemi sınırı artınca) tamamlanmış tarama yeniden açılır."""
    targets = cfg.dest_countries()
    k = {"hedef": t, "sinir": cfg.gecmis["max_gemi_liman"],
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
        if self.out or (self.deadline is not None and time.time() > self.deadline):
            self.out = True
        return not self.out

    def area(self, key: str, fetch) -> list[dict] | None:
        """Alan sorgusunun sonucu (önbellekten ya da yeni istekle); süre yoksa None."""
        self.total += 1
        data = _cache_get(self.con, key)
        if data is None and self._time_left():
            data = _store(self.con, key, fetch())
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


def _vessels_in(evs: list[dict] | None, into: dict[str, dict]) -> None:
    for e in evs or []:
        v = e.get("vessel") or {}
        if v.get("id") and not any(x in str(v.get("type") or "").lower() for x in SKIP_TYPES):
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
    segs = segments(t, today)
    try:
        # 1) ana tarama
        vessel_ids: dict[str, dict] = {}
        partial = False
        for ports, cap in ((dest_ports, None), (dark_ports, cfg.gecmis["max_gemi_liman"])):
            for p in ports:
                seen_here: dict[str, dict] = {}
                for a, b in chunks(start, end):
                    evs = plan.area(f"area_pv:{p.code}:{a}:{b}",
                                    lambda p=p, a=a, b=b: client.area_events(DS_PV, geometry(p.area), a, b, pv_extra))
                    partial |= evs is None
                    _vessels_in(evs, seen_here)
                ids = list(seen_here)
                if cap and len(ids) > cap:
                    log.warning("%s: %d gemi bulundu, ilk %d tanesi taranacak", p.name, len(ids), cap)
                    ids = ids[:cap]
                for vid in ids:
                    vessel_ids.setdefault(vid, seen_here[vid])
        for vid in vessel_ids:
            for ds, kind in ((DS_PV, "v_pv"), (DS_GAP, "v_gap")):
                plan.ensure(f"{kind}:{vid}:{v_start}:{end}",
                            lambda ds=ds, vid=vid: client.vessel_events(ds, vid, v_start, end))
        if not partial:
            set_meta(con, "gecmis_gemiler", json.dumps(list(vessel_ids)))
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
    return {"baslangic": g.get("start"), "bitis": g.get("end"), "saat": round(dur or 0, 1),
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
    # tarama sürerken de önbelleğe girmiş bütün gemiler, bütün pencereleriyle hesaba katılır
    vkeys = _vessel_keys(con)
    ids = sorted(vkeys)
    th = cfg.th
    max_h = th["guzergah_max_gun"] * 24
    dark_h = th["karanlik_sefer_saat"]
    dark_win = th["karanlik_sefer_gun"] * 24
    max_mids = th["aktarma_max_liman"]
    via_h = th["aktarma_max_gun"] * 24
    direct_h = th["dogrudan_max_gun"] * 24
    t = target(con)
    period = f"{t['baslangic']}T00:00:00Z" if t else ""
    # beyanı veren ülke (izlenen limanların ülkesi): dönem kuralı o ülkedeki uğrağa bakar
    home = {p.country for p in cfg.ports if p.role == "izlenen"}
    # ara liman sayılan ülkeler: yapılandırmadaki diğer ülkeler (Yunanistan, Bulgaristan, Mısır, Kıbrıs).
    # Başka bir ülkenin limanına uğrayan geminin yükü oradan gelmiş olabilir (ör. Ambarlı → Novorossiysk → Hayfa).
    aktarma = set(th.get("aktarma_ulkeleri") or []) or (set(cfg.countries) - home - cfg.dest_countries())
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
            visits.append({"c": c, "name": name, "code": code, "lat": lat, "lon": lon,
                           "start": e["start"], "end": e["end"] or e["start"],
                           "vessel": e["vessel"]})
        gl = [_gap_info(g) for g in gaps if g.get("start")]
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
                # GFW'nin "kasıtlı kapatma" saydığı, liman yakınında olmayan uzun boşluklar
                legs = [g for g in gl if o["end"] <= g["baslangic"] < lim and g["saat"] >= dark_h
                        and g.get("kasitli") is not False
                        and None not in g["kapanis"] and cfg.in_dark_box(*g["kapanis"])
                        and not cfg.near_port(*g["kapanis"])]
                if legs:
                    _insert(con, A, B, "karanlik_sefer", vid, o["vessel"], o, None, nxt, [], legs)
                    n += 1
    con.commit()
    return n


def _insert(con, A, B, cls, vid, vessel, o, d, nxt, mids, gaps):
    con.execute(
        """INSERT INTO gecmis(direction,cls,vessel_id,ssvid,name,flag,vtype,origin,origin_country,t_dep,dest,
           dest_country,t_arr,next_port,mids,gaps,o_lat,o_lon,d_lat,d_lon)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (f"{A}>{B}", cls, vid, vessel.get("ssvid"), vessel.get("name"), vessel.get("flag"), vessel.get("type"),
         o["name"], o["c"], o["end"], d["name"] if d else None, d["c"] if d else None,
         d["start"] if d else (gaps[0]["bitis"] if gaps else None), nxt["name"] if nxt else None,
         json.dumps([{"liman": m["name"], "ulke": m["c"], "giris": m["start"], "cikis": m["end"],
                      "lat": m.get("lat"), "lon": m.get("lon")} for m in mids], ensure_ascii=False),
         json.dumps(gaps, ensure_ascii=False),
         o.get("lat"), o.get("lon"), d.get("lat") if d else None, d.get("lon") if d else None))


def run(cfg, start: str | None, end: str | None, budget_min: float | None) -> dict:
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
        client = Client(token) if token else None
        if client is None:
            log.warning("GFW anahtarı yok (%s); yalnızca önbellekteki veriler işlenecek", cfg.gecmis["anahtar_degiskeni"])
        return scan(cfg, con, client, budget_min)
    finally:
        con.close()
