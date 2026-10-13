#!/usr/bin/env python3
"""MINAS 드라이브를 「처음 연결」 상태에 가깝게 · 시험용 · 2026-10-13 (사용자 요청 · 미니 PC 에서 실행)

전체 공장 초기화가 아니다 · 파라미터 (고급) 표의 객체(`drive_params.CATALOG`)만 출하값으로 · 나머지 수백 개
(필터 · 진동 억제 · 출력 핀 등)는 그대로 · 완전 초기화는 PANATERM 으로만 된다.

    python3 scripts/minas_factory_reset.py                 # 읽고 기록만 (기본 · 안전)
    python3 scripts/minas_factory_reset.py --apply         # 출하값 쓰기 + 앱솔루트 1 + Alias 0 + EEPROM 저장

--apply 조건 · 모터 프로그램이 멈춰 있어야 한다(`systemctl --user stop motion-motor`) · 끝나면 드라이브 제어
전원을 껐다 켠다(앱솔루트 방식 · Alias 는 그때 반영) · 그 뒤 웹 「앱솔루트 설정」 부터 다시.

입력 핀(SI1~8 · Pr4.00~4.07)은 **되돌리지 않는다** · 출하값은 리밋 스위치(POT/NOT)가 켜진 배선이라
스위치가 없는 축은 한 방향으로 못 움직이거나 Err38 · 다르면 기록만 한다(--include-pins 로 강제).
CiA402 의 「모터 설정에서 계산」(auto) 값은 부팅 때 다시 쓰이므로 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'web_bridge'))
from motion_web_bridge.drive_params import CATALOG  # noqa: E402

MINAS_VENDOR = 0x066F
ABSOLUTE_FACTORY = 1          # Pr0.15 출하값 · 인크리멘털 · A6B 레퍼런스 부록


def run(command, check=False):
    done = subprocess.run(command, capture_output=True, text=True, timeout=20)
    if check and done.returncode != 0:
        raise RuntimeError(f"{' '.join(command)} · {(done.stderr or done.stdout).strip()}")
    return done


def minas_slaves(master: int):
    text = run(['ethercat', 'slaves', '-m', str(master), '-v'], check=True).stdout
    slaves = []
    for block in re.split(r'(?m)^=== ', text)[1:]:
        position = re.search(r'Slave (\d+)', block)
        vendor = re.search(r'Vendor Id:\s+(0x[0-9a-fA-F]+)', block)
        alias = re.search(r'Alias:\s+(\d+)', block)
        if position and vendor and int(vendor.group(1), 16) == MINAS_VENDOR:
            slaves.append({'position': int(position.group(1)), 'alias': int(alias.group(1)) if alias else None})
    return slaves


def upload(master, position, index, sub, data_type):
    done = run(['ethercat', 'upload', '-m', str(master), '-p', str(position), '-t', data_type, f'0x{index:04X}', str(sub)])
    if done.returncode != 0:
        return None, (done.stderr or done.stdout).strip()
    try:
        return int(done.stdout.split()[-1], 0), ''
    except (IndexError, ValueError):
        return None, done.stdout.strip()


def download(master, position, index, sub, data_type, value):
    run(['ethercat', 'download', '-m', str(master), '-p', str(position), '-t', data_type, f'0x{index:04X}', str(sub), str(value)],
        check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description='MINAS 드라이브 · 파라미터 (고급) 표 객체를 출하값으로(시험용)')
    parser.add_argument('--master', type=int, default=0)
    parser.add_argument('--apply', action='store_true', help='출하값 쓰기 + 앱솔루트 1 + Alias 0 + EEPROM 저장')
    parser.add_argument('--include-pins', action='store_true', help='입력 핀(SI1~8)도 출하값으로 · 리밋 스위치가 배선된 경우만')
    parser.add_argument('--keep-alias', action='store_true', help='Alias 는 그대로')
    args = parser.parse_args()

    if args.apply and run(['systemctl', '--user', 'is-active', 'motion-motor']).stdout.strip() == 'active':
        print('!! 모터 프로그램이 돌고 있습니다 · 먼저 `systemctl --user stop motion-motor` (서보 꺼짐 · 브레이크 없는 축은 받치기)')
        return 2

    report = {'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'apply': args.apply, 'drives': []}
    for slave in minas_slaves(args.master):
        position = slave['position']
        rows = []
        for group, label, number, index, sub, data_type, factory, _unit, memo in CATALOG:
            value, error = upload(args.master, position, index, sub, data_type)
            rows.append({'number': number, 'label': label, 'group': group, 'index': f'0x{index:04X}', 'sub': sub,
                         'type': data_type, 'value': value, 'factory': factory, 'memo': memo, 'error': error,
                         'differs': value is not None and factory is not None and value != factory})
        drive = {'position': position, 'alias': slave['alias'], 'rows': rows, 'written': [], 'skipped': []}
        print(f'\n== 슬레이브 {position} · Alias {slave["alias"]}')
        for row in rows:
            if row['differs'] or row['error']:
                mark = '못 읽음 ' + row['error'] if row['error'] else f"{row['value']} (출하 {row['factory']})"
                print(f"  {row['number']:<9} {row['label']:<24} {mark}")
        if args.apply:
            for row, (group, _l, _n, index, sub, data_type, factory, _u, memo) in zip(rows, CATALOG):
                if factory is None or memo == 'auto' or index == 0x3015:
                    continue
                if group == '입력 핀' and not args.include_pins:
                    if row['differs']:
                        drive['skipped'].append(row['number'])
                    continue
                if row['value'] != factory:
                    download(args.master, position, index, sub, data_type, factory)
                    drive['written'].append(row['number'])
            download(args.master, position, 0x3015, 0, 'int16', ABSOLUTE_FACTORY)          # 앱솔루트 → 인크리멘털
            drive['written'].append('Pr0.15')
            download(args.master, position, 0x1010, 1, 'uint32', 0x65766173)              # EEPROM 저장 ("save")
            time.sleep(3)
            if not args.keep_alias and slave['alias']:
                run(['ethercat', 'alias', '-m', str(args.master), '-p', str(position), '0'], check=True)
                drive['written'].append('Alias → 0')
            print(f"  썼음 · {', '.join(drive['written'])}")
            if drive['skipped']:
                print(f"  입력 핀은 출하값과 다르지만 그대로 둠 · {', '.join(drive['skipped'])} (리밋 스위치 배선 확인 뒤 --include-pins)")
        report['drives'].append(drive)

    out = ROOT / 'log' / 'field_check' / f"minas_factory_{'apply' if args.apply else 'report'}_{time.strftime('%Y%m%d_%H%M%S')}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'\n기록 · {out}')
    if args.apply:
        print('끝 · 드라이브 제어 전원을 껐다 켜세요(앱솔루트 방식 · Alias 반영) → `systemctl --user start motion-motor` → 웹 「전체 검색」')
    return 0


if __name__ == '__main__':
    sys.exit(main())
