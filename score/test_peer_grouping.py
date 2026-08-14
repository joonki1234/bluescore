"""
담당: 김준기, 오동규

score/peer_grouping.py 단위 테스트.
"""

import pytest

from score.peer_grouping import (
    PeerGroup,
    build_peer_groups,
    gear_type_key,
    peer_group_for_vessel,
    region_key,
    season_key,
    tonnage_band,
)


def make_vessel(vessel_id, tonnage, fishing_type):
    return {"vesselId": vessel_id, "tonnage": tonnage, "fishingType": fishing_type}


def make_event(vessel_id, start, latitude, longitude):
    return {"vesselId": vessel_id, "start": start, "latitude": latitude, "longitude": longitude}


class TestTonnageBand:
    def test_bands_by_width(self):
        assert tonnage_band(24.0, band_width=10.0) == 20
        assert tonnage_band(29.9, band_width=10.0) == 20
        assert tonnage_band(30.0, band_width=10.0) == 30

    def test_none_returns_none(self):
        assert tonnage_band(None) is None

    def test_negative_raises(self):
        with pytest.raises(ValueError):
            tonnage_band(-1.0)


class TestGearTypeKey:
    def test_none_or_empty_returns_none(self):
        assert gear_type_key(None) is None
        assert gear_type_key([]) is None

    def test_string_passthrough(self):
        assert gear_type_key("TRAWLERS") == "TRAWLERS"

    def test_list_picks_sorted_first_regardless_of_order(self):
        assert gear_type_key(["TRAWLERS", "GILLNETS"]) == "GILLNETS"
        assert gear_type_key(["GILLNETS", "TRAWLERS"]) == "GILLNETS"


class TestRegionKey:
    def test_none_coordinates_returns_none(self):
        assert region_key(None, 125.0) is None
        assert region_key(35.0, None) is None

    def test_nearby_points_same_region(self):
        assert region_key(35.1, 129.1, grid_size_deg=1.0) == region_key(35.9, 129.9, grid_size_deg=1.0)

    def test_far_points_different_region(self):
        assert region_key(35.0, 129.0, grid_size_deg=1.0) != region_key(40.0, 135.0, grid_size_deg=1.0)


class TestSeasonKey:
    def test_first_half_year(self):
        assert season_key("2026-03-01T00:00:00Z") == "2026-H1"

    def test_second_half_year(self):
        assert season_key("2026-08-01T00:00:00Z") == "2026-H2"

    def test_invalid_string_returns_none(self):
        assert season_key("not-a-date") is None

    def test_none_returns_none(self):
        assert season_key(None) is None


class TestBuildPeerGroups:
    def test_same_key_vessels_grouped_together(self):
        vessels = [
            make_vessel("V1", 25.0, ["TRAWLERS"]),
            make_vessel("V2", 26.0, ["TRAWLERS"]),
        ]
        events = [
            make_event("V1", "2026-03-01T00:00:00Z", 35.1, 129.1),
            make_event("V2", "2026-03-15T00:00:00Z", 35.2, 129.2),
        ]
        groups, vessel_to_key = build_peer_groups(vessels, events)
        assert len(groups) == 1
        (group,) = groups.values()
        assert sorted(group.vessel_ids) == ["V1", "V2"]
        assert vessel_to_key["V1"] == vessel_to_key["V2"]

    def test_different_tonnage_band_splits_groups(self):
        vessels = [
            make_vessel("V1", 25.0, ["TRAWLERS"]),
            make_vessel("V2", 95.0, ["TRAWLERS"]),
        ]
        events = [
            make_event("V1", "2026-03-01T00:00:00Z", 35.1, 129.1),
            make_event("V2", "2026-03-01T00:00:00Z", 35.1, 129.1),
        ]
        groups, _ = build_peer_groups(vessels, events)
        assert len(groups) == 2

    def test_vessel_with_no_events_still_grouped_with_none_region_season(self):
        vessels = [make_vessel("V1", 25.0, ["TRAWLERS"])]
        groups, vessel_to_key = build_peer_groups(vessels, [])
        key = vessel_to_key["V1"]
        assert key == (20, "TRAWLERS", None, None)
        assert groups[key].vessel_ids == ["V1"]

    def test_vessel_without_id_is_skipped(self):
        vessels = [{"tonnage": 25.0, "fishingType": ["TRAWLERS"]}]
        groups, vessel_to_key = build_peer_groups(vessels, [])
        assert groups == {}
        assert vessel_to_key == {}

    def test_uses_most_recent_event_as_representative(self):
        vessels = [make_vessel("V1", 25.0, ["TRAWLERS"])]
        events = [
            make_event("V1", "2026-01-01T00:00:00Z", 35.1, 129.1),  # H1
            make_event("V1", "2026-08-01T00:00:00Z", 40.1, 135.1),  # H2, more recent
        ]
        groups, vessel_to_key = build_peer_groups(vessels, events)
        _, _, region, season = vessel_to_key["V1"]
        assert season == "2026-H2"
        assert region == region_key(40.1, 135.1)


class TestPeerGroupSampleSize:
    def test_sufficient_sample(self):
        group = PeerGroup(key=(20, "TRAWLERS", None, None), vessel_ids=[f"V{i}" for i in range(20)])
        assert group.sample_size == 20
        assert group.has_sufficient_sample(min_size=20) is True

    def test_insufficient_sample(self):
        group = PeerGroup(key=(20, "TRAWLERS", None, None), vessel_ids=["V1", "V2"])
        assert group.has_sufficient_sample(min_size=20) is False


class TestPeerGroupForVessel:
    def test_returns_group_for_known_vessel(self):
        vessels = [make_vessel("V1", 25.0, ["TRAWLERS"])]
        groups, vessel_to_key = build_peer_groups(vessels, [])
        group = peer_group_for_vessel("V1", groups, vessel_to_key)
        assert group is not None
        assert "V1" in group.vessel_ids

    def test_returns_none_for_unknown_vessel(self):
        groups, vessel_to_key = build_peer_groups([], [])
        assert peer_group_for_vessel("ghost", groups, vessel_to_key) is None
