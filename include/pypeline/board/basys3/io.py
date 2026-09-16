# pyright: reportInvalidTypeForm=none
"""Digilent Basys 3 basic board I/O for Pypeline designs."""

from pypeline import Input, Output, make_clock, uint1_t

# Basys 3 on-board 100 MHz oscillator, PACKAGE_PIN W5.
clk: Input[uint1_t] = make_clock(100.0)

# User LEDs LD0..LD15.
led0: Output[uint1_t]
led1: Output[uint1_t]
led2: Output[uint1_t]
led3: Output[uint1_t]
led4: Output[uint1_t]
led5: Output[uint1_t]
led6: Output[uint1_t]
led7: Output[uint1_t]
led8: Output[uint1_t]
led9: Output[uint1_t]
led10: Output[uint1_t]
led11: Output[uint1_t]
led12: Output[uint1_t]
led13: Output[uint1_t]
led14: Output[uint1_t]
led15: Output[uint1_t]
