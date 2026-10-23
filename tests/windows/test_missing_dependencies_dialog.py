from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QLabel, QPushButton, QWidget
from pytestqt.qtbot import QtBot

from app.services.dependency_resolver import DepResolveResult
from app.services.ignored_dependencies import (
    load_ignored_dependencies,
    set_dependency_ignored,
)
from app.windows.missing_dependencies_dialog import MissingDependenciesDialog

_LOCAL_DEPS_SUMMARY = {
    "active.mod": {
        "satisfied": set(),
        "local": {"dep.local"},
        "download": set(),
    }
}
_LOCAL_MISSING_DEPS = {"active.mod": {"dep.local"}}


@pytest.fixture
def metadata_controller() -> MagicMock:
    controller = MagicMock()
    controller.get_mod_name_from_package_id.side_effect = lambda pkg_id: pkg_id
    return controller


@pytest.fixture
def dialog(metadata_controller: MagicMock, qtbot: QtBot) -> MissingDependenciesDialog:
    missing_dialog = MissingDependenciesDialog(metadata_controller)
    qtbot.addWidget(missing_dialog)
    return missing_dialog


def _find_button(parent: QWidget, text: str) -> QPushButton:
    for button in parent.findChildren(QPushButton):
        if button.text() == text:
            return button
    raise AssertionError(f"Button {text!r} not found")


def test_show_dialog_is_non_modal_and_returns_selected(
    dialog: MissingDependenciesDialog,
) -> None:
    def accept_with_selection() -> None:
        dialog.checkboxes["dep.local"][0].setChecked(True)
        dialog.accept()

    QTimer.singleShot(100, accept_with_selection)

    selected = dialog.show_dialog(_LOCAL_DEPS_SUMMARY, _LOCAL_MISSING_DEPS)

    assert dialog.windowModality() == Qt.WindowModality.NonModal
    assert selected == {"dep.local"}


def test_show_dialog_reject_returns_empty(dialog: MissingDependenciesDialog) -> None:
    QTimer.singleShot(100, dialog.reject)

    selected = dialog.show_dialog(_LOCAL_DEPS_SUMMARY, _LOCAL_MISSING_DEPS)

    assert selected == set()


class TestMissingDependenciesDialogPopulate:
    def test_empty_deps_summary_shows_message(
        self, dialog: MissingDependenciesDialog
    ) -> None:
        dialog._populate_dependencies({})

        item = dialog.scroll_layout.itemAt(0)
        assert item is not None
        widget = item.widget()
        assert isinstance(widget, QLabel)
        assert "No dependencies found" in widget.text()

    def test_download_with_workshop_id_enables_download_button(
        self, dialog: MissingDependenciesDialog, qtbot: QtBot
    ) -> None:
        dep_resolve = {
            "author.missing": DepResolveResult(
                package_id="author.missing",
                workshop_id="12345",
                workshop_url="https://steamcommunity.com/sharedfiles/filedetails/?id=12345",
                source="steam_db",
            )
        }
        deps_summary = {
            "active.mod": {
                "satisfied": set(),
                "local": set(),
                "download": {"author.missing"},
            }
        }

        dialog._dep_resolve = dep_resolve
        dialog._populate_dependencies(deps_summary)

        download_btn = _find_button(dialog, "Download")
        open_btn = _find_button(dialog, "Open Workshop")

        assert download_btn.isEnabled()
        assert open_btn.isEnabled()

        with qtbot.waitSignal(dialog.download_requested, timeout=1000) as blocker:
            qtbot.mouseClick(download_btn, Qt.MouseButton.LeftButton)  # type: ignore[no-untyped-call]

        assert blocker.args == ["12345"]

    def test_download_without_workshop_id_disables_download_button(
        self,
        dialog: MissingDependenciesDialog,
    ) -> None:
        deps_summary = {
            "active.mod": {
                "satisfied": set(),
                "local": set(),
                "download": {"author.unknown"},
            }
        }

        dialog._dep_resolve = {
            "author.unknown": DepResolveResult(
                package_id="author.unknown",
                workshop_id=None,
                workshop_url=None,
                source="none",
            )
        }
        dialog._populate_dependencies(deps_summary)

        download_btn = _find_button(dialog, "Download")
        open_btn = _find_button(dialog, "Open Workshop")

        assert not download_btn.isEnabled()
        assert open_btn.isEnabled()

        hints = dialog.findChildren(QLabel, "missingWorkshopHint")
        assert len(hints) == 1
        assert "Workshop ID not found" in hints[0].text()


