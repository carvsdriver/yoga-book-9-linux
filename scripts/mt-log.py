#!/usr/bin/env python3
"""
mt-log.py — Multi-touch event logger for INGENIC touchscreen diagnostics.

Reads raw evdev events from a /dev/input/eventX device and prints a
per-sync-frame summary showing active contacts, tracking IDs, and positions.
Helps identify ghost contacts, stale slots, and protocol violations.

Usage:
    python3 mt-log.py [/dev/input/eventN]         # default: event7 (top screen)
    python3 mt-log.py event8                       # bottom screen
    python3 mt-log.py --raw                        # also dump every raw event
    python3 mt-log.py --duration=60                # auto-stop after 60 seconds
    python3 mt-log.py --duration=60 > /tmp/mt.log  # write to file, no terminal needed

Output key:
    SYNC  #N  fingers=K  slot0:tid=N@(x,y)  slot1:tid=N@(x,y) ...
    SYNC  DROPPED  (SYN_DROPPED — kernel lost events, data unreliable)
    WARNING — slots still ACTIVE at exit (stuck finger or ghost)

Ctrl-C to stop, or use --duration for unattended capture.
"""

import sys
import struct
import time
import select

# input_event: struct timeval (8+8) + __u16 type + __u16 code + __s32 value = 24 bytes
EVENT_FMT = "llHHi"
EVENT_SIZE = struct.calcsize(EVENT_FMT)

EV_SYN               = 0x00
EV_ABS               = 0x03
SYN_REPORT           = 0
SYN_DROPPED          = 3
ABS_MT_SLOT          = 0x2f
ABS_MT_TRACKING_ID   = 0x39
ABS_MT_POSITION_X    = 0x35
ABS_MT_POSITION_Y    = 0x36

MAX_SLOTS = 16


def main():
    raw_mode = "--raw" in sys.argv
    duration = None
    args = []
    for a in sys.argv[1:]:
        if a.startswith("--duration="):
            duration = float(a.split("=", 1)[1])
        elif not a.startswith("--"):
            args.append(a)

    dev = f"/dev/input/{args[0]}" if args and not args[0].startswith("/") else \
          args[0] if args else "/dev/input/event7"

    print(f"mt-log: reading {dev}", flush=True)
    if duration:
        print(f"mt-log: auto-stop after {duration:.0f}s", flush=True)
    print("", flush=True)

    deadline = (time.time() + duration) if duration else None

    slot_id = [-1] * MAX_SLOTS
    slot_x  = [0]  * MAX_SLOTS
    slot_y  = [0]  * MAX_SLOTS
    cur_slot = 0
    frame = 0

    def print_summary():
        still_active = [(i, slot_id[i], slot_x[i], slot_y[i])
                        for i in range(MAX_SLOTS) if slot_id[i] != -1]
        print(f"\nmt-log: {frame} sync frames total", flush=True)
        if still_active:
            print(f"mt-log: WARNING — {len(still_active)} slot(s) still ACTIVE at exit "
                  f"(stuck finger or ghost):", flush=True)
            for i, tid, x, y in still_active:
                print(f"  slot{i}: tid={tid} @ ({x},{y})", flush=True)
        else:
            print("mt-log: all slots clean at exit", flush=True)

    try:
        with open(dev, "rb") as f:
            while True:
                if deadline:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        break
                    ready, _, _ = select.select([f], [], [], min(remaining, 0.1))
                    if not ready:
                        continue
                else:
                    ready, _, _ = select.select([f], [], [], 1.0)
                    if not ready:
                        continue

                data = f.read(EVENT_SIZE)
                if len(data) < EVENT_SIZE:
                    break

                _, _, typ, code, value = struct.unpack(EVENT_FMT, data)

                if raw_mode:
                    print(f"  RAW  t={typ:02x} c={code:04x} v={value:8d}", flush=True)

                if typ == EV_ABS:
                    if code == ABS_MT_SLOT and 0 <= value < MAX_SLOTS:
                        cur_slot = value
                    elif code == ABS_MT_TRACKING_ID:
                        slot_id[cur_slot] = value
                    elif code == ABS_MT_POSITION_X:
                        slot_x[cur_slot] = value
                    elif code == ABS_MT_POSITION_Y:
                        slot_y[cur_slot] = value

                elif typ == EV_SYN:
                    if code == SYN_REPORT:
                        frame += 1
                        active = [(i, slot_id[i], slot_x[i], slot_y[i])
                                  for i in range(MAX_SLOTS) if slot_id[i] != -1]
                        contacts = "  ".join(
                            f"slot{i}:tid={tid}@({x},{y})"
                            + (" [GHOST?]" if x == 0 and y == 0 else "")
                            for i, tid, x, y in active
                        )
                        print(f"SYNC #{frame:5d}  fingers={len(active)}  {contacts}",
                              flush=True)
                    elif code == SYN_DROPPED:
                        print("SYNC DROPPED  (kernel lost events)", flush=True)

        print_summary()

    except KeyboardInterrupt:
        print_summary()
    except PermissionError:
        print(f"mt-log: permission denied — try: sudo python3 mt-log.py", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
