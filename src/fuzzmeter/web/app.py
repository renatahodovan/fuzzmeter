# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from __future__ import annotations

import os
from pathlib import Path

from flask import Flask

from .routes import files_bp, reports_bp, runs_bp

_env_runs_root = os.environ.get("FM_RUNS_ROOT")
if _env_runs_root:
    RUNS_ROOT = Path(_env_runs_root).resolve()
else:
    RUNS_ROOT = Path(os.environ.get("FM_OUT", "/tmp/fuzzmeter/out")).resolve() / "runs"


def create_app() -> Flask:
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["RUNS_ROOT_PROVIDER"] = lambda: RUNS_ROOT
    app.register_blueprint(runs_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(files_bp)
    return app


app = create_app()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