_MIXED_DEPS_SUMMARY = {
    "active.mixed": {
        "satisfied": {"dep.done"},
        "local": {"dep.local"},
        "download": set(),
    },
    "active.clean": {
        "satisfied": {"dep.other"},
        "local": set(),
        "download": set(),
    },
}

_SATISFIED_ONLY_SUMMARY = {
    "active.clean": {
        "satisfied": {"dep.other"},
        "local": set(),
        "download": set(),
    }
}


def _header_texts(dialog: MissingDependenciesDialog) -> list[str]:
    return [label.text() for label in dialog.findChildren(QLabel, "modHeaderLabel")]


class TestShowSatisfiedToggle:
    def test_toggle_defaults_to_unchecked(
        self, dialog: MissingDependenciesDialog
    ) -> None:
        assert not dialog.show_satisfied_checkbox.isChecked()

    def test_fully_satisfied_mods_hidden_by_default(
        self, dialog: MissingDependenciesDialog
    ) -> None:
        dialog._deps_summary = _MIXED_DEPS_SUMMARY
        dialog._populate_dependencies(_MIXED_DEPS_SUMMARY)

        headers = _header_texts(dialog)
        assert any("active.mixed" in text for text in headers)
        assert not any("active.clean" in text for text in headers)
        assert dialog.findChildren(QLabel, "satisfiedDepLabel") == []
        assert "dep.local" in dialog.checkboxes

    def test_toggle_on_restores_full_overview(
        self, dialog: MissingDependenciesDialog
    ) -> None:
        dialog._deps_summary = _MIXED_DEPS_SUMMARY
        dialog._populate_dependencies(_MIXED_DEPS_SUMMARY)

        dialog.show_satisfied_checkbox.setChecked(True)

        headers = _header_texts(dialog)
        assert any("active.mixed" in text for text in headers)
        assert any("active.clean" in text for text in headers)
        assert len(dialog.findChildren(QLabel, "satisfiedDepLabel")) == 2
        assert "dep.local" in dialog.checkboxes

    def test_selection_survives_toggle(self, dialog: MissingDependenciesDialog) -> None:
        dialog._deps_summary = _MIXED_DEPS_SUMMARY
        dialog._populate_dependencies(_MIXED_DEPS_SUMMARY)

        dialog.checkboxes["dep.local"][0].setChecked(True)
        dialog.show_satisfied_checkbox.setChecked(True)
        dialog.show_satisfied_checkbox.setChecked(False)

        assert "dep.local" in dialog.selected_mods
        assert dialog.checkboxes["dep.local"][0].isChecked()

    def test_all_satisfied_shows_fallback_and_toggle_reveals(
        self, dialog: MissingDependenciesDialog
    ) -> None:
        dialog._deps_summary = _SATISFIED_ONLY_SUMMARY
        dialog._populate_dependencies(_SATISFIED_ONLY_SUMMARY)

        fallback = dialog.findChildren(QLabel, "noMissingDepsLabel")
        assert len(fallback) == 1
        assert "All dependencies are satisfied" in fallback[0].text()
        assert dialog.findChildren(QLabel, "satisfiedDepLabel") == []

        dialog.show_satisfied_checkbox.setChecked(True)

        assert len(dialog.findChildren(QLabel, "satisfiedDepLabel")) == 1
        assert any("active.clean" in text for text in _header_texts(dialog))


_SHARED_DEP_SUMMARY = {
    "active.first": {"satisfied": set(), "local": {"dep.shared"}, "download": set()},
    "active.second": {"satisfied": set(), "local": {"dep.shared"}, "download": set()},
}


