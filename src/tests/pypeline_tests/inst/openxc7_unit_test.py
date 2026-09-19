#!/usr/bin/env python3
"""Pure unit coverage for PipelineC's open-source Xilinx 7-series flow.

No FPGA tools are invoked here.  The real Basys 3 hardware proof is kept out of
run_all; these tests pin the configuration/selection behavior that makes that
flow reproducible on any host with a compatible OpenXC7 toolchain.
"""

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../")
)

import C_TO_LOGIC  # Establish PipelineC's normal module-import order.
import SYN
import OPEN_TOOLS


PART = "xc7a35tcpg236-1"


def _restore_env(name, old):
    if old is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = old


def test_xc7_part_and_chipdb_candidates():
    assert OPEN_TOOLS.IS_XC7_PART(PART)
    assert not OPEN_TOOLS.IS_XC7_PART("LFE5U-85F-6BG381C")
    assert OPEN_TOOLS._XC7_ARCH_CHIPDB_NAMES(PART) == [
        "xc7a35tcpg236.bin",
        "xc7a35t.bin",
    ]


def test_xc7_chipdb_directory_lookup_accepts_device_fallback():
    old_openxc7 = os.environ.get("OPENXC7_CHIPDB")
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            candidate = Path(tmp_dir) / "xc7a35t.bin"
            candidate.write_bytes(b"chipdb")
            os.environ["OPENXC7_CHIPDB"] = tmp_dir
            assert OPEN_TOOLS.GET_XC7_CHIPDB_PATH(PART) == str(candidate)
    finally:
        _restore_env("OPENXC7_CHIPDB", old_openxc7)


def test_part_set_tool_keeps_existing_xilinx_vivado_default():
    old_tool = SYN.SYN_TOOL
    try:
        SYN.SYN_TOOL = None
        SYN.PART_SET_TOOL(PART, allow_fail=True)
        assert SYN.SYN_TOOL is SYN.VIVADO
    finally:
        SYN.SYN_TOOL = old_tool


def test_openxc7_characterization_avoids_physical_iopads():
    import openxc7_characterization_netlist

    repo_root = Path(__file__).resolve().parents[4]
    open_tools_text = (repo_root / "src" / "OPEN_TOOLS.py").read_text()
    assert 'xc7_iopad_arg = "" if is_final_top else " -noiopad"' in open_tools_text
    assert "xc7{xc7_iopad_arg} -top {top_entity_name}" in open_tools_text
    assert "openxc7_characterization_netlist.py" in open_tools_text
    assert "openxc7_characterization.xdc" not in open_tools_text

    with tempfile.TemporaryDirectory() as tmp_dir:
        json_path = Path(tmp_dir) / "top.json"
        json_path.write_text(
            json.dumps(
                {
                    "modules": {
                        "timing_top": {
                            "ports": {
                                "clk": {"direction": "input", "bits": [2]},
                                "a": {"direction": "input", "bits": [3, 4]},
                                "y": {"direction": "output", "bits": [5]},
                            },
                            "netnames": {
                                "clk": {"bits": [2]},
                                "a_input_reg": {"bits": [6, 7]},
                                "y_output_reg": {"bits": [8]},
                            },
                            "cells": {
                                "input_ff": {
                                    "type": "FDRE",
                                    "connections": {"C": [9], "D": [3], "Q": [6]},
                                },
                                "output_ff": {
                                    "type": "FDRE",
                                    "connections": {"C": [9], "D": [10], "Q": [5]},
                                },
                            },
                        }
                    }
                }
            )
        )
        openxc7_characterization_netlist.strip_top_ports(json_path, "timing_top")
        netlist = json.loads(json_path.read_text())
        top = netlist["modules"]["timing_top"]
        assert top["ports"] == {}
        assert top["netnames"]["a_input_reg"]["bits"] == [6, 7]
        assert top["cells"]["input_ff"]["type"] == "FDRE"
        assert top["cells"]["output_ff"]["type"] == "FDRE"


def test_openxc7_timing_parser_accepts_colons_in_synthesized_clock_names():
    text = """\
Info: Critical path report for clock '$auto$clkbufmap.cc:294:execute$2176' (posedge -> posedge):
Info: curr total
Info:  0.1  0.1  Source input_ff.Q
Info:  1.8  1.9    Net logic
Info:                Sink output_ff.D
Info:  0.1  2.0  Setup output_ff.D
Info: 1.3 ns logic, 0.7 ns routing
Info: Max frequency for clock '$auto$clkbufmap.cc:294:execute$2176': 498.50 MHz (FAIL at 1000.00 MHz)
"""
    report = OPEN_TOOLS.ParsedTimingReport(text)
    assert "$auto$clkbufmap.cc:294:execute$2176" in report.path_reports
    path = report.path_reports["$auto$clkbufmap.cc:294:execute$2176"]
    assert abs(path.path_delay_ns - (1000.0 / 498.50)) < 1e-9
    assert path.source_ns_per_clock == 1.0


def test_openxc7_comb_timing_uses_board_constrained_final_top():
    repo_root = Path(__file__).resolve().parents[4]
    syn_text = (repo_root / "src" / "SYN.py").read_text()
    assert "SYN_TOOL is OPEN_TOOLS and OPEN_TOOLS.IS_XC7_PART(parser_state.part)" in syn_text
    assert "timing_report = OPEN_TOOLS.SYN_AND_REPORT_TIMING_NEW(" in syn_text
    assert "is_final_top=True" in syn_text


def test_pipelinec_cli_exposes_openxc7_override():
    repo_root = Path(__file__).resolve().parents[4]
    cli_text = (repo_root / "src" / "pipelinec").read_text()
    assert 'choices=["pyrtl", "sky130", "openxc7"]' in cli_text
    assert 'elif args.syn_tool == "openxc7":' in cli_text
    assert "SYN.SYN_TOOL = SYN.OPEN_TOOLS" in cli_text


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
