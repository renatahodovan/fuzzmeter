====================
|fm-logo| FuzzMeter
====================

.. |fm-logo| image:: docs/images/avatar.png
   :alt: FuzzMeter logo

*Systematic fuzzer execution, measurement, replay, and reporting*

.. image:: https://img.shields.io/badge/python-%3E%3D3.10-blue?logo=python&logoColor=white
   :target: https://www.python.org/
.. image:: https://img.shields.io/coverallsCoverage/github/renatahodovan/fuzzmeter/main?logo=coveralls&logoColor=white
   :target: https://coveralls.io/github/renatahodovan/fuzzmeter
.. image:: https://img.shields.io/badge/license-BSD--3--Clause-blue?logo=open-source-initiative&logoColor=white
   :target: LICENSE.rst
.. image:: https://img.shields.io/badge/docker-required-2496ed?logo=docker&logoColor=white
   :target: https://www.docker.com/

.. start included documentation

*FuzzMeter* is a Docker-based fuzzer runner and evaluation platform for
comparing multiple fuzzers on the same target set. It runs repeated
fuzzer-target trials, records periodic snapshots, measures coverage
independently from the fuzzers, reproduces crashes, stores all raw and derived
data in a SQLite database, and generates interactive reports.

The goal of FuzzMeter is not to collapse performance into a single ranking, but
to help researchers and practitioners analyze different aspects of fuzzer
behavior: coverage growth, bug discovery, corpus evolution, execution speed,
resource usage, statistical comparisons, replayed artifacts, and fuzzer-specific
measurements.

+--------------------------------------------------------------------------+
| **TL;DR - KEY FEATURES**                                                 |
+--------------------------------------------------------------------------+
| *Quick overview of the most important capabilities*                      |
+==========================================================================+
|                                                                          |
| * **Run repeated fuzzer-target trials** in isolated Docker workspaces,   |
|   with configurable duration, repetitions, parallelism, memory limits,   |
|   seed corpora, and snapshot-based measuring mechanism.                  |
|                                                                          |
| * **Measure coverage independently** by replaying captured corpus files  |
|   with LLVM coverage-instrumented target binaries.                       |
|                                                                          |
| * **Reproduce crashes** under sanitizer-enabled builds and deduplicate   |
|   raw crashing inputs by unique sanitizer stack traces.                  |
|                                                                          |
| * **Track more than final coverage**: corpus size, executed tests,       |
|   execution speed, resource telemetry, bug timelines, uniqueness,        |
|   significance tests, and effect sizes.                                  |
|                                                                          |
| * **Replay existing artifacts** without rerunning fuzzers. Historical    |
|   corpora and crashes can be remeasured after report logic, coverage     |
|   tooling, or bug deduplication changes.                                 |
|                                                                          |
| * **Support multiple target formats**, including libFuzzer-style         |
|   in-process targets, command-line targets, and standard input-based     |
|   setups.                                                                |
|                                                                          |
| * **Keep fuzzer-specific corpus** while still measuring concrete tests.  |
|   Snapshot preprocess hooks can transform corpus in custom formats into  |
|   raw tests before coverage and crash measurement.                       |
|                                                                          |
| * **Extensible plugin model** for custom metric collection and custom    |
|   report sections.                                                       |
|                                                                          |
| * **Interactive and static web reports** with filtering, sortable        |
|   rankings, target charts, bug tables, coverage links, and exportable    |
|   PDF/PNG figures or even with composite results assembled from previous |
|   evaluations.                                                           |
|                                                                          |
| * **Configuration inheritance** for fuzzer variants, allowing one base   |
|   implementation to be reused with different build/runtime settings,     |
|   plugins, measurements, and reporting behavior.                         |
+--------------------------------------------------------------------------+


Requirements
============

* Python_ >= 3.10
* Docker_ with BuildKit/buildx support

.. _Python: https://www.python.org/
.. _Docker: https://www.docker.com/


Install
=======

For development use, clone the repository and install it into a virtual
environment::

    python3 -m venv .venv
    . .venv/bin/activate
    python3 -m pip install -e .

The package exposes the ``fuzzmeter`` command::

    fuzzmeter --help

