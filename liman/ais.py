"""aisstream.io mesajlarını sade bir sözlüğe çevirir."""
from __future__ import annotations

import datetime as dt

from .util import UTC, iso, now_utc

POS_TYPES = {"PositionReport", "StandardClassBPositionReport", "ExtendedClassBPositionReport"}
MESSAGE_TYPES = sorted(POS_TYPES | {"ShipStaticData", "StaticDataReport"})


def parse_time(s) -> str:
    if not s:
        return iso(now_utc())
    try:
        t = dt.datetime.strptime(str(s)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        return iso(t)
    except ValueError:
        try:
            return iso(dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")))
        except ValueError:
            return iso(now_utc())


def _clean(s) -> str | None:
    if s is None:
        return None
    s = str(s).replace("@", " ").strip()
    return " ".join(s.split()) or None


def _num(v, bad=None):
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if bad is not None and f >= bad:
        return None
    return f


def parse(msg: dict) -> dict | None:
    mt = msg.get("MessageType")
    meta = msg.get("MetaData") or {}
    body = (msg.get("Message") or {}).get(mt) or {}
    mmsi = meta.get("MMSI") or body.get("UserID")
    if not mmsi:
        return None
    try:
        mmsi = int(mmsi)
    except (TypeError, ValueError):
        return None
    t = parse_time(meta.get("time_utc"))
    meta_name = _clean(meta.get("ShipName"))

    if mt in POS_TYPES:
        lat = _num(body.get("Latitude", meta.get("latitude")))
        lon = _num(body.get("Longitude", meta.get("longitude")))
        if lat is None or lon is None or abs(lat) > 90 or abs(lon) > 180:
            return None
        if lat == 0 and lon == 0:
            return None
        return {
            "kind": "pos", "mmsi": mmsi, "t": t, "lat": lat, "lon": lon,
            "sog": _num(body.get("Sog"), bad=102.2),
            "cog": _num(body.get("Cog"), bad=360),
            "nav": body.get("NavigationalStatus"),
            "name": meta_name,
        }

    if mt == "ShipStaticData":
        dim = body.get("Dimension") or {}
        length = (dim.get("A") or 0) + (dim.get("B") or 0)
        width = (dim.get("C") or 0) + (dim.get("D") or 0)
        imo = body.get("ImoNumber") or None
        draught = _num(body.get("MaximumStaticDraught"))
        return {
            "kind": "static", "mmsi": mmsi, "t": t,
            "imo": int(imo) if imo else None,
            "name": _clean(body.get("Name")) or meta_name,
            "callsign": _clean(body.get("CallSign")),
            "type": body.get("Type") or None,
            "length": float(length) or None,
            "width": float(width) or None,
            "draught": draught if draught else None,
            "dest": _clean(body.get("Destination")),
        }

    if mt == "StaticDataReport":
        ra = body.get("ReportA") or {}
        rb = body.get("ReportB") or {}
        out = {"kind": "static", "mmsi": mmsi, "t": t, "imo": None, "name": meta_name,
               "callsign": None, "type": None, "length": None, "width": None,
               "draught": None, "dest": None}
        if ra.get("Valid"):
            out["name"] = _clean(ra.get("Name")) or meta_name
        if rb.get("Valid"):
            out["type"] = rb.get("ShipType") or None
            out["callsign"] = _clean(rb.get("CallSign"))
            dim = rb.get("Dimension") or {}
            out["length"] = float((dim.get("A") or 0) + (dim.get("B") or 0)) or None
        return out
    return None
