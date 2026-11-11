"""Basit coğrafi yardımcılar: mesafe, poligon içinde mi, alan tanımı."""
from __future__ import annotations

import math

R_KM = 6371.0088


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R_KM * math.asin(min(1.0, math.sqrt(h)))


def point_in_polygon(lat: float, lon: float, poly: list[tuple[float, float]]) -> bool:
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        yi, xi = poly[i]
        yj, xj = poly[j]
        if (yi > lat) != (yj > lat):
            x = (xj - xi) * (lat - yi) / (yj - yi) + xi
            if lon < x:
                inside = not inside
        j = i
    return inside


class Area:
    """Ayar dosyasındaki bir alan: ya `alan` (poligon, [enlem, boylam] listesi)
    ya da `merkez` + `yaricap_km` (daire)."""

    def __init__(self, spec: dict):
        poly = spec.get("alan")
        if poly:
            self.poly = [(float(a), float(b)) for a, b in poly]
            if len(self.poly) < 3:
                raise ValueError("Poligon en az 3 nokta içermeli")
            self.center = (
                sum(p[0] for p in self.poly) / len(self.poly),
                sum(p[1] for p in self.poly) / len(self.poly),
            )
            self.radius_km = None
        elif spec.get("merkez"):
            lat, lon = spec["merkez"]
            self.poly = None
            self.center = (float(lat), float(lon))
            self.radius_km = float(spec.get("yaricap_km", 5))
        else:
            raise ValueError("Alan için 'alan' (poligon) veya 'merkez' + 'yaricap_km' gerekli")

    def contains(self, lat: float, lon: float) -> bool:
        if self.poly:
            return point_in_polygon(lat, lon, self.poly)
        return haversine_km(lat, lon, *self.center) <= self.radius_km

    def bbox(self, margin_km: float = 0.0) -> list[list[float]]:
        if self.poly:
            lats = [p[0] for p in self.poly]
            lons = [p[1] for p in self.poly]
            lat0, lat1, lon0, lon1 = min(lats), max(lats), min(lons), max(lons)
        else:
            dlat = self.radius_km / 111.32
            dlon = self.radius_km / (111.32 * max(0.05, math.cos(math.radians(self.center[0]))))
            lat0, lat1 = self.center[0] - dlat, self.center[0] + dlat
            lon0, lon1 = self.center[1] - dlon, self.center[1] + dlon
        mlat = margin_km / 111.32
        mlon = margin_km / (111.32 * max(0.05, math.cos(math.radians(self.center[0]))))
        return [
            [round(max(-90, lat0 - mlat), 5), round(max(-180, lon0 - mlon), 5)],
            [round(min(90, lat1 + mlat), 5), round(min(180, lon1 + mlon), 5)],
        ]

    def outline(self) -> list[tuple[float, float]]:
        if self.poly:
            return self.poly + [self.poly[0]]
        pts = []
        for k in range(65):
            a = 2 * math.pi * k / 64
            dlat = self.radius_km / 111.32 * math.sin(a)
            dlon = self.radius_km / (111.32 * max(0.05, math.cos(math.radians(self.center[0])))) * math.cos(a)
            pts.append((self.center[0] + dlat, self.center[1] + dlon))
        return pts
