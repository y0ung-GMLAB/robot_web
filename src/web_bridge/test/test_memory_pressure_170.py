"""웹 브리지 메모리 · 이벤트 루프 · 수정 목록 170 (NY 실물 2026-11-03)

floating4(4.7 GB) · 920 s × 20 조인트 애니(25 MB)를 목록에 두고 3D 화면을 켜자 브리지가 700 MB ·
스왑 1.25 GB · 루프 지연 1.6 s · 05:23 마스터 floating1 은 MuJoCo 3D 를 켠 직후 「웹 서비스 끊김」 으로
그룹이 섰다.

여기서 지키는 것:

    목록 분석 · 3D 조인트 값 · 올리기 검사가 JSON Lines 를 한 줄씩 읽어도 옛 결과와 같다
    분석 캐시는 그래프 점을 배열로 들고 · 꺼낸 상세는 옛 상세와 같다 · 바이트 예산
    재생 기록 그래프 · 두 번 훑어 고른 줄만 · 옛 결과와 같다 · 캐시
    큰 JSON 응답은 스레드에서 글로(루프는 바이트만)
    MuJoCo 계산은 낮은 우선순위 · 재생 중이면 미루고 끝나면 시작
    메모리 · 스왑 판정 · 스케줄 상태 · PC 현황 칸
"""

import csv
import json
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from motion_common import motion_table
from motion_web_bridge import (
    animation_preview, memory_status, motion_file_analysis, motion_joint_values, remote_run_mode,
)
from motion_web_bridge.motion_trace_service import MotionTraceService
from motion_web_bridge.json_body import json_response

BRIDGE_DIR = Path(__file__).resolve().parents[1] / 'motion_web_bridge'
JOINTS = ('f1_neck_yaw', 'f1_neck_pitch', 'f2_eye_pitch')


def _jsonl(path, frames=120, *, unit='rad', fields=('frame', 'time_sec', 'id', 'value'), extra_lines=(), shuffle=False):
    header = {'title': 't', 'type': 'motion_header', 'rotation_unit': unit, 'fields': list(fields)}
    lines = [json.dumps(header), '# comment', '']
    order = list(range(1, frames + 1))
    if shuffle:
        order = order[::-1] + [5, 5]
    for n, frame in enumerate(order):
        t = round(frame * 0.02, 4)
        row = [frame, t]
        for index, joint in enumerate(JOINTS):
            row += [joint, round(0.25 * math.sin(0.9 * t + index) + n * 1e-7, 9)]
        lines.append(json.dumps(row))
    lines.extend(extra_lines)
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return path


CASES = {
    'plain': {},
    'deg': {'unit': 'deg'},
    'shuffled_duplicates': {'shuffle': True},
    'bad_rows': {'extra_lines': ['[999, -1.0, "f1_neck_yaw", 0.1]', '[1000, 20.0, "f1_neck_yaw", "x"]', 'garbage line']},
    'long_ids_20': {'frames': 700},
}


@pytest.mark.parametrize('case', sorted(CASES))
@pytest.mark.parametrize('include_records', [True, False])
def test_streamed_analysis_equals_the_old_analysis(tmp_path, case, include_records):
    path = _jsonl(tmp_path / 'a.json', **CASES[case])
    old = motion_file_analysis.analyze_motion_json(path.read_text(encoding='utf-8'), include_records=include_records)
    new = motion_file_analysis.analyze_motion_path(path, include_records=include_records)
    assert json.dumps(new, ensure_ascii=False) == json.dumps(old, ensure_ascii=False)


def test_other_shapes_fall_back_to_the_old_analysis(tmp_path):
    whole = tmp_path / 'whole.json'
    whole.write_text(json.dumps({'data': [[1, 0.0, 'a', 1.0], [2, 0.02, 'a', 2.0]]}), encoding='utf-8')
    header_only = tmp_path / 'header.json'
    header_only.write_text(json.dumps({'type': 'motion_header', 'fields': ['frame', 'time_sec', 'id', 'value']}) + '\n', encoding='utf-8')
    bad_unit = _jsonl(tmp_path / 'unit.json', 5, unit='furlong')
    for path in (whole, header_only, bad_unit):
        old = motion_file_analysis.analyze_motion_json(path.read_text(encoding='utf-8'), include_records=True)
        assert motion_file_analysis.analyze_motion_path(path, include_records=True) == old


