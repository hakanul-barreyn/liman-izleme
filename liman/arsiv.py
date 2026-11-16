"""Kaynakçadaki bağlantıların İnternet Arşivi (Wayback Machine) kopyaları.

arsiv/kaynaklar.json: {url: {"kopya": "https://web.archive.org/web/<zaman>/<url>", "zaman": "YYYY-MM-DDTHH:MM:SSZ",
                             "yol": "kaydedildi" | "var olan kopya", "denendi": "...", "hata": "..."}}

Dosyayı kurulum/kaynak_arsivle.py doldurur (GitHub Actions'ta, "Kaynakları arşivle" iş akışı). Rapor ve ekler,
bir kaynağın kopyası varsa onu tarihiyle verir; yoksa yalnızca özgün bağlantıyı gösterir.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

DOSYA = Path("arsiv") / "kaynaklar.json"
TARANAN = ("config.yaml", "gemiler.yaml", "liman/makale.py")
URL = re.compile(r"https?://[^\s\"'<>)\]]+")
DISLA = ("web.archive.org", "archive.org/wayback", "api.github.com", "github.com/", "x.com/intent", "fonts.",
         "cdn.", "unpkg.com", "marinetraffic.com/en/ais", "myshiptracking.com", "globalfishingwatch.org/map",
         "github.io", "doi.org", "127.0.0.1", "localhost", "example")


def harita(root: Path) -> dict:
    f = Path(root) / DOSYA
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def kopya(root: Path, url: str | None) -> dict | None:
    """Bir bağlantının arşiv kopyası: {"kopya", "zaman"} ya da None."""
    if not url:
        return None
    k = harita(root).get(url.rstrip("."))
    return k if k and k.get("kopya") else None


def toplanan(root: Path) -> list[str]:
    """Kaynak dosyalarında geçen ve arşivlenecek bütün bağlantılar."""
    out: list[str] = []
    for ad in TARANAN:
        f = Path(root) / ad
        if not f.exists():
            continue
        for u in URL.findall(f.read_text(encoding="utf-8")):
            u = u.rstrip(".,;")
            if "{" in u or "." not in u.split("//", 1)[1] or any(d in u for d in DISLA) or u in out:
                continue
            out.append(u)
    return out
