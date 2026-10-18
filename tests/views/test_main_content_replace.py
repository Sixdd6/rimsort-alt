from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.models.metadata.metadata_structure import ModType
from app.views.main_content_panel import MainContent
from app.windows.use_this_instead_panel import ReplacementRequest


def _mod(pfid: str | None = None) -> MagicMock:
    mod = MagicMock()
    mod.published_file_id = pfid
    return mod


@pytest.fixture
def content(
    main_content: tuple[MainContent, list[bool]], monkeypatch: pytest.MonkeyPatch
) -> tuple[MainContent, MagicMock]:
    mc, _calls = main_content
    monkeypatch.setattr(
        mc.metadata_controller,
        "mods_metadata",
        {"/m/a": _mod(), "/m/b": _mod(), "/m/c": _mod(), "/m/r": _mod("9")},
    )
    mc.mods_panel.active_mods_list.paths = ["/m/a", "/m/b", "/m/c"]
    insert = MagicMock()
    monkeypatch.setattr(mc, "_insert_data_into_lists", insert)
    return mc, insert


def test_replacement_takes_the_originals_place(
    content: tuple[MainContent, Any],
) -> None:
    mc, insert = content
    mc._swap_active_mods({"/m/b": "/m/r"})
    insert.assert_called_once_with(["/m/a", "/m/r", "/m/c"], ["/m/b"])


def test_one_replacement_for_two_originals_is_placed_once(
    content: tuple[MainContent, Any],
) -> None:
    mc, insert = content
    mc._swap_active_mods({"/m/a": "/m/r", "/m/c": "/m/r"})
    insert.assert_called_once_with(["/m/r", "/m/b"], ["/m/a", "/m/c"])


def test_already_active_replacement_is_not_duplicated(
    content: tuple[MainContent, Any],
) -> None:
    mc, insert = content
    mc.mods_panel.active_mods_list.paths = ["/m/a", "/m/r", "/m/b"]
    mc._swap_active_mods({"/m/b": "/m/r"})
    insert.assert_called_once_with(["/m/a", "/m/r"], ["/m/b", "/m/c"])


def test_inactive_original_leaves_the_list_untouched(
    content: tuple[MainContent, Any],
) -> None:
    mc, insert = content
    mc.mods_panel.active_mods_list.paths = ["/m/a"]
    mc._swap_active_mods({"/m/b": "/m/r"})
    insert.assert_not_called()


def test_uninstalled_replacement_is_downloaded_then_swapped_after_refresh(
    content: tuple[MainContent, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    mc, insert = content
    download = MagicMock()
    monkeypatch.setattr(mc, "_do_download_mods_with_steamcmd", download)

    mc._apply_replacements(
        [
            ReplacementRequest(["/m/b"], "77", None),
            ReplacementRequest(["/m/c"], "9", "/m/r"),
        ]
    )

    download.assert_called_once_with(["77"])
    insert.assert_called_once_with(["/m/a", "/m/b", "/m/r"], ["/m/c"])
    assert mc._pending_replacements == {"77": ["/m/b"]}

    insert.reset_mock()
    mc.mods_panel.active_mods_list.paths = ["/m/a", "/m/b", "/m/r"]
    mc.metadata_controller.mods_metadata["/m/new"] = _mod("77")
    mc._apply_pending_replacements()

    insert.assert_called_once_with(["/m/a", "/m/new", "/m/r"], ["/m/b", "/m/c"])
    assert mc._pending_replacements == {}


def test_delete_setting_removes_originals_after_the_swap(
    content: tuple[MainContent, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mc, insert = content
    mc.settings.use_this_instead_delete_replaced = True
    original_dir = tmp_path / "orig"
    (original_dir / "About").mkdir(parents=True)
    original = mc.metadata_controller.mods_metadata["/m/b"]
    original.mod_path = original_dir
    original.published_file_id = "1372003680"
    original.mod_type = ModType.STEAM_WORKSHOP
    original.name = "Replace Stuff"
    mc.settings.instances[mc.settings.current_instance].steam_client_integration = True
    steamworks = MagicMock()
    monkeypatch.setattr(mc, "_do_steamworks_api_call_animated", steamworks)

    mc._apply_replacements([ReplacementRequest(["/m/b"], "9", "/m/r")])

    assert not original_dir.exists()
    metadata: MagicMock = mc.metadata_controller  # type: ignore[assignment]
    metadata.delete_mod.assert_called_once_with(Path("/m/b"))
    steamworks.assert_called_once_with(["unsubscribe", ["1372003680"]])
    # swap first, then the rebuild without the deleted original
    assert insert.call_args_list[0].args == (["/m/a", "/m/r", "/m/c"], ["/m/b"])
    assert insert.call_count == 2


def test_delete_setting_off_keeps_originals(
    content: tuple[MainContent, Any], tmp_path: Path
) -> None:
    mc, insert = content
    mc.settings.use_this_instead_delete_replaced = False
    original_dir = tmp_path / "orig"
    original_dir.mkdir()
    mc.metadata_controller.mods_metadata["/m/b"].mod_path = original_dir

    mc._apply_replacements([ReplacementRequest(["/m/b"], "9", "/m/r")])

    assert original_dir.exists()
    metadata: MagicMock = mc.metadata_controller  # type: ignore[assignment]
    metadata.delete_mod.assert_not_called()
    assert insert.call_count == 1


def test_workshop_original_without_steam_integration_warns(
    content: tuple[MainContent, Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    mc, _insert = content
    mc.settings.use_this_instead_delete_replaced = True
    original_dir = tmp_path / "orig"
    original_dir.mkdir()
    original = mc.metadata_controller.mods_metadata["/m/b"]
    original.mod_path = original_dir
    original.published_file_id = "5"
    original.mod_type = ModType.STEAM_WORKSHOP
    mc.settings.instances[mc.settings.current_instance].steam_client_integration = False
    warn = MagicMock()
    monkeypatch.setattr("app.views.main_content_panel.dialogue.show_warning", warn)

    mc._delete_replaced_originals(["/m/b"])

    assert not original_dir.exists()
    warn.assert_called_once()
