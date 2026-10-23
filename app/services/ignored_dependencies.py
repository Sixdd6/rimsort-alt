"""Per-mod dependencies the user chose to ignore, kept in the aux metadata DB."""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

from loguru import logger
from sqlalchemy import select

from app.controllers.metadata_db_controller import AuxMetadataController
from app.models.metadata.metadata_db import IgnoredDependencyEntry
from app.models.metadata.metadata_structure import AboutXmlMod, ListedMod

# How long to keep an ignore for a mod that is no longer installed
IGNORE_RETENTION = timedelta(days=30)

IgnoredDependencies = frozenset[tuple[str, str]]


def _utc_now() -> datetime:
    # Naive UTC, like SQLite's CURRENT_TIMESTAMP
    return datetime.now(UTC).replace(tzinfo=None)


def ignore_key(mod_package_id: str, dependency_package_id: str) -> tuple[str, str]:
    """
    Build the lookup key for a (mod, dependency) pair.

    :param mod_package_id: Package ID of the mod declaring the dependency.
    :param dependency_package_id: Package ID of the dependency.
    :return: Both package IDs, lowercased.
    """
    return mod_package_id.lower(), dependency_package_id.lower()


def load_ignored_dependencies(db_path: Path) -> IgnoredDependencies:
    """
    Read every ignored (mod, dependency) pair.

    :param db_path: Path to the instance's aux metadata DB.
    :return: Set of keys as built by ``ignore_key``.
    """
    controller = AuxMetadataController.get_or_create_cached_instance(db_path)
    with controller.Session() as session:
        rows = session.execute(
            select(
                IgnoredDependencyEntry.mod_package_id,
                IgnoredDependencyEntry.dependency_package_id,
            )
        )
        return frozenset((mod_id, dep_id) for mod_id, dep_id in rows)


def set_dependency_ignored(
    db_path: Path,
    mod_package_id: str,
    dependency_package_id: str,
    ignored: bool,
) -> None:
    """
    Ignore or stop ignoring one dependency of one mod.

    :param db_path: Path to the instance's aux metadata DB.
    :param mod_package_id: Package ID of the mod declaring the dependency.
    :param dependency_package_id: Package ID of the dependency.
    :param ignored: True to ignore the dependency, False to report it again.
    """
    mod_id, dep_id = ignore_key(mod_package_id, dependency_package_id)
    controller = AuxMetadataController.get_or_create_cached_instance(db_path)
    with controller.Session() as session:
        entry = session.get(IgnoredDependencyEntry, (mod_id, dep_id))
        if ignored and entry is None:
            session.add(
                IgnoredDependencyEntry(
                    mod_package_id=mod_id,
                    dependency_package_id=dep_id,
                    last_seen=_utc_now(),
                )
            )
        elif not ignored and entry is not None:
            session.delete(entry)
        session.commit()
    logger.info(
        f"{'Ignoring' if ignored else 'No longer ignoring'} dependency "
        f"[{dep_id}] of [{mod_id}]"
    )


def prune_ignored_dependencies(
    db_path: Path,
    mods_metadata: Mapping[str, ListedMod],
    now: datetime | None = None,
) -> int:
    """
    Drop ignores that no longer apply.

    An ignore is dropped at once when its mod is installed but no longer
    declares the dependency, and after ``IGNORE_RETENTION`` when its mod is
    no longer installed. The grace period keeps ignores for mods that are
    briefly missing, for example while a mod folder is unavailable.

    :param db_path: Path to the instance's aux metadata DB.
    :param mods_metadata: Metadata of every installed mod.
    :param now: Current naive UTC time, for tests.
    :return: Number of ignores dropped.
    """
    now = now or _utc_now()
    declared: dict[str, set[str]] = {}
    for mod in mods_metadata.values():
        if isinstance(mod, AboutXmlMod) and mod.package_id:
            declared.setdefault(str(mod.package_id).lower(), set()).update(
                str(dep_id).lower() for dep_id in mod.overall_rules.dependencies
            )

    dropped = 0
    controller = AuxMetadataController.get_or_create_cached_instance(db_path)
    with controller.Session() as session:
        for entry in session.scalars(select(IgnoredDependencyEntry)).all():
            dependencies = declared.get(entry.mod_package_id)
            if dependencies is None:
                if now - entry.last_seen > IGNORE_RETENTION:
                    session.delete(entry)
                    dropped += 1
            elif entry.dependency_package_id in dependencies:
                entry.last_seen = now
            else:
                session.delete(entry)
                dropped += 1
        session.commit()
    if dropped:
        logger.info(f"Dropped {dropped} ignored dependencies that no longer apply")
    return dropped
