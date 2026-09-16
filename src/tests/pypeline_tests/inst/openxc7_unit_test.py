#!/usr/bin/env python3
"""Pure unit coverage for PipelineC's open-source Xilinx 7-series flow.

No FPGA tools are invoked here.  The real Basys 3 hardware proof is kept out of
run_all; these tests pin the configuration/selection behavior that makes that
flow reproducible on any host with a compatible OpenXC7 toolchain.
"""

import os
import shlex
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
    old_artix7 = os.environ.get("ARTIX7_CHIPDB")
    try:
        os.environ.pop("ARTIX7_CHIPDB", None)
        with tempfile.TemporaryDirectory() as tmp_dir:
            candidate = Path(tmp_dir) / "xc7a35t.bin"
            candidate.write_bytes(b"chipdb")
            os.environ["OPENXC7_CHIPDB"] = tmp_dir
            assert OPEN_TOOLS.GET_XC7_CHIPDB_PATH(PART) == str(candidate)
    finally:
        _restore_env("OPENXC7_CHIPDB", old_openxc7)
        _restore_env("ARTIX7_CHIPDB", old_artix7)


def test_xc7_pythonpath_prefix_is_optional_and_shell_quoted():
    old = os.environ.get("OPENXC7_PYTHONPATH")
    try:
        os.environ.pop("OPENXC7_PYTHONPATH", None)
        assert OPEN_TOOLS.GET_XC7_PYTHONPATH_PREFIX() == ""
        value = "/tmp/fasm modules:/opt/project xray/python"
        os.environ["OPENXC7_PYTHONPATH"] = value
        assert OPEN_TOOLS.GET_XC7_PYTHONPATH_PREFIX() == (
            "PYTHONPATH=" + shlex.quote(value) + " "
        )
    finally:
        _restore_env("OPENXC7_PYTHONPATH", old)


def test_part_set_tool_prefers_openxc7_when_available():
    old_tool = SYN.SYN_TOOL
    old_probe = OPEN_TOOLS.XC7_IS_INSTALLED
    try:
        SYN.SYN_TOOL = None
        OPEN_TOOLS.XC7_IS_INSTALLED = lambda part: part == PART
        SYN.PART_SET_TOOL(PART)
        assert SYN.SYN_TOOL is OPEN_TOOLS
    finally:
        SYN.SYN_TOOL = old_tool
        OPEN_TOOLS.XC7_IS_INSTALLED = old_probe


def test_part_set_tool_preserves_vivado_fallback_when_openxc7_unavailable():
    old_tool = SYN.SYN_TOOL
    old_probe = OPEN_TOOLS.XC7_IS_INSTALLED
    try:
        SYN.SYN_TOOL = None
        OPEN_TOOLS.XC7_IS_INSTALLED = lambda part: False
        SYN.PART_SET_TOOL(PART, allow_fail=True)
        assert SYN.SYN_TOOL is SYN.VIVADO
    finally:
        SYN.SYN_TOOL = old_tool
        OPEN_TOOLS.XC7_IS_INSTALLED = old_probe


def test_basys3_board_package_pins_clock_and_part():
    repo_root = Path(__file__).resolve().parents[4]
    board_dir = repo_root / "include" / "pypeline" / "board" / "basys3"

    part_text = (board_dir / "part35t.py").read_text()
    io_text = (board_dir / "io.py").read_text()
    xdc_text = (board_dir / "pins.xdc").read_text()

    assert 'PART("xc7a35tcpg236-1")' in part_text
    assert "make_clock(100.0)" in io_text
    assert "PACKAGE_PIN W5" in io_text
    assert "PACKAGE_PIN U16" in io_text
    assert "LOC W5 [get_ports clk]" in xdc_text
    assert "LOC U16 [get_ports led0]" in xdc_text
    assert "IOSTANDARD LVCMOS33 [get_ports clk]" in xdc_text
    assert "IOSTANDARD LVCMOS33 [get_ports led0]" in xdc_text


def test_pipelinec_cli_exposes_openxc7_override():
    repo_root = Path(__file__).resolve().parents[4]
    cli_text = (repo_root / "src" / "pipelinec").read_text()
    assert 'choices=["pyrtl", "sky130", "openxc7"]' in cli_text
    assert 'elif args.syn_tool == "openxc7":' in cli_text
    assert "SYN.SYN_TOOL = SYN.OPEN_TOOLS" in cli_text


def test_basys3_has_dedicated_openxc7_example():
    repo_root = Path(__file__).resolve().parents[4]
    example_text = (repo_root / "examples" / "pypeline" / "basys3_blink.py").read_text()
    assert "import board.basys3.part35t" in example_text
    assert "import board.basys3.io as board" in example_text
    assert "@MAIN(100.0)" in example_text
    assert "board.led0 = led" in example_text
    assert "--syn_tool openxc7" in example_text


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
