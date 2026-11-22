"""Create a disposable, entirely synthetic MediaCleanup demo library."""

from __future__ import annotations

import argparse
from pathlib import Path


FIXTURES = {
    "Aurora.Bridge.2020/Aurora.Bridge.2020.[ENG].1080p.mkv": b"Demo movie placeholder\n",
    "Aurora.Bridge.2020/Aurora.Bridge.2020.[ENG].srt": b"1\n00:00:00,000 --> 00:00:01,000\nSynthetic subtitle\n",
    "Example.Show/Example.Show.S01E01.mkv": b"Demo episode 1 placeholder\n",
    "Example.Show/Example.Show.S01E02.mkv": b"Demo episode 2 placeholder\n",
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="A new directory that does not already exist")
    args = parser.parse_args()
    root = args.directory.expanduser().absolute()

    try:
        # Exclusive creation prevents the demo from writing over an existing library.
        root.mkdir(exist_ok=False)
        for filename, content in FIXTURES.items():
            path = root / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as handle:
                handle.write(content)
    except OSError as error:
        parser.exit(1, f"Unable to create demo: {error}\n")

    print(f"Created synthetic demo: {root}")
    print("These are placeholders, not playable media.")


if __name__ == "__main__":
    main()
