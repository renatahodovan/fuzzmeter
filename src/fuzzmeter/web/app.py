# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

"""Create and configure the dynamic Fuzzmeter Flask application."""

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask

from ..composite import CompositeRegistry, CompositeViewStore
from .routes import composite_bp, files_bp, reports_bp, runs_bp


def resolve_runs_root(path: Path) -> Path:
    """Return the run-directory root for an output root, runs root, or run directory."""
    root = Path(path).resolve()
    if (root / 'fuzzmeter.db').is_file():
        return root.parent
    if (root / 'runs').is_dir():
        return (root / 'runs').resolve()
    return root


_env_runs_root = os.environ.get("FM_RUNS_ROOT")
if _env_runs_root:
    RUNS_ROOT = resolve_runs_root(Path(_env_runs_root))
else:
    RUNS_ROOT = resolve_runs_root(Path(os.environ.get("FM_OUT", "/tmp/fuzzmeter/out")))


def configure_runs_root(path: Path, flask_app: Flask | None = None) -> Path:
    """Bind the dynamic web app and composite registry to a runs root."""
    runs_root = resolve_runs_root(path)
    globals()['RUNS_ROOT'] = runs_root
    target_app = flask_app or globals().get('app')
    if target_app is not None:
        target_app.config['RUNS_ROOT_PROVIDER'] = lambda: RUNS_ROOT
        target_app.config['COMPOSITE_REGISTRY'] = CompositeRegistry(runs_root)
    return runs_root


def create_app() -> Flask:
    """Create the dynamic web app bound to the current runs root."""
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["RUNS_ROOT_PROVIDER"] = lambda: RUNS_ROOT
    app.config['COMPOSITE_REGISTRY'] = CompositeRegistry(RUNS_ROOT)
    app.config['COMPOSITE_VIEW_STORE'] = CompositeViewStore()
    app.register_blueprint(runs_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(composite_bp)
    app.register_blueprint(files_bp)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
