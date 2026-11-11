"""Kanıt zinciri: her günün dosyaları hash'lenir, günler birbirine zincirlenir,
OpenTimestamps kuruluysa gün hash'i Bitcoin blok zincirine damgalanır."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from .util import iso, now_utc

MANIFEST = "MANIFEST.sha256"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_text(day_dir: Path) -> str:
    lines = []
    for p in sorted(day_dir.rglob("*")):
        if p.is_file() and p.name not in (MANIFEST, MANIFEST + ".ots"):
            lines.append(f"{sha256_file(p)}  {p.relative_to(day_dir).as_posix()}")
    return "\n".join(lines) + "\n"


def chain_path(cfg) -> Path:
    return cfg.site_dir / "kanit" / "zincir.jsonl"


def read_chain(cfg) -> list[dict]:
    p = chain_path(cfg)
    if not p.exists():
        return []
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def seal(cfg, con, day: str, day_dir: Path) -> dict:
    text = manifest_text(day_dir)
    (day_dir / MANIFEST).write_text(text, encoding="utf-8")
    day_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    chain = [c for c in read_chain(cfg) if c["gun"] != day]
    prev = chain[-1]["kayit_hash"] if chain else "0" * 64
    entry = {
        "gun": day, "gun_hash": day_hash, "onceki": prev,
        "kayit_hash": hashlib.sha256(f"{prev}{day}{day_hash}".encode()).hexdigest(),
        "olusturma": iso(now_utc()), "dosya_sayisi": text.count("\n"),
    }
    stamped = False
    if cfg.pub.get("opentimestamps") and shutil.which("ots"):
        try:
            subprocess.run(["ots", "stamp", str(day_dir / MANIFEST)], check=True, timeout=120,
                           capture_output=True)
            stamped = True
        except Exception:  # noqa: BLE001  (ağ yoksa damga sonra yeniden denenebilir)
            stamped = False
    entry["opentimestamps"] = stamped
    chain.append(entry)
    chain.sort(key=lambda c: c["gun"])
    # zinciri sıraya göre yeniden hesapla (geç arşivlenen gün varsa)
    prev = "0" * 64
    for c in chain:
        c["onceki"] = prev
        c["kayit_hash"] = hashlib.sha256(f"{prev}{c['gun']}{c['gun_hash']}".encode()).hexdigest()
        prev = c["kayit_hash"]
    p = chain_path(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(c, ensure_ascii=False) + "\n" for c in chain), encoding="utf-8")
    con.execute("INSERT INTO archived_days(day,day_hash,created) VALUES(?,?,?) "
                "ON CONFLICT(day) DO UPDATE SET day_hash=excluded.day_hash, created=excluded.created",
                (day, day_hash, entry["olusturma"]))
    con.commit()
    return entry


def verify(cfg, day: str) -> tuple[bool, list[str]]:
    """Bir günün dosyalarını manifest ve zincirle karşılaştırır."""
    day_dir = cfg.site_dir / "arsiv" / day
    out = []
    ok = True
    mf = day_dir / MANIFEST
    if not mf.exists():
        return False, [f"{day} için manifest yok"]
    for line in mf.read_text(encoding="utf-8").splitlines():
        h, name = line.split("  ", 1)
        p = day_dir / name
        if not p.exists():
            ok = False
            out.append(f"EKSİK   {name}")
        elif sha256_file(p) != h:
            ok = False
            out.append(f"DEĞİŞMİŞ {name}")
        else:
            out.append(f"tamam   {name}")
    day_hash = hashlib.sha256(mf.read_bytes()).hexdigest()
    entry = next((c for c in read_chain(cfg) if c["gun"] == day), None)
    if not entry or entry["gun_hash"] != day_hash:
        ok = False
        out.append("Gün hash'i zincirdeki kayıtla eşleşmiyor")
    else:
        out.append(f"Gün hash'i zincirle eşleşiyor: {day_hash}")
    return ok, out
