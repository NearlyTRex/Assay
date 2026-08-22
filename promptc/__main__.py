# Allows `python3 -m promptc`

# Imports
import sys

# Local imports
from .cli import main

if __name__ == "__main__":
    sys.exit(main())
