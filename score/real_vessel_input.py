"""Build service vessel records from the tracked matching snapshots."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATCHES_PATH = PROJECT_ROOT / "data_new" / "processed" / "final_vessel_matches.jsonl"
DEFAULT_GFW_VESSELS_PATH = (
    PROJECT_ROOT / "data_new" / "processed" / "gfw_vessels_normalized.jsonl"
)

# These labels describe non-fishing vessels rather than fishing gear.
SELF_CONTRADICTING_GEAR_LABELS = {"CARGO", "PASSENGER", "CARRIER"}

# Broad labels do not provide a useful peer-group distinction.
AMBIGUOUS_GEAR_LABELS = {
    "FISHING",
    "OTHER",
    "NA",
    "INCONCLUSIVE",
    "GEAR",
    "FIXED_GEAR",
    "TROLLERS",
    "OTHER_PURSE_SEINES",
    "OTHER_SEINES",
}
EXCLUDED_GEAR_LABELS = SELF_CONTRADICTING_GEAR_LABELS | AMBIGUOUS_GEAR_LABELS


def _to_float(value) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def load_gear_types(path: Path = DEFAULT_GFW_VESSELS_PATH) -> Dict[str, List[str]]:
    """Load the usable GFW gear labels indexed by vessel ID."""
    gear_by_vessel: Dict[str, List[str]] = {}
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            gear_types = [
                gear
                for gear in (row.get("combinedGearTypes") or [])
                if gear not in EXCLUDED_GEAR_LABELS
            ]
            gear_by_vessel[row["vesselId"]] = gear_types
    return gear_by_vessel


def convert_row(row: dict, gear_by_vessel: Optional[Dict[str, List[str]]] = None) -> dict:
    """Convert one matching row to the service vessel schema."""
    gear_by_vessel = gear_by_vessel or {}
    tac = row.get("tac") or {}
    mof = row.get("mof") or {}

    tonnage = _to_float(tac.get("tonnageGtTac"))
    tonnage_source = "TAC" if tonnage is not None else None
    if tonnage is None:
        tonnage = _to_float(mof.get("tonnageGtMof"))
        tonnage_source = "MOF" if tonnage is not None else None

    vessel_id = row["gfwVesselId"]
    fishing_types = gear_by_vessel.get(vessel_id, [])
    verified = row.get("matchTier") == "verified"
    matched_name = tac.get("nameTac") or mof.get("nameMof") if verified else None
    return {
        "vesselId": vessel_id,
        "name": row.get("gfwName"),
        "tonnage": tonnage,
        "fishingType": fishing_types,
        "matchTier": row.get("matchTier"),
        "matchConfidence": row.get("matchConfidence"),
        "matchingEvidence": {
            "matchTier": row.get("matchTier"),
            "confidenceLabel": row.get("matchConfidence") if verified else None,
            "source": tonnage_source if verified else None,
            "gfwName": row.get("gfwName"),
            "matchedName": matched_name,
            "distanceKm": _to_float(row.get("distKm")) if verified else None,
            "tonnageGt": tonnage if verified else None,
            "tonnageSource": tonnage_source if verified else None,
            "fishingTypes": fishing_types,
            "fishingTypeSource": "GFW" if fishing_types else None,
            "unmatchedReason": None if verified else row.get("unmatchedReason"),
        },
    }


def load_real_vessel_records(
    matches_path: Path = DEFAULT_MATCHES_PATH,
    gfw_vessels_path: Path = DEFAULT_GFW_VESSELS_PATH,
) -> List[dict]:
    """Join the tracked matching and GFW snapshots into service records."""
    gear_by_vessel = load_gear_types(Path(gfw_vessels_path))
    with Path(matches_path).open(encoding="utf-8") as stream:
        return [convert_row(json.loads(line), gear_by_vessel) for line in stream]
