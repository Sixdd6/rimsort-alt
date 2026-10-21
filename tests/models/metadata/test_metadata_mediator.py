import json
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from app.models.metadata.metadata_mediator import MetadataMediator
from app.models.metadata.metadata_structure import AboutXmlMod

_MEDIATOR = "app.models.metadata.metadata_mediator"


@pytest.fixture
def mediator() -> MetadataMediator:
    return MetadataMediator(
        user_rules_path=Path("tests/data/dbs/userRules.json"),
        community_rules_path=None,
        steam_db_path=None,
        workshop_mods_path=None,
        local_mods_path=Path("tests/data/mod_examples/Local"),
        game_path=Path("tests/data/mod_examples/RimWorld"),
    )


def test_initial_state(mediator: MetadataMediator) -> None:
    assert mediator.user_rules is None
    assert mediator.community_rules is None
    assert mediator.steam_db is None
    assert mediator.game_version == "Unknown"

    assert mediator.mods_metadata == {}


def test_refresh_metadata(mediator: MetadataMediator) -> None:
    mediator.refresh_metadata()
    assert mediator.user_rules is not None
    assert mediator.community_rules is None
    assert mediator.steam_db is None
    assert mediator.mods_metadata is not None
    assert len(mediator.mods_metadata) > 0
    a = len(mediator.mods_metadata)
    assert mediator.game_version != "Unknown"

    mediator.workshop_mods_path = Path("tests/data/mod_examples/Steam")
    mediator.steam_db_path = Path("tests/data/dbs/steamDB.json")
    mediator.refresh_metadata()
    assert mediator.user_rules is not None
    assert mediator.community_rules is None
    assert mediator.steam_db is not None
    assert mediator.mods_metadata is not None
    assert len(mediator.mods_metadata) > 0
    assert len(mediator.mods_metadata) > a
    assert mediator.game_version != "Unknown"

    mediator.game_path = Path("tests/data/mod_examples")
    mediator.refresh_metadata()
    assert mediator.game_version == "Unknown"


def test_user_rules_addition(mediator: MetadataMediator) -> None:
    mediator.refresh_metadata()

    assert mediator.user_rules is not None
    assert mediator.mods_metadata is not None
    assert len(mediator.mods_metadata) > 0

    mod = mediator.mods_metadata.get(
        str(Path("tests/data/mod_examples/Local/local_mod_1")), None
    )
    assert mod is not None

    assert isinstance(mod, AboutXmlMod)
    assert mod.about_rules.load_after == {}
    assert len(mod.user_rules.load_after) > 0
    assert len(mod.overall_rules.load_after) > 0

    assert mod.user_rules.load_last
    assert mod.overall_rules.load_last


def test_mediator_no_version_warning_defaults_none(tmp_path: Path) -> None:
    """no_version_warning is None when no path configured."""
    mediator = MetadataMediator(
        user_rules_path=tmp_path / "rules.json",
        community_rules_path=None,
        steam_db_path=None,
        workshop_mods_path=None,
        local_mods_path=None,
        game_path=None,
    )
    assert mediator.no_version_warning is None


def test_mediator_use_this_instead_defaults_none(tmp_path: Path) -> None:
    """use_this_instead is None when no path configured."""
    mediator = MetadataMediator(
        user_rules_path=tmp_path / "rules.json",
        community_rules_path=None,
        steam_db_path=None,
        workshop_mods_path=None,
        local_mods_path=None,
        game_path=None,
    )
    assert mediator.use_this_instead is None


def _load_no_version_warning(tmp_path: Path, body: str) -> list[str] | None:
    nvw_path = tmp_path / "ModIdsToFix.xml"
    nvw_path.write_text(
        '\ufeff<?xml version="1.0" encoding="utf-8"?>\n' + body, encoding="utf-8"
    )
    mediator = MetadataMediator(
        user_rules_path=tmp_path / "rules.json",
        community_rules_path=None,
        steam_db_path=None,
        workshop_mods_path=None,
        local_mods_path=None,
        game_path=None,
        no_version_warning_path=nvw_path,
    )
    mediator._load_no_version_warning()
    return mediator.no_version_warning


