#!/usr/bin/env python3

from pathlib import Path
import runpy
import sys


def main() -> None:
    base_script = (
        Path(__file__).resolve().parents[1]
        / "Base Script"
        / "media_metadata_and_extras_getter_base.py"
    )
    sys.path.insert(0, str(base_script.parent))
    runpy.run_path(str(base_script), run_name="__main__")


if __name__ == "__main__":
    main()
