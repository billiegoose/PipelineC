#!/usr/bin/env python3
"""Explicit Basys 3 OpenXC7 hardware smoke test.

This helper is intentionally NOT part of the automated test suite. It validates
an already-built .bit file and loads it into volatile FPGA SRAM only. It never
passes openFPGALoader's ``-f`` option, so the board's configuration flash is not
modified.
"""

import argparse
import os
import shutil
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("bitstream", help="Basys 3 .bit file to load into volatile SRAM")
    parser.add_argument(
        "--openfpgaloader",
        default=shutil.which("openFPGALoader") or "/usr/local/bin/openFPGALoader",
        help="openFPGALoader executable",
    )
    args = parser.parse_args()

    bitstream = os.path.abspath(args.bitstream)
    if not os.path.isfile(bitstream) or os.path.getsize(bitstream) == 0:
        parser.error(f"bitstream is missing or empty: {bitstream}")
    if not os.path.isfile(args.openfpgaloader) and shutil.which(args.openfpgaloader) is None:
        parser.error(f"openFPGALoader not found: {args.openfpgaloader}")

    cmd = [args.openfpgaloader, "--board", "basys3", "--bitstream", bitstream]
    print("Volatile SRAM load only; configuration flash will not be written.", flush=True)
    print("Running:", " ".join(cmd), flush=True)
    return subprocess.call(cmd)


if __name__ == "__main__":
    sys.exit(main())
