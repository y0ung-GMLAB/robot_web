"""모션 파일 → 조인트별 배열 · 노드 밖 함수 · 수정 목록 208

`MotionRunManager._parse_motion_records` 의 본문을 그대로 옮겼다 · 애니 변환(`plan_artifact`)이
별도 프로세스에서 같은 함수로 읽는다 · ROS 노드를 띄우지 않는다.

옛 레코드 사전과 같은 값 · 같은 순서 · 수정 목록 170 · 164(읽으면서 이 PC 조인트만 남긴다).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

from motion_common import motion_table, motion_tracks


def parse_motion_tracks(path: Path, motion_ids: Any = None) -> motion_tracks.MotionTracks:
    """파일 → 조인트별 배열 · 옛 레코드 사전과 같은 값 · 같은 순서 · 수정 목록 170

    JSON Lines(머리 줄 + 프레임마다 한 줄)는 한 줄씩 읽어 바로 배열에 넣는다 · 파일 글 전체도,
    레코드 사전 목록도 만들지 않는다. 그 밖의 모양(통짜 JSON 등)은 옛 길로 읽어서 옮긴다.
    """
    path = Path(path)
    keep = None if motion_ids is None else {str(item) for item in motion_ids}
    #: 조인트 매핑에 없어 뺀 것 · 파일에 자료는 있었다는 뜻 · 「쓸 수 있는 줄 없음」 과 가른다
    dropped = 0
    memo: Dict[Any, bool] = {}
    first_line = ''
    # 큰 버퍼 · 기본 8 KB 면 읽는 동안 실행기 스레드가 GIL 을 못 받아 굶는다 · 수정 목록 170
    with motion_table.open_text(path) as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if line and not line.startswith('#'):
                first_line = line
                break
        try:
            first_payload = json.loads(first_line)
        except json.JSONDecodeError:
            first_payload = None
        if (
            isinstance(first_payload, dict)
            and first_payload.get('type') == 'motion_header'
        ):
            headers = first_payload.get(
                'fields',
                first_payload.get('headers', first_payload.get('columns', [])),
            )
            headers = (
                [str(item) for item in headers]
                if isinstance(headers, list)
                else []
            )
            # 헤더의 `rotation_unit` · rad 파일을 deg 로 읽던 것을 막는다 · 수정 목록 6-2
            unit = motion_table.header_rotation_unit(first_payload)
            pairs_first = keep is not None and motion_table.pair_rows_expandable(headers)
            tracks: Dict[str, motion_tracks.JointTrack] = {}
            row_index = 0
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith('#'):
                    continue
                parsed = motion_table.parse_text_row(line)
                if parsed is None:
                    continue
                if pairs_first:
                    parsed, skipped = motion_table.keep_pairs(parsed, keep, memo)
                    dropped += skipped
                for row in motion_table.expand_pair_rows([parsed]):
                    record, _row_error = motion_table.parse_row(row, headers)
                    if record is None:
                        continue
                    motion_id = record['motion_id']
                    if keep is not None and motion_id not in keep:
                        dropped += 1
                        continue
                    track = tracks.get(motion_id)
                    if track is None:
                        track = tracks[motion_id] = motion_tracks.JointTrack(motion_id)
                    track.append(record['frame'], record['time_sec'], record['value'], row_index)
                    row_index += 1
            if not tracks:
                if dropped:
                    return motion_tracks.MotionTracks()
                raise ValueError('motion file has no valid records')
            # `motion_table.scale_record_values` 와 같은 식(`float(값) * 배율`)
            scale = motion_table.rotation_unit_scale(unit)
            for track in tracks.values():
                track.scale_values(scale)
            return motion_tracks.MotionTracks.from_builder(tracks)

    # 통짜 JSON 등 · 옛 길 · 행 해석은 `motion_run_rules` 하나(ROS 메시지 모듈을 같이 읽으므로 여기서만)
    from .motion_run_rules import _extract_motion_rows

    content = path.read_text(encoding='utf-8')
    rows, headers = _extract_motion_rows(content)
    records = []
    for index, row in enumerate(rows):
        record, _row_error = motion_table.parse_row(row, headers)
        if record is None:
            continue
        if keep is not None and record['motion_id'] not in keep:
            dropped += 1
            continue
        record['row_index'] = index
        records.append(record)
    if not records:
        if dropped:
            return motion_tracks.MotionTracks()
        raise ValueError('motion file has no valid records')
    motion_table.scale_record_values(
        records, motion_table.rotation_unit_from_content(content),
    )
    return motion_tracks.MotionTracks.from_records(
        sorted(records, key=lambda item: (item['time_sec'], str(item['motion_id']), item['row_index']))
    )
