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


def _bare_panel_with_alternatives(
    qtbot: object, alternatives: list[str | None]
) -> ModsPanel:
    metadata = MagicMock()
    metadata.mods_metadata = {}
    panel = ModsPanel(Settings(), metadata)
    qtbot.addWidget(panel)  # type: ignore[attr-defined]
    for mod_list in (panel.active_mods_list, panel.inactive_mods_list):
        mod_list.check_widgets_visible = MagicMock()  # type: ignore[method-assign]
    for index, alternative in enumerate(alternatives):
        data = _add_mod_item(panel, "Inactive", f"/mods/{index}").data(
            Qt.ItemDataRole.UserRole
        )
        data.alternative = alternative
        data.errors_warnings = data.errors = data.warnings = ""
        data.warning_toggled = data.mismatch = data.hidden_by_filter = False
    return panel


def test_use_this_instead_button_reports_replacement_count(qtbot: object) -> None:
    panel = _bare_panel_with_alternatives(qtbot, ["Better Mod (1)", None, "Other (2)"])
    panel.settings.external_use_this_instead_metadata_source = "Configured URL"

    panel.update_use_this_instead_button()

    assert panel.use_this_instead_button.isEnabled()
    assert panel.use_this_instead_button.text() == "Replacements available (2)"


def test_use_this_instead_button_is_disabled_without_matches_or_database(
    qtbot: object,
) -> None:
    panel = _bare_panel_with_alternatives(qtbot, [None, None])
    panel.settings.external_use_this_instead_metadata_source = "Configured URL"
    panel.update_use_this_instead_button()
    assert not panel.use_this_instead_button.isEnabled()
    assert panel.use_this_instead_button.text() == "No replacements available"

    panel.settings.external_use_this_instead_metadata_source = "None"
    panel.update_use_this_instead_button()
    assert not panel.use_this_instead_button.isEnabled()
    assert "not configured" in panel.use_this_instead_button.text()


def test_use_this_instead_button_ignores_replaced_inactive_originals(
    qtbot: object,
) -> None:
    from app.models.metadata.metadata_structure import ReplacementInfo

    panel = _bare_panel_with_alternatives(qtbot, ["New Mod (9)", "Other (8)"])
    panel.settings.external_use_this_instead_metadata_source = "Configured URL"
    installed = MagicMock()
    installed.published_file_id = "9"
    metadata: MagicMock = panel.metadata_controller  # type: ignore[assignment]
    metadata.mods_metadata = {"/mods/new": installed}
    replacements = {
        "/mods/0": ReplacementInfo("New Mod", "a", "pkg", "9", []),
        "/mods/1": ReplacementInfo("Other", "a", "pkg", "8", []),
    }
    metadata.has_alternative_mod.side_effect = replacements.get

    panel.update_use_this_instead_button()

    # /mods/0 is inactive and its replacement (9) is installed: already handled
    assert panel.use_this_instead_button.text() == "Replacements available (1)"

    # The same original counts again once it is active
    panel.active_mods_list.paths = ["/mods/0"]
    item = panel.inactive_mods_list.takeItem(0)
    panel.active_mods_list.addItem(item)
    panel.update_use_this_instead_button()
    assert panel.use_this_instead_button.text() == "Replacements available (2)"


def test_tag_refresh_reapplies_the_kept_search(
    qtbot: object, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings()
    matching_path = "/mods/matching"
    other_path = "/mods/other"
    metadata = MagicMock()
    metadata.mods_metadata = {
        matching_path: AboutXmlMod(
            name="Matching Mod", package_id=CaseInsensitiveStr("example.matching")
        ),
        other_path: AboutXmlMod(
            name="Other Mod", package_id=CaseInsensitiveStr("example.other")
        ),
    }
    metadata.get_mod.side_effect = metadata.mods_metadata.get
    monkeypatch.setattr("app.views.mods_panel.auxdb_get_all_tags", lambda _settings: [])

    panel = ModsPanel(settings, metadata)
    qtbot.addWidget(panel)  # type: ignore[attr-defined]
    panel.inactive_mods_search.setText("matching")
    # Lists rebuilt by a refresh come back unfiltered
    matching_item = _add_mod_item(panel, "Inactive", matching_path)
    other_item = _add_mod_item(panel, "Inactive", other_path)
    panel.inactive_mods_list.paths = [matching_path, other_path]
    panel.inactive_mods_list.check_widgets_visible = MagicMock()  # type: ignore[method-assign]

    panel.refresh_all_tag_filter_selectors()

    assert panel.inactive_mods_search.text() == "matching"
    assert not matching_item.isHidden()
    assert other_item.isHidden()
