"""Raporlardaki gemiler için kimlik, firma ve serbest lisanslı fotoğraf bilgisi.

- Kimlik ve sahip firma: Global Fishing Watch gemi kimliği (IMO, çağrı işareti, sicildeki sahipler).
  Yük gemilerinde sicil sahibi bilgisi çoğu zaman boştur; o zaman elle doldurulan gemiler.yaml kullanılır.
- Fotoğraf: Wikimedia Commons'taki "IMO <numara>" kategorisi. Yalnızca serbest lisanslı dosyalar
  vardır; fotoğraf, çekenin adı ve lisansıyla gösterilir.

Sonuçlar gfw_cache tablosunda saklanır (anahtar: gkimlik:<gfw kimliği>, foto:<imo>) ve 30 günde bir yenilenir.
"""
from __future__ import annotations

import html
import json
import logging
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from .db import connect, db_path
from .util import add_hours, iso, now_utc

log = logging.getLogger("gemi_bilgi")
VESSEL_API = "https://gateway.api.globalfishingwatch.org/v3/vessels/"
DS_ID = "public-global-vessel-identity:latest"
COMMONS = "https://commons.wikimedia.org/w/api.php"
UA = "avvam/1.0 (https://github.com/hakanul-barreyn/liman-izleme)"
YENILE_GUN = 30


def _taze(con, key: str) -> bool:
    r = con.execute("SELECT fetched FROM gfw_cache WHERE key=?", (key,)).fetchone()
    return bool(r) and r[0] >= add_hours(iso(now_utc()), -24 * YENILE_GUN)


def _yaz(con, key: str, data) -> None:
    con.execute("INSERT OR REPLACE INTO gfw_cache(key,data,fetched) VALUES(?,?,?)",
                (key, json.dumps(data, ensure_ascii=False, separators=(",", ":")), iso(now_utc())))
    con.commit()


def oku(con, key: str):
    r = con.execute("SELECT data FROM gfw_cache WHERE key=?", (key,)).fetchone()
    return json.loads(r[0]) if r else None


def _get(url: str, headers: dict) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, **headers})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())


def _kimlik(d: dict) -> dict:
    """GFW gemi kimliği yanıtından gerekenler."""
    def liste(x):
        return [x] if isinstance(x, dict) else [y for y in (x or []) if isinstance(y, dict)]
    sr = sorted(liste(d.get("selfReportedInfo")), key=lambda x: x.get("transmissionDateTo") or "", reverse=True)
    reg = liste(d.get("registryInfo"))
    imo = next((x.get("imo") for x in reg + sr if x.get("imo")), None)
    owners = []
    for o in liste(d.get("registryOwners")):
        if o.get("name"):
            owners.append({"ad": o["name"].strip(), "ulke": o.get("flag"), "bas": (o.get("dateFrom") or "")[:10],
                           "son": (o.get("dateTo") or "")[:10], "kaynak": o.get("sourceCode")})
    return {"imo": str(imo) if imo else None, "cagri": next((x.get("callsign") for x in sr if x.get("callsign")), None),
            "sahipler": owners}


def _foto(imo: str) -> list[dict]:
    q = urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "categorymembers", "gcmtitle": f"Category:IMO {imo}",
        "gcmtype": "file", "gcmlimit": 6, "prop": "imageinfo", "iiprop": "url|extmetadata|mime", "iiurlwidth": 640})
    d = _get(f"{COMMONS}?{q}", {})
    out = []
    for p in sorted((d.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("title", "")):
        ii = (p.get("imageinfo") or [{}])[0]
        if not str(ii.get("mime", "")).startswith("image/"):
            continue
        meta = ii.get("extmetadata") or {}
        val = lambda k: re.sub(r"<[^>]+>", "", html.unescape((meta.get(k) or {}).get("value", ""))).strip()  # noqa: E731
        out.append({"kucuk": ii.get("thumburl"), "sayfa": ii.get("descriptionurl"), "yazar": val("Artist")[:120],
                    "lisans": val("LicenseShortName"), "lisans_url": (meta.get("LicenseUrl") or {}).get("value"),
                    "tarih": val("DateTimeOriginal")[:10]})
    return out


def guncelle(cfg, budget_min: float = 3) -> dict:
    """Geçmiş taramadaki gemilerin kimliğini ve IMO'su bilinen gemilerin fotoğraflarını çeker (süre bütçesiyle)."""
    deadline = time.time() + budget_min * 60
    token = os.environ.get(cfg.gecmis["anahtar_degiskeni"], "").strip()
    con = connect(db_path(cfg))
    n = {"kimlik": 0, "foto": 0, "hata": 0}
    try:
        vids = [r[0] for r in con.execute(
            "SELECT vessel_id FROM gecmis WHERE vessel_id IS NOT NULL GROUP BY vessel_id ORDER BY count(*) DESC")]
        if token:
            for vid in vids:
                if time.time() > deadline:
                    break
                key = f"gkimlik:{vid}"
                if _taze(con, key):
                    continue
                q = urllib.parse.urlencode({"dataset": DS_ID, "registries-info-data": "ALL"})
                try:
                    _yaz(con, key, _kimlik(_get(f"{VESSEL_API}{urllib.parse.quote(vid)}?{q}",
                                                {"Authorization": f"Bearer {token}"})))
                    n["kimlik"] += 1
                except Exception as e:  # noqa: BLE001
                    n["hata"] += 1
                    log.warning("GFW gemi kimliği alınamadı (%s): %s", vid, e)
                    if n["hata"] > 20:
                        break
                time.sleep(0.2)
        imos = set()
        for vid in vids:
            k = oku(con, f"gkimlik:{vid}") or {}
            if k.get("imo"):
                imos.add(k["imo"])
        imos |= {str(r[0]) for r in con.execute("SELECT imo FROM vessels WHERE imo IS NOT NULL AND imo > 0")}
        for imo in sorted(imos):
            if time.time() > deadline:
                break
            key = f"foto:{imo}"
            if _taze(con, key):
                continue
            try:
                _yaz(con, key, _foto(imo))
                n["foto"] += 1
            except Exception as e:  # noqa: BLE001
                n["hata"] += 1
                log.warning("Commons sorgusu başarısız (IMO %s): %s", imo, e)
                if n["hata"] > 40:
                    break
            time.sleep(0.1)
        kim = [json.loads(r[0]) for r in con.execute("SELECT data FROM gfw_cache WHERE key LIKE 'gkimlik:%'")]
        fot = [json.loads(r[0]) for r in con.execute("SELECT data FROM gfw_cache WHERE key LIKE 'foto:%'")]
        n.update({"gemi": len(vids), "imo_bilinen": sum(1 for k in kim if k.get("imo")),
                  "sahibi_bilinen": sum(1 for k in kim if k.get("sahipler")), "foto_sorgulanan": len(fot),
                  "fotografli": sum(1 for f in fot if f)})
    finally:
        con.close()
    log.info("Gemi bilgisi: %s", n)
    return n


def elle(cfg) -> dict[str, dict]:
    """gemiler.yaml: elle girilen firma bilgisi. Anahtar IMO ya da MMSI."""
    import yaml
    p = Path(cfg.root) / "gemiler.yaml"
    if not p.exists():
        return {}
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return {str(k): v for k, v in (data.get("gemiler") or {}).items() if isinstance(v, dict)}
