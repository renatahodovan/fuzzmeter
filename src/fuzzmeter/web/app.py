# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

'''Create and configure the dynamic Fuzzmeter Flask application.'''

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from flask import Flask

from ..composite import CompositeRegistry, CompositeViewStore
from .routes import composite_bp, files_bp, reports_bp, runs_bp


def create_app(run_dirs: Sequence[Path] = ()) -> Flask:
    '''Create the dynamic web app bound to the given run directories.'''

    run_dirs = tuple(run_dirs)
    app = Flask(__name__, template_folder='templates', static_folder='static')
    app.config['RUN_DIRS_PROVIDER'] = lambda: run_dirs
    app.config['COMPOSITE_REGISTRY'] = CompositeRegistry(run_dirs)
    app.config['COMPOSITE_VIEW_STORE'] = CompositeViewStore()
    app.register_blueprint(runs_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(composite_bp)
    app.register_blueprint(files_bp)
    return app


if __name__ == '__main__':
    create_app().run(host='0.0.0.0', port=8000, debug=True)