.. note::

   This release is intended to be run from a local repository checkout, either
   directly as a local script or through an editable install that exposes the
   ``fuzzmeter`` command. Standalone PyPI-style installation is not supported
   yet.


Usage
=====

FuzzMeter runs a *campaign*. A campaign is configured by a YAML file that
selects the participating fuzzers, fuzz targets, and runtime settings.

A small campaign looks like this::

    fuzzers:
      - aflplusplus
      - libfuzzer
      - id: libfuzzer_entropic
        parent: libfuzzer
        runtime:
          args:
            - -entropic=1
    fuzz_targets:
      - jerryscript:jerry
    run:
      time_seconds: 300
      repetitions: 3
      parallel_jobs: 16
      snapshot:
        every_seconds: 60

Run it with::

    fuzzmeter --log-level INFO run --config configs/minimal.yaml --out out

Every run gets its own directory under the output root, named after the time
the run started: ``out/<YYYY-MM-DD_HHMMSS>/``, or
``out/<YYYY-MM-DD_HHMMSS>-<label>/`` when ``run --label`` is given. On
successful completion, FuzzMeter also exports a static HTML report under
``report/`` inside that directory.

The command-line interface contains three main subcommands::

    fuzzmeter run --config <config.yaml> --out <output-root>
    fuzzmeter report <run-dir>
    fuzzmeter serve --root <run-dir> [<run-dir> ...]

``run`` executes the campaign and exports a static report. ``serve`` starts the
dynamic database-backed web UI for existing runs. ``report`` exports a static
report for an existing run.

