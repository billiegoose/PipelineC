# pyright: reportInvalidTypeForm=none
"""Digilent Basys 3 basic board I/O used by simple Pypeline designs."""

from pypeline import Input, Output, make_clock, uint1_t

# Basys 3 on-board 100 MHz oscillator, PACKAGE_PIN W5.
clk: Input[uint1_t] = make_clock(100.0)

# First user LED, LD0, PACKAGE_PIN U16.
led0: Output[uint1_t]
