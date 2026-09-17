#!/usr/bin/env python3
"""Generate OpenXC7 characterization XDC from a synthesized Yosys JSON top."""

import json
import sys


def flattened_port_names(module):
    """Return nextpnr-xilinx PAD names for one synthesized Yosys module."""
    names = []
    for port_name, info in module.get("ports", {}).items():
        width = len(info.get("bits", []))
        if width <= 1:
            names.append(port_name)
            continue
        offset = int(info.get("offset", 0))
        names.extend(f"{port_name}[{offset + index}]" for index in range(width))
    return names


def write_characterization_xdc(json_path, xdc_path, top_entity_name):
    with open(json_path, "r") as f:
        design = json.load(f)
    try:
        module = design["modules"][top_entity_name]
    except KeyError as exc:
        raise RuntimeError(f"Yosys JSON is missing top module {top_entity_name!r}") from exc

    ports = flattened_port_names(module)
    if not ports:
        raise RuntimeError(f"Yosys top module {top_entity_name!r} has no ports")

    with open(xdc_path, "w") as f:
        for port in ports:
            # Braces prevent Tcl/XDC interpretation of [] in vector and struct names.
            f.write(f"set_property IOSTANDARD LVCMOS33 [get_ports {{{port}}}]\n")


def main(argv):
    if len(argv) != 4:
        raise SystemExit(
            "usage: openxc7_characterization_xdc.py YOSYS_JSON XDC TOP_ENTITY"
        )
    write_characterization_xdc(argv[1], argv[2], argv[3])


if __name__ == "__main__":
    main(sys.argv)
