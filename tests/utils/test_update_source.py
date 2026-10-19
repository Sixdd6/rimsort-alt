"""The updater reads releases from this fork, not from upstream RimSort."""

from unittest.mock import MagicMock, patch

from app.utils import update_utils
from app.utils.update_utils import UpdateManager


def test_release_check_queries_the_fork() -> None:
    assert update_utils.UPDATE_REPOSITORY == "Sixdd6/rimsort-alt"
    manager = UpdateManager(MagicMock(github_token=""), None, None)
    response = MagicMock()
    response.json.return_value = {"tag_name": "v1.0.0"}

    with patch.object(update_utils.http, "get", return_value=response) as get:
        manager._fetch_release_data()

    assert get.call_args.args[0] == (
        "https://api.github.com/repos/Sixdd6/rimsort-alt/releases/latest"
    )


def test_release_error_links_the_forks_releases_page() -> None:
    manager = UpdateManager(MagicMock(), None, None)

    with patch.object(update_utils.dialogue, "show_warning") as warn:
        manager.show_update_error()

    assert (
        "https://github.com/Sixdd6/rimsort-alt/releases"
        in warn.call_args.kwargs["text"]
    )
