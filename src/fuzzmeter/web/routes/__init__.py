# Copyright (c) 2026 Renata Hodovan, Akos Kiss.
#
# Licensed under the BSD 3-Clause License
# <LICENSE.rst or https://opensource.org/licenses/BSD-3-Clause>.
# This file may not be copied, modified, or distributed except
# according to those terms.

from .files import bp as files_bp
from .reports import bp as reports_bp
from .runs import bp as runs_bp

__all__ = ["files_bp", "reports_bp", "runs_bp"]
