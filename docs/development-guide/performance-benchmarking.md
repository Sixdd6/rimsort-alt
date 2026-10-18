---
layout: default
title: Performance Benchmarking
nav_order: 5
parent: Development Guide
permalink: development-guide/performance-benchmarking
---

# Performance Benchmarking

{: .no_toc}

RimSort ships an end-to-end benchmark that times the flows users wait on most: refreshing metadata, filling the mod lists, searching, moving mods, sorting, checking dependencies and saving. Use it to measure a performance change before and after you make it.

## Table of Contents

{: .no_toc .text-delta }

1. TOC
{:toc}

## What it measures

The benchmark (`tests/benchmarks/bench_app.py`) builds the real `MainContent` panel offscreen and drives it the same way the app does. Each scenario runs `--repeat` times and reports the median and the fastest run.

| Scenario | What runs |
| --- | --- |
| `refresh_metadata` | `MetadataController.refresh_metadata`: scan mod folders, parse every `About.xml`, load the databases and update the aux database, then rebuild both lists in response to `metadata_refreshed` (as after a runner panel closes) |
| `populate_lists` | Read `ModsConfig.xml` and rebuild both mod lists, including error and warning checks |
| `search_typing` | Type `vanilla` into the inactive search box one key at a time, then clear it |
| `move_mods` | Select `--move` inactive mods and press Return to move them to the active list |
| `select_mods` | Select 40 inactive mods one after another, as when holding the down arrow key, updating the mod info panel each time |
| `sort` | Sort the active list (dependency dialog off) |
| `sort_again` | Sort the already sorted active list again |
| `dependency_check` | Build the missing-dependency report used before sorting |
| `save` | Write `ModsConfig.xml`, settings and a mod list history snapshot |
| `loading_overhead` | Run a no-op task behind the loading animation that refresh uses, measuring only the animation's own delay |

All writes go to the work directory. Real game and Workshop folders are only read, and the databases folder is copied, not used in place.

## Choosing mods to test with

Synthetic mods give repeatable numbers at any scale but do not have real-world quirks: unusual `About.xml` files, large texture folders, real dependency graphs. Real mods have those quirks but differ between machines. For a performance change, measure with both:

- `--game-dir` adds the official content (Core and DLC) from a RimWorld install.
- `--workshop-dir` adds a real Steam Workshop folder (`.../steamapps/workshop/content/294100`).
- `--synthetic N` generates `N` mods with dependencies, load order rules, versioned folders and assemblies (`tests/benchmarks/mod_corpus.py`). The same `--seed` always produces the same mods.
- `--dbs-dir` copies a RimSort `dbs` folder so the Steam Workshop database and community rules load too. On Linux this is `~/.local/share/RimSort/dbs`.

`--history N` saves once, then copies that snapshot so the mod list history holds `N` snapshots, like an install that has reached the default retention of 100.

`--active N` picks `N` installed mods, spread evenly by package ID, and writes them to the benchmark's `ModsConfig.xml`, after the official content.

## Running it

From the repository root:

```bash
uv run python -m tests.benchmarks.bench_app \
  --game-dir ~/.local/share/Steam/steamapps/common/RimWorld \
  --workshop-dir ~/.local/share/Steam/steamapps/workshop/content/294100 \
  --dbs-dir ~/.local/share/RimSort/dbs \
  --synthetic 2000 --active 500 --repeat 3 \
  --work-dir /tmp/rimsort-bench --json /tmp/rimsort-bench/baseline.json
```

`--work-dir` keeps the generated mods between runs so you only pay for generating them once. Delete its `dev` folder to start from an empty aux database. The `--synthetic` count is only applied when the work directory has no generated mods yet.

On Linux, run `ulimit -c 1` in the shell first. If the benchmark crashes, no core dump is written and the desktop does not show a crash report.

## Comparing a change

1. On the base branch, run the benchmark with `--json baseline.json`.
2. On your branch, run it again with the same arguments and `--compare baseline.json`.
3. Include both sets of numbers in the pull request, along with the mod counts the benchmark prints.

Timings move around by a few percent between runs. Use `--repeat 5` or more when the change is small.

`--only` runs a subset, for example `--only sort,save`. `sort_again` measures sorting an already sorted list, so run it together with `sort`.

## Profiling

`--profile DIR` writes one cProfile file per scenario, covering every run of that scenario. Profiling makes every scenario slower, so only compare profiled runs with other profiled runs. Read the files with the standard library:

```bash
uv run python -c "import pstats; pstats.Stats('DIR/populate_lists.prof').sort_stats('cumulative').print_stats(30)"
```

`--debug-logging` logs at DEBUG level, like dev mode. Leave it off when measuring: the default matches a normal install and keeps logging cost realistic.
