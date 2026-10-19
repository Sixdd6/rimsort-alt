"""The fork is shown as RimSort Alt."""

from unittest.mock import MagicMock

from app.services.import_export_service import ImportExportService
from app.utils.constants import APP_DISPLAY_NAME
from app.views import dialogue


def test_display_name_sets_the_fork_apart() -> None:
    assert APP_DISPLAY_NAME == "RimSort Alt"
    assert dialogue.DEFAULT_TITLE == APP_DISPLAY_NAME


def test_exported_report_names_the_fork() -> None:
    metadata = MagicMock()
    metadata.game_version = "1.6"
    service = ImportExportService(metadata, MagicMock())

    report = service.build_clipboard_report([], {})

    assert report.startswith("Created with RimSort Alt ")
