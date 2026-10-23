from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from app.controllers import menu_bar_controller
from app.controllers.menu_bar_controller import MenuBarController


@pytest.mark.parametrize(
    ("slot", "expected_url"),
    [
        (
            MenuBarController._on_menu_bar_wiki_triggered,
            "https://sixdd6.github.io/rimsort-alt/",
        ),
        (
            MenuBarController._on_menu_bar_github_triggered,
            "https://github.com/Sixdd6/rimsort-alt",
        ),
    ],
)
def test_help_links_open_the_fork(
    monkeypatch: pytest.MonkeyPatch,
    slot: Callable[[MagicMock], None],
    expected_url: str,
) -> None:
    opened = MagicMock()
    monkeypatch.setattr(menu_bar_controller, "open_url_browser", opened)

    slot(MagicMock())

    opened.assert_called_once_with(expected_url)