def test_cached_detail_equals_the_fresh_detail_and_stays_small(tmp_path):
    motion_file_analysis._SUMMARY_CACHE.clear()
    path = _jsonl(tmp_path / 'a.json', 900)
    fresh = motion_file_analysis.analyze_motion_json(path.read_text(encoding='utf-8'), include_records=True)
    first = motion_file_analysis.motion_file_entry(path, include_detail=True)['analysis']
    again = motion_file_analysis.motion_file_entry(path, include_detail=True)['analysis']
    summary = motion_file_analysis.motion_file_entry(path, include_detail=False)['analysis']
    assert json.dumps(first) == json.dumps(again) == json.dumps(fresh)
    assert not set(motion_file_analysis.DETAIL_ONLY_KEYS) & set(summary)
    stored = next(iter(motion_file_analysis._SUMMARY_CACHE.values()))
    assert 'graph_series' not in stored and motion_file_analysis._GRAPH_KEY in stored
    # 응답을 고쳐도 캐시는 그대로
    again['graph_series'][0]['points'][0]['value'] = 123.0
    assert motion_file_analysis.motion_file_entry(path, include_detail=True)['analysis'] == fresh


def test_analysis_cache_has_a_byte_budget(tmp_path, monkeypatch):
    motion_file_analysis._SUMMARY_CACHE.clear()
    monkeypatch.setattr(motion_file_analysis, '_SUMMARY_CACHE_MAX_BYTES', 30_000)
    for index in range(6):
        motion_file_analysis.motion_file_entry(_jsonl(tmp_path / f'm{index}.json', 300), include_detail=False)
    assert 1 <= len(motion_file_analysis._SUMMARY_CACHE) < 6
    assert set(motion_file_analysis._SUMMARY_BYTES) == set(motion_file_analysis._SUMMARY_CACHE)


@pytest.mark.parametrize('case', ['plain', 'deg', 'shuffled_duplicates', 'bad_rows'])
def test_streamed_joint_values_equal_the_old_ones(tmp_path, case):
    path = _jsonl(tmp_path / 'a.json', **CASES[case])
    old = motion_joint_values.joint_values_from_content(path.read_text(encoding='utf-8'))
    assert motion_joint_values.joint_values_from_path(path) == old


def test_joint_values_cache_has_a_byte_budget(tmp_path, monkeypatch):
    motion_joint_values._CACHE.clear()
    monkeypatch.setattr(motion_joint_values, '_CACHE_MAX_BYTES', 50_000)
    for index in range(4):
        assert motion_joint_values.joint_values_payload(_jsonl(tmp_path / f'm{index}.json', 300))['success']
    assert 1 <= len(motion_joint_values._CACHE) < 4


@pytest.mark.parametrize('case', sorted(CASES))
def test_lazy_upload_check_counts_the_same(tmp_path, case):
    text = _jsonl(tmp_path / 'a.json', **CASES[case]).read_text(encoding='utf-8')
    rows, headers, _source, _warning = motion_table.extract_rows_from_content(text)
    expected = sum(1 for row in rows if motion_table.parse_row(row, headers)[0] is not None)
    assert motion_table.validate_motion_content(text) == expected


@pytest.mark.parametrize('text, message', [
    ('# only\n', '애니메이션 행을 찾지 못했습니다 · text format requires at least one data row'),
    ('{"type":"motion_header","fields":["frame","time_sec","id","value"]}\nnot a row\n', 'bracket data rows not found'),
    ('{"type":"motion_header","fields":["frame","time_sec","id","value"]}\n[1, "x", "a", 1]\n', '재생할 수 있는 행이 없습니다'),
])
def test_lazy_upload_check_keeps_the_messages(text, message):
    with pytest.raises(ValueError, match=message):
        motion_table.validate_motion_content(text)


# ---- 재생 기록 그래프 ----