def test_mediator_loads_no_version_warning(tmp_path: Path) -> None:
    """Mediator loads No Version Warning from XML file."""
    entries = _load_no_version_warning(
        tmp_path, "<ModIdsToFix><li>mod.a</li><li>Mod.B</li></ModIdsToFix>"
    )
    assert entries == ["mod.a", "mod.b"]


def test_mediator_loads_a_single_no_version_warning_entry(tmp_path: Path) -> None:
    entries = _load_no_version_warning(
        tmp_path, "<ModIdsToFix><li>mod.a</li></ModIdsToFix>"
    )
    assert entries == ["mod.a"]


@pytest.mark.parametrize(
    "body",
    ["<ModIdsToFix>\n</ModIdsToFix>", "<ModIdsToFix/>", "<ModIdsToFix></ModIdsToFix>"],
)
def test_mediator_accepts_an_empty_no_version_warning_db(
    tmp_path: Path, body: str
) -> None:
    """The DB for a new game version (e.g. 1.7) can have no entries yet; loading
    it used to raise AttributeError and crash every refresh."""
    assert _load_no_version_warning(tmp_path, body) == []


def test_mediator_loads_use_this_instead(tmp_path: Path) -> None:
    """Mediator loads Use This Instead from JSON file, indexed by oldWorkshopId."""
    uti_data = {
        "version": "2026-01-01T00:00:00Z",
        "rules": [
            {
                "oldWorkshopId": "111111",
                "oldName": "Old Mod",
                "oldPackageId": "old.mod.a",
                "newWorkshopId": "222222",
                "newName": "New Mod",
                "newPackageId": "new.mod.b",
                "newAuthor": "Author",
                "oldVersions": ["1.4"],
                "newVersions": ["1.5"],
            }
        ],
    }
    uti_path = tmp_path / "use_this_instead.json"
    uti_path.write_text(json.dumps(uti_data))

    mediator = MetadataMediator(
        user_rules_path=tmp_path / "rules.json",
        community_rules_path=None,
        steam_db_path=None,
        workshop_mods_path=None,
        local_mods_path=None,
        game_path=None,
        use_this_instead_path=uti_path,
    )
    mediator._load_use_this_instead()
    assert mediator.use_this_instead is not None
    assert "111111" in mediator.use_this_instead
    entry = mediator.use_this_instead["111111"]
    assert entry["newName"] == "New Mod"
    assert entry["newPackageId"] == "new.mod.b"


@pytest.fixture
def steam_db_mediator(tmp_path: Path) -> MetadataMediator:
    steam_db_path = tmp_path / "steamDB.json"
    shutil.copy(Path("tests/data/dbs/steamDB.json"), steam_db_path)
    return MetadataMediator(
        user_rules_path=Path("tests/data/dbs/userRules.json"),
        community_rules_path=None,
        steam_db_path=steam_db_path,
        workshop_mods_path=None,
        local_mods_path=Path("tests/data/mod_examples/Local"),
        game_path=Path("tests/data/mod_examples/RimWorld"),
    )


def test_unchanged_steam_db_is_reused_across_refreshes(
    steam_db_mediator: MetadataMediator,
) -> None:
    steam_db_mediator.refresh_metadata()
    first = steam_db_mediator.steam_db
    assert first is not None

    with patch(f"{_MEDIATOR}.read_steam_db") as read_steam_db:
        steam_db_mediator.refresh_metadata()

    read_steam_db.assert_not_called()
    assert steam_db_mediator.steam_db is first


def test_changed_steam_db_is_reloaded(steam_db_mediator: MetadataMediator) -> None:
    steam_db_mediator.refresh_metadata()
    first = steam_db_mediator.steam_db
    assert steam_db_mediator.steam_db_path is not None
    with open(steam_db_mediator.steam_db_path, "a", encoding="utf-8") as handle:
        handle.write("\n")

    steam_db_mediator.refresh_metadata()

    assert steam_db_mediator.steam_db is not None
    assert steam_db_mediator.steam_db is not first


def test_invalidated_steam_db_is_reloaded(steam_db_mediator: MetadataMediator) -> None:
    steam_db_mediator.refresh_metadata()
    first = steam_db_mediator.steam_db

    steam_db_mediator.invalidate_steam_db_cache()
    steam_db_mediator.refresh_metadata()

    assert steam_db_mediator.steam_db is not None
    assert steam_db_mediator.steam_db is not first
