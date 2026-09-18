# pyright: reportInvalidTypeForm=none
"""Digilent Basys 3 USB-UART bridge pins.

Use this narrow board module for reusable serial transports so importing UART
support does not also declare unrelated LEDs, switches, buttons, or seven-segment
outputs from `board.basys3.io`.
"""

from pypeline import Input, Output, make_clock, uint1_t

clk: Input[uint1_t] = make_clock(100.0)

# PCB / Digilent constraint names: host -> FPGA and FPGA -> host respectively.
RsRx: Input[uint1_t]
RsTx: Output[uint1_t]
