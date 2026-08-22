"""Module entry point.

Allows `python3 -m promptc`, so the tool runs from a checkout with only
PYTHONPATH set and no install step. The test suite relies on this.
"""

# Imports
import sys

# Local imports
from .cli import main

if __name__ == "__main__":
    sys.exit(main())
