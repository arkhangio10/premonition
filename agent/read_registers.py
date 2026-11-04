#!/usr/bin/env python3
"""Lee el PCA9685 sin escribir registros. Son pulsos comandados, no la posición física del brazo."""
import json

import smbus

BUS, ADDR = 1, 0x40
MODE1, LED0, PRESCALE = 0x00, 0x06, 0xFE
FULL_OFF = 0x10
PERIOD_US = 20000
JOINTS = ["base", "shoulder", "elbow", "wrist_pitch", "wrist_roll", "gripper"]


def read_us(bus, channel):
    base = LED0 + 4 * channel
    on_l, on_h, off_l, off_h = [bus.read_byte_data(ADDR, base + i) for i in range(4)]
    if off_h & FULL_OFF or on_h & FULL_OFF:
        return None
    count = (((off_h & 0x0F) << 8 | off_l) - ((on_h & 0x0F) << 8 | on_l)) % 4096
    return int(round(count * PERIOD_US / 4096.0))


def main():
    bus = smbus.SMBus(BUS)
    try:
        print(json.dumps({"mode1": bus.read_byte_data(ADDR, MODE1),
                          "prescale": bus.read_byte_data(ADDR, PRESCALE),
                          "commanded_us": {joint: read_us(bus, channel) for channel, joint in enumerate(JOINTS)}}))
    finally:
        bus.close()


if __name__ == "__main__":
    main()
