from unittest.mock import MagicMock, patch

import pytest

from app.views.main_content_panel import MainContent


def _mod(path: str) -> MagicMock:
    mod = MagicMock()
    mod.mod_path = path
    return mod


@pytest.fixture
def sort_context(
    main_content: tuple[MainContent, list[bool]], monkeypatch: pytest.MonkeyPatch
) -> tuple[MainContent, MagicMock]:
    mc, _calls = main_content
    monkeypatch.setattr(
        mc.metadata_controller,
        "mods_metadata",
        {path: _mod(path) for path in ("/m/a", "/m/b", "/m/inactive")},
    )
    mc.mods_panel.active_mods_list.paths = ["/m/a", "/m/b"]
    insert = MagicMock()
    monkeypatch.setattr(mc, "_insert_data_into_lists", insert)
    return mc, insert


def _sort_returning(mc: MainContent, new_order: list[str]) -> None:
    with patch("app.views.main_content_panel.Sorter") as sorter:
        sorter.return_value.sort.return_value = (True, new_order)
        mc._do_sort(check_deps=False)


def test_sort_skips_reinsert_when_order_is_unchanged(
    sort_context: tuple[MainContent, MagicMock],
) -> None:
    mc, insert = sort_context

    _sort_returning(mc, ["/m/a", "/m/b"])

    insert.assert_not_called()


def test_sort_reinserts_when_order_changes(
    sort_context: tuple[MainContent, MagicMock],
) -> None:
    mc, insert = sort_context

    _sort_returning(mc, ["/m/b", "/m/a"])

    insert.assert_called_once_with(
        ["/m/b", "/m/a"], ["/m/inactive"], skip_unchanged_inactive=True
    )
