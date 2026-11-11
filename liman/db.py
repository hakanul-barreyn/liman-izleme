"""SQLite veritabanı şeması ve bağlantı."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS positions(
  id INTEGER PRIMARY KEY, mmsi INTEGER NOT NULL, t TEXT NOT NULL,
  lat REAL, lon REAL, sog REAL, cog REAL, nav INTEGER,
  port TEXT, terminal TEXT, src TEXT);
CREATE INDEX IF NOT EXISTS ix_pos_mmsi_t ON positions(mmsi, t);
CREATE INDEX IF NOT EXISTS ix_pos_t ON positions(t);
CREATE INDEX IF NOT EXISTS ix_pos_port_t ON positions(port, t);

CREATE TABLE IF NOT EXISTS statics(
  id INTEGER PRIMARY KEY, mmsi INTEGER NOT NULL, t TEXT NOT NULL,
  imo INTEGER, name TEXT, callsign TEXT, type INTEGER,
  length REAL, width REAL, draught REAL, dest TEXT);
CREATE INDEX IF NOT EXISTS ix_st_mmsi_t ON statics(mmsi, t);

CREATE TABLE IF NOT EXISTS vessels(
  mmsi INTEGER PRIMARY KEY, imo INTEGER, name TEXT, callsign TEXT, type INTEGER,
  length REAL, width REAL, draught REAL, dest TEXT,
  first_seen TEXT, last_seen TEXT, history TEXT DEFAULT '[]');

CREATE TABLE IF NOT EXISTS visits(
  id INTEGER PRIMARY KEY, mmsi INTEGER NOT NULL, port TEXT NOT NULL,
  t_in TEXT NOT NULL, last_in TEXT NOT NULL, t_out TEXT,
  stopped INTEGER DEFAULT 0, status TEXT NOT NULL, transit INTEGER,
  draught_in REAL, draught_out REAL, terminal TEXT, dest_out TEXT);
CREATE INDEX IF NOT EXISTS ix_visits_mmsi ON visits(mmsi, t_in);
CREATE INDEX IF NOT EXISTS ix_visits_port ON visits(port, t_in);

CREATE TABLE IF NOT EXISTS tracking(
  mmsi INTEGER PRIMARY KEY, start TEXT, until TEXT, visit_id INTEGER,
  status TEXT, ended TEXT, end_reason TEXT);

CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, mmsi INTEGER, mmsi2 INTEGER,
  t_start TEXT, t_end TEXT, lat REAL, lon REAL, detail TEXT);
CREATE INDEX IF NOT EXISTS ix_events ON events(kind, t_start);

CREATE TABLE IF NOT EXISTS outages(
  id INTEGER PRIMARY KEY, conn TEXT, t_start TEXT, t_end TEXT, reason TEXT);

CREATE TABLE IF NOT EXISTS routes(
  id INTEGER PRIMARY KEY, direction TEXT, kind TEXT, vkey TEXT, mmsi INTEGER, name TEXT,
  origin_port TEXT, t_dep TEXT, dest_port TEXT, t_arr TEXT,
  cls TEXT, flags TEXT, mids TEXT, evts TEXT, masked INTEGER, dest_text TEXT,
  tracked INTEGER, cargo TEXT, cargo_conf TEXT, cargo_basis TEXT,
  via_vkey TEXT, via_mmsi INTEGER, via_name TEXT);

CREATE TABLE IF NOT EXISTS seen_offport(mmsi INTEGER, hour TEXT, PRIMARY KEY(mmsi, hour));

CREATE TABLE IF NOT EXISTS archived_days(day TEXT PRIMARY KEY, day_hash TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
"""


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path), timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(SCHEMA)
    return con


def get_meta(con, k: str, default=None):
    r = con.execute("SELECT v FROM meta WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default


def set_meta(con, k: str, v) -> None:
    con.execute("INSERT INTO meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))


def db_path(cfg) -> Path:
    return cfg.data_dir / "liman.db"
