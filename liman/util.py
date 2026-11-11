"""Zaman ve gemi tipi yardımcıları."""
from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

UTC = dt.timezone.utc


def now_utc() -> dt.datetime:
    return dt.datetime.now(UTC).replace(microsecond=0)


def iso(t: dt.datetime) -> str:
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_iso(s: str) -> dt.datetime:
    return dt.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def hours_between(a: str, b: str) -> float:
    return (parse_iso(b) - parse_iso(a)).total_seconds() / 3600.0


def add_hours(s: str, h: float) -> str:
    return iso(parse_iso(s) + dt.timedelta(hours=h))


def local_day(s: str, tz: str) -> str:
    return parse_iso(s).astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d")


def day_bounds_utc(day: str, tz: str) -> tuple[str, str]:
    """Yerel günün [başlangıç, bitiş) aralığını UTC ISO olarak döndürür."""
    z = ZoneInfo(tz)
    d = dt.datetime.strptime(day, "%Y-%m-%d")
    start = d.replace(tzinfo=z)
    end = (d + dt.timedelta(days=1)).replace(tzinfo=z)
    return iso(start), iso(end)


def fmt_local(s: str | None, tz: str, with_date: bool = True) -> str:
    if not s:
        return "–"
    t = parse_iso(s).astimezone(ZoneInfo(tz))
    return t.strftime("%d.%m.%Y %H:%M" if with_date else "%H:%M")


SHIP_GROUP_LABELS = {
    "kargo": "Kargo gemisi",
    "tanker": "Tanker",
    "yolcu": "Yolcu gemisi",
    "balikci": "Balıkçı",
    "romorkor": "Römorkör / hizmet",
    "askeri": "Askeri",
    "gezi": "Gezi / yelkenli",
    "diger": "Diğer",
    "bilinmiyor": "Bilinmiyor",
}


def ship_group(code) -> str:
    if code in (None, "", 0):
        return "bilinmiyor"
    c = int(code)
    if 70 <= c <= 79:
        return "kargo"
    if 80 <= c <= 89:
        return "tanker"
    if 60 <= c <= 69:
        return "yolcu"
    if c == 30:
        return "balikci"
    if c in (31, 32, 33, 50, 51, 52, 53, 54, 55, 58):
        return "romorkor"
    if c == 35:
        return "askeri"
    if c in (36, 37):
        return "gezi"
    return "diger"


def hazard_category(code) -> str | None:
    """AIS tip kodunun ikinci hanesi (kargo/tanker için) tehlikeli yük kategorisini verir."""
    if code in (None, "", 0):
        return None
    c = int(code)
    if 70 <= c <= 89:
        return {1: "X (en tehlikeli)", 2: "Y", 3: "Z", 4: "OS"}.get(c % 10)
    return None
