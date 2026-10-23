from datetime import UTC, datetime
from pathlib import Path

from app.models.metadata.metadata_structure import (
    AboutXmlMod,
    CaseInsensitiveStr,
    DependencyMod,
    ListedMod,
)
from app.services.ignored_dependencies import (
    IGNORE_RETENTION,
    ignore_key,
    load_ignored_dependencies,
    prune_ignored_dependencies,
    set_dependency_ignored,
)

_NOW = datetime.now(UTC).replace(tzinfo=None)


def _mod(package_id: str, *dependencies: str) -> AboutXmlMod:
    mod = AboutXmlMod(package_id=CaseInsensitiveStr(package_id))
    mod.about_rules.dependencies = {
        CaseInsensitiveStr(dep): DependencyMod(package_id=CaseInsensitiveStr(dep))
        for dep in dependencies
    }
    return mod


def test_ignore_and_unignore_round_trip(tmp_path: Path) -> None:
    db = tmp_path / "aux.db"
    assert load_ignored_dependencies(db) == frozenset()

    set_dependency_ignored(db, "Author.Mod", "Author.Dep", True)
    set_dependency_ignored(db, "author.mod", "author.dep", True)
    assert load_ignored_dependencies(db) == {ignore_key("author.mod", "author.dep")}

    set_dependency_ignored(db, "AUTHOR.MOD", "AUTHOR.DEP", False)
    assert load_ignored_dependencies(db) == frozenset()


def test_prune_drops_dependencies_the_mod_no_longer_declares(tmp_path: Path) -> None:
    db = tmp_path / "aux.db"
    set_dependency_ignored(db, "author.mod", "author.kept", True)
    set_dependency_ignored(db, "author.mod", "author.dropped", True)
    mods: dict[str, ListedMod] = {"/mods/mod": _mod("author.mod", "Author.Kept")}

    assert prune_ignored_dependencies(db, mods, now=_NOW) == 1
    assert load_ignored_dependencies(db) == {("author.mod", "author.kept")}


def test_prune_keeps_missing_mods_for_the_retention_period(tmp_path: Path) -> None:
    db = tmp_path / "aux.db"
    ignored_at = datetime.now(UTC).replace(tzinfo=None)
    set_dependency_ignored(db, "author.gone", "author.dep", True)
    set_dependency_ignored(db, "author.mod", "author.dep", True)
    mods: dict[str, ListedMod] = {"/mods/mod": _mod("author.mod", "author.dep")}

    assert (
        prune_ignored_dependencies(db, {}, now=ignored_at + IGNORE_RETENTION / 2) == 0
    )
    assert len(load_ignored_dependencies(db)) == 2

    # Only the mod that is no longer installed expires
    later = ignored_at + IGNORE_RETENTION * 2
    assert prune_ignored_dependencies(db, mods, now=later) == 1
    assert load_ignored_dependencies(db) == {("author.mod", "author.dep")}
