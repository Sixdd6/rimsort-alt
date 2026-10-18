"""Deterministic synthetic RimWorld mod corpus for performance benchmarks.

Generated mods mimic the shape of real Workshop mods (dependencies, load
order rules, versioned folders, assemblies, long descriptions) so the
benchmark exercises the same code paths as a real install. Pair them with a
real mods folder via ``bench_app.py`` to cover real-world About.xml quirks.
"""

import random
from pathlib import Path
from xml.sax.saxutils import escape

SYNTHETIC_PACKAGE_PREFIX = "bench.synthetic"

_WORDS = [
    "vanilla",
    "expanded",
    "framework",
    "faction",
    "weapons",
    "apparel",
    "furniture",
    "biomes",
    "animals",
    "genes",
    "xenotypes",
    "psycasts",
    "storage",
    "medical",
    "research",
    "quality",
    "security",
    "power",
    "plants",
    "hair",
    "textures",
    "patch",
    "compatibility",
    "retexture",
    "outposts",
    "mechanoids",
    "anomaly",
    "odyssey",
    "ideology",
    "royalty",
    "biotech",
    "tweaks",
]
_AUTHORS = [f"Author{i:02d}" for i in range(60)]
_SHARED_DEPENDENCIES = ("brrainz.harmony", "unlimitedhugs.hugslib")


def synthetic_package_id(index: int) -> str:
    """Return the package ID of the synthetic mod at ``index``.

    >>> synthetic_package_id(7)
    'bench.synthetic.mod00007'
    """
    return f"{SYNTHETIC_PACKAGE_PREFIX}.mod{index:05d}"


def _li_block(tag: str, values: list[str]) -> str:
    if not values:
        return ""
    items = "".join(f"\n    <li>{escape(v)}</li>" for v in values)
    return f"\n  <{tag}>{items}\n  </{tag}>"


def _dependency_block(package_ids: list[str]) -> str:
    if not package_ids:
        return ""
    items = "".join(
        f"\n    <li>\n      <packageId>{pid}</packageId>"
        f"\n      <displayName>{pid}</displayName>"
        "\n      <steamWorkshopUrl>steam://url/CommunityFilePage/1</steamWorkshopUrl>"
        "\n    </li>"
        for pid in package_ids
    )
    return f"\n  <modDependencies>{items}\n  </modDependencies>"


def _about_xml(index: int, count: int, rng: random.Random) -> str:
    title_words = rng.sample(_WORDS, 3)
    name = f"Synthetic {' '.join(w.title() for w in title_words)} {index}"
    earlier = [synthetic_package_id(i) for i in range(index)]
    later = [synthetic_package_id(i) for i in range(index + 1, count)]

    dependencies: list[str] = []
    if earlier and rng.random() < 0.4:
        dependencies.extend(rng.sample(earlier, min(len(earlier), rng.randint(1, 3))))
    if rng.random() < 0.3:
        dependencies.append(rng.choice(_SHARED_DEPENDENCIES))

    load_after = (
        rng.sample(earlier, min(len(earlier), rng.randint(0, 3))) if earlier else []
    )
    load_before = (
        rng.sample(later, min(len(later), 1)) if later and rng.random() < 0.1 else []
    )
    incompatible = [rng.choice(earlier)] if earlier and rng.random() < 0.02 else []
    description = " ".join(rng.choices(_WORDS, k=rng.randint(30, 250)))

    return (
        '<?xml version="1.0" encoding="utf-8"?>\n<ModMetaData>'
        f"\n  <name>{escape(name)}</name>"
        f"\n  <author>{rng.choice(_AUTHORS)}</author>"
        f"\n  <packageId>{synthetic_package_id(index)}</packageId>"
        + _li_block("supportedVersions", ["1.5", "1.6"])
        + _dependency_block(dependencies)
        + _li_block("loadAfter", load_after)
        + _li_block("loadBefore", load_before)
        + _li_block("incompatibleWith", incompatible)
        + f"\n  <description>{escape(description)}</description>"
        + "\n</ModMetaData>\n"
    )


def generate_corpus(target: Path, count: int, seed: int = 1) -> list[Path]:
    """Write ``count`` synthetic mods into ``target``.

    Dependencies and ``loadAfter`` rules only point at lower-indexed mods, so
    the corpus always has a valid load order; about a third also depend on
    shared framework mods that may or may not be installed.

    :param target: Folder to create the mod folders in.
    :param count: Number of mods to generate.
    :param seed: Seed for the random generator; same seed, same corpus.
    :return: The created mod folders.
    """
    rng = random.Random(seed)
    target.mkdir(parents=True, exist_ok=True)
    mod_folders: list[Path] = []
    for index in range(count):
        mod_folder = target / f"SyntheticMod{index:05d}"
        about_folder = mod_folder / "About"
        about_folder.mkdir(parents=True, exist_ok=True)
        (about_folder / "About.xml").write_text(
            _about_xml(index, count, rng), encoding="utf-8"
        )
        defs_folder = mod_folder / "1.6" / "Defs"
        defs_folder.mkdir(parents=True, exist_ok=True)
        (defs_folder / "ThingDefs.xml").write_text("<Defs />\n", encoding="utf-8")
        if rng.random() < 0.3:
            assemblies = mod_folder / "1.6" / "Assemblies"
            assemblies.mkdir(parents=True, exist_ok=True)
            (assemblies / "Synthetic.dll").write_bytes(b"\0")
        mod_folders.append(mod_folder)
    return mod_folders
