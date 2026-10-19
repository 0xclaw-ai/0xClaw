"""Load this checkout and keep provider metadata lookups offline in tests."""

import os
import sys
from pathlib import Path

os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
os.environ["DO_NOT_TRACK"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "0xclaw"))
