"""Makes the service modules importable when pytest is run from this folder or from the repo root."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
