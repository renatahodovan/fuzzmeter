# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Command line entrypoints for fuzzmeter runs and the local web UI.'''

from __future__ import annotations

import argparse
import logging
import os
import subprocess
from pathlib import Path

logging.basicConfig(format='%(asctime)s - %(levelname)-7s - %(name)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S')
logger = logging.getLogger('fuzzmeter')


def _default_repo_root() -> Path:
    cwd = Path.cwd().resolve()
    if (cwd / 'fuzzers').is_dir() and (cwd / 'src').is_dir():
        return cwd
    return Path(__file__).resolve().parents[2]


def _docker_available() -> bool:
    try:
        result = subprocess.run(
            ['docker', 'version'],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _docker_buildx_available() -> bool:
    try:
        result = subprocess.run(
            ['docker', 'buildx', 'version'],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _validate_docker() -> bool:
    if not _docker_available():
        logger.error('Docker is not available. Start Docker and retry.')
        return False
    if not _docker_buildx_available():
        logger.error('Docker Buildx is not available.')
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    '''Run fuzzmeter commands from the host.'''
    ap = argparse.ArgumentParser(prog='fuzzmeter')
    ap.add_argument(
        '-l',
        '--log-level',
        choices=('CRITICAL', 'ERROR', 'WARNING', 'INFO', 'DEBUG'),
        default='INFO',
        help='Log level',
    )

    sub = ap.add_subparsers(dest='cmd', required=True)

    ap_run = sub.add_parser('run',
                            help='Run fuzzing config and export a static report on success')
    ap_run.add_argument('--config', type=Path, required=True,
                        help='Host path to the config YAML')
    ap_run.add_argument('--out', type=Path, default=Path('out'),
                        help='Host output directory')

    ap_report = sub.add_parser('report', help='Generate a static report for an existing run')
    ap_report.add_argument('run_dir', type=Path,
                           help='Run directory containing fuzzmeter.db')
    ap_report.add_argument('--out', dest='out_dir', type=Path, default=None,
                           help='Report output directory')

    ap_srv = sub.add_parser('serve', help='Run the dynamic DB-backed web UI')
    ap_srv.add_argument('--root', type=Path, default=Path('out'),
                        help='OUT_ROOT or RUNS_ROOT directly')
    ap_srv.add_argument('--host', default='0.0.0.0',
                        help='Host interface for the web UI')
    ap_srv.add_argument('--port', type=int, default=8000,
                        help='Port for the web UI')
    ap_srv.add_argument('--debug', action='store_true',
                        help='Run the web UI in Flask debug mode')

    args = ap.parse_args(argv)
    logger.setLevel(getattr(logging, args.log_level))
    os.environ['FM_LOG_LEVEL'] = args.log_level

    if args.cmd == 'run':
        from .config import load_campaign_config
        from .reporting import write_report
        from .run.runner import run_experiment

        config_path = args.config.expanduser().resolve()
        if not config_path.is_file():
            ap.error(f'Config file is not a file: {config_path}')

        fm_out = args.out.expanduser().resolve()
        if fm_out.exists() and not fm_out.is_dir():
            ap.error(f'Output directory is not a directory: {fm_out}')
        fm_out.mkdir(parents=True, exist_ok=True)

        repo = _default_repo_root()
        try:
            config_src = config_path.read_text(encoding='utf-8')
            campaign_config = load_campaign_config(repo, config_src)
        except (OSError, UnicodeDecodeError, TypeError, ValueError, RuntimeError) as exc:
            ap.error(str(exc))

        if not _validate_docker():
            return 1

        os.environ['FM_OUT_SRC'] = str(fm_out)
        try:
            logger.info('Start experiment')
            run_dir = run_experiment(
                campaign_config,
                out_root=fm_out,
                repo_root=repo,
                config_src=config_src,
            )
        except KeyboardInterrupt:
            logger.warning('Interrupted by user')
            return 130

        logger.info('Experiment completed: %s', run_dir)
        report_dir = write_report(Path(run_dir))
        logger.info('Static report generated to: %s', report_dir)
        return 0

    if args.cmd == 'report':
        from .reporting import write_report

        run_dir = args.run_dir.expanduser().resolve()
        out_dir = args.out_dir.expanduser().resolve() if args.out_dir else None
        report_dir = write_report(run_dir, out_dir=out_dir)
        logger.info('Static report generated to: %s', report_dir)
        return 0

    if args.cmd == 'serve':
        import fuzzmeter.web.app as webapp

        try:
            root = args.root.expanduser().resolve()
            webapp.RUNS_ROOT = (root / 'runs').resolve() if (root / 'runs').is_dir() else root
            if not webapp.RUNS_ROOT.is_dir():
                raise NotADirectoryError(f'Runs root is not a directory: {webapp.RUNS_ROOT}')
        except (FileNotFoundError, NotADirectoryError, PermissionError, OSError) as exc:
            logger.error('Invalid runs root: %s', exc)
            return 1

        os.environ['FM_RUNS_ROOT'] = str(webapp.RUNS_ROOT)
        os.environ['FM_OUT_ROOT'] = (
            str(webapp.RUNS_ROOT.parent) if webapp.RUNS_ROOT.name == 'runs' else str(webapp.RUNS_ROOT)
        )
        if args.debug:
            os.environ['FM_WEB_DEBUG'] = '1'

        from .web.app import app

        app.run(host=args.host, port=args.port, debug=args.debug)
        return 0

    return 2


if __name__ == '__main__':
    main()
