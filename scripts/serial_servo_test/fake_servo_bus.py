#!/usr/bin/env python3
"""Fake serial servo bus on a pty · Dynamixel Protocol 2.0 or Feetech SCS/STS.

Run:  fake_servo_bus.py dxl2|scs <link path> <id>[,<id>...] [--state FILE]
The pty slave is exposed through a symlink at <link path>. A control file
(<link path>.ctl, one command per line, polled) lets a test unplug/replug:
  unplug   · close the pty and remove the link (like pulling the USB cable)
  plug     · new pty, link again
  move <id> <raw>  · set present position while torque is off
The state (control tables, write log, forbidden events) is dumped as JSON to
<link path>.state after every packet.
"""
import json
import os
import pty
import select
import sys
import time
import tty

DXL_MODEL = 1120  # XM540-W270


def crc16(data):
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x8005) if crc & 0x8000 else (crc << 1)
            crc &= 0xFFFF
    return crc


def stuff(payload):
    out = bytearray()
    for b in payload:
        out.append(b)
        if len(out) >= 3 and out[-3:] == b'\xff\xff\xfd':
            out.append(0xFD)
    return bytes(out)


def unstuff(data):
    out = bytearray()
    for b in data:
        out.append(b)
        if len(out) >= 4 and out[-4:] == b'\xff\xff\xfd\xfd':
            out.pop()
    return bytes(out)


class Servo:
    def __init__(self, kind, sid):
        self.kind = kind
        self.id = sid
        self.table = bytearray(1024 if kind == 'dxl2' else 256)
        if kind == 'dxl2':
            self.table[0:2] = DXL_MODEL.to_bytes(2, 'little')
            self.table[7] = sid
            self.table[11] = 3  # Operating Mode · Position (the boot item must make it 4)
            self.torque_addr, self.goal_addr, self.present_addr, self.goal_size = 64, 116, 132, 4
            self.set_present(2048 + 100 * sid)
        else:
            self.table[3:5] = (777).to_bytes(2, 'little')
            self.table[5] = sid
            self.table[33] = 0
            self.torque_addr, self.goal_addr, self.present_addr, self.goal_size = 40, 42, 56, 2
            self.set_present(2048 + 100 * sid)
        self.writes = []
        self.forbidden = []

    def eeprom(self, addr):
        return addr < (64 if self.kind == 'dxl2' else 40)

    def set_present(self, raw):
        if self.kind == 'dxl2':
            self.table[self.present_addr:self.present_addr + 4] = (raw & 0xFFFFFFFF).to_bytes(4, 'little')
        else:
            v = (-raw) | 0x8000 if raw < 0 else raw
            self.table[self.present_addr:self.present_addr + 2] = v.to_bytes(2, 'little')

    def write(self, addr, data):
        self.writes.append([addr, list(data)])
        if self.kind == 'scs' and addr <= self.torque_addr < addr + len(data):
            val = data[self.torque_addr - addr]
            if val not in (0, 1):
                self.forbidden.append(f'torque_enable={val}')
                return 0
        if self.kind == 'dxl2' and self.eeprom(addr) and self.table[self.torque_addr] == 1:
            return 7  # access error
        self.table[addr:addr + len(data)] = data
        # torque on → present follows goal instantly
        if self.table[self.torque_addr] == 1 and addr <= self.goal_addr < addr + len(data):
            g = bytes(self.table[self.goal_addr:self.goal_addr + self.goal_size])
            if self.kind == 'dxl2':
                self.table[self.present_addr:self.present_addr + 4] = g
            else:
                self.table[self.present_addr:self.present_addr + 2] = g
        return 0

    def read(self, addr, n):
        return bytes(self.table[addr:addr + n])

    def dump(self):
        return {'id': self.id, 'torque': self.table[self.torque_addr],
                'goal': list(self.table[self.goal_addr:self.goal_addr + self.goal_size]),
                'present': list(self.table[self.present_addr:self.present_addr + self.goal_size]),
                'mode': self.table[11] if self.kind == 'dxl2' else self.table[33],
                'writes': self.writes[-200:], 'forbidden': self.forbidden}


