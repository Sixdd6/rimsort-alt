"""Rebuilding the mod lists (sort, clear, restore) must not flash or blink."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QEvent, QObject, Qt

from app.models.metadata.metadata_structure import AboutXmlMod, CaseInsensitiveStr
from app.views.main_content_panel import MainContent
from app.views.mods_panel import ModListWidget


class _PaintCounter(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.count = 0

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.Paint:
            self.count += 1
        return False


def _mods(count: int) -> dict[str, AboutXmlMod]:
    return {
        f"/m/{i}": AboutXmlMod(
            name=f"Mod {i}",
            _mod_path=Path(f"/m/{i}"),
            package_id=CaseInsensitiveStr(f"m.{i}"),
        )
        for i in range(count)
    }


@pytest.fixture
def shown_content(
    main_content: tuple[MainContent, list[bool]],
    mock_metadata_controller: MagicMock,
    qtbot: Any,
) -> tuple[MainContent, dict[str, AboutXmlMod]]:
    mc, _calls = main_content
    mods = _mods(90)
    mock_metadata_controller.mods_metadata = mods
    mock_metadata_controller.get_mod.side_effect = mods.get
    mock_metadata_controller.is_version_mismatch.return_value = False
    mock_metadata_controller.has_alternative_mod.return_value = None
    mock_metadata_controller.steamdb_packageid_to_name = {}
    mock_metadata_controller.settings = mc.settings
    mc.main_layout_frame.resize(1200, 800)
    mc.main_layout_frame.show()
    qtbot.waitExposed(mc.main_layout_frame)
    mc._insert_data_into_lists(["/m/0", "/m/1", "/m/2"], list(mods)[3:])
    qtbot.wait(50)
    assert mc.mods_panel.active_mods_list.count() == 3
    return mc, mods


def _watch(mod_list: ModListWidget) -> _PaintCounter:
    counter = _PaintCounter()
    mod_list.viewport().installEventFilter(counter)
    return counter


def _sort_to(mc: MainContent, new_order: list[str]) -> None:
    with patch("app.views.main_content_panel.Sorter") as sorter:
        # The sorter speaks str(mod_path), which uses backslashes on Windows
        paths = [str(Path(uuid)) for uuid in new_order]
        sorter.return_value.sort.return_value = (True, paths)
        mc._do_sort(check_deps=False)


def test_sort_repaints_once_after_the_rebuild_without_disabling_widgets(
    shown_content: tuple[MainContent, dict[str, AboutXmlMod]], qtbot: Any
) -> None:
    mc, _mods_by_path = shown_content
    active = mc.mods_panel.active_mods_list
    disable_emits: list[bool] = []
    mc.disable_enable_widgets_signal.connect(disable_emits.append)
    active_paints = _watch(active)
    inactive_paints = _watch(mc.mods_panel.inactive_mods_list)

    _sort_to(mc, ["/m/2", "/m/1", "/m/0"])

    assert active.paths == ["/m/2", "/m/1", "/m/0"]
    assert (active_paints.count, inactive_paints.count) == (0, 0)
    assert disable_emits == []
    assert active.isEnabled()

    qtbot.waitUntil(lambda: active_paints.count >= 1, timeout=2000)
    for row in active.get_visible_indexes():
        assert active.itemWidget(active.item(row)) is not None


def test_sort_keeps_the_unchanged_inactive_list_in_place(
    shown_content: tuple[MainContent, dict[str, AboutXmlMod]], qtbot: Any
) -> None:
    mc, _mods_by_path = shown_content
    inactive = mc.mods_panel.inactive_mods_list
    scrollbar = inactive.verticalScrollBar()
    assert scrollbar.maximum() > 0
    scrollbar.setValue(scrollbar.maximum())
    qtbot.wait(20)
    scrolled_to = scrollbar.value()
    first_item = inactive.item(0)
    paths_before = list(inactive.paths)

    _sort_to(mc, ["/m/2", "/m/1", "/m/0"])
    qtbot.wait(50)

    assert inactive.item(0) is first_item
    assert inactive.paths == paths_before
    assert scrollbar.value() == scrolled_to


def test_items_dropped_from_the_other_list_become_mod_items(
    shown_content: tuple[MainContent, dict[str, AboutXmlMod]], qtbot: Any
) -> None:
    """A drop between the lists inserts plain QListWidgetItems; PySide6 6.12
    has no copy constructor to convert them with, which crashed every drag."""
    from PySide6.QtWidgets import QListWidgetItem

    from app.utils.custom_list_widget_item import CustomListWidgetItem

    mc, _mods = shown_content
    active = mc.mods_panel.active_mods_list
    source = mc.mods_panel.inactive_mods_list.item(0)
    metadata = source.data(Qt.ItemDataRole.UserRole)
    dropped = QListWidgetItem()
    dropped.setData(Qt.ItemDataRole.UserRole, metadata)

    active.insertItem(1, dropped)
    # rowsInserted is handled through a queued connection
    qtbot.waitUntil(lambda: isinstance(active.item(1), CustomListWidgetItem))

    converted = active.item(1)
    assert isinstance(converted, CustomListWidgetItem)
    assert converted.data(Qt.ItemDataRole.UserRole) is metadata
    assert active.paths[1] == metadata["path"]
    assert active.count() == 4
