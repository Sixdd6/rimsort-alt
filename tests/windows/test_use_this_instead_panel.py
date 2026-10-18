from typing import Any
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt

from app.models.metadata.metadata_structure import ReplacementInfo
from app.views.mod_table import GROUP_ROLE, STATUS_COLUMN
from app.windows.base_mods_panel import ColumnIndex
from app.windows.use_this_instead_panel import (
    ReplacementRequest,
    UseThisInsteadPanel,
    build_replacement_groups,
)
from tests.mod_fixtures import fake_about_mod

_mod = fake_about_mod


def _replacement(pfid: str, name: str) -> ReplacementInfo:
    return ReplacementInfo(
        name=name,
        author="Author",
        packageid=f"new.{pfid}",
        pfid=pfid,
        supportedversions=["1.6"],
    )


@pytest.fixture
def world(mock_metadata_controller: MagicMock) -> dict[str, Any]:
    mods = {
        "/m/a": _mod("Alpha", "1", "/m/a"),
        "/m/b": _mod("Beta", "2", "/m/b"),
        "/m/c": _mod("Gamma", "3", "/m/c"),
        "/m/r1": _mod("Alpha Reborn", "9", "/m/r1"),
    }
    replacements = {
        "/m/a": _replacement("9", "Alpha Reborn"),
        "/m/b": _replacement("8", "Beta Continued"),
        "/m/c": _replacement("8", "Beta Continued"),
    }
    mock_metadata_controller.mods_metadata = mods
    mock_metadata_controller.has_alternative_mod.side_effect = replacements.get
    mock_metadata_controller.settings = MagicMock()
    return mods


def test_groups_are_keyed_by_replacement_and_know_if_it_is_installed(
    world: dict[str, Any], mock_metadata_controller: MagicMock
) -> None:
    groups = build_replacement_groups(world, mock_metadata_controller)

    assert [g.replacement.name for g in groups] == ["Alpha Reborn", "Beta Continued"]
    assert groups[0].originals == ["/m/a"]
    assert groups[0].replacement_path == "/m/r1"
    assert groups[1].originals == ["/m/b", "/m/c"]
    assert groups[1].replacement_path is None


@pytest.fixture
def panel(
    qtbot: Any, world: dict[str, Any], mock_metadata_controller: MagicMock
) -> UseThisInsteadPanel:
    panel = UseThisInsteadPanel(
        mod_metadata=world,
        metadata_controller=mock_metadata_controller,
        active_mod_paths=["/m/a"],
    )
    qtbot.addWidget(panel)
    assert panel.show_if_has_alternatives()
    return panel


def _column(panel: UseThisInsteadPanel, column: int) -> list[str]:
    return [
        panel.editor_model.item(row, column).text()
        for row in range(panel.editor_model.rowCount())
    ]


def test_rows_show_originals_then_replacement_with_status(
    panel: UseThisInsteadPanel,
) -> None:
    names = _column(panel, ColumnIndex.NAME.value)
    assert names == [
        "Alpha Reborn by Author  ·  replaces 1",
        "Alpha",
        "Alpha Reborn",
        "Beta Continued by Author  ·  replaces 2",
        "Beta",
        "Gamma",
        "Beta Continued",
    ]
    assert _column(panel, STATUS_COLUMN) == [
        "",
        "Original · Active",
        "Replacement · Installed",
        "",
        "Original",
        "Original",
        "Replacement · Not installed",
    ]
    assert panel.editor_model.item(0, 1).data(GROUP_ROLE)
    assert panel.editor_model.item(6, 1).data(0x0100) is None  # no path for uninstalled
    assert panel.editor_model.item(6, ColumnIndex.PUBLISHED_FILE_ID.value).text() == "8"


def test_replace_all_emits_one_request_per_group_and_closes(
    panel: UseThisInsteadPanel, qtbot: Any
) -> None:
    with qtbot.waitSignal(panel.replace_requested, timeout=1000) as blocker:
        panel._replace_all()

    assert blocker.args is not None
    assert blocker.args[0] == [
        ReplacementRequest(["/m/a"], "9", "/m/r1"),
        ReplacementRequest(["/m/b", "/m/c"], "8", None),
    ]
    assert not panel.isVisible()


def test_replace_selected_uses_checked_rows_of_either_kind(
    panel: UseThisInsteadPanel, qtbot: Any
) -> None:
    panel._select_all_replacements()
    panel.editor_model.item(2, 0).setCheckState(Qt.CheckState.Unchecked)
    with qtbot.waitSignal(panel.replace_requested, timeout=1000) as blocker:
        panel._replace_selected()

    assert blocker.args is not None
    assert [r.replacement_pfid for r in blocker.args[0]] == ["8"]


def test_replace_selected_with_nothing_checked_does_nothing(
    panel: UseThisInsteadPanel, qtbot: Any
) -> None:
    received: list[Any] = []
    panel.replace_requested.connect(received.append)
    panel._replace_selected()
    assert received == []
    assert panel.isVisible()
