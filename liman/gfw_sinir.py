"""GFW API istek sınırı.

GFW, kullanıcı başına günde en fazla 50.000 istek istiyor; aşılırsa kullanıcının bütün anahtarları
24 saat kapanır. Bu yüzden son 24 saatte yapılan istekler veritabanında saat saat tutulur ve her iş
(geçmiş tarama, gemi kimliği) yalnızca bu sınırın altında kalan hakkı kullanır.
"""
from __future__ import annotations

import datetime as dt
import json

from .db import get_meta, set_meta
from .util import now_utc

GUNLUK = 44000  # 50.000'in altında, kaydedilmeyen elle çalıştırmalar için pay bırakır
ANAHTAR = "gfw_istek"


def _oku(con) -> dict[str, int]:
    try:
        return {k: int(v) for k, v in json.loads(get_meta(con, ANAHTAR, "{}") or "{}").items()}
    except (TypeError, ValueError):
        return {}


def son24(con, simdi: dt.datetime | None = None) -> int:
    simdi = simdi or now_utc()
    sinir = (simdi - dt.timedelta(hours=24)).strftime("%Y-%m-%dT%H")
    return sum(n for saat, n in _oku(con).items() if saat >= sinir)


def hak(con, istenen: int, simdi: dt.datetime | None = None) -> int:
    """Bu iş en fazla kaç istek yapabilir."""
    return max(0, min(int(istenen), GUNLUK - son24(con, simdi)))


def yaz(con, n: int, simdi: dt.datetime | None = None) -> None:
    if n <= 0:
        return
    simdi = simdi or now_utc()
    d = _oku(con)
    saat = simdi.strftime("%Y-%m-%dT%H")
    d[saat] = d.get(saat, 0) + int(n)
    eski = (simdi - dt.timedelta(hours=30)).strftime("%Y-%m-%dT%H")
    set_meta(con, ANAHTAR, json.dumps({k: v for k, v in sorted(d.items()) if k >= eski}))
    con.commit()
