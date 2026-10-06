"""애니메이션 파일 각도 단위 바꾸기 · 수정 목록 6-2 (2026-10-06)

JSON Lines 애니메이션(첫 줄 `motion_header` · 다음 줄부터 `[frame, time, id, v, ...]`)
의 값과 헤더 `rotation_unit` 을 함께 바꾼다 · 칸이 없는 옛 파일은 deg 로 본다.

재생 쪽은 이미 두 단위를 다 읽는다 · 이 도구는 파일을 한 단위로 맞추고 싶을 때만
쓴다 (예 · 옛 deg 파일을 rad 로).

    python scripts/convert_motion_unit.py --to rad a.json b.json        # 옆에 a.rad.json
    python scripts/convert_motion_unit.py --to rad --in-place a.json    # 덮어쓰기
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'motion_common'))

from motion_common import motion_table  # noqa: E402


def convert_text(content: str, target: str) -> tuple[str, str]:
    """(바꾼 본문, 원래 단위) · 이미 그 단위면 본문 그대로."""
    goal = motion_table.normalize_rotation_unit(target)
    lines = content.splitlines()
    index = next(
        (i for i, line in enumerate(lines) if line.strip() and not line.strip().startswith('#')),
        None,
    )
    if index is None:
        raise ValueError('빈 파일입니다')
    header = json.loads(lines[index])
    if not isinstance(header, dict) or header.get('type') != 'motion_header':
        raise ValueError('첫 줄이 motion_header 가 아닙니다 · JSON Lines 애니메이션만 바꿉니다')
    source = motion_table.header_rotation_unit(header)
    if source == goal:
        return content, source
    scale = motion_table.rotation_unit_scale(source, goal)
    header['rotation_unit'] = goal
    out = lines[:index] + [json.dumps(header, ensure_ascii=False)]
    for line in lines[index + 1:]:
        text = line.strip()
        if not text or text.startswith('#'):
            out.append(line)
            continue
        row = json.loads(text)
        if not isinstance(row, list) or len(row) < 4 or (len(row) - 2) % 2:
            raise ValueError(f'프레임 줄 모양이 다릅니다: {text[:60]}')
        values = [
            round(float(item) * scale, 9) if position % 2 else item
            for position, item in enumerate(row[2:])
        ]
        out.append(json.dumps(row[:2] + values, ensure_ascii=False, separators=(',', ':')))
    return '\n'.join(out) + '\n', source


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('files', nargs='+', type=Path)
    parser.add_argument('--to', required=True, choices=('rad', 'deg'))
    parser.add_argument('--in-place', action='store_true', help='원본을 덮어쓴다')
    args = parser.parse_args(argv)
    failed = 0
    for path in args.files:
        try:
            converted, source = convert_text(path.read_text(encoding='utf-8'), args.to)
        except (OSError, ValueError) as exc:
            print(f'실패 · {path}: {exc}', file=sys.stderr)
            failed += 1
            continue
        if source == args.to:
            print(f'그대로 · {path} (이미 {source})')
            continue
        target = path if args.in_place else path.with_name(f'{path.stem}.{args.to}{path.suffix}')
        target.write_text(converted, encoding='utf-8')
        print(f'{source} → {args.to} · {target}')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
