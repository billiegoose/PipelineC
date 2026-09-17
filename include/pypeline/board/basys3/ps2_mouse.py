# pyright: reportInvalidTypeForm=none
"""Digilent Basys 3 USB-HID bridge exposed to the FPGA as a PS/2 mouse.

The PIC24 USB host on the board presents PS/2 clock/data on C17/B17.  Both are
open-drain: assigning 0 pulls a line low and assigning 1 releases it.

This deliberately implements only the classic three-byte mouse protocol needed
for a pointer: send F4 (enable reporting), validate incoming PS/2 frames, then
accumulate X/Y deltas and buttons.  X/Y are clamped to a 640x480 coordinate
space, initialized at screen center.
"""

from pypeline import *


clk: Input[uint1_t] = make_clock(100.0)
PS2Clk: OpenDrain[uint1_t]
PS2Data: OpenDrain[uint1_t]


@struct
class ps2_mouse_t(NamedTuple):
    x: uint10_t
    y: uint9_t
    left: uint1_t
    middle: uint1_t
    right: uint1_t
    ready: uint1_t


mouse: Wire[ps2_mouse_t]

# Link states.
_ST_POWER_WAIT = 0
_ST_TX_INHIBIT = 1
_ST_TX_RTS = 2
_ST_TX_START = 3
_ST_TX_BITS = 4
_ST_TX_STOP_ACK = 5
_ST_TX_RELEASE = 6
_ST_WAIT_FA = 7
_ST_STREAM = 8

# 100 MHz board-clock counts.
_POWER_WAIT_CYCLES = 2_000_000   # 20 ms; failed early attempts simply retry.
_INHIBIT_CYCLES = 12_000         # 120 us, PS/2 requires >=100 us.
_RTS_SETUP_CYCLES = 2_000        # 20 us with Clock+Data low before releasing Clock.
_LINK_TIMEOUT_CYCLES = 2_000_000 # 20 ms for device-generated clock / link ACK.
_RESPONSE_TIMEOUT_CYCLES = 5_000_000  # 50 ms for command response byte.


