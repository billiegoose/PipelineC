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
    wheel: uint8_t
    wheel_mode: uint1_t
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
_ST_WAIT_ID = 8
_ST_STREAM = 9

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
    tx_byte: Reg[uint8_t] = 243  # 0xF3, first IntelliMouse negotiation command.
    init_step: Reg[uint4_t] = 0

    # Device-to-host byte receiver.
    rx_bit: Reg[uint4_t] = 0
    rx_shift: Reg[uint8_t] = 0
    rx_parity: Reg[uint1_t] = 0
    rx_parity_ok: Reg[uint1_t] = 0

    # Three- or four-byte packet assembly (four bytes in IntelliMouse wheel mode).
    packet_byte: Reg[uint2_t] = 0
    status: Reg[uint8_t] = 0
    dx: Reg[uint8_t] = 0
    dy: Reg[uint8_t] = 0

    # Public mouse state.  `wheel` is a wrapping cumulative position so a wheel
    # detent remains observable long after the packet-level delta has passed.
    x: Reg[uint10_t] = 320
    y: Reg[uint9_t] = 240
    left: Reg[uint1_t] = 0
    middle: Reg[uint1_t] = 0
    right: Reg[uint1_t] = 0
    wheel: Reg[uint8_t] = 0
    wheel_mode: Reg[uint1_t] = 0
    ready: Reg[uint1_t] = 0

    # Publish only registered state.  Pypeline forwards later Reg assignments
    # within this function, so constructing `mouse` directly from x/y/buttons at
    # the end would expose their combinational next-state logic to every consumer
    # (notably the VGA renderer).  These snapshots deliberately add one 100 MHz
    # cycle of output latency and keep the module boundary register-to-register.
    out_x: uint10_t = x
    out_y: uint9_t = y
    out_left: uint1_t = left
    out_middle: uint1_t = middle
    out_right: uint1_t = right
    out_wheel: uint8_t = wheel
    out_wheel_mode: uint1_t = wheel_mode
    out_ready: uint1_t = ready

    # Sample first; edge flags intentionally describe the previously synchronized
    # values, which is exactly what a synchronous edge detector needs.
    clk_fall: uint1_t = clk_prev & (~clk_sync)
    # Pypeline forwards sequential assignments within a hardware function, so
    # shift-register transfers must be written oldest-destination first.  This
    # preserves the previous-cycle values instead of collapsing every stage to
    # the current asynchronous pad sample.
    clk_prev = clk_sync
    clk_sync = clk_meta
    clk_meta = PS2Clk
    data_sync = data_meta
    data_meta = PS2Data

    # Open-drain defaults: release both lines.  States below only ever pull low.
    PS2Clk = 1
    PS2Data = 1

    # Byte-complete pulse and value derived by the receive state machine below.
    rx_valid: uint1_t = 0
    rx_byte: uint8_t = rx_shift

    # Never let our receiver interpret device clocks used while transmitting.
    # During initialization we receive command ACKs and, after F2, the device ID.
    receiving: uint1_t = (
        (state == _ST_WAIT_FA) | (state == _ST_WAIT_ID) | (state == _ST_STREAM)
    )
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
            init_step = 0
            tx_byte = 243  # 0xF3 Set Sample Rate
            wheel_mode = 0
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
        # Commands and parameters are sent LSB-first.  Bit 8 supplies odd parity.
        if tx_bit == 0:
            PS2Data = tx_byte[0]
        elif tx_bit == 1:
            PS2Data = tx_byte[1]
        elif tx_bit == 2:
            PS2Data = tx_byte[2]
        elif tx_bit == 3:
            PS2Data = tx_byte[3]
        elif tx_bit == 4:
            PS2Data = tx_byte[4]
        elif tx_bit == 5:
            PS2Data = tx_byte[5]
        elif tx_bit == 6:
            PS2Data = tx_byte[6]
        elif tx_bit == 7:
            PS2Data = tx_byte[7]
        else:
            PS2Data = ~(
                tx_byte[0] ^ tx_byte[1] ^ tx_byte[2] ^ tx_byte[3]
                ^ tx_byte[4] ^ tx_byte[5] ^ tx_byte[6] ^ tx_byte[7]
            )

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
                # IntelliMouse wheel negotiation is the canonical sample-rate
                # sequence 200, 100, 80 followed by F2 Read Device ID.  Every
                # command byte and parameter byte is separately acknowledged.
                if init_step == 0:
                    tx_byte = 200
                    init_step = 1
                    state = _ST_TX_INHIBIT
                elif init_step == 1:
                    tx_byte = 243  # F3
                    init_step = 2
                    state = _ST_TX_INHIBIT
                elif init_step == 2:
                    tx_byte = 100
                    init_step = 3
                    state = _ST_TX_INHIBIT
                elif init_step == 3:
                    tx_byte = 243  # F3
                    init_step = 4
                    state = _ST_TX_INHIBIT
                elif init_step == 4:
                    tx_byte = 80
                    init_step = 5
                    state = _ST_TX_INHIBIT
                elif init_step == 5:
                    tx_byte = 242  # F2 Read Device ID
                    init_step = 6
                    state = _ST_TX_INHIBIT
                elif init_step == 6:
                    state = _ST_WAIT_ID
                else:
                    # F4 Enable Data Reporting has been acknowledged.
                    ready = 1
                    packet_byte = 0
                    state = _ST_STREAM
            else:
                # Retry the current byte after an unexpected response.
                state = _ST_TX_INHIBIT
        elif timer >= _RESPONSE_TIMEOUT_CYCLES - 1:
            timer = 0
            state = _ST_TX_INHIBIT
        else:
            timer = timer + 1

    elif state == _ST_WAIT_ID:
        if rx_valid:
            timer = 0
            # ID 3 is IntelliMouse wheel mode; accept ID 4 too in case a bridge
            # exposes the five-button extension.  ID 0 gracefully retains the
            # working classic three-byte packet format.
            wheel_mode = (rx_byte == 3) | (rx_byte == 4)
            tx_byte = 244  # F4 Enable Data Reporting
            init_step = 7
            state = _ST_TX_INHIBIT
        elif timer >= _RESPONSE_TIMEOUT_CYCLES - 1:
            # Failure to obtain an ID must not regress ordinary mouse support.
            timer = 0
            wheel_mode = 0
            tx_byte = 244
            init_step = 7
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
            elif packet_byte == 2:
                dy = rx_byte

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
                        y_mag: uint9_t = 256 - rx_byte
                        y_sum: uint10_t = y + y_mag
                        if y_sum > 479:
                            y = 479
                        else:
                            y = y_sum[8:0]
                    else:
                        if y >= rx_byte:
                            y = y - rx_byte
                        else:
                            y = 0

                if wheel_mode:
                    packet_byte = 3
                else:
                    packet_byte = 0
            else:
                # IntelliMouse Z is a signed four-bit two's-complement delta.
                # Accumulate modulo 256 so every detent remains visible to a
                # slow video consumer without needing a pulse stretcher.
                z: uint4_t = rx_byte[3:0]
                if z[3]:
                    z_mag: uint5_t = 16 - z
                    wheel = wheel - z_mag
                else:
                    wheel = wheel + z
                packet_byte = 0

    mouse = ps2_mouse_t(
        x=out_x,
        y=out_y,
        left=out_left,
        middle=out_middle,
        right=out_right,
        wheel=out_wheel,
        wheel_mode=out_wheel_mode,
        ready=out_ready,
    )