def _show(
    dialog: MissingDependenciesDialog,
    summary: dict[str, dict[str, set[str]]],
    ignored: frozenset[tuple[str, str]] = frozenset(),
) -> None:
    dialog._deps_summary = summary
    dialog._ignored = set(ignored)
    dialog._populate_dependencies(summary)


def _ignore_boxes(dialog: MissingDependenciesDialog) -> list[QCheckBox]:
    return dialog.findChildren(QCheckBox, "ignoreDependencyCheckbox")


class TestRepeatedDependencies:
    def test_select_all_ticks_every_copy(
        self, dialog: MissingDependenciesDialog
    ) -> None:
        _show(dialog, _SHARED_DEP_SUMMARY)

        dialog.select_all()

        copies = dialog.checkboxes["dep.shared"]
        assert len(copies) == 2
        assert all(box.isChecked() for box in copies)
        assert dialog.selected_mods == {"dep.shared"}

    def test_copies_follow_each_other(self, dialog: MissingDependenciesDialog) -> None:
        _show(dialog, _SHARED_DEP_SUMMARY)
        first, second = dialog.checkboxes["dep.shared"]

        second.setChecked(True)
        assert first.isChecked()

        first.setChecked(False)
        assert not second.isChecked()
        assert dialog.selected_mods == set()


class TestIgnoreDependency:
    @pytest.fixture(autouse=True)
    def aux_db(self, metadata_controller: MagicMock, tmp_path: Path) -> Path:
        db = tmp_path / "aux.db"
        metadata_controller.settings.aux_db_path = db
        return db

    def test_ignore_saves_and_disables_the_row(
        self, dialog: MissingDependenciesDialog, aux_db: Path
    ) -> None:
        _show(dialog, _LOCAL_DEPS_SUMMARY)
        add_box = dialog.checkboxes["dep.local"][0]
        add_box.setChecked(True)

        _ignore_boxes(dialog)[0].setChecked(True)

        assert load_ignored_dependencies(aux_db) == {("active.mod", "dep.local")}
        assert dialog.ignores_changed
        assert not add_box.isEnabled()
        assert not add_box.isChecked()
        assert dialog.selected_mods == set()

        dialog.select_all()
        assert not add_box.isChecked()

        _ignore_boxes(dialog)[0].setChecked(False)
        assert load_ignored_dependencies(aux_db) == frozenset()
        assert add_box.isEnabled()

    def test_ignoring_one_copy_keeps_the_other_selected(
        self, dialog: MissingDependenciesDialog
    ) -> None:
        _show(dialog, _SHARED_DEP_SUMMARY)
        dialog.select_all()

        _ignore_boxes(dialog)[0].setChecked(True)

        first, second = dialog.checkboxes["dep.shared"]
        assert not first.isChecked()
        assert second.isChecked()
        assert dialog.selected_mods == {"dep.shared"}

    def test_ignored_dependencies_are_hidden_until_shown(
        self, dialog: MissingDependenciesDialog, aux_db: Path
    ) -> None:
        summary = {
            "active.mod": {
                "satisfied": set(),
                "local": {"dep.local"},
                "download": set(),
                "ignored": {"dep.ignored"},
            }
        }
        _show(dialog, summary, frozenset({("active.mod", "dep.ignored")}))
        assert dialog.findChildren(QLabel, "ignoredDepLabel") == []
        assert "(1)" in dialog.show_ignored_checkbox.text()

        dialog.show_ignored_checkbox.setChecked(True)

        labels = dialog.findChildren(QLabel, "ignoredDepLabel")
        assert len(labels) == 1
        assert "dep.ignored" in labels[0].text()
        ignore_box = next(box for box in _ignore_boxes(dialog) if box.isChecked())
        set_dependency_ignored(aux_db, "active.mod", "dep.ignored", True)

        ignore_box.setChecked(False)

        assert load_ignored_dependencies(aux_db) == frozenset()