@MAIN(100.0)
def ps2_mouse_io():
    # Two-stage synchronizers for the asynchronous PS/2 wires, plus delayed clock
    # for edge detection in the 100 MHz domain.
    clk_meta: Reg[uint1_t] = 1
    clk_sync: Reg[uint1_t] = 1
    clk_prev: Reg[uint1_t] = 1
    data_meta: Reg[uint1_t] = 1
    data_sync: Reg[uint1_t] = 1

    state: Reg[uint4_t] = _ST_POWER_WAIT
    timer: Reg[uint32_t] = 0
    tx_bit: Reg[uint4_t] = 0

    # Device-to-host byte receiver.
    rx_bit: Reg[uint4_t] = 0
    rx_shift: Reg[uint8_t] = 0
    rx_parity: Reg[uint1_t] = 0
    rx_parity_ok: Reg[uint1_t] = 0

    # Three-byte packet assembly.
    packet_byte: Reg[uint2_t] = 0
    status: Reg[uint8_t] = 0
    dx: Reg[uint8_t] = 0

    # Public mouse state.
    x: Reg[uint10_t] = 320
    y: Reg[uint9_t] = 240
    left: Reg[uint1_t] = 0
    middle: Reg[uint1_t] = 0
    right: Reg[uint1_t] = 0
    ready: Reg[uint1_t] = 0

    # Sample first; edge flags intentionally describe the previously synchronized
    # values, which is exactly what a synchronous edge detector needs.
    clk_fall: uint1_t = clk_prev & (~clk_sync)
    clk_meta = PS2Clk
    clk_sync = clk_meta
    clk_prev = clk_sync
    data_meta = PS2Data
    data_sync = data_meta

    # Open-drain defaults: release both lines.  States below only ever pull low.
    PS2Clk = 1
    PS2Data = 1

    # Byte-complete pulse and value derived by the receive state machine below.
    rx_valid: uint1_t = 0
    rx_byte: uint8_t = rx_shift

    # Never let our receiver interpret the device clock pulses used while we are
    # transmitting.  Receive only while awaiting F4's 0xFA response or streaming.
    receiving: uint1_t = (state == _ST_WAIT_FA) | (state == _ST_STREAM)
    if receiving:
        if clk_fall:
            if rx_bit == 0:
                # Start bit must be zero.  Ignore idle/noise falling edges.
                if data_sync == 0:
                    rx_bit = 1
                    rx_shift = 0
                    rx_parity = 0
                    rx_parity_ok = 0
            elif rx_bit < 9:
                # D0..D7 arrive LSB-first.  Shifting each new bit into bit 7
                # yields the normal byte ordering after all eight samples.
                rx_shift = concat(data_sync, rx_shift[7:1])
                rx_parity = rx_parity ^ data_sync
                rx_bit = rx_bit + 1
            elif rx_bit == 9:
                # Odd parity: eight data bits plus parity bit contain odd 1s.
                rx_parity_ok = rx_parity ^ data_sync
                rx_bit = 10
            else:
                # Stop bit is one.  rx_shift already contains the complete byte.
                if rx_parity_ok & data_sync:
                    rx_valid = 1
                    rx_byte = rx_shift
                rx_bit = 0
    else:
        rx_bit = 0

    # Minimal host initialization: repeatedly send F4 until the mouse returns the
    # normal command response 0xFA, then leave the bus entirely device-driven.
    if state == _ST_POWER_WAIT:
        ready = 0
        if timer >= _POWER_WAIT_CYCLES - 1:
            timer = 0
            state = _ST_TX_INHIBIT
        else:
            timer = timer + 1

    elif state == _ST_TX_INHIBIT:
        PS2Clk = 0
        if timer >= _INHIBIT_CYCLES - 1:
            timer = 0
            state = _ST_TX_RTS
        else:
            timer = timer + 1

    elif state == _ST_TX_RTS:
        PS2Clk = 0
        PS2Data = 0
        if timer >= _RTS_SETUP_CYCLES - 1:
            timer = 0
            state = _ST_TX_START
        else:
            timer = timer + 1

    elif state == _ST_TX_START:
        # Clock is released; Data low is the start bit.  After the device's first
        # falling edge, present D0 while Clock is low.
        PS2Data = 0
        if clk_fall:
            timer = 0
            tx_bit = 0
            state = _ST_TX_BITS
        elif timer >= _LINK_TIMEOUT_CYCLES - 1:
            timer = 0
            state = _ST_TX_INHIBIT
        else:
            timer = timer + 1

    elif state == _ST_TX_BITS:
        # F4 = 11110100b, LSB first.  Bit 8 is odd parity (0 for F4: five data 1s).
        if tx_bit == 0:
            PS2Data = 0
        elif tx_bit == 1:
            PS2Data = 0
        elif tx_bit == 2:
            PS2Data = 1
        elif tx_bit == 3:
            PS2Data = 0
        elif tx_bit == 4:
            PS2Data = 1
        elif tx_bit == 5:
            PS2Data = 1
        elif tx_bit == 6:
            PS2Data = 1
        elif tx_bit == 7:
            PS2Data = 1
        else:
            PS2Data = 0

        if clk_fall:
            timer = 0
            if tx_bit == 8:
                state = _ST_TX_STOP_ACK
            else:
                tx_bit = tx_bit + 1
        elif timer >= _LINK_TIMEOUT_CYCLES - 1:
            timer = 0
            state = _ST_TX_INHIBIT
        else:
            timer = timer + 1

    elif state == _ST_TX_STOP_ACK:
        # Releasing Data supplies the stop bit.  After the device samples it on a
        # rising edge, it pulls Data low for the link-layer ACK; observe that on
        # the following falling edge.
        if clk_fall:
            timer = 0
            if data_sync == 0:
                state = _ST_TX_RELEASE
            else:
                state = _ST_TX_INHIBIT
        elif timer >= _LINK_TIMEOUT_CYCLES - 1:
            timer = 0
            state = _ST_TX_INHIBIT
        else:
            timer = timer + 1

    elif state == _ST_TX_RELEASE:
        if clk_sync & data_sync:
            timer = 0
            rx_bit = 0
            state = _ST_WAIT_FA
        elif timer >= _LINK_TIMEOUT_CYCLES - 1:
            timer = 0
            state = _ST_TX_INHIBIT
        else:
            timer = timer + 1

    elif state == _ST_WAIT_FA:
        if rx_valid:
            timer = 0
            if rx_byte == 250:  # 0xFA command acknowledge
                ready = 1
                packet_byte = 0
                state = _ST_STREAM
            else:
                state = _ST_TX_INHIBIT
        elif timer >= _RESPONSE_TIMEOUT_CYCLES - 1:
            timer = 0
            state = _ST_TX_INHIBIT
        else:
            timer = timer + 1

    else:  # _ST_STREAM
        ready = 1
        if rx_valid:
            if packet_byte == 0:
                # Byte 0 bit 3 is always one; use it as a cheap packet resync.
                if rx_byte[3]:
                    status = rx_byte
                    packet_byte = 1
            elif packet_byte == 1:
                dx = rx_byte
                packet_byte = 2
            else:
                dy: uint8_t = rx_byte
                packet_byte = 0

                left = status[0]
                right = status[1]
                middle = status[2]

                # Ignore overflowing movement axes; buttons still update.
                if status[6] == 0:
                    if status[4]:
                        x_mag: uint9_t = 256 - dx
                        if x >= x_mag:
                            x = x - x_mag
                        else:
                            x = 0
                    else:
                        x_sum: uint10_t = x + dx
                        if x_sum > 639:
                            x = 639
                        else:
                            x = x_sum

                # PS/2 positive Y is upward; VGA Y increases downward.
                if status[7] == 0:
                    if status[5]:
                        y_mag: uint9_t = 256 - dy
                        y_sum: uint10_t = y + y_mag
                        if y_sum > 479:
                            y = 479
                        else:
                            y = y_sum[8:0]
                    else:
                        if y >= dy:
                            y = y - dy
                        else:
                            y = 0

    mouse = ps2_mouse_t(
        x=x,
        y=y,
        left=left,
        middle=middle,
        right=right,
        ready=ready,
    )
