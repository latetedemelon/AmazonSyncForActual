"""Make the ``src`` layout importable without installing the package."""

import os
import sys

SRC = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "src"))
if SRC not in sys.path:
    sys.path.insert(0, SRC)

DATA = os.path.join(os.path.dirname(__file__), "data")
