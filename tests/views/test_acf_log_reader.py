from typing import Any
from unittest.mock import MagicMock, patch

from app.views.acf_log_reader import AcfLogReader


def _make_reader(qtbot: Any, mock_metadata_controller: MagicMock) -> AcfLogReader:
    mock_metadata_controller.settings = MagicMock()
    reader = AcfLogReader(metadata_controller=mock_metadata_controller)
    qtbot.addWidget(reader)
    return reader


def test_populate_waits_until_shown(
    qtbot: Any, mock_metadata_controller: MagicMock
) -> None:
    reader = _make_reader(qtbot, mock_metadata_controller)

    with patch.object(reader, "_extract_acf_entries", return_value=[]) as extract:
        reader._populate_from_metadata()
        extract.assert_not_called()

        reader.show()
        qtbot.waitExposed(reader)

    extract.assert_called_once()


def test_acf_mods_use_one_bulk_aux_lookup(
    qtbot: Any, mock_metadata_controller: MagicMock
) -> None:
    reader = _make_reader(qtbot, mock_metadata_controller)
    mod = MagicMock()
    mod.published_file_id = "123"
    mod.mod_path = "/mods/ws"
    mod.supported_versions = ["1.6"]
    mod.internal_time_touched = 1
    other = MagicMock()
    other.published_file_id = "999"
    mock_metadata_controller.mods_metadata = {"/mods/ws": mod, "/mods/other": other}
    aux_entry = MagicMock(external_time_updated=42)
    aux_db = mock_metadata_controller.metadata_db_controller
    aux_db.get_many.return_value = {"/mods/ws": aux_entry}

    pfid_to_mod = reader._get_acf_mods_from_metadata({"123"})

    aux_db.get_many.assert_called_once()
    assert aux_db.get_many.call_args.args[1] == ["/mods/ws"]
    assert pfid_to_mod["123"][1]["external_time_updated"] == 42
    mock_metadata_controller.get_metadata_with_path.assert_not_called()
