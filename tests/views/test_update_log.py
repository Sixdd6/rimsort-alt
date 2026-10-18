import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QImage, QPainter

from app.views.mod_table import GROUP_ROLE, GROUP_ROW_HEIGHT, ROW_HEIGHT, STATUS_COLUMN
from app.views.update_log import (
    UpdateBucket,
    UpdateLog,
    bucket_for,
    extract_update_entries,
)
from app.windows.base_mods_panel import ColumnIndex
from tests.image_fixtures import write_png
from tests.mod_fixtures import fake_about_mod

DAY = 86400


def _start_of_today(now: float) -> float:
    local = time.localtime(now)
    return time.mktime((local.tm_year, local.tm_mon, local.tm_mday, 0, 0, 0, 0, 0, -1))


def test_bucket_for_uses_calendar_day_then_a_rolling_week() -> None:
    now = time.time()
    midnight = _start_of_today(now)

    assert bucket_for(int(now) - 60, now) is UpdateBucket.TODAY
    assert bucket_for(int(midnight) + 1, now) is UpdateBucket.TODAY
    assert bucket_for(int(midnight) - 1, now) is UpdateBucket.THIS_WEEK
    assert bucket_for(int(now - 6.9 * DAY), now) is UpdateBucket.THIS_WEEK
    assert bucket_for(int(now - 7 * DAY), now) is UpdateBucket.THIS_MONTH_PLUS
    assert bucket_for(int(now - 400 * DAY), now) is UpdateBucket.THIS_MONTH_PLUS
    assert bucket_for(None, now) is UpdateBucket.UNKNOWN
    assert bucket_for(0, now) is UpdateBucket.UNKNOWN