class Bus:
    def __init__(self, kind, link, ids):
        self.kind = kind
        self.link = link
        self.servos = {i: Servo(kind, i) for i in ids}
        self.buf = bytearray()
        self.master = None
        self.events = []
        self.plug()

    def plug(self):
        self.master, self.slave = pty.openpty()
        tty.setraw(self.slave)
        name = os.ttyname(self.slave)  # kept open: a pty master with no slave reads EIO
        if os.path.lexists(self.link):
            os.remove(self.link)
        os.symlink(name, self.link)
        self.events.append(['plug', time.time()])

    def unplug(self):
        if self.master is not None:
            os.close(self.master)
            os.close(self.slave)
            self.master = None
        if os.path.lexists(self.link):
            os.remove(self.link)
        self.events.append(['unplug', time.time()])

    def send(self, data):
        if self.master is not None:
            try:
                os.write(self.master, data)
            except OSError:
                pass

    # --- Dynamixel Protocol 2.0 ---
    def dxl_status(self, sid, err=0, params=b''):
        payload = bytes([0x55, err]) + params
        st = stuff(payload)
        pkt = bytes([0xFF, 0xFF, 0xFD, 0x00, sid]) + (len(st) + 2).to_bytes(2, 'little') + st
        self.send(pkt + crc16(pkt).to_bytes(2, 'little'))

    def handle_dxl(self):
        while True:
            i = self.buf.find(b'\xff\xff\xfd\x00')
            if i < 0:
                del self.buf[:max(0, len(self.buf) - 3)]
                return
            del self.buf[:i]
            if len(self.buf) < 7:
                return
            ln = int.from_bytes(self.buf[5:7], 'little')
            total = ln + 7
            if len(self.buf) < total:
                return
            pkt = bytes(self.buf[:total])
            del self.buf[:total]
            if crc16(pkt[:-2]) != int.from_bytes(pkt[-2:], 'little'):
                continue
            sid = pkt[4]
            payload = unstuff(pkt[7:-2])
            inst, p = payload[0], payload[1:]
            self.dxl_instruction(sid, inst, p)

    def dxl_instruction(self, sid, inst, p):
        s = self.servos.get(sid)
        if inst == 0x01 and s:
            self.dxl_status(sid, 0, s.read(0, 2) + b'\x2d')
        elif inst == 0x02 and s:
            addr, n = int.from_bytes(p[0:2], 'little'), int.from_bytes(p[2:4], 'little')
            self.dxl_status(sid, 0, s.read(addr, n))
        elif inst == 0x03 and s:
            addr = int.from_bytes(p[0:2], 'little')
            self.dxl_status(sid, s.write(addr, p[2:]))
        elif inst == 0x08 and s:
            self.dxl_status(sid)
            s.table[s.torque_addr] = 0
        elif inst == 0x92 and sid == 0xFE:
            for k in range(0, len(p), 5):
                bid = p[k]
                addr, n = int.from_bytes(p[k + 1:k + 3], 'little'), int.from_bytes(p[k + 3:k + 5], 'little')
                if bid in self.servos:
                    self.dxl_status(bid, 0, self.servos[bid].read(addr, n))
        elif inst == 0x93 and sid == 0xFE:
            k = 0
            while k < len(p):
                bid = p[k]
                addr, n = int.from_bytes(p[k + 1:k + 3], 'little'), int.from_bytes(p[k + 3:k + 5], 'little')
                data = p[k + 5:k + 5 + n]
                if bid in self.servos:
                    self.servos[bid].write(addr, data)
                k += 5 + n
        else:
            self.events.append(['dxl_unknown', inst, sid])

    # --- Feetech SCS/STS ---
    def scs_status(self, sid, err=0, params=b''):
        body = bytes([sid, len(params) + 2, err]) + params
        chk = (~sum(body)) & 0xFF
        self.send(b'\xff\xff' + body + bytes([chk]))

    def handle_scs(self):
        while True:
            i = self.buf.find(b'\xff\xff')
            if i < 0:
                del self.buf[:max(0, len(self.buf) - 1)]
                return
            del self.buf[:i]
            if len(self.buf) < 4:
                return
            ln = self.buf[3]
            total = ln + 4
            if len(self.buf) < total:
                return
            pkt = bytes(self.buf[:total])
            del self.buf[:total]
            if ((~sum(pkt[2:-1])) & 0xFF) != pkt[-1]:
                self.events.append(['scs_bad_checksum'])
                continue
            sid, inst, p = pkt[2], pkt[4], pkt[5:-1]
            self.scs_instruction(sid, inst, p)

    def scs_instruction(self, sid, inst, p):
        s = self.servos.get(sid)
        if inst == 0x06:
            for sv in self.servos.values():
                sv.forbidden.append('RESET')
            return
        if inst == 0x01 and s:
            self.scs_status(sid)
        elif inst == 0x02 and s:
            self.scs_status(sid, 0, s.read(p[0], p[1]))
        elif inst == 0x03 and s:
            s.write(p[0], p[1:])
            self.scs_status(sid)
        elif inst == 0x82 and sid == 0xFE:
            addr, n = p[0], p[1]
            for bid in p[2:]:
                if bid in self.servos:
                    self.scs_status(bid, 0, self.servos[bid].read(addr, n))
        elif inst == 0x83 and sid == 0xFE:
            addr, n = p[0], p[1]
            k = 2
            while k + n < len(p) + 1:
                bid, data = p[k], p[k + 1:k + 1 + n]
                if bid in self.servos:
                    self.servos[bid].write(addr, data)
                k += 1 + n
        else:
            self.events.append(['scs_unknown', inst, sid])

    def dump(self):
        state = {'kind': self.kind, 'plugged': self.master is not None, 'events': self.events[-50:],
                 'servos': {str(k): v.dump() for k, v in self.servos.items()}}
        tmp = self.link + '.state.tmp'
        with open(tmp, 'w') as f:
            json.dump(state, f)
        os.replace(tmp, self.link + '.state')

    def control(self):
        path = self.link + '.ctl'
        if not os.path.exists(path):
            return
        with open(path) as f:
            lines = f.read().split('\n')
        os.remove(path)
        for line in lines:
            parts = line.split()
            if not parts:
                continue
            if parts[0] == 'unplug':
                self.unplug()
            elif parts[0] == 'plug':
                self.plug()
            elif parts[0] == 'move':
                self.servos[int(parts[1])].set_present(int(parts[2]))

    def run(self):
        last_dump = -1.0
        while True:
            self.control()
            fds = [self.master] if self.master is not None else []
            r, _, _ = select.select(fds, [], [], 0.005)
            if r:
                try:
                    data = os.read(self.master, 4096)
                except OSError:
                    data = b''
                self.buf += data
                (self.handle_dxl if self.kind == 'dxl2' else self.handle_scs)()
            now = time.monotonic()  # WSL corrects its wall clock after a cold start
            if now - last_dump > 0.05:
                self.dump()
                last_dump = now


if __name__ == '__main__':
    kind, link, ids = sys.argv[1], sys.argv[2], [int(x) for x in sys.argv[3].split(',')]
    Bus(kind, link, ids).run()
