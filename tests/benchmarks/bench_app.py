"""End-to-end performance benchmark for RimSort's main mod list flows.

Builds the real ``MainContent`` panel offscreen against an isolated dev data
folder and times refresh, list population, search, moving mods, sorting,
dependency checks and saving. Mods come from any mix of a real game folder,
a real Workshop folder and a generated synthetic corpus. Real folders are
only read; every write goes to the work directory.

Run ``uv run python -m tests.benchmarks.bench_app --help`` for usage, and see
``docs/development-guide/performance-benchmarking.md``.
"""

import argparse
import cProfile
import json
import os
import platform
import shutil
import statistics
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from tests.benchmarks.mod_corpus import generate_corpus

SEARCH_PATTERN = "vanilla"


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark RimSort refresh/populate/search/move/sort/save."
    )
    parser.add_argument("--game-dir", type=Path, help="RimWorld install folder")
    parser.add_argument("--workshop-dir", type=Path, help="Workshop 294100 folder")
    parser.add_argument(
        "--dbs-dir",
        type=Path,
        help="RimSort dbs folder to copy (e.g. ~/.local/share/RimSort/dbs)",
    )
    parser.add_argument(
        "--synthetic", type=int, default=0, help="Number of synthetic mods to add"
    )
    parser.add_argument(
        "--active", type=int, default=300, help="Number of mods in the active list"
    )
    parser.add_argument(
        "--move", type=int, default=25, help="Number of mods to move per move run"
    )
    parser.add_argument("--repeat", type=int, default=3, help="Runs per scenario")
    parser.add_argument("--seed", type=int, default=1, help="Synthetic corpus seed")
    parser.add_argument(
        "--work-dir",
        type=Path,
        help="Reuse this folder for synthetic mods and dev data (default: temp)",
    )
    parser.add_argument(
        "--only", help="Comma-separated scenario names to run (default: all)"
    )
    parser.add_argument("--json", type=Path, help="Write results to this JSON file")
    parser.add_argument(
        "--compare", type=Path, help="Baseline JSON file to compare results with"
    )
    parser.add_argument(
        "--profile", type=Path, help="Write a cProfile .prof file per scenario here"
    )
    parser.add_argument(
        "--debug-logging", action="store_true", help="Log at DEBUG like dev mode"
    )
    return parser.parse_args(argv)


