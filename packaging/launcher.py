"""Entry point for the standalone program; PyInstaller needs a script rather than a module."""

import sys

from portalite2snirf.cli import main

sys.exit(main())
