"""Gelen AIS mesajlarını ham dosyaya ve veritabanına yazar.

Kaydedilen her mesaj ham dosyaya değiştirilmeden yazılır (kanıtın kaynağı). Aynı geminin çok sık
tekrarlanan konum mesajları seyreltilir: kaydedilmeyen mesaj ne ham dosyaya ne veritabanına girer.
Fiziksel olarak imkânsız konum sıçramaları (GPS karıştırma / sahte konum) ham dosyaya yazılır ama
analizde kullanılmaz; 'spoof' olayı olarak işaretlenir.
"""
from __future__ import annotations

import json
from pathlib import Path

from .ais import parse
from .geo import haversine_km
from .util import local_day, parse_iso

SPOOF_KNOTS = 60      # bundan hızlı görünen sıçrama fiziksel olarak imkânsız sayılır
SPOOF_MIN_KM = 10
SPOOF_RESET = 3       # art arda bu kadar "imkânsız" konum gelirse yeni konum doğru kabul edilir


class Ingestor:
    # saniye cinsinden en sık kayıt aralıkları
    T_OFFPORT = 300       # açık denizde
    T_WATCHED = 60        # izlenen limanda hareket hâlinde (harita için)
    T_OTHERPORT = 180     # diğer limanlarda hareket hâlinde
    T_STOPPED = 900       # herhangi bir limanda dururken
    STATIC_REFRESH_S = 6 * 3600

    def __init__(self, cfg, con):
        self.cfg = cfg
        self.con = con
        self.raw_dir: Path = cfg.data_dir / "ham"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self._files: dict[str, object] = {}
        self._last: dict[int, tuple[str, str | None]] = {}
        self._lastpos: dict[int, tuple[str, float, float]] = {}
        self._bad: dict[int, int] = {}
        self._spoof_hours: set[tuple[int, str]] = set()
        self._last_static: dict[int, tuple] = {}
        self.count = 0
        self.kept = 0
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

    def _raw(self, msg: dict, src: str, t: str) -> None:
        line = json.dumps({"alindi": src, "mesaj": msg}, ensure_ascii=False, separators=(",", ":"))
        self._raw_file(local_day(t, self.cfg.tz)).write(line + "\n")
        self.kept += 1

    def handle(self, msg: dict, src: str) -> dict | None:
        p = parse(msg)
        if p is None:
            return None
        self.count += 1
        self.last_message_t = p["t"]
        if p["kind"] == "pos":
            if self._position(p, src):
                self._raw(msg, src, p["t"])
        elif self._static(p):
            self._raw(msg, src, p["t"])
        return p

    # --- konum ---
    def _is_spoof(self, p: dict) -> dict | None:
        lp = self._lastpos.get(p["mmsi"])
        if not lp:
            return None
        km = haversine_km(lp[1], lp[2], p["lat"], p["lon"])
        if km < SPOOF_MIN_KM:
            return None
        h = abs((parse_iso(p["t"]) - parse_iso(lp[0])).total_seconds()) / 3600
        kn = km / 1.852 / h if h > 0 else float("inf")
        if kn <= SPOOF_KNOTS:
            return None
        return {"konum": [p["lat"], p["lon"]], "onceki": [lp[1], lp[2]], "onceki_t": lp[0],
                "km": round(km, 1), "gorunen_hiz_knot": None if kn == float("inf") else round(kn)}

    def _position(self, p: dict, src: str) -> bool:
        mmsi = p["mmsi"]
        spoof = self._is_spoof(p)
        if spoof:
            self._bad[mmsi] = self._bad.get(mmsi, 0) + 1
            if self._bad[mmsi] < SPOOF_RESET:
                key = (mmsi, p["t"][:13])
                if key not in self._spoof_hours:
                    self._spoof_hours.add(key)
                    self.con.execute(
                        "INSERT INTO events(kind,mmsi,t_start,t_end,lat,lon,detail) VALUES('spoof',?,?,?,?,?,?)",
                        (mmsi, p["t"], p["t"], p["lat"], p["lon"], json.dumps(spoof)))
                return True  # ham dosyaya yaz (kanıt), analize alma
        self._bad[mmsi] = 0
        port, terminal = self.cfg.locate(p["lat"], p["lon"])
        last = self._last.get(mmsi)
        if last and last[1] == port:
            stopped = p["sog"] is not None and p["sog"] < 1
            if port is None:
                limit = self.T_OFFPORT
            elif stopped:
                limit = self.T_STOPPED
            elif self.cfg.port_by_code[port].role == "izlenen":
                limit = self.T_WATCHED
            else:
                limit = self.T_OTHERPORT
            if 0 <= (parse_iso(p["t"]) - parse_iso(last[0])).total_seconds() < limit:
                return False
        self._last[mmsi] = (p["t"], port)
        self._lastpos[mmsi] = (p["t"], p["lat"], p["lon"])
        if port is None:
            # liman dışında izlendiği saatleri kalıcı tut (eski konumlar silinse de güzergâh sınıfı bozulmasın)
            self.con.execute("INSERT OR IGNORE INTO seen_offport(mmsi, hour) VALUES(?,?)", (mmsi, p["t"][:13]))
        self.con.execute(
            "INSERT INTO positions(mmsi,t,lat,lon,sog,cog,nav,port,terminal,src) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (mmsi, p["t"], p["lat"], p["lon"], p["sog"], p["cog"], p["nav"], port, terminal, src),
        )
        self.con.execute(
            """INSERT INTO vessels(mmsi,name,first_seen,last_seen) VALUES(?,?,?,?)
               ON CONFLICT(mmsi) DO UPDATE SET last_seen=max(last_seen, excluded.last_seen),
               name=coalesce(vessels.name, excluded.name)""",
            (mmsi, p["name"], p["t"], p["t"]),
        )
        return True

    # --- statik bilgi ---
    def _static(self, p: dict) -> bool:
        sig = (p["imo"], p["name"], p["callsign"], p["type"], p["draught"], p["dest"])
        prev = self._last_static.get(p["mmsi"])
        if prev and prev[1] == sig and (parse_iso(p["t"]) - parse_iso(prev[0])).total_seconds() < self.STATIC_REFRESH_S:
            return False  # değişmemiş statik mesajı tekrar yazma
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
        return True

    def flush(self) -> None:
        self.con.commit()
        for f in self._files.values():
            f.flush()

    def close(self) -> None:
        self.flush()
        for f in self._files.values():
            f.close()
        self._files.clear()