``serve --root`` takes the run directories themselves, not the output root:
every value must be a directory that already contains a ``fuzzmeter.db``. The
option accepts several directories at once and can be repeated, so a whole
output root is served with a shell glob::

    fuzzmeter serve --root out/*

The subcommands accept a few more options:

.. list-table::
   :header-rows: 1

   * - Option
     - Description
   * - ``run --out <dir>``
     - Output root. Defaults to ``out``.
   * - ``run --label <label>``
     - Human-readable label appended to the run directory name.
   * - ``run --fuzzers <dir>...``, ``run --benchmarks <dir>...``
     - Fuzzer and benchmark definition directories. Both default to every
       directory under ``fuzzers/`` and ``benchmarks/`` in the current working
       directory.
   * - ``report --out <dir>``
     - Report output directory. Defaults to ``report/`` inside the run
       directory.
   * - ``report --fuzzers <dir>...``
     - Fuzzer definition directories, needed for fuzzer-defined report
       sections.
   * - ``serve --host <host>``, ``serve --port <port>``
     - Web UI interface and port. The default host is ``0.0.0.0``, which
       exposes the UI on every interface; pass ``127.0.0.1`` to keep it local.
   * - ``serve --debug``
     - Run the web UI in Flask debug mode.


Campaign Configuration
======================

The most important campaign fields are:

.. list-table::
   :header-rows: 1

   * - Field
     - Description
   * - ``fuzzers``
     - Names or derived entries. A plain string loads
       ``fuzzers/<name>/build/build.yaml`` merged with
       ``fuzzers/<name>/run/run.yaml``. A mapping defines a fuzzer variant and
       must carry an ``id``; ``parent`` names the fuzzer it derives from, and
       defaults to the ``id`` itself.
   * - ``fuzz_targets``
     - Fuzz target specifications in ``benchmark:fuzz_target`` form. The
       benchmark definition in ``benchmarks/<benchmark>/benchmark.yaml`` can
       define more than one ``fuzz_target`` entry.
   * - ``run.time_seconds``
     - Fuzzing duration of each trial (i.e., one repetition of a fuzzer-target
       pair).
   * - ``run.repetitions``
     - Number of repetitions per fuzzer-target pair.
   * - ``run.parallel_jobs``
     - Total job budget shared by trials and snapshot workers.
   * - ``run.snapshot.every_seconds``
     - Snapshot cadence. Each tick records corpus/crash state and telemetry, and
       schedules coverage, reproduction, and custom measurements.
   * - ``run.snapshot.jobs``
     - Part of the job budget reserved for snapshot measurement workers,
       ``1`` by default. It must stay below ``run.parallel_jobs``; ``0`` lets
       the run split the budget itself.
   * - ``run.snapshot.export_every_ticks``
     - Render the HTML coverage export only on every Nth snapshot tick. ``0``
       skips it except where a report needs it.
   * - ``run.memory`` and ``run.memory_swap``
     - Optional Docker memory limits.

Besides ``id``, ``parent``, ``build``, and ``runtime``, a fuzzer entry can
carry ``allowed_fuzz_targets`` (restrict the entry to some of the campaign fuzz
targets), ``replay_trials`` (see `Replay Mode`_), ``source_dependencies``,
``reporting_parent``, and ``local_repo_env``.

Fuzzer entries can derive from existing fuzzers and override only the parts
that change::

    fuzzers:
      - libfuzzer
      - id: libfuzzer_shallow
        parent: libfuzzer
        runtime:
          args:
            - -mutate_depth=5

Benchmark Configuration
=======================

Benchmark configuration defines one or more fuzz targets that are available.
Fuzz target configuration can also influence fuzzer configuration. For example,
a fuzz target can tell a grammar-based fuzzer which grammar rule or grammar file
should be used for that target. Benchmark files define their fuzz targets in a
``fuzz_targets`` mapping::

    benchmark: jerryscript
    fuzz_targets:
      jerry:
        input_mode: in_process
        timeout_s: 1
        fuzzers:
          grammarinator:
            build:
              env:
                GRAMMARINATOR_RULE: program

Campaign files refer to fuzz targets as ``benchmark:fuzz_target``.


Basic Workflow
==============

For a live campaign, FuzzMeter performs the following steps:

1. Loads the selected fuzzer and fuzz target configurations.
2. Builds the Docker images required for fuzzing, coverage replay, and
   sanitizer-based crash reproduction.
3. Starts one isolated trial for every fuzzer-target repetition.
4. Periodically snapshots corpus, crash, hang, statistics, and resource data.
5. Runs measurement workers over the captured artifacts.
6. Stores raw and derived data in database.
7. Generates a report from the database and associated coverage artifacts.


Replay Mode
===========

Replay mode evaluates existing fuzzer output directories with the current
FuzzMeter measurement pipeline. It does not start the original fuzzer.
Instead, it reconstructs the snapshot timeline from file timestamps and runs
coverage, crash reproduction, bug deduplication, and report generation over the
historical artifacts.

Replay is useful when:

* fuzzer executions already exist and only the metrics need to be recomputed;
* report logic changed;
* archived corpus and crash directories need to be included in a new
  comparison;
* coverage or bug reproduction should be rerun.

Replay sources are configured on fuzzer entries with ``replay_trials``::

    fuzzers:
      - id: aflplusplus_old
        parent: aflplusplus
        allowed_fuzz_targets:
          - jerryscript:jerry
        replay_trials:
          jerryscript:jerry:
            - /data/old-runs/afl/default
      - id: libfuzzer_old
        parent: libfuzzer
        allowed_fuzz_targets:
          - jerryscript:jerry
        replay_trials:
          jerryscript:jerry:
            - /data/old-runs/libfuzzer/corpus
    fuzz_targets:
      - jerryscript:jerry
    run:
      time_seconds: 86400
      parallel_jobs: 8
      snapshot:
        every_seconds: 900

``replay_trials`` maps ``benchmark:fuzz_target`` specs to the directories to
replay, so one entry can replay several fuzz targets. A fuzzer definition can
carry its own ``replay_trials``; a campaign entry replaces them.

The ``parent`` fuzzer is still important in replay mode. It tells FuzzMeter how
to interpret the output layout, where corpora and crashes are located, and
which snapshot preprocessing hook should be used.


Reports
=======

FuzzMeter reports can be opened as static HTML exports or through the dynamic
``serve`` command. Both views are built from the same report payload.

The report includes:

.. list-table::
   :header-rows: 1

   * - View
     - Purpose
   * - Overview ranking
     - Compare fuzzers across all targets.
   * - Target summary tables
     - Inspect per-fuzzer metrics and per-trial distributions.
   * - Coverage time series
     - Compare branch, region, line, or function coverage growth.
   * - Coverage distribution plots
     - Inspect variation across repetitions.
   * - Unique and relative coverage matrices
     - Identify complementary coverage and overlap between fuzzers.
   * - Bug views
     - Separate raw crash volume from deduplicated bugs and timelines.
   * - Throughput and corpus views
     - Track saved corpus size and executed tests.
   * - Resource telemetry
     - Inspect container memory and corpus disk usage.
   * - Statistical matrices
     - Compare final metric distributions with Mann-Whitney U tests and
       Vargha-Delaney A12 effect sizes.
   * - Custom sections
     - Show fuzzer-defined metrics beside the built-in measurements.

Charts and tables can be exported as publication-friendly PNG or PDF files.
Reports also link to complete HTML coverage reports when coverage exports are
available.

Temporary Composite Report Views
--------------------------------

When ``fuzzmeter serve`` starts, it indexes the composite measurement
descriptors stored in the ``fuzzmeter.db`` of every configured run directory.
Only descriptor metadata is loaded at startup; time series, trial, bug, and
coverage data stay in their original run directories and are read lazily when a
temporary composite report view needs them.

Composite views are read-only and no-copy. FuzzMeter does not create a merged
database, copy artifacts, or write a ``comparison.json`` file. The view
selection lives only in the running ``serve`` process. The browser keeps the
view id in the URL, so refreshing the page preserves the comparison until the
server restarts. After a restart the same URL reports an expired view and the
selection must be recreated.

Composite views can be created in two ways:

* from the runs page by selecting stored measurements and opening a comparison;
* from an active run report by adding historical measurements to the current
  report. In this case the active run is first seeded into the same temporary
  view model, then historical series are added through the shared API.

Compatibility follows an "inform, do not filter" policy. Different
``benchmark`` or ``fuzz_target`` values and invalid descriptors are marked
``incompatible``. Environment, config-detail, and user-defined source
differences are marked ``risky`` and are shown as field-level metadata for the
user to judge. Runtime length, repetition count, and fuzzer version metadata
are displayed in the source summary and report payload, but they do not block
selection.

Benchmark-specific source metadata is optional. FuzzMeter looks for a
``source_info.py`` hook under the benchmark and the fuzzer root, and runs the
same hook infrastructure with two scopes: ``benchmark_source`` and
``fuzzer_version``. Hook output is redacted before storage: likely secret
fields and private absolute path fragments are replaced with placeholder
values, and the report treats missing source metadata as ``risky`` rather than
silently compatible.

To serve existing runs dynamically::

    fuzzmeter --log-level INFO serve --root out/* --host 127.0.0.1 --port 8000

To regenerate a static report from an existing run directory::

    fuzzmeter report out/<run-dir>


Output Layout
=============

By default, the output root is ``out/``. Each run is stored under
``out/<YYYY-MM-DD_HHMMSS>/``, named after the time the run started.

Important paths are:

.. list-table::
   :header-rows: 1

   * - Path
     - Description
   * - ``fuzzmeter.db``
     - SQLite database containing run, trial, snapshot, coverage, resource,
       and bug data.
   * - ``config.yaml``
     - The campaign YAML captured at run start.
   * - ``benchmark_config.json``
     - The resolved fuzzer identities, recorded for later reporting runs.
   * - ``trials/``
     - Per-trial workspaces with logs, live outputs, snapshots, and target
       binary references.
   * - ``coverage/``
     - Per-trial coverage exports and HTML coverage reports.
   * - ``coverage_seed/``
     - Optional seed-corpus baseline coverage.
   * - ``report/``
     - Static HTML report export.


Working Example
===============

The repository contains ``configs/minimal.yaml``, which compares several
available fuzzer integrations on JerryScript.

Run it with a short time budget from the repository root::

    fuzzmeter --log-level INFO run --config configs/minimal.yaml --out out

Then open the dynamic web UI::

    fuzzmeter serve --root out/* --host 127.0.0.1 --port 8000

or open the generated static report under the ``report/`` directory of the run.

.. end included documentation


Copyright and Licensing
=======================

Licensed under the BSD 3-Clause License_.

.. _License: LICENSE.rst
