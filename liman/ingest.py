"""Gelen her AIS mesajını ham dosyaya ve veritabanına yazar."""
from __future__ import annotations

import json
from pathlib import Path

from .ais import parse
from .util import local_day, parse_iso


class Ingestor:
    """Ham mesajlar değiştirilmeden günlük JSONL dosyalarına eklenir (kanıtın kaynağı);
    ayrıştırılmış hâlleri analiz için veritabanına yazılır."""

    THROTTLE_S = 30        # aynı gemiden 30 sn'den sık konum kaydedilmez (ham dosyada hepsi kalır)
    THROTTLE_BERTH_S = 600  # limanda duran gemi için 10 dakikada bir yeter
    STATIC_REFRESH_S = 6 * 3600

    def __init__(self, cfg, con):
        self.cfg = cfg
        self.con = con
        self.raw_dir: Path = cfg.data_dir / "ham"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._files: dict[str, object] = {}
        self._last: dict[int, tuple[str, str | None]] = {}
        self._last_static: dict[int, tuple] = {}
        self.count = 0
        self.last_message_t: str | None = None

    def _raw_file(self, day: str):
        f = self._files.get(day)
        if f is None:
            if len(self._files) > 2:  # eski günlerin dosyalarını kapat
                for d in sorted(self._files)[:-2]:
                    self._files.pop(d).close()
            f = open(self.raw_dir / f"{day}.jsonl", "a", encoding="utf-8")
            self._files[day] = f
        return f

    def handle(self, msg: dict, src: str) -> dict | None:
        p = parse(msg)
        if p is None:
            return None
        day = local_day(p["t"], self.cfg.tz)
        line = json.dumps({"alindi": src, "mesaj": msg}, ensure_ascii=False, separators=(",", ":"))
        self._raw_file(day).write(line + "\n")
        self.count += 1
        self.last_message_t = p["t"]
        if p["kind"] == "pos":
            self._position(p, src)
        else:
            self._static(p)
        return p

    def _position(self, p: dict, src: str) -> None:
        port, terminal = self.cfg.locate(p["lat"], p["lon"])
        last = self._last.get(p["mmsi"])
        if last and last[1] == port:
            limit = self.THROTTLE_BERTH_S if port and p["sog"] is not None and p["sog"] < 1 else self.THROTTLE_S
            if (parse_iso(p["t"]) - parse_iso(last[0])).total_seconds() < limit:
                return
        if port is None:
            # liman dışında izlendiği saatleri kalıcı tut (eski konumlar silinse de güzergâh sınıfı bozulmasın)
            self.con.execute("INSERT OR IGNORE INTO seen_offport(mmsi, hour) VALUES(?,?)", (p["mmsi"], p["t"][:13]))
        self._last[p["mmsi"]] = (p["t"], port)
        self.con.execute(
            "INSERT INTO positions(mmsi,t,lat,lon,sog,cog,nav,port,terminal,src) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (p["mmsi"], p["t"], p["lat"], p["lon"], p["sog"], p["cog"], p["nav"], port, terminal, src),
        )
        self.con.execute(
            """INSERT INTO vessels(mmsi,name,first_seen,last_seen) VALUES(?,?,?,?)
               ON CONFLICT(mmsi) DO UPDATE SET last_seen=max(last_seen, excluded.last_seen),
               name=coalesce(vessels.name, excluded.name)""",
            (p["mmsi"], p["name"], p["t"], p["t"]),
        )

    def _static(self, p: dict) -> None:
        sig = (p["imo"], p["name"], p["callsign"], p["type"], p["draught"], p["dest"])
        prev = self._last_static.get(p["mmsi"])
        if prev and prev[1] == sig and (parse_iso(p["t"]) - parse_iso(prev[0])).total_seconds() < self.STATIC_REFRESH_S:
            return  # değişmemiş statik mesajı tekrar yazma
        self._last_static[p["mmsi"]] = (p["t"], sig)
        self.con.execute(
            "INSERT INTO statics(mmsi,t,imo,name,callsign,type,length,width,draught,dest) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (p["mmsi"], p["t"], p["imo"], p["name"], p["callsign"], p["type"],
             p["length"], p["width"], p["draught"], p["dest"]),
        )
        row = self.con.execute("SELECT * FROM vessels WHERE mmsi=?", (p["mmsi"],)).fetchone()
        if row is None:
            self.con.execute("INSERT INTO vessels(mmsi,first_seen,last_seen) VALUES(?,?,?)",
                             (p["mmsi"], p["t"], p["t"]))
            row = self.con.execute("SELECT * FROM vessels WHERE mmsi=?", (p["mmsi"],)).fetchone()
        history = json.loads(row["history"] or "[]")
        # İsim, IMO ve çağrı işareti değişimlerini kayıt altına al (kimlik değiştirme izleri)
        for field in ("name", "imo", "callsign"):
            new = p.get(field)
            if new and row[field] and str(new) != str(row[field]):
                history.append({"t": p["t"], "alan": field, "eski": row[field], "yeni": new})
        self.con.execute(
            """UPDATE vessels SET imo=coalesce(?,imo), name=coalesce(?,name), callsign=coalesce(?,callsign),
               type=coalesce(?,type), length=coalesce(?,length), width=coalesce(?,width),
               draught=coalesce(?,draught), dest=coalesce(?,dest), history=?,
               last_seen=max(coalesce(last_seen,''), ?) WHERE mmsi=?""",
            (p["imo"], p["name"], p["callsign"], p["type"], p["length"], p["width"],
             p["draught"], p["dest"], json.dumps(history, ensure_ascii=False), p["t"], p["mmsi"]),
        )

    def flush(self) -> None:
        self.con.commit()
        for f in self._files.values():
            f.flush()

    def close(self) -> None:
        self.flush()
        for f in self._files.values():
            f.close()
        self._files.clear()