def _old_trace_columns(path, max_points):
    with path.open(encoding='utf-8', newline='') as handle:
        rows = list(csv.reader(handle))
    header, data = rows[0], rows[1:]
    step = max(1, -(-len(data) // max_points))
    picked = data[::step]
    if data and picked[-1] is not data[-1]:
        picked.append(data[-1])
    return len(data), step, [row[0] for row in picked]


@pytest.mark.parametrize('count', [0, 1, 2999, 3000, 3001, 7000, 9001])
def test_trace_picks_the_same_rows(tmp_path, count):
    day = tmp_path / 'logs' / 'motion_trace' / '2026-11-03'
    day.mkdir(parents=True)
    path = day / '052324_c0001_dummy.csv'
    lines = ['time_sec,a_target_deg,a_actual_deg,a_error_deg']
    lines += [f'{i * 0.02:.3f},{i},{"" if i % 7 == 0 else i + 0.5},0.5' for i in range(count)]
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    service = MotionTraceService(SimpleNamespace(
        selected_project_id=lambda: 'p', project_logs_dir=lambda _pid: tmp_path / 'logs',
    ))
    result = service.trace('2026-11-03', path.name)
    total, step, times = _old_trace_columns(path, 3000)
    assert result['sample_count'] == total and result['decimation'] == step
    assert result['time'] == [float(t) for t in times]
    assert result['axes'][0]['actual'][0] is None if count else result['axes'][0]['actual'] == []
    assert service.trace('2026-11-03', path.name)['time'] is result['time']   # 캐시


# ---- 큰 JSON 은 스레드에서 글로 ----

def test_json_response_is_the_same_text_as_jsonresponse():
    from fastapi.responses import JSONResponse
    payload = {'success': True, 'joints': {'가': [0.1, -2.0, 3]}, 'n': None}
    assert json_response(payload).body == JSONResponse(payload).body
    assert json_response(payload).media_type == 'application/json'


def test_big_lists_are_encoded_in_pieces_but_give_the_same_text():
    from fastapi.responses import JSONResponse
    payload = {
        'success': True, 't': [i * 0.01 for i in range(2501)],
        'qpos': [[0.1 * i, -i, None] for i in range(3003)], 'joints': {'a': [1.5] * 1001, 'b': []},
        'nested': [{'x': list(range(1500))}], 'int_keys': {1: 'one'}, '한글': '값',
    }
    assert json_response(payload).body == JSONResponse(payload).body
    with pytest.raises(ValueError):
        json_response({'v': [float('nan')] * 2000})


def test_heavy_routes_encode_in_the_worker_thread():
    run_routes = (BRIDGE_DIR / 'routes' / 'motion_run_routes.py').read_text(encoding='utf-8')
    assert 'asyncio.to_thread(lambda: json_response(bridge.motion_joint_values(file_id)))' in run_routes
    assert 'asyncio.to_thread(lambda: json_response(bridge.preview_motion_frames(file_id)))' in run_routes
    trace_routes = (BRIDGE_DIR / 'routes' / 'motion_trace_routes.py').read_text(encoding='utf-8')
    assert 'json_response(bridge.motion_trace.trace(date, file))' in trace_routes


# ---- MuJoCo 계산 · 낮은 우선순위 · 재생 중이면 미룸 ----

GATED = (
    'precompute:\n'
    '  command:\n'
    '    - simulate\n'
    "    - '{motion_path}'\n"
    "  result: '{motion_stem}.sim.npz'\n"
)


@pytest.fixture
def preview_workspace(tmp_path):
    animation_preview._RUNNING.clear()
    animation_preview._LAST_RC.clear()
    animation_preview._PENDING_META.clear()
    animation_preview._DEFERRED.clear()
    (tmp_path / 'config').mkdir()
    (tmp_path / 'config' / 'animation_preview.yaml').write_text(GATED, encoding='utf-8')
    motion = tmp_path / 'demo.json'
    motion.write_text('{}', encoding='utf-8')
    yield tmp_path, motion
    animation_preview._RUNNING.clear()
    animation_preview._DEFERRED.clear()


def test_detached_job_gets_low_priority_and_memory_caps(preview_workspace):
    workspace, motion = preview_workspace
    calls = []
    run = lambda command, **_kw: calls.append(command) or SimpleNamespace(returncode=0, stdout='', stderr='')  # noqa: E731
    assert animation_preview.launch_precompute(workspace, motion, detach=True, run=run)['success']
    [launch] = calls
    props = [launch[i + 1] for i, item in enumerate(launch) if item == '-p']
    assert props == list(animation_preview.JOB_PROPERTIES)
    assert {'Nice=19', 'CPUWeight=1', 'IOSchedulingClass=idle', 'MemoryMax=1G', 'MemorySwapMax=0'} <= set(props)
    # systemd 250 의 'idle' 값은 22.04(249)에 없다
    assert 'CPUWeight=idle' not in props
    assert launch.index('-p') < launch.index('/bin/bash')


def test_child_job_lowers_its_priority(preview_workspace, monkeypatch):
    workspace, motion = preview_workspace
    seen = {}

    def popen(args, **kwargs):
        seen.update(kwargs)
        return SimpleNamespace(poll=lambda: None)

    monkeypatch.setattr(animation_preview.subprocess, 'Popen', popen)
    monkeypatch.setattr(animation_preview, 'detach_available', lambda: False)
    monkeypatch.setattr(animation_preview.os, 'name', 'posix')
    assert animation_preview.launch_precompute(workspace, motion)['success']
    assert seen.get('preexec_fn') is animation_preview._lower_priority


def test_busy_defers_and_the_tick_starts_it_after_playback(preview_workspace):
    workspace, motion = preview_workspace
    spawned = []

    def spawn(args, **_kw):
        spawned.append(args)
        return SimpleNamespace(poll=lambda: None)

    deferred = animation_preview.launch_precompute(workspace, motion, spawn=spawn, busy='그룹 재생 중')
    assert deferred['success'] is True and deferred['deferred'] is True and '미뤘습니다' in deferred['message']
    assert spawned == [] and animation_preview.deferred_count() == 1
    # 아직 재생 중 · 그대로
    assert animation_preview.start_deferred(lambda: '재생 중', spawn=spawn) is None
    assert spawned == [] and animation_preview.deferred_count() == 1
    # 재생 끝 · 하나 시작
    started = animation_preview.start_deferred(lambda: '', spawn=spawn)
    assert started['success'] is True and len(spawned) == 1 and animation_preview.deferred_count() == 0


def test_bridge_wires_the_busy_reason_and_the_tick():
    source = (BRIDGE_DIR / 'bridge_node.py').read_text(encoding='utf-8')
    assert 'busy=self._precompute_busy_reason()' in source
    assert 'self.create_timer(5.0, self._precompute_deferred_tick)' in source


# ---- 메모리 · 스왑 ----

MEMINFO = """MemTotal:        4812345 kB
MemFree:          100000 kB
MemAvailable:     430080 kB
SwapTotal:       2097148 kB
SwapFree:         817148 kB
"""


def test_meminfo_judgement():
    view = memory_status.evaluate(memory_status.parse_meminfo(MEMINFO))
    assert view['total_mb'] == 4699 and view['available_mb'] == 420 and view['swap_used_mb'] == 1250
    assert view['low'] is True and view['reasons'] == ['남은 메모리 420 MB', '스왑 1250 MB']
    healthy = memory_status.evaluate({'MemTotal': 4812345, 'MemAvailable': 1843200, 'SwapTotal': 2097148, 'SwapFree': 1482748})
    assert healthy['low'] is False and healthy['swap_used_mb'] == 600
    swapping = memory_status.evaluate({'MemTotal': 4812345, 'MemAvailable': 1843200, 'SwapTotal': 0, 'SwapFree': 0}, 300.0)
    assert swapping['low'] is True and swapping['reasons'] == ['스왑 읽는 중 1.2 MB/s']


def test_snapshot_reads_proc_files_with_a_cache_and_swap_in_rate(tmp_path):
    memory_status.reset_cache()
    meminfo = tmp_path / 'meminfo'
    vmstat = tmp_path / 'vmstat'
    meminfo.write_text(MEMINFO, encoding='ascii')
    vmstat.write_text('pswpin 1000\npswpout 5\n', encoding='ascii')
    first = memory_status.snapshot(now=100.0, meminfo_path=meminfo, vmstat_path=vmstat)
    assert first['swap_in_pages_per_sec'] is None
    vmstat.write_text('pswpin 4000\n', encoding='ascii')
    assert memory_status.snapshot(now=102.0, meminfo_path=meminfo, vmstat_path=vmstat) == first   # 5 초 캐시
    later = memory_status.snapshot(now=110.0, meminfo_path=meminfo, vmstat_path=vmstat)
    assert later['swap_in_pages_per_sec'] == 300.0
    memory_status.reset_cache()
    assert memory_status.snapshot(now=1.0, meminfo_path=tmp_path / 'none', vmstat_path=vmstat) == {
        'available': False, 'low': False, 'reasons': [],
    }
    memory_status.reset_cache()


def test_schedule_status_carries_memory_and_pc_rows_pass_it_on():
    source = (BRIDGE_DIR / 'schedule_service.py').read_text(encoding='utf-8')
    assert "'memory': memory_status.snapshot()," in source
    low = memory_status.evaluate(memory_status.parse_meminfo(MEMINFO))
    pcs = [
        {'pc_id': 'floating1', 'is_local': True},
        {'pc_id': 'floating4', 'web_url': 'http://f4:8000'},
        {'pc_id': 'floating2', 'web_url': 'http://f2:8000'},
    ]
    answers = {'http://f4:8000': {'run_mode': 'schedule', 'memory': low}, 'http://f2:8000': {'run_mode': 'manual'}}
    rows = remote_run_mode.run_modes(
        pcs, lambda: 'schedule', http=lambda url, **_kw: answers[url.rsplit('/api', 1)[0]],
        local_memory=lambda: {'available': False},
    )['pcs']
    by_id = {row['pc_id']: row for row in rows}
    assert by_id['floating4']['memory']['low'] is True and by_id['floating4']['memory']['swap_used_mb'] == 1250
    assert 'memory' not in by_id['floating2']   # 옛 버전 PC
    assert by_id['floating1']['memory'] == {}
