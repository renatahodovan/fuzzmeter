# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Create and configure the dynamic Fuzzmeter Flask application.'''

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from flask import Flask

from ..composite import CompositeRegistry, CompositeViewStore
from .routes import composite_bp, files_bp, reports_bp, runs_bp


def configure_run_dirs(paths: Iterable[Path], flask_app: Flask | None = None) -> tuple[Path, ...]:
    '''Bind the dynamic web app and composite registry to direct run directories.'''

    run_dirs = tuple(Path(path).resolve() for path in paths)
    names: set[str] = set()
    for run_dir in run_dirs:
        if not run_dir.is_dir():
            raise NotADirectoryError(f'Run directory is not a directory: {run_dir}')
        if not (run_dir / 'fuzzmeter.db').is_file():
            raise FileNotFoundError(f'Run directory does not contain fuzzmeter.db: {run_dir}')
        if run_dir.name in names:
            raise ValueError(f'Duplicate run directory name: {run_dir.name}')
        names.add(run_dir.name)

    target_app = flask_app or globals().get('app')
    if target_app is not None:
        target_app.config['RUN_DIRS_PROVIDER'] = lambda: run_dirs
        target_app.config['COMPOSITE_REGISTRY'] = CompositeRegistry(run_dirs)
    return run_dirs


def create_app() -> Flask:
    '''Create the dynamic web app bound to configured run directories.'''
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.config['RUN_DIRS_PROVIDER'] = lambda: ()
    app.config['COMPOSITE_REGISTRY'] = CompositeRegistry(())
    app.config['COMPOSITE_VIEW_STORE'] = CompositeViewStore()
    app.register_blueprint(runs_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(composite_bp)
    app.register_blueprint(files_bp)
    return app


app = create_app()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
