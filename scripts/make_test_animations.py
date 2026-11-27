#!/usr/bin/env python3
"""실물 시험용 애니메이션 만들기 · 관절 N개 · Blender 내보내기와 같은 형식(JSON Lines · 50 fps)

    python3 scripts/make_test_animations.py --out ~/test_anims
    python3 scripts/make_test_animations.py --out ~/test_anims --joints 1-1,1-2,1-3 --amp-deg 20

만드는 파일 (값은 조인트 각도 · 매핑의 감속비·방향·기준점이 모터 값으로 바꾼다)
    t01_sine_rad        20 s · 관절마다 위상 어긋난 사인 · 0.1 Hz 2주기(처음 = 끝 = 0) · 첫 관절 ±A · 나머지 최대 약 ±1.9A · rad
    t02_sine_deg        t01 과 같은 움직임 · 헤더 deg            → t01 과 같은 크기로 돌아야 한다(6-2)
    t03_sine_noheader   t01 과 같은 움직임 · 헤더에 단위 칸 없음(= deg) → 같은 크기(6-2)
    t04_far_start       첫 프레임이 --far-deg 떨어진 자세 · 1 s 머문 뒤 0 으로 · 초기 이동·이어 붙이기(13)
    t05_steps           0 → +A/2 → −A/2 → 0 · 1 s 최소저크 이동 + 3 s 정지 · 도달·오차·실물 위치 3D(12 · 7-c)
    t06_too_fast        첫 관절만 0.1 s 에 A 만큼 · 매핑 최대 속도를 적어 두면 재생 거부(5-2)
    t07_out_of_range    ±3A 까지 · 매핑 범위를 ±2A 안으로 줄여 두면 경계에서 멈춤 + 경고(22)

모든 파일 첫 프레임과 마지막 프레임은 0(t04 · t07 은 예외 표시) · 시간은 프레임 × 0.02 s.
"""

import argparse
import json
import math
from pathlib import Path

FPS = 50
PERIOD = 1.0 / FPS


def min_jerk(u):
    u = min(max(u, 0.0), 1.0)
    return u * u * u * (10.0 - 15.0 * u + 6.0 * u * u)


def segments(points):
    """[(시간 s, 값 deg)] 를 최소저크로 잇는다 · 같은 값 = 정지"""
    def value(t):
        if t <= points[0][0]:
            return points[0][1]
        for (t0, v0), (t1, v1) in zip(points, points[1:]):
            if t <= t1:
                return v0 + (v1 - v0) * min_jerk((t - t0) / (t1 - t0))
        return points[-1][1]
    return value, points[-1][0]


def write(path, title, joints, curves, duration, unit):
    """curves · 관절마다 t(s) → deg · unit · 'rad' | 'deg' | None(헤더 칸 없음 = deg)"""
    header = {'title': title, 'type': 'motion_header', 'rotation_mode': 'relative',
              'fields': ['frame', 'time_sec', 'id', 'value'], 'file_title': title}
    if unit is not None:
        header['rotation_unit'] = unit
    frames = int(round(duration * FPS))
    with open(path, 'w', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(header, ensure_ascii=False) + '\n')
        for k in range(frames + 1):
            t = k * PERIOD
            row = [k + 1, round((k + 1) * PERIOD, 9)]
            for joint, curve in zip(joints, curves):
                deg = curve(t)
                value = math.radians(deg) if unit == 'rad' else deg
                row.extend((joint, round(value, 9) + 0.0))
            f.write(json.dumps(row, separators=(',', ':')) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--out', required=True, help='출력 폴더')
    parser.add_argument('--joints', default='1-1,1-2,1-3', help='조인트 이름 · 쉼표 · PC 조인트 매핑과 같게')
    parser.add_argument('--amp-deg', type=float, default=20.0, help='기본 진폭 A (조인트 deg)')
    parser.add_argument('--far-deg', type=float, default=40.0, help='t04 첫 프레임 거리 (조인트 deg)')
    args = parser.parse_args()

    joints = [name.strip() for name in args.joints.split(',') if name.strip()]
    if not joints:
        parser.error('--joints 가 비었다')
    a = float(args.amp_deg)
    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)

    def sine(index):
        phase = 2.0 * math.pi * index / max(len(joints), 1)
        return lambda t: a * (math.sin(2.0 * math.pi * 0.1 * t + phase) - math.sin(phase))

    sines = [sine(i) for i in range(len(joints))]
    for name, unit in (('t01_sine_rad', 'rad'), ('t02_sine_deg', 'deg'), ('t03_sine_noheader', None)):
        write(out / f'{name}.json', name, joints, sines, 20.0, unit)

    far, far_end = segments([(0.0, args.far_deg), (1.0, args.far_deg), (4.0, 0.0), (6.0, 0.0)])
    write(out / 't04_far_start.json', 't04_far_start', joints, [far] * len(joints), far_end, 'rad')

    steps, steps_end = segments([
        (0.0, 0.0), (1.0, 0.0), (2.0, a / 2), (5.0, a / 2), (6.0, -a / 2), (9.0, -a / 2), (10.0, 0.0), (13.0, 0.0),
    ])
    write(out / 't05_steps.json', 't05_steps', joints, [steps] * len(joints), steps_end, 'rad')

    fast, fast_end = segments([(0.0, 0.0), (1.0, 0.0), (1.1, a), (3.0, a), (5.0, 0.0), (6.0, 0.0)])
    still = lambda t: 0.0  # noqa: E731
    write(out / 't06_too_fast.json', 't06_too_fast', joints, [fast] + [still] * (len(joints) - 1), fast_end, 'rad')

    wide, wide_end = segments([(0.0, 0.0), (3.0, 3 * a), (5.0, 3 * a), (11.0, -3 * a), (13.0, -3 * a), (16.0, 0.0)])
    write(out / 't07_out_of_range.json', 't07_out_of_range', joints, [wide] * len(joints), wide_end, 'rad')

    for path in sorted(out.glob('t0*.json')):
        print(path)


if __name__ == '__main__':
    main()
