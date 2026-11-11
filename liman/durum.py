"""GitHub Actions modu için kalıcı durum: veritabanı ve henüz arşivlenmemiş ham dosyalar
her çalıştırmanın sonunda sıkıştırılıp 'durum' dalına yazılır, sonraki çalıştırmada geri yüklenir."""
from __future__ import annotations

import io
import logging
import sqlite3
import tarfile
from pathlib import Path

from .db import connect, db_path
from .util import add_hours, iso, now_utc

log = logging.getLogger("durum")
PART = 90 * 1024 * 1024  # GitHub'ın 100 MB dosya sınırının altında parçalar
NAME = "durum.tar.gz"


def prune(cfg) -> None:
    """Eski ayrıntılı konumları siler (ziyaretler, olaylar, güzergâhlar ve arşiv kalır)."""
    keep = cfg.raw.get("durum", {}).get("konum_saklama_gun", 21)
    con = connect(db_path(cfg))
    try:
        cut = add_hours(iso(now_utc()), -24 * keep)
        con.execute("DELETE FROM positions WHERE t < ?", (cut,))
        con.execute("DELETE FROM statics WHERE t < ? AND id NOT IN (SELECT max(id) FROM statics GROUP BY mmsi)",
                    (add_hours(cut, -24 * 100),))
        con.commit()
        done = {r[0] for r in con.execute("SELECT day FROM archived_days")}
    finally:
        con.close()
    # Arşivlenmiş günlerin ham dosyaları, GitHub Releases'a yüklendiği doğrulandıktan sonra
    # iş akışı tarafından silinir; burada silinmez.
    del done
    c = sqlite3.connect(str(db_path(cfg)))
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.execute("VACUUM")
    c.close()


def prepare_raw(cfg) -> list[str]:
    """Arşivlenmiş ama ham dosyası henüz Releases'a yüklenmemiş günler için ham.jsonl.gz'yi
    yeniden üretir. Sıkıştırma deterministik olduğu için hash manifesttekiyle aynı çıkar."""
    from .archive import _gzip_deterministic
    from .proof import MANIFEST
    out = []
    for f in sorted((cfg.data_dir / "ham").glob("*.jsonl")):
        day_dir = cfg.site_dir / "arsiv" / f.stem
        gz = day_dir / "ham.jsonl.gz"
        if (day_dir / MANIFEST).exists() and not gz.exists():
            _gzip_deterministic(f, gz)
            out.append(f.stem)
    return out


def save(cfg, out_dir: Path) -> list[Path]:
    prune(cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob(NAME + "*"):
        old.unlink()
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=6) as tar:
        tar.add(cfg.data_dir, arcname=cfg.data_dir.name,
                filter=lambda ti: None if ti.name.endswith(("-wal", "-shm")) else ti)
    data = buf.getvalue()
    parts = []
    for i in range(0, max(1, len(data)), PART):
        p = out_dir / f"{NAME}.{i // PART:03d}"
        p.write_bytes(data[i:i + PART])
        parts.append(p)
    log.info("Durum kaydedildi: %.1f MB, %d parça", len(data) / 1e6, len(parts))
    return parts


def load(cfg, in_dir: Path) -> bool:
    parts = sorted(in_dir.glob(NAME + ".*")) if in_dir.exists() else []
    if not parts:
        log.info("Kayıtlı durum yok; sıfırdan başlanıyor")
        return False
    data = b"".join(p.read_bytes() for p in parts)
    target = cfg.data_dir.parent
    root = cfg.data_dir.name
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
        for m in tar.getmembers():
            if not (m.name == root or m.name.startswith(root + "/")) or ".." in m.name or m.issym() or m.islnk():
                raise SystemExit(f"Durum arşivinde beklenmeyen dosya: {m.name}")
        if hasattr(tarfile, "data_filter"):
            tar.extractall(target, filter="data")
        else:
            tar.extractall(target)
    log.info("Durum yüklendi: %.1f MB", len(data) / 1e6)
    return True
