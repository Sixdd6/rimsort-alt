from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt

from app.models.metadata.metadata_structure import (
    AboutXmlMod,
    CaseInsensitiveStr,
    ListedMod,
)
from app.models.settings import Settings
from app.utils.custom_list_widget_item import CustomListWidgetItem
from app.utils.custom_list_widget_item_metadata import CustomListWidgetItemMetadata
from app.views.mods_panel import SEARCH_DEBOUNCE_MS, ModsPanel


def _add_mod_item(panel: ModsPanel, list_type: str, path: str) -> CustomListWidgetItem:
    mod_list = (
        panel.active_mods_list if list_type == "Active" else panel.inactive_mods_list
    )
    data = object.__new__(CustomListWidgetItemMetadata)
    data.path = path
    data.filtered = False
    data.invalid = False
    data.mod_tags = []
    item = CustomListWidgetItem()
    item.setData(Qt.ItemDataRole.UserRole, data, avoid_emit=True)
    mod_list.addItem(item)
    return item


@pytest.mark.parametrize("list_type", ["Active", "Inactive"])
def test_author_search_filters_mods_case_insensitively(
    qtbot: object, list_type: str
) -> None:
    settings = Settings()
    matching_path = "/mods/matching"
    other_path = "/mods/other"
    matching_mod = AboutXmlMod(
        name="Matching Mod",
        package_id=CaseInsensitiveStr("example.matching"),
        authors=["Jane Doe", "Second Author"],
    )
    other_mod = AboutXmlMod(
        name="Other Mod",
        package_id=CaseInsensitiveStr("example.other"),
        authors=["Someone Else"],
    )
    metadata = MagicMock()
    metadata.mods_metadata = {
        matching_path: matching_mod,
        other_path: other_mod,
    }
    metadata.get_mod.side_effect = metadata.mods_metadata.get

    panel = ModsPanel(settings, metadata)
    qtbot.addWidget(panel)  # type: ignore[attr-defined]
    mod_list = (
        panel.active_mods_list if list_type == "Active" else panel.inactive_mods_list
    )
    search_filter = (
        panel.active_mods_search_filter
        if list_type == "Active"
        else panel.inactive_mods_search_filter
    )
    matching_item = _add_mod_item(panel, list_type, matching_path)
    other_item = _add_mod_item(panel, list_type, other_path)
    mod_list.paths = [matching_path, other_path]
    mod_list.check_widgets_visible = MagicMock()  # type: ignore[method-assign]
    search_filter.setCurrentText(panel.tr("Author(s)"))

    panel.signal_search_and_filters(list_type, "jAnE")

    assert not matching_item.isHidden()
    assert other_item.isHidden()


@pytest.mark.parametrize(
    "mod",
    [
        AboutXmlMod(
            name="No Author Mod",
            package_id=CaseInsensitiveStr("example.noauthor"),
        ),
        ListedMod(name="Invalid Mod"),
    ],
)
def test_author_search_filters_mods_without_authors(
    qtbot: object, mod: AboutXmlMod | ListedMod
) -> None:
    settings = Settings()
    path = "/mods/no-author"
    metadata = MagicMock()
    metadata.mods_metadata = {path: mod}
    metadata.get_mod.side_effect = metadata.mods_metadata.get

    panel = ModsPanel(settings, metadata)
    qtbot.addWidget(panel)  # type: ignore[attr-defined]
    item = _add_mod_item(panel, "Active", path)
    panel.active_mods_list.paths = [path]
    panel.active_mods_list.check_widgets_visible = MagicMock()  # type: ignore[method-assign]
    panel.active_mods_search_filter.setCurrentText(panel.tr("Author(s)"))

    panel.signal_search_and_filters("Active", "author")

    assert item.isHidden()


def _bare_panel(qtbot: object) -> tuple[ModsPanel, MagicMock]:
    metadata = MagicMock()
    metadata.mods_metadata = {}
    panel = ModsPanel(Settings(), metadata)
    qtbot.addWidget(panel)  # type: ignore[attr-defined]
    run_filter = MagicMock()
    panel.signal_search_and_filters = run_filter  # type: ignore[method-assign]
    return panel, run_filter


def test_typing_filters_once_after_debounce(qtbot: object) -> None:
    panel, run_filter = _bare_panel(qtbot)

    for text in ("v", "va", "van"):
        panel.inactive_mods_search.setText(text)
    assert run_filter.call_count == 0

    qtbot.waitUntil(lambda: run_filter.call_count == 1, timeout=2000)  # type: ignore[attr-defined]
    qtbot.wait(SEARCH_DEBOUNCE_MS * 2)  # type: ignore[attr-defined]
    run_filter.assert_called_once_with(list_type="Inactive", pattern="van")


def test_clearing_search_filters_immediately_and_cancels_pending(
    qtbot: object,
) -> None:
    panel, run_filter = _bare_panel(qtbot)
    panel.active_mods_search.setText("van")

    panel.signal_clear_search("Active")
    assert run_filter.call_count == 1
    run_filter.assert_called_with(list_type="Active", pattern="")

    qtbot.wait(SEARCH_DEBOUNCE_MS * 2)  # type: ignore[attr-defined]
    assert run_filter.call_count == 1
    assert panel.active_mods_search.text() == ""
