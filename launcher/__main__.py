"""Entry point for the 0xclaw CLI command.

Python cannot parse `from 0xclaw.main import main` because `0x` is a hex
literal prefix. This wrapper adds 0xclaw/ to sys.path directly so that
`import main` resolves to 0xclaw/main.py without using the package name.
"""
from pathlib import Path
import sys

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "0xclaw"))

from main import main  # noqa: E402  (resolves to 0xclaw/main.py)

if __name__ == "__main__":
    raise SystemExit(main())
