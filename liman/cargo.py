"""Muhtemel yük çıkarımı. Kesin yük bilgisi değildir; dayanakları her zaman birlikte yayımlanır."""
from __future__ import annotations

from .config import CARGO_LABELS
from .util import SHIP_GROUP_LABELS, hazard_category, ship_group

TYPE_GUESS = {
    "tanker": ("sivi_dokme", "Sıvı yük (tanker)"),
    "kargo": (None, "Kuru yük / dökme / konteyner (kargo gemisi)"),
}
LOAD_M = 0.5  # bu kadar su çekimi artışı = yükleme


def infer(cfg, vessel_type, origin_visit, dest_visit, sts_draughts=None) -> dict:
    group = ship_group(vessel_type)
    basis: list[str] = []
    score = 0
    guess_code = None
    guess = None

    if group in TYPE_GUESS:
        guess_code, guess = TYPE_GUESS[group]
        basis.append(f"Gemi tipi: {SHIP_GROUP_LABELS[group]}")
        hz = hazard_category(vessel_type)
        if hz:
            basis.append(f"AIS tehlikeli yük kategorisi: {hz}")
        score += 1
    else:
        basis.append(f"Gemi tipi: {SHIP_GROUP_LABELS.get(group, group)}")

    term_cargo = cfg.terminal_cargo(origin_visit["port"], origin_visit["terminal"]) if origin_visit else None
    if term_cargo:
        if guess_code is None or guess_code == term_cargo or group == "kargo":
            guess_code = term_cargo
            guess = CARGO_LABELS.get(term_cargo, term_cargo)
            score += 1
        basis.append(f"Çıkış limanında yanaştığı terminal: {origin_visit['terminal']}")

    def delta(v):
        if v and v["draught_in"] is not None and v["draught_out"] is not None:
            return round(v["draught_out"] - v["draught_in"], 1)
        return None

    d0 = delta(origin_visit)
    if d0 is not None:
        if d0 >= LOAD_M:
            basis.append(f"Çıkış limanında su çekimi arttı: {origin_visit['draught_in']} → {origin_visit['draught_out']} m (yükleme)")
            score += 1
        else:
            basis.append(f"Çıkış limanında su çekimi değişmedi/azaldı: {origin_visit['draught_in']} → {origin_visit['draught_out']} m")
    d1 = delta(dest_visit)
    if d1 is not None:
        if d1 <= -LOAD_M:
            basis.append(f"Varış limanında su çekimi azaldı: {dest_visit['draught_in']} → {dest_visit['draught_out']} m (boşaltma)")
            score += 1
        else:
            basis.append(f"Varış limanında su çekimi azalmadı: {dest_visit['draught_in']} → {dest_visit['draught_out']} m")
    if sts_draughts:
        basis.append(sts_draughts)
        score += 1

    if guess is None:
        guess = "Belirlenemedi"
    conf = "yüksek" if score >= 3 else "orta" if score == 2 else "düşük"
    return {"cargo": guess, "conf": conf, "basis": basis}
