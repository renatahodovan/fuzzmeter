=========
FuzzMeter
=========
*Systematic fuzzer execution, measurement, replay, and reporting*

.. image:: https://img.shields.io/badge/python-%3E%3D3.10-blue?logo=python&logoColor=white
   :target: https://www.python.org/
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
to help researchers and preacticioners analyze different aspects of fuzzer
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
|   PDF/PNG figures.                                                       |
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
selects the participating fuzzers, targets, and runtime settings.

A small campaign looks like this::

    fuzzers:
      - aflplusplus
      - libfuzzer
      - fuzzer: libfuzzer_entropic
        parent: libfuzzer
        runtime:
          args:
            - -entropic=1
    targets:
      - jerryscript:jerry
    run:
      time_seconds: 300
      repetitions: 3
      parallel_jobs: 16
      snapshot:
        every_seconds: 60

Run it with::

    fuzzmeter --log-level INFO run --config configs/minimal.yaml --out out

The output is written under ``out/runs/<run_id>/``. On successful completion,
FuzzMeter also exports a static HTML report under the same directory.

The command-line interface contains two main subcommands::

    fuzzmeter run --config <suite.yaml> --out <output-root>
    fuzzmeter serve --root <output-root-or-runs-dir> --host 127.0.0.1 --port 8000

``run`` executes the campaign and exports a static report. ``serve`` starts the
dynamic database-backed web UI for existing runs.


Campaign Configuration
======================

The most important campaign are:

.. list-table::
   :header-rows: 1

   * - Field
     - Description
   * - ``fuzzers``
     - Names or derived entries. A plain string loads
       ``fuzzers/<name>/fuzzer.yaml``. A mapping can define a fuzzer variant
       with ``fuzzer`` and ``parent``.
   * - ``targets``
     - Target specifications in ``project:fuzz_target`` form. The project
       loads ``targets/<project>/benchmark.yaml``.
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
   * - ``run.memory`` and ``run.memory_swap``
     - Optional Docker memory limits.

Fuzzer entries can derive from existing fuzzers and override only the parts
that change::

    fuzzers:
      - libfuzzer
      - fuzzer: libfuzzer_shallow
        parent: libfuzzer
        runtime:
          args:
            - -mutate_depth=5

Target configuration can also influence fuzzer configuration. For example, a target
can tell a grammar-based fuzzer which grammar rule or grammar file should be
used for that target.


Basic Workflow
==============

For a live campaign, FuzzMeter performs the following steps:

1. Loads the campaign YAML, the selected fuzzer and target configurations, and
   target-specific overrides.
2. Builds the Docker images required for fuzzing, coverage replay, and
   sanitizer-based crash reproduction.
3. Starts one isolated trial workspace for every fuzzer-target repetition.
4. Periodically snapshots corpus, crash, hang, statistics, and resource data.
5. Runs measurement workers over the captured artifacts.
6. Stores raw and derived data in database.
7. Generates a report from the database and associated coverage artifacts.

Coverage replax containers (a.k.a. workers) re-execute corpus elements with
coverage-instrumented target binaries. Crash reproduction workers re-execute
candidate failures with sanitizer-enabled target binaries. This separation keeps
fuzzer execution and measurement independent.


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
      - fuzzer: aflplusplus_old
        parent: aflplusplus
        allowed_benchmarks: jerryscript:jerry
        replay_trials:
          - /data/old-runs/afl/default
      - fuzzer: libfuzzer_old
        parent: libfuzzer
        allowed_benchmarks: jerryscript:jerry
        replay_trials:
          - /data/old-runs/libfuzzer/corpus
    targets:
      - jerryscript:jerry
    run:
      time_seconds: 86400
      parallel_jobs: 8
      snapshot:
        every_seconds: 900

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

To serve existing runs dynamically::

    fuzzmeter --log-level INFO serve --root out/runs --host 127.0.0.1 --port 8000

To regenerate a static report from an existing run directory::

    python3 -m fuzzmeter.reporting.generate out/runs/<run_id>


Output Layout
=============

By default, the output root is ``out/``. Each run is stored under
``out/runs/<run_id>/``.

Important paths are:

.. list-table::
   :header-rows: 1

   * - Path
     - Description
   * - ``fuzzmeter.db``
     - SQLite database containing run, trial, snapshot, coverage, resource,
       and bug data.
   * - ``suite.yaml``
     - The campaign YAML captured at run start.
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

    fuzzmeter serve --root out/runs --host 127.0.0.1 --port 8000

or open the generated static report under the corresponding
``out/runs/<run_id>/report/`` directory.

.. end included documentation


Copyright and Licensing
=======================

Licensed under the BSD 3-Clause License_.

.. _License: LICENSE.rst