def _prepare_environment(work_dir: Path) -> None:
    """Point AppInfo at an isolated dev folder; must run before importing app."""
    # AppInfo derives the application folder (themes, locales) from the
    # __main__ script, expecting app/__main__.py as with `python -m app`.
    main_module = sys.modules["__main__"]
    main_module.__file__ = str(
        Path(__file__).resolve().parents[2] / "app" / "__main__.py"
    )
    os.environ["RIMSORT_DEV"] = "1"
    os.environ["RIMSORT_DEV_DIR"] = str(work_dir / "dev")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _Bench:
    """Owns the app objects and runs the timed scenarios."""

    def __init__(self, args: argparse.Namespace, work_dir: Path) -> None:
        from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

        from app.controllers.metadata_controller import MetadataController
        from app.controllers.metadata_db_controller import AuxMetadataController
        from app.models.settings import Settings
        from app.utils.app_info import AppInfo
        from app.utils.log_setup import setup_logging
        from app.utils.steam.steamcmd.wrapper import SteamcmdInterface
        from app.views.main_content_panel import MainContent

        self.args = args
        self.blocked_dialogs: list[str] = []
        self.app = QApplication.instance() or QApplication([])

        def _no_modal(dialog: QDialog) -> int:
            self.blocked_dialogs.append(dialog.windowTitle())
            return 0

        QDialog.exec = _no_modal  # type: ignore[method-assign]
        QMessageBox.exec = _no_modal  # type: ignore[method-assign]

        setup_logging(log_dir=AppInfo().user_log_folder, debug=args.debug_logging)

        if args.dbs_dir:
            shutil.copytree(
                args.dbs_dir, AppInfo().databases_folder, dirs_exist_ok=True
            )

        local_dir = work_dir / "local_mods"
        local_dir.mkdir(parents=True, exist_ok=True)
        if args.synthetic and not any(local_dir.iterdir()):
            generate_corpus(local_dir, args.synthetic, args.seed)
        self.config_dir = work_dir / "config"
        self.config_dir.mkdir(parents=True, exist_ok=True)

        self.settings = Settings()
        self.settings.load()
        instance = self.settings.instances[self.settings.current_instance]
        instance.game_folder = str(args.game_dir) if args.game_dir else ""
        instance.workshop_folder = str(args.workshop_dir) if args.workshop_dir else ""
        instance.steam_client_integration = bool(args.workshop_dir)
        instance.local_folder = str(local_dir)
        instance.config_folder = str(self.config_dir)
        instance.initial_setup = False
        self.settings.check_dependencies_on_sort = False
        self.settings.steam_mods_update_check = False
        self.settings.save()

        SteamcmdInterface.instance(
            instance.steamcmd_install_path, self.settings.steamcmd_validate_downloads
        )
        self.metadata_controller = MetadataController.instance(
            settings=self.settings,
            get_active_instance=lambda: self.settings.instances[
                self.settings.current_instance
            ],
            metadata_db_controller=AuxMetadataController.get_or_create_cached_instance(
                self.settings.aux_db_path
            ),
        )
        self.main_content = MainContent(self.settings, self.metadata_controller)
        self.main_content.main_layout_frame.resize(1600, 1000)
        self.main_content.main_layout_frame.show()

    def drain_events(self) -> None:
        """Run queued slots (rowsInserted etc.) so their cost is measured."""
        for _ in range(10):
            self.app.sendPostedEvents()
            self.app.processEvents()

    def shutdown(self) -> None:
        """Run the app's quit hooks so worker threads stop before teardown."""
        self.app.aboutToQuit.emit()
        self.drain_events()

    def write_mods_config(self) -> None:
        """Write a deterministic ModsConfig.xml with ``--active`` mods."""
        from app.models.metadata.metadata_structure import AboutXmlMod
        from app.utils.constants import RIMWORLD_PACKAGE_IDS
        from app.utils.schema import generate_rimworld_mods_list
        from app.utils.xml import json_to_xml_write

        package_ids = sorted(
            {
                str(mod.package_id)
                for mod in self.metadata_controller.mods_metadata.values()
                if isinstance(mod, AboutXmlMod) and mod.package_id
            }
        )
        official = [pid for pid in RIMWORLD_PACKAGE_IDS if pid in package_ids]
        candidates = [pid for pid in package_ids if pid not in official]
        step = max(1, len(candidates) // max(1, self.args.active))
        chosen = candidates[::step][: self.args.active]
        json_to_xml_write(
            generate_rimworld_mods_list(
                self.metadata_controller.game_version, official + chosen
            ),
            str(self.config_dir / "ModsConfig.xml"),
        )

    def populate(self) -> None:
        self.main_content._MainContent__repopulate_lists()  # type: ignore[attr-defined]
        self.drain_events()

    def search(self) -> None:
        search_box = self.main_content.mods_panel.inactive_mods_search
        for length in range(1, len(SEARCH_PATTERN) + 1):
            search_box.setText(SEARCH_PATTERN[:length])
            self.drain_events()
        search_box.clear()
        self.drain_events()

    def move(self) -> None:
        inactive = self.main_content.mods_panel.inactive_mods_list
        inactive.clearSelection()
        for row in range(min(self.args.move, inactive.count())):
            item = inactive.item(row)
            if item is not None:
                item.setSelected(True)
        inactive.key_press_signal.emit("Return")
        self.drain_events()

    def sort(self) -> None:
        self.main_content._do_sort(check_deps=False)
        self.drain_events()

    def dependency_check(self) -> None:
        from app.services.dependency_resolver import build_dependencies_dialog_context

        active = set(self.main_content.mods_panel.active_mods_list.paths)
        build_dependencies_dialog_context(self.metadata_controller, active)

    def loading_overhead(self) -> None:
        """Run a no-op task behind the loading animation used by refresh."""
        from app.utils.app_info import AppInfo

        gif = AppInfo().theme_data_folder / "default-icons" / "rimsort.gif"
        self.main_content.do_threaded_loading_animation(
            gif_path=str(gif), target=lambda: None
        )

    def save(self) -> None:
        self.main_content._do_save()
        self.drain_events()


def _time_scenario(
    name: str,
    run: Callable[[], None],
    repeat: int,
    profile_dir: Path | None,
    reset: Callable[[], None] | None = None,
) -> dict[str, Any]:
    profiler = cProfile.Profile() if profile_dir else None
    runs: list[float] = []
    for _ in range(repeat):
        if reset is not None:
            reset()
        if profiler is not None:
            profiler.enable()
        start = time.perf_counter()
        run()
        runs.append(time.perf_counter() - start)
        if profiler is not None:
            profiler.disable()
    if profiler is not None and profile_dir is not None:
        profile_dir.mkdir(parents=True, exist_ok=True)
        profiler.dump_stats(str(profile_dir / f"{name}.prof"))
    result = {"median_s": statistics.median(runs), "min_s": min(runs), "runs": runs}
    print(
        f"  {name:<18} median {result['median_s']:8.3f}s  min {min(runs):8.3f}s",
        flush=True,
    )
    return result


def _print_comparison(results: dict[str, Any], baseline_path: Path) -> None:
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))["results"]
    print(f"\nCompared with {baseline_path}:")
    for name, result in results.items():
        if name not in baseline:
            continue
        before = baseline[name]["median_s"]
        after = result["median_s"]
        change = (after - before) / before * 100 if before else 0.0
        print(f"  {name:<18} {before:8.3f}s -> {after:8.3f}s  ({change:+.1f}%)")


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark and return a process exit code."""
    args = _parse_args(argv)
    work_dir = args.work_dir or Path(tempfile.mkdtemp(prefix="rimsort-bench-"))
    work_dir.mkdir(parents=True, exist_ok=True)
    _prepare_environment(work_dir)

    bench = _Bench(args, work_dir)
    bench.metadata_controller.refresh_metadata()
    bench.write_mods_config()
    bench.populate()

    mod_count = len(bench.metadata_controller.mods_metadata)
    active_count = bench.main_content.mods_panel.active_mods_list.count()
    print(f"Work dir: {work_dir}")
    print(f"Mods: {mod_count} total, {active_count} active, {args.repeat} runs each")

    scenarios: list[tuple[str, Callable[[], None], Callable[[], None] | None]] = [
        ("refresh_metadata", bench.metadata_controller.refresh_metadata, None),
        ("populate_lists", bench.populate, None),
        ("search_typing", bench.search, None),
        ("move_mods", bench.move, bench.populate),
        ("sort", bench.sort, bench.populate),
        ("sort_again", bench.sort, None),
        ("dependency_check", bench.dependency_check, None),
        ("save", bench.save, None),
        ("loading_overhead", bench.loading_overhead, None),
    ]
    only = set(args.only.split(",")) if args.only else None
    results: dict[str, Any] = {
        name: _time_scenario(name, run, args.repeat, args.profile, reset=reset)
        for name, run, reset in scenarios
        if only is None or name in only
    }
    bench.shutdown()
    if bench.blocked_dialogs:
        print(f"Suppressed modal dialogs: {bench.blocked_dialogs}")

    if args.compare:
        _print_comparison(results, args.compare)
    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "meta": {
                        "mods": mod_count,
                        "active": active_count,
                        "synthetic": args.synthetic,
                        "repeat": args.repeat,
                        "python": sys.version.split()[0],
                        "platform": platform.platform(),
                    },
                    "results": results,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
