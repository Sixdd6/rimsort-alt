from pathlib import Path
from typing import Any

from app.utils.xml import xml_path_to_json
from tests.benchmarks.mod_corpus import generate_corpus, synthetic_package_id


def _about(mod_folder: Path) -> dict[str, Any]:
    return xml_path_to_json(str(mod_folder / "About" / "About.xml"))["ModMetaData"]


def _rule_ids(about: dict[str, Any], tag: str) -> list[str]:
    block = about.get(tag)
    if not isinstance(block, dict):
        return []
    items = block["li"]
    return [items] if isinstance(items, str) else list(items)


def test_generate_corpus_is_deterministic(tmp_path: Path) -> None:
    first = generate_corpus(tmp_path / "a", 15, seed=3)
    second = generate_corpus(tmp_path / "b", 15, seed=3)

    for left, right in zip(first, second, strict=True):
        assert (left / "About" / "About.xml").read_text(encoding="utf-8") == (
            right / "About" / "About.xml"
        ).read_text(encoding="utf-8")


def test_generate_corpus_rules_only_point_at_earlier_mods(tmp_path: Path) -> None:
    mod_folders = generate_corpus(tmp_path, 40, seed=5)

    assert len(mod_folders) == 40
    for index, mod_folder in enumerate(mod_folders):
        about = _about(mod_folder)
        assert about["packageId"] == synthetic_package_id(index)
        earlier = {synthetic_package_id(i) for i in range(index)}
        for package_id in _rule_ids(about, "loadAfter"):
            assert package_id in earlier
