#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Regression coverage for dependency-driven pipeline scheduling."""

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "../../../"))

import AUTO_PIPELINE
import C_TO_LOGIC
import PY_TO_LOGIC


def _root(state, func_name):
    return next(
        name
        for name in state.main_mhz
        if state.LogicInstLookupTable[name].func_name == func_name
    )


def _write_zero_latency_chain(directory: str, count: int) -> str:
    path = Path(directory) / "large_zero_latency_chain.py"
    lines = [
        "from pypeline import *",
        "",
        "@hw_func",
        "def step(x: uint16_t) -> uint16_t:",
        "    return x + 1",
        "",
        "@MAIN",
        "def chain(x: uint16_t) -> uint16_t:",
        "    y: uint16_t = x",
    ]
    lines.extend("    y = step(y)" for _ in range(count))
    lines.append("    return y")
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def _write_mixed_latency_graph(directory: str) -> str:
    path = Path(directory) / "mixed_latency_graph.py"
    path.write_text(
        """from pypeline import *

@pipeline_latency(1)
def delay1(x: uint16_t) -> uint16_t:
    return x

@pipeline_latency(2)
def delay2(x: uint16_t) -> uint16_t:
    return x

@MAIN
def mixed(x: uint16_t) -> uint16_t:
    a = delay1(x)
    b = delay2(x)
    return delay1(a + b)
"""
    )
    return str(path)


def test_scheduler_discovers_each_input_dependency_once():
    count = 64
    with tempfile.TemporaryDirectory() as directory:
        state = PY_TO_LOGIC.PARSE_FILE(
            _write_zero_latency_chain(directory, count)
        )
        root = _root(state, "chain")
        logic = state.LogicInstLookupTable[root]
        timing = AUTO_PIPELINE.GET_ZERO_ADDED_CLKS_TIMING_PARAMS_LOOKUP(state)
        assert len(logic.submodule_instances) == count

        input_driver_lookups = 0
        original = C_TO_LOGIC.GET_SUBMODULE_INPUT_PORT_DRIVING_WIRE

        def counted(*args, **kwargs):
            nonlocal input_driver_lookups
            input_driver_lookups += 1
            return original(*args, **kwargs)

        C_TO_LOGIC.GET_SUBMODULE_INPUT_PORT_DRIVING_WIRE = counted
        try:
            pipeline_map = AUTO_PIPELINE.GET_PIPELINE_MAP(root, logic, state, timing)
        finally:
            C_TO_LOGIC.GET_SUBMODULE_INPUT_PORT_DRIVING_WIRE = original

    # There is exactly one input edge per step. The dependency index discovers
    # each edge once; there is no later readiness recheck. The repeated-scan
    # scheduler did 2080 lookups for this graph; the sidecar fast path did 128.
    assert input_driver_lookups == count, input_driver_lookups
    assert pipeline_map.num_stages == 1
    scheduled = sum(
        len(level.submodule_insts)
        for stage in pipeline_map.stage_infos
        for level in stage.submodule_level_infos
    )
    assert scheduled == count, scheduled


def test_mixed_latency_outputs_wake_only_their_ready_stage():
    with tempfile.TemporaryDirectory() as directory:
        state = PY_TO_LOGIC.PARSE_FILE(_write_mixed_latency_graph(directory))
        root = _root(state, "mixed")
        logic = state.LogicInstLookupTable[root]
        timing = {
            name: AUTO_PIPELINE.TimingParams(name, sublogic)
            for name, sublogic in state.LogicInstLookupTable.items()
        }
        pipeline_map = AUTO_PIPELINE.GET_PIPELINE_MAP(root, logic, state, timing)

    assert pipeline_map.num_stages == 4

    scheduled_funcs = []
    output_funcs = []
    for stage in pipeline_map.stage_infos[:4]:
        scheduled_funcs.append(
            [
                logic.submodule_instances[submodule_inst]
                for level in stage.submodule_level_infos
                for submodule_inst in level.submodule_insts
            ]
        )
        output_funcs.append(
            [
                logic.submodule_instances[
                    output_wire.split(C_TO_LOGIC.SUBMODULE_MARKER)[0]
                ]
                for output_wire in stage.submodule_output_ports
            ]
        )

    # delay1 and delay2 launch together at stage 0. Their outputs become visible
    # at stages 1 and 2 respectively. When delay2 arrives, the zero-latency add
    # and the final delay1 both schedule in stage 2; that delay1 appears at 3.
    assert scheduled_funcs == [
        ["delay1", "delay2"],
        [],
        ["BIN_OP_PLUS_uint16_t_uint16_t", "delay1"],
        [],
    ], scheduled_funcs
    assert output_funcs == [
        [],
        ["delay1"],
        ["delay2"],
        ["delay1"],
    ], output_funcs


if __name__ == "__main__":
    from _test_main import run_module_tests

    run_module_tests()
