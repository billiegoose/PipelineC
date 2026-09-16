# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none
"""Minimal Digilent Basys 3 hardware example for the OpenXC7 backend.

Build with a configured nextpnr-xilinx / Project X-Ray toolchain, for example:

    pypelinec examples/pypeline/basys3_blink.py \
        --syn_tool openxc7 \
        --pins include/pypeline/board/basys3/pins.xdc
"""

from pypeline import *
import board.basys3.part35t
import board.basys3.io as board


@MAIN(100.0)
def basys3_blink():
    counter: Reg[uint32_t] = 0
    led: Reg[uint1_t] = 0

    if counter == (50_000_000 - 1):
        led = ~led
        counter = 0
    else:
        counter = counter + 1

    board.led0 = led