def _acf(
    details: dict[str, dict[str, str]],
    installed: dict[str, dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "AppWorkshop": {
            "WorkshopItemDetails": details,
            "WorkshopItemsInstalled": installed or {},
        }
    }


def test_extract_update_entries_prefers_steamcmd_and_flags_pending_updates() -> None:
    steamcmd = _acf({"1": {"timeupdated": "100", "latest_timeupdated": "200"}})
    workshop = _acf(
        {
            "1": {"timeupdated": "50", "latest_timeupdated": "50"},
            "2": {"timeupdated": "300", "latest_timeupdated": "300"},
        },
        installed={"3": {"timeupdated": "400"}},
    )

    entries = {
        entry.pfid: entry for entry in extract_update_entries(steamcmd, workshop)
    }

    assert entries["1"].source == "SteamCMD"
    assert entries["1"].time_updated == 100
    assert entries["1"].update_available
    assert entries["2"].source == "Steam"
    assert not entries["2"].update_available
    assert entries["3"].time_updated == 400
    assert entries["3"].latest_time_updated is None
    assert not entries["3"].update_available


_mod = fake_about_mod


def _make_panel(
    qtbot: Any,
    mock_metadata_controller: MagicMock,
    mods: dict[str, MagicMock],
    details: dict[str, dict[str, str]],
    active_paths: list[str],
    show: bool = True,
) -> UpdateLog:
    mock_metadata_controller.settings = MagicMock()
    mock_metadata_controller.mods_metadata = mods
    mock_metadata_controller.get_mod.side_effect = mods.get
    mock_metadata_controller.metadata_db_controller.get_many.return_value = {}
    mock_metadata_controller.workshop_acf_data = _acf(details)
    mock_metadata_controller.steamcmd_acf_data = {}
    active = MagicMock()
    active.paths = active_paths
    panel = UpdateLog(
        metadata_controller=mock_metadata_controller, active_mods_list=active
    )
    qtbot.addWidget(panel)
    panel.resize(900, 600)
    if show:
        panel.show()
        qtbot.waitExposed(panel)
    return panel


def _populate(qtbot: Any, panel: UpdateLog) -> None:
    panel._populate_from_metadata()
    qtbot.waitUntil(lambda: panel.editor_model.rowCount() > 0, timeout=3000)


def _column_texts(panel: UpdateLog, column: int) -> list[str]:
    return [
        panel.editor_model.item(row, column).text()
        for row in range(panel.editor_model.rowCount())
    ]


@pytest.fixture
def panel(qtbot: Any, mock_metadata_controller: MagicMock) -> UpdateLog:
    now = int(time.time())
    mods = {
        "/m/a": _mod("Alpha", "1", "/m/a"),
        "/m/b": _mod("Beta", "2", "/m/b"),
        "/m/c": _mod("Gamma", "3", "/m/c"),
    }
    details = {
        "3": {
            "timeupdated": str(now - 40 * DAY),
            "latest_timeupdated": str(now - 40 * DAY),
        },
        "2": {"timeupdated": str(now - 3 * DAY), "latest_timeupdated": str(now)},
        "1": {"timeupdated": str(now - 600), "latest_timeupdated": str(now - 600)},
    }
    panel = _make_panel(qtbot, mock_metadata_controller, mods, details, ["/m/b"])
    _populate(qtbot, panel)
    return panel


def test_rows_are_grouped_by_recency_newest_first(panel: UpdateLog) -> None:
    names = _column_texts(panel, ColumnIndex.NAME.value)
    assert names == [
        "Today  ·  1",
        "Alpha",
        "This Week  ·  1",
        "Beta",
        "This Month+  ·  1",
        "Gamma",
    ]
    model = panel.editor_model
    assert [bool(model.item(r, 1).data(GROUP_ROLE)) for r in range(6)] == [
        True,
        False,
        True,
        False,
        True,
        False,
    ]
    view = panel.editor_table_view
    assert view.rowHeight(0) == GROUP_ROW_HEIGHT
    assert view.rowHeight(1) == ROW_HEIGHT
    assert view.columnSpan(0, 0) == model.columnCount()


def test_status_column_flags_pending_updates_and_active_mods(panel: UpdateLog) -> None:
    status = _column_texts(panel, STATUS_COLUMN)
    assert status[1] == ""
    assert status[3] == "Update available, Active"
    assert status[5] == ""
    assert panel.editor_model.item(1, ColumnIndex.PUBLISHED_FILE_ID.value).text() == "1"
    assert panel.editor_model.item(1, 1).data(Qt.ItemDataRole.UserRole) == "/m/a"


def test_rows_have_no_per_row_widgets_and_select_all_uses_check_states(
    panel: UpdateLog,
) -> None:
    model = panel.editor_model
    view = panel.editor_table_view
    assert view.indexWidget(model.index(1, 0)) is None
    assert view.indexWidget(model.index(1, ColumnIndex.WORKSHOP_PAGE.value)) is None
    assert model.item(1, 0).isCheckable()
    assert not model.item(0, 0).isCheckable()

    panel._set_all_checkbox_rows(True)
    assert panel._get_selected_row_indices() == {1, 3, 5}
    panel._set_all_checkbox_rows(False)
    assert panel._get_selected_row_indices() == set()


def test_clicking_the_workshop_cell_opens_the_page(
    panel: UpdateLog, qtbot: Any
) -> None:
    view = panel.editor_table_view
    index = panel.editor_model.index(1, ColumnIndex.WORKSHOP_PAGE.value)
    assert index.data() == "https://steamcommunity.com/sharedfiles/filedetails/?id=1"
    with patch("app.views.mod_table.platform_specific_open") as opener:
        qtbot.mouseClick(
            view.viewport(),
            Qt.MouseButton.LeftButton,
            pos=view.visualRect(index).center(),
        )
    opener.assert_called_once_with(index.data())


def test_noisy_columns_are_hidden_and_visible_order_is_readable(
    panel: UpdateLog,
) -> None:
    view = panel.editor_table_view
    header = view.horizontalHeader()
    for column in UpdateLog.HIDDEN_COLUMNS:
        assert view.isColumnHidden(column)
    visible = [
        header.logicalIndex(pos)
        for pos in range(header.count())
        if not view.isColumnHidden(header.logicalIndex(pos))
    ]
    assert visible == list(UpdateLog.VISIBLE_ORDER)
    assert panel.ui_elements.editor_cancel_button.isHidden()
    assert panel.persistent_view is True


def test_search_hides_rows_and_groups_left_empty(panel: UpdateLog) -> None:
    panel.apply_search_filter("gam")

    hidden = [panel.editor_table_view.isRowHidden(r) for r in range(6)]
    assert hidden == [True, True, True, True, False, False]

    panel.apply_search_filter("")
    assert not any(panel.editor_table_view.isRowHidden(r) for r in range(6))


def test_populate_waits_until_shown(
    qtbot: Any, mock_metadata_controller: MagicMock
) -> None:
    now = int(time.time())
    mods = {"/m/a": _mod("Alpha", "1", "/m/a")}
    details = {"1": {"timeupdated": str(now), "latest_timeupdated": str(now)}}
    panel = _make_panel(qtbot, mock_metadata_controller, mods, details, [], show=False)

    panel._populate_from_metadata()
    qtbot.wait(30)
    assert panel.editor_model.rowCount() == 0

    panel.show()
    qtbot.waitExposed(panel)
    qtbot.waitUntil(lambda: panel.editor_model.rowCount() == 2, timeout=3000)


def _many_mods_with_previews(
    tmp_path: Path, count: int = 80
) -> tuple[dict[str, MagicMock], dict[str, dict[str, str]]]:
    """``count`` mods named ``Mod 00``.. with a Preview.png each, newest first."""
    now = int(time.time())
    mods: dict[str, MagicMock] = {}
    details: dict[str, dict[str, str]] = {}
    for i in range(count):
        preview = write_png(tmp_path / f"m{i}" / "About" / "Preview.png", 32, 32)
        mods[f"/m/{i}"] = _mod(f"Mod {i:02d}", str(i), f"/m/{i}", preview)
        details[str(i)] = {"timeupdated": str(now - i), "latest_timeupdated": str(now)}
    return mods, details


def test_thumbnails_load_lazily_for_rows_near_the_viewport(
    qtbot: Any, mock_metadata_controller: MagicMock, tmp_path: Path
) -> None:
    mods, details = _many_mods_with_previews(tmp_path)
    panel = _make_panel(qtbot, mock_metadata_controller, mods, details, [])
    requested: list[str] = []
    real_load = panel._thumbnails._thumbnail_loader.load

    def tracking_load(path: str) -> QImage | None:
        requested.append(path)
        return real_load(path)

    with patch.object(
        panel._thumbnails._thumbnail_loader, "load", side_effect=tracking_load
    ):
        _populate(qtbot, panel)
        qtbot.waitUntil(lambda: len(requested) > 0, timeout=3000)
        first_batch = len(requested)
        assert 0 < first_batch < 80

        def decorated() -> int:
            return sum(
                1
                for row in range(panel.editor_model.rowCount())
                if panel.editor_model.item(row, 1).data(Qt.ItemDataRole.DecorationRole)
            )

        qtbot.waitUntil(lambda: decorated() >= first_batch, timeout=5000)

        scrollbar = panel.editor_table_view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
        qtbot.waitUntil(lambda: len(requested) > first_batch, timeout=3000)
    last = panel.editor_model.item(panel.editor_model.rowCount() - 1, 1)
    qtbot.waitUntil(
        lambda: last.data(Qt.ItemDataRole.DecorationRole) is not None, timeout=5000
    )


def test_filtered_rows_get_thumbnails_even_when_far_apart(
    qtbot: Any, mock_metadata_controller: MagicMock, tmp_path: Path
) -> None:
    mods, details = _many_mods_with_previews(tmp_path)
    panel = _make_panel(qtbot, mock_metadata_controller, mods, details, [])
    _populate(qtbot, panel)
    requested: list[str] = []
    with patch.object(
        panel._thumbnails._thumbnail_loader, "load", side_effect=requested.append
    ):
        # "Mod 70".."Mod 79": matches sit far down a table that scrolls
        panel.apply_search_filter("Mod 7")
        qtbot.waitUntil(lambda: len(requested) >= 10, timeout=3000)

    wanted = {mods[f"/m/{i}"].preview_img_path for i in (70, 71, 75, 79)}
    assert {Path(p) for p in requested} >= wanted


def test_mods_for_pfids_uses_one_bulk_aux_lookup(
    qtbot: Any, mock_metadata_controller: MagicMock
) -> None:
    mods = {"/m/a": _mod("Alpha", "1", "/m/a"), "/m/z": _mod("Zeta", "9", "/m/z")}
    panel = _make_panel(qtbot, mock_metadata_controller, mods, {}, [], show=False)
    aux_db = mock_metadata_controller.metadata_db_controller
    aux_db.get_many.return_value = {"/m/a": MagicMock(external_time_updated=42)}

    result = panel._get_mods_for_pfids({"1"})

    aux_db.get_many.assert_called_once()
    assert aux_db.get_many.call_args.args[1] == ["/m/a"]
    assert result["1"]["external_time_updated"] == 42
    assert "9" not in result


def test_delegate_paints_without_a_focus_frame(panel: UpdateLog) -> None:
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

    delegate = panel.editor_table_view.itemDelegate()
    seen: list[QStyleOptionViewItem] = []
    original = QStyledItemDelegate.paint

    def spy(self: Any, painter: Any, option: QStyleOptionViewItem, index: Any) -> None:
        seen.append(QStyleOptionViewItem(option))
        original(self, painter, option, index)

    option = QStyleOptionViewItem()
    option.state = QStyle.StateFlag.State_HasFocus | QStyle.StateFlag.State_Enabled
    option.rect = panel.editor_table_view.visualRect(panel.editor_model.index(1, 0))
    pixmap = QPixmap(60, 60)
    painter = QPainter(pixmap)
    with patch.object(QStyledItemDelegate, "paint", spy):
        delegate.paint(painter, option, panel.editor_model.index(1, 0))
    painter.end()

    assert seen and not (seen[0].state & QStyle.StateFlag.State_HasFocus)


def test_preview_popup_sits_beside_the_cell_and_flips_when_cramped() -> None:
    from PySide6.QtCore import QRect, QSize

    from app.views.mod_table import preview_popup_position

    screen = QRect(0, 0, 1920, 1080)
    cell = QRect(100, 500, 600, 80)
    pos = preview_popup_position(cell, QSize(400, 300), screen)
    assert pos.x() == cell.right() + 12
    assert pos.y() == cell.center().y() - 150

    cramped_cell = QRect(1400, 1000, 500, 80)
    pos = preview_popup_position(cramped_cell, QSize(400, 300), screen)
    assert pos.x() == 1400 - 12 - 400
    assert pos.y() == 1080 - 300


def _hover(view: Any, pos: Any) -> None:
    """Deliver a mouse-move straight to the viewport, independent of the cursor."""
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    event = QMouseEvent(
        QEvent.Type.MouseMove,
        QPointF(pos),
        QPointF(pos),
        QPointF(view.viewport().mapToGlobal(pos)),
        Qt.MouseButton.NoButton,
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    )
    QApplication.sendEvent(view.viewport(), event)


def test_hovering_a_mod_shows_its_preview_beside_the_row(
    qtbot: Any, mock_metadata_controller: MagicMock, tmp_path: Path
) -> None:
    from app.views.mod_table import IDENTIFIERS_ROLE

    mods, details = _many_mods_with_previews(tmp_path, count=3)
    panel = _make_panel(qtbot, mock_metadata_controller, mods, details, [])
    # Narrow enough that the popup fits to the right on the offscreen screen
    panel.resize(600, 400)
    _populate(qtbot, panel)
    qtbot.wait(50)
    view = panel.editor_table_view
    name_index = panel.editor_model.index(1, ColumnIndex.NAME.value)
    assert panel.editor_model.item(1, 1).data(IDENTIFIERS_ROLE)[1].endswith(": 0")

    _hover(view, view.visualRect(name_index).center())
    qtbot.waitUntil(lambda: panel._thumbnails.popup.isVisible(), timeout=3000)
    qtbot.waitUntil(
        lambda: panel._thumbnails.popup.image.pixmap().width() == 32, timeout=3000
    )
    assert "Published File ID: 0" in panel._thumbnails.popup.text.text()
    cell_right = view.viewport().mapToGlobal(view.visualRect(name_index).topRight())
    assert panel._thumbnails.popup.x() > cell_right.x()

    group_index = panel.editor_model.index(0, ColumnIndex.NAME.value)
    _hover(view, view.visualRect(group_index).center())
    qtbot.waitUntil(lambda: not panel._thumbnails.popup.isVisible(), timeout=3000)


def test_every_theme_styles_the_preview_popup(panel: UpdateLog) -> None:
    assert panel._thumbnails.popup.objectName() == "updateLogPreviewPopup"
    themes = sorted(Path("themes").glob("*/style.qss"))
    assert themes
    for theme in themes:
        assert "QFrame#updateLogPreviewPopup" in theme.read_text(encoding="utf-8"), (
            theme
        )
