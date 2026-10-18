"""
Use This Instead panel: installed Workshop mods that the "Use This Instead"
database says have a newer replacement, grouped by replacement, with a
one-click Replace that swaps the replacement into the active list.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from loguru import logger
from PySide6.QtCore import QCoreApplication, Qt, Signal
from PySide6.QtGui import QColor, QHideEvent, QPalette, QShowEvent, QStandardItem
from PySide6.QtWidgets import QLabel, QPushButton

from app.controllers.metadata_controller import MetadataController
from app.models.metadata.metadata_structure import (
    AboutXmlMod,
    ListedMod,
    ReplacementInfo,
)
from app.utils.button_factory import ButtonConfig, ButtonType
from app.utils.mod_info import ModInfo
from app.views.mod_table import (
    ACTIVE_COLOR,
    ACTIVE_ROLE,
    IDENTIFIERS_ROLE,
    STATUS_COLUMN,
    THUMBNAIL_PATH_ROLE,
    ModTableDelegate,
    ModTableThumbnails,
    add_group_row,
    append_mod_row,
    configure_mod_table,
    identifier_lines,
    mod_table_columns,
    row_is_checked,
    set_rows_checked,
)
from app.windows.base_mods_panel import BaseModsPanel, ColumnIndex, UIElements


@dataclass
class ReplacementGroup:
    """One suggested replacement and the installed mods it supersedes."""

    replacement: ReplacementInfo
    replacement_path: str | None
    originals: list[str]

    @property
    def installed(self) -> bool:
        return self.replacement_path is not None


@dataclass
class ReplacementRequest:
    """What the Replace action asks the main panel to do for one group.

    The originals are deactivated, never deleted. When the replacement is not
    installed yet, it is downloaded first and swapped in once it has landed.
    """

    original_paths: list[str]
    replacement_pfid: str
    replacement_path: str | None


def build_replacement_groups(
    mods_metadata: dict[str, ListedMod], metadata_controller: MetadataController
) -> list[ReplacementGroup]:
    """Group installed mods by the replacement the database suggests for them.

    :param mods_metadata: All known mods keyed by path.
    :param metadata_controller: Supplies the Use This Instead lookup.
    :return: Groups ordered by replacement name.
    """
    path_by_pfid: dict[str, str] = {}
    for path, mod in mods_metadata.items():
        if mod.published_file_id:
            path_by_pfid.setdefault(mod.published_file_id, path)
    groups: dict[str, ReplacementGroup] = {}
    for path in mods_metadata:
        replacement = metadata_controller.has_alternative_mod(path)
        if replacement is None or not replacement.pfid:
            continue
        group = groups.get(replacement.pfid)
        if group is None:
            group = ReplacementGroup(
                replacement=replacement,
                replacement_path=path_by_pfid.get(replacement.pfid),
                originals=[],
            )
            groups[replacement.pfid] = group
        group.originals.append(path)
    return sorted(groups.values(), key=lambda g: g.replacement.name.lower())


class UseThisInsteadPanel(BaseModsPanel):
    """
    Replacements found for installed Workshop mods, one band per replacement.

    Each band lists the original mod(s) followed by the suggested replacement,
    with Status showing whether each is active, installed or not installed.
    Replace swaps an installed replacement into the active list where the
    original sat (downloading it first if needed) and deactivates the original.
    """

    replace_requested = Signal(list)

    HIDDEN_COLUMNS = (
        ColumnIndex.AUTHOR.value,
        ColumnIndex.PACKAGE_ID.value,
        ColumnIndex.PUBLISHED_FILE_ID.value,
        ColumnIndex.MOD_DOWNLOADED.value,
        ColumnIndex.UPDATED_ON_WORKSHOP.value,
        ColumnIndex.PATH.value,
    )
    VISIBLE_ORDER = (
        ColumnIndex.CHECKBOX.value,
        ColumnIndex.NAME.value,
        STATUS_COLUMN,
        ColumnIndex.SUPPORTED_VERSIONS.value,
        ColumnIndex.SOURCE.value,
        ColumnIndex.WORKSHOP_PAGE.value,
    )

    def __init__(
        self,
        mod_metadata: dict[str, Any],
        metadata_controller: MetadataController,
        active_mod_paths: Iterable[str] = (),
    ) -> None:
        """
        :param mod_metadata: All known mods keyed by path.
        :param metadata_controller: Supplies the Use This Instead lookup.
        :param active_mod_paths: Paths of the mods currently in the active list.
        """
        logger.debug("Initializing UseThisInsteadPanel")
        self.mod_metadata = mod_metadata
        self._active_paths = set(active_mod_paths)
        self._groups: list[ReplacementGroup] = []
        # Row index -> group index, for originals and replacements respectively
        self._original_rows: dict[int, int] = {}
        self._replacement_rows: dict[int, int] = {}

        super().__init__(
            object_name="useThisInsteadModsPanel",
            window_title=self.tr("RimSort - Replacements found for Workshop mods"),
            title_text=self.tr("Replacements are available for some of your mods"),
            details_text=self.tr(
                'Each group shows an original mod and the replacement the "Use This '
                'Instead" database recommends. Replace swaps the replacement into your '
                "active list where the original was, downloading it first if needed; "
                "originals are only deactivated, never deleted."
            ),
            additional_columns=mod_table_columns(),
            metadata_controller=metadata_controller,
        )
        self.ui_elements.editor_cancel_button.setText(self.tr("Close"))

        steam_client_integration_enabled = self._get_steam_client_integration_enabled()
        button_configs = list(self._get_base_button_configs())
        if steam_client_integration_enabled:
            button_configs.append(
                ButtonConfig(
                    button_type=ButtonType.STEAM,
                    pfid_column=ColumnIndex.PUBLISHED_FILE_ID.value,
                ),
            )
        button_configs.append(
            self._create_delete_button_config(
                self.tr("Delete Selected Mods"),
                enable_delete_and_unsubscribe=steam_client_integration_enabled,
            )
        )
        self._setup_buttons_from_config(button_configs)
        self.replace_button = self.get_button_factory().create_dropdown_button(
            self.tr("Replace"),
            "actionButton",
            [
                (self.tr("Replace selected groups"), self._replace_selected),
                (self.tr("Replace all groups"), self._replace_all),
            ],
        )
        self.layouts.editor_main_actions_layout.addWidget(self.replace_button)

        configure_mod_table(
            self.editor_table_view, self.HIDDEN_COLUMNS, self.VISIBLE_ORDER
        )
        self.editor_table_view.setItemDelegate(ModTableDelegate(self))
        self._thumbnails = ModTableThumbnails(
            self, self.editor_table_view, self.editor_model
        )

    # ------------------------------------------------------------------ setup
    def _initialize_ui_elements(self) -> None:
        """Initialize UI elements with custom select button."""
        self.ui_elements = UIElements(
            title=QLabel(),
            details_label=QLabel(),
            editor_select_all_button=self._create_custom_select_button(),
            editor_cancel_button=QPushButton(self.tr("Close")),
        )

    def _create_custom_select_button(self) -> QPushButton:
        """Create the select button with Originals/Replacements dropdown."""
        factory = self.get_button_factory()
        return factory.create_dropdown_button(
            QCoreApplication.translate("UseThisInsteadPanel", "Select"),
            "actionButton",
            [
                (
                    QCoreApplication.translate(
                        "UseThisInsteadPanel", "Select all Originals"
                    ),
                    self._select_all_originals,
                ),
                (
                    QCoreApplication.translate(
                        "UseThisInsteadPanel", "Select all Replacements"
                    ),
                    self._select_all_replacements,
                ),
            ],
        )

    def _row_is_checked(self, row: int) -> bool:
        return row_is_checked(self.editor_model, row)

    def _set_all_checkbox_rows(self, value: bool) -> None:
        set_rows_checked(self.editor_model, lambda _row: value)

    def _select_all_originals(self) -> None:
        set_rows_checked(self.editor_model, lambda row: row in self._original_rows)

    def _select_all_replacements(self) -> None:
        set_rows_checked(self.editor_model, lambda row: row in self._replacement_rows)

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        self._thumbnails.schedule()

    def hideEvent(self, event: QHideEvent) -> None:
        self._thumbnails.hide_popup()
        super().hideEvent(event)

    # ------------------------------------------------------------- population
    def show_if_has_alternatives(self) -> bool:
        """Populate the panel and show it if alternatives exist.

        :return: True if alternatives were found and the panel was shown.
        """
        self._populate_from_metadata()
        if self.editor_model.rowCount() > 0:
            self.showNormal()
            return True
        return False

    def _populate_from_metadata(self) -> None:
        """Fill the table with one band per replacement."""
        try:
            self._groups = build_replacement_groups(
                self.mod_metadata, self.metadata_controller
            )
        except Exception as e:
            logger.error(f"Error collecting replacements: {e}")
            self._groups = []
        self._thumbnails.reset()
        self.editor_table_view.setUpdatesEnabled(False)
        try:
            self._clear_table_model()
            self.editor_table_view.clearSpans()
            self._original_rows = {}
            self._replacement_rows = {}
            for group_index, group in enumerate(self._groups):
                add_group_row(
                    self.editor_model,
                    self.editor_table_view,
                    self.tr("{name} by {author}  ·  replaces {count}").format(
                        name=group.replacement.name,
                        author=group.replacement.author,
                        count=len(group.originals),
                    ),
                )
                for original in group.originals:
                    self._add_original_row(original)
                    self._original_rows[self.editor_model.rowCount() - 1] = group_index
                self._add_replacement_row(group)
                self._replacement_rows[self.editor_model.rowCount() - 1] = group_index
        finally:
            self.editor_table_view.setUpdatesEnabled(True)
        self._thumbnails.schedule()

    def _add_original_row(self, path: str) -> None:
        mod = self.mod_metadata.get(path)
        if mod is None:
            return
        active = path in self._active_paths
        role = self.tr("Original")
        status = f"{role} · {self.tr('Active')}" if active else role
        self._add_mod_row_items(
            key=path,
            name=mod.name,
            authors=", ".join(mod.authors) if isinstance(mod, AboutXmlMod) else "",
            package_id=str(mod.package_id) if isinstance(mod, AboutXmlMod) else "",
            pfid=mod.published_file_id or "",
            versions=ModInfo._parse_supported_versions_static(mod.supported_versions),
            source=self.tr("Installed"),
            path=str(mod.mod_path) if mod.mod_path else "",
            preview=str(mod.preview_img_path)
            if isinstance(mod, AboutXmlMod) and mod.preview_img_path
            else "",
            active=active,
            status=status,
            status_colour=ACTIVE_COLOR if active else None,
        )

    def _add_replacement_row(self, group: ReplacementGroup) -> None:
        replacement = group.replacement
        installed = self.mod_metadata.get(group.replacement_path or "")
        active = group.replacement_path in self._active_paths
        role = self.tr("Replacement")
        if active:
            status, colour = f"{role} · {self.tr('Active')}", ACTIVE_COLOR
        elif installed is not None:
            status, colour = f"{role} · {self.tr('Installed')}", None
        else:
            status, colour = (
                f"{role} · {self.tr('Not installed')}",
                self.palette().color(QPalette.ColorRole.Highlight),
            )
        if installed is not None:
            name = installed.name
            authors = (
                ", ".join(installed.authors)
                if isinstance(installed, AboutXmlMod)
                else ""
            )
            versions = ModInfo._parse_supported_versions_static(
                installed.supported_versions
            )
            path = str(installed.mod_path) if installed.mod_path else ""
            preview = (
                str(installed.preview_img_path)
                if isinstance(installed, AboutXmlMod) and installed.preview_img_path
                else ""
            )
        else:
            name, authors, path, preview = replacement.name, replacement.author, "", ""
            versions = ModInfo._parse_supported_versions_static(
                replacement.supportedversions
            )
        self._add_mod_row_items(
            key=group.replacement_path,
            name=name,
            authors=authors,
            package_id=replacement.packageid,
            pfid=replacement.pfid,
            versions=versions,
            source=self.tr("Workshop"),
            path=path,
            preview=preview,
            active=active,
            status=status,
            status_colour=colour,
        )

    def _add_mod_row_items(
        self,
        *,
        key: str | None,
        name: str,
        authors: str,
        package_id: str,
        pfid: str,
        versions: str,
        source: str,
        path: str,
        preview: str,
        active: bool,
        status: str,
        status_colour: QColor | None,
    ) -> None:
        name_item = QStandardItem(name)
        if key:
            name_item.setData(key, Qt.ItemDataRole.UserRole)
        if preview:
            name_item.setData(preview, THUMBNAIL_PATH_ROLE)
        name_item.setData(active, ACTIVE_ROLE)
        name_item.setData(identifier_lines(package_id, pfid, path), IDENTIFIERS_ROLE)
        status_item = QStandardItem(status)
        if status_colour is not None:
            status_item.setForeground(status_colour)
        row = append_mod_row(
            self.editor_model,
            name_item=name_item,
            authors=authors,
            package_id=package_id,
            pfid=pfid,
            versions=versions,
            source=source,
            path=path,
            workshop_url=ModInfo._generate_workshop_url(pfid) if pfid else "",
            status_item=status_item,
        )
        if preview:
            self._thumbnails.register_row(preview, row)

    # ---------------------------------------------------------------- replace
    def _selected_group_indices(self) -> set[int]:
        rows = {**self._original_rows, **self._replacement_rows}
        return {
            group_index
            for row, group_index in rows.items()
            if row_is_checked(self.editor_model, row)
        }

    def _replace_selected(self) -> None:
        self._emit_replace(self._selected_group_indices())

    def _replace_all(self) -> None:
        self._emit_replace(set(range(len(self._groups))))

    def _emit_replace(self, group_indices: set[int]) -> None:
        requests = [
            ReplacementRequest(
                original_paths=list(group.originals),
                replacement_pfid=group.replacement.pfid,
                replacement_path=group.replacement_path,
            )
            for index, group in enumerate(self._groups)
            if index in group_indices
        ]
        if not requests:
            return
        self.replace_requested.emit(requests)
        self.close()


__all__ = [
    "ReplacementGroup",
    "ReplacementRequest",
    "UseThisInsteadPanel",
    "build_replacement_groups",
]
