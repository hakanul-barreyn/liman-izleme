"""Ayar dosyasını (config.yaml) ve gizli anahtarları (.env) okur."""
from __future__ import annotations

import copy
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .geo import Area, haversine_km

DEFAULTS: dict = {
    "proje": {
        "ad": "Liman İzleme",
        "aciklama": "Seçilen limanlara uğrayan gemilerin açık ve doğrulanabilir arşivi.",
        "saat_dilimi": "Europe/Istanbul",
        "veri_klasoru": "data",
        "site_klasoru": "site",
        "kurgusal": False,
    },
    "beyan": {"aktif": False, "yonler": [], "metin": "", "tarih": "", "kaynak": ""},
    "ulkeler": {},
    "limanlar": [],
    "esikler": {
        "ziyaret_min_dakika": 60,
        "cikis_tolerans_dakika": 45,
        "ziyaret_birlestirme_saat": 3,
        "durma_hizi_knot": 1.0,
        "takip_gun": 30,
        "guzergah_max_gun": 90,
        "ais_bosluk_saat": 6,
        "liman_uzaklik_km": 30,
        "sts_mesafe_m": 500,
        "sts_sure_saat": 2,
        "draft_degisim_m": 1.0,
        "durak_sure_saat": 6,
        "anomali_pencere_gun": 4,
    },
    "gemi_filtresi": {"tipler": ["kargo", "tanker", "bilinmiyor"], "min_boy_m": 0},
    "aisstream": {
        "anahtar_degiskeni": "AISSTREAM_API_KEY",
        "liman_kenar_payi_km": 5,
        "takip_baglanti_sayisi": 2,
        "mmsi_baglanti_basina": 50,
        "sessizlik_dakika": 15,
    },
    "yayin": {
        "ham_veri_yayinla": True,
        "git_push": False,
        "opentimestamps": True,
        "site_guncelleme_dakika": 60,
        "gunluk_saat": "00:05",
    },
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class Terminal:
    name: str
    cargo: str
    area: Area


@dataclass
class Port:
    code: str
    name: str
    country: str
    role: str  # "izlenen" | "varis"
    area: Area
    terminals: list[Terminal] = field(default_factory=list)


CARGO_LABELS = {
    "sivi_dokme": "Sıvı dökme (ham petrol / ürün / kimyasal)",
    "gaz": "Gaz (LNG / LPG)",
    "kuru_dokme": "Kuru dökme (tahıl, maden, kömür vb.)",
    "konteyner": "Konteyner",
    "ro_ro": "Araç / Ro-Ro",
    "genel_kargo": "Genel kargo",
}


class Config:
    def __init__(self, raw: dict, root: Path):
        self.raw = _merge(DEFAULTS, raw)
        self.root = root
        p = self.raw["proje"]
        self.name = p["ad"]
        self.description = p["aciklama"]
        self.tz = p["saat_dilimi"]
        self.fictional = bool(p.get("kurgusal"))
        self.data_dir = (root / p["veri_klasoru"]).resolve()
        self.site_dir = (root / p["site_klasoru"]).resolve()
        self.th = self.raw["esikler"]
        self.ship_filter = self.raw["gemi_filtresi"]
        self.ais = self.raw["aisstream"]
        self.pub = self.raw["yayin"]
        self.declaration = self.raw["beyan"]
        self.countries: dict = self.raw["ulkeler"] or {}
        self.ports: list[Port] = []
        seen = set()
        for spec in self.raw["limanlar"] or []:
            code = str(spec["kod"]).strip()
            if code in seen:
                raise ValueError(f"Liman kodu iki kez kullanılmış: {code}")
            seen.add(code)
            terms = [
                Terminal(t["ad"], t.get("yuk", "genel_kargo"), Area(t))
                for t in spec.get("terminaller") or []
            ]
            self.ports.append(
                Port(code, spec.get("ad", code), str(spec.get("ulke", "")).upper(),
                     spec.get("rol", "izlenen"), Area(spec), terms)
            )
        self.port_by_code = {p.code: p for p in self.ports}
        self.directions: list[tuple[str, str]] = []
        for d in self.declaration.get("yonler") or []:
            a, b = [x.strip().upper() for x in str(d).split(">")]
            self.directions.append((a, b))

    # --- yardımcılar ---
    def locate(self, lat: float, lon: float) -> tuple[str | None, str | None]:
        for p in self.ports:
            if p.area.contains(lat, lon):
                for t in p.terminals:
                    if t.area.contains(lat, lon):
                        return p.code, t.name
                return p.code, None
        return None, None

    def near_port(self, lat: float, lon: float, km: float | None = None) -> bool:
        km = self.th["liman_uzaklik_km"] if km is None else km
        return any(haversine_km(lat, lon, *p.area.center) <= km for p in self.ports)

    def country_name(self, code: str) -> str:
        return (self.countries.get(code) or {}).get("ad", code)

    def terminal_cargo(self, port_code: str | None, terminal: str | None) -> str | None:
        if not port_code or not terminal:
            return None
        for t in self.port_by_code[port_code].terminals:
            if t.name == terminal:
                return t.cargo
        return None

    def destination_matches(self, dest: str | None, country: str) -> bool | None:
        """AIS'te beyan edilen varış noktası verilen ülkeyi gösteriyor mu?
        None: varış noktası boş."""
        if not dest:
            return None
        d = dest.upper().replace(">", " ").replace("-", " ").replace(",", " ")
        keys = [k.upper() for k in (self.countries.get(country) or {}).get("varis_anahtarlari", [])]
        keys += [p.name.upper() for p in self.ports if p.country == country]
        for k in keys:
            if k and k in d:
                return True
        for tok in d.split():
            if len(tok) == 5 and tok.isalpha() and tok.startswith(country):
                return True  # UN/LOCODE (ör. TRIST)
        return False


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def load(path: str | Path) -> Config:
    path = Path(path).resolve()
    if not path.exists():
        raise SystemExit(f"Ayar dosyası bulunamadı: {path}\n"
                         "config.example.yaml dosyasını config.yaml adıyla kopyalayıp doldur.")
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    load_env(path.parent / ".env")
    return Config(raw, path.parent)
