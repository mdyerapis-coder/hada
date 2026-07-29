"""DEPRECATED — use `from hermes_ctl.cli import build_parser, main`.

This module exists only for backward compatibility (some tools still reference
`hermes_ctl.cli` as a module). The real code lives in the `hermes_ctl/cli/` package.

All imports, re-exports, and `python3 -m` invocation now use the package.
"""

from hermes_ctl.cli import build_parser, main, load_brains, TelegramChannel

__all__ = ["build_parser", "main"]
