"""Support `python3 -m hermes_ctl.cli <subcommand>` via the package."""
from hermes_ctl.cli import main
import sys

sys.exit(main())
