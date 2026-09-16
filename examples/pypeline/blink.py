# pyright: reportInvalidTypeForm=none
# pyright: reportUndefinedVariable=none

from pypeline import *
import board.basys3.part35t
import board.basys3.io as board


@MAIN(100.0)
def blink():
    # Basys 3 clock is 100 MHz. Toggle LD0 every 0.5 s, giving a 1 Hz blink.
    counter: Reg[uint32_t] = 0
    led: Reg[uint1_t] = 0

    if counter == (50_000_000 - 1):
        led = ~led
        counter = 0
    else:
        counter = counter + 1

    board.led0 = led
