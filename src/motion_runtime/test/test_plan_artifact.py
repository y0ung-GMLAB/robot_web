"""애니 변환본 · 등록 때 한 번 변환해 디스크에 · 준비 검사 · 그룹 준비는 읽기만 · 수정 목록 208

NY 실물 · 준비 검사 · 그룹 준비 · 재생 목록 짓기가 그때마다 920 s × 20 조인트 파일(25 MB)을 읽고 20 ms
재샘플 · 속도 검사를 했다 · 재생 · ROS 응답과 같은 프로세스(GIL) · 메모리 캐시는 재부팅마다 비었다(174).

여기서 지키는 것:

    변환본으로 지은 계획 = 지금까지(메모리)의 계획 · 샘플 칸 바이트까지 같다 · 통째 · 구간 · 초기 위치
    파일 읽기 · 재샘플은 자식 프로세스 · 이 프로세스의 CPU 는 거의 안 쓴다
    서비스가 다시 떠도(새 관리자) 파일을 다시 안 읽는다 · 자식 프로세스도 안 띄운다
    깨진 변환본(잘림 · 바이트 바뀜 · 쓰레기 · 빈 파일 · 쓰다 만 임시 파일)은 알아보고 다시 만든다
    키 · 매핑 줄 · 파일 · 모터 한계 · 코드가 바뀌면 다시 · 모터 위치 · 알람은 안 든다 · 종류마다 `KEEP` 개만
    자식 프로세스가 안 되면 이 프로세스에서 같은 값으로 · 읽기 오류는 전과 같은 오류
    프로젝트 `motions/` 밖 파일(스튜디오 임시 · 시험)은 변환본을 안 만든다
"""

import os
import resource
import sys
from unittest import mock

import pytest

from motion_runtime import motion_run_rules, plan_artifact, plan_builder as plan_builder_mod
from motion_runtime.motion_run_manager import MotionRunManager
from motion_runtime.packed_samples import PackedSamples

from test_group_prepare_long_file import (  # noqa: F401 · `_patched_rules` 는 자동 고정물
    _check_payload, _manager, _mapping, _motors, _patched_rules, _strip, _write_motion,
)


def _project(tmp_path, frames, names=('a.json',)):
    project_dir = tmp_path / 'proj'
    (project_dir / 'motions').mkdir(parents=True, exist_ok=True)
    (project_dir / 'project.json').write_text('{}', encoding='utf-8')
    for index, name in enumerate(names):
        _write_motion(project_dir / 'motions' / name, frames, phase=float(index))
    return project_dir


def _project_manager(project_dir, mapping, motors=None):
    """프로젝트 폴더의 애니 · 변환본 자리가 있다 · 새로 만들면 메모리 캐시 없는 「다시 뜬 서비스」"""
    manager = _manager(project_dir, mapping, motors)
    manager._motion_file_path = lambda file_id: project_dir / 'motions' / file_id
    manager.logger = mock.Mock()
    manager.get_logger = lambda: manager.logger
    return manager


def _artifacts(project_dir, name='a.json'):
    folder = project_dir / 'runtime' / 'plan_artifacts' / name
    return sorted(folder.glob('*.rwplan')) if folder.is_dir() else []


def _kinds(project_dir, name='a.json'):
    return sorted(path.name.split('-')[0] for path in _artifacts(project_dir, name))


def _column_bytes(samples):
    assert isinstance(samples, PackedSamples)
    times, absolute, positions, values = samples.columns()
    return (times.tobytes(), absolute.tobytes(), tuple(c.tobytes() for c in positions), tuple(c.tobytes() for c in values))


def _hard_mapping(**extra):
    """감속비 · 배율 · 반전 · 기준점 · 오프셋 · 범위 자르기가 실제로 일어나는 매핑"""
    return _mapping(
        offset_deg=1.5, gear_ratio=37.0, scale=1.1, motion_lower_deg=-8.0, motion_upper_deg=8.0, **extra,
    )


def _hard_motors():
    # 모터 한계를 조인트 범위 끝(반올림 차이 안쪽)에 · 모터 한계 자르기도 실제로 일어나게
    return _motors(upper_deg=8.0 * 37.0 * 1.1 + 3.0 - 1e-9)


def _warnings(manager):
    return [str(call.args[0]) for call in manager.logger.warning.call_args_list]


# --------------------------------------------------------------------------- #
# 같은 값 · 비트까지
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize('segment', [None, (3.3, 71.17)], ids=['whole', 'segment'])
def test_plan_through_a_compiled_artifact_is_bit_identical(tmp_path, monkeypatch, segment):
    project_dir = _project(tmp_path, 6000)
    extra = {} if segment is None else {'segment_start_sec': segment[0], 'segment_end_sec': segment[1]}
    payload = _check_payload(**extra)

    # 옛 길 · 변환본 없이 메모리에서
    with monkeypatch.context() as patch:
        patch.setattr(plan_artifact, 'store_for', lambda _path: None)
        before = _project_manager(project_dir, _hard_mapping(), _hard_motors())
        expected = before._plan_builder.build(payload)
        expected_init = before._plan_builder.build(payload, initialization_only=True)
    assert _artifacts(project_dir) == []

    compiled = _project_manager(project_dir, _hard_mapping(), _hard_motors())
    timing = {}
    plan = compiled._plan_builder.build(payload, timing=timing)
    assert (timing['records_from'], timing['samples_from']) == ('compiled', 'compiled'), timing
    assert _kinds(project_dir) == ['samples' if segment is None else 'segment', 'tracks']

    restarted = _project_manager(project_dir, _hard_mapping(), _hard_motors())
    timing = {}
    loaded = restarted._plan_builder.build(payload, timing=timing)
    assert (timing['records_from'], timing['samples_from']) == ('artifact', 'artifact'), timing
    loaded_init = restarted._plan_builder.build(payload, initialization_only=True)

    for candidate in (plan, loaded):
        assert _column_bytes(candidate['samples']) == _column_bytes(expected['samples'])
        assert _strip(candidate) == _strip(expected)
    assert _strip(loaded_init) == _strip(expected_init)
    assert any(axis['motion_clamped'] for axis in expected['axes'])


@pytest.mark.slow
def test_real_size_plan_through_the_artifact_is_bit_identical(tmp_path, monkeypatch):
    """46000 프레임(920 s) × 20 조인트 · NY 나레이션과 같은 크기"""
    project_dir = _project(tmp_path, 46000)
    with monkeypatch.context() as patch:
        patch.setattr(plan_artifact, 'store_for', lambda _path: None)
        expected = _project_manager(project_dir, _hard_mapping(), _hard_motors())._plan_builder.build(_check_payload())
    plan = _project_manager(project_dir, _hard_mapping(), _hard_motors())._plan_builder.build(_check_payload())
    loaded = _project_manager(project_dir, _hard_mapping(), _hard_motors())._plan_builder.build(_check_payload())
    assert len(expected['samples']) == 46000
    assert _column_bytes(plan['samples']) == _column_bytes(expected['samples'])
    assert _column_bytes(loaded['samples']) == _column_bytes(expected['samples'])


def test_a_speed_refusal_is_the_same_through_the_artifact(tmp_path):
    """속도·가속 거절 사유도 변환본에 담긴다 · 다시 뜬 서비스도 같은 사유로 거절한다"""
    project_dir = _project(tmp_path, 600)
    mapping = _mapping(max_velocity_deg_s=0.5)
    with pytest.raises(ValueError) as first:
        _project_manager(project_dir, mapping)._plan_builder.build(_check_payload())
    with pytest.raises(ValueError) as again:
        _project_manager(project_dir, mapping)._plan_builder.build(_check_payload())
    assert str(first.value) == str(again.value)
    assert '속도·가속도 상한' in str(first.value) and ' 속도 ' in str(first.value)
    assert 'samples' in _kinds(project_dir)


# --------------------------------------------------------------------------- #
# 무거운 일은 자식 프로세스 · 다시 떠도 안 읽는다
# --------------------------------------------------------------------------- #

def _cpu(who):
    usage = resource.getrusage(who)
    return usage.ru_utime + usage.ru_stime


def test_parsing_and_resampling_run_in_a_child_process(tmp_path):
    """이 프로세스(재생 · ROS 응답)는 기다리고 읽기만 · 계산 CPU 는 자식 쪽에 잡힌다 · 고치기 전엔 전부 이 프로세스"""
    project_dir = _project(tmp_path, 20000)
    manager = _project_manager(project_dir, _mapping())
    self_before, children_before = _cpu(resource.RUSAGE_SELF), _cpu(resource.RUSAGE_CHILDREN)
    timing = {}
    plan = manager._plan_builder.build(_check_payload(), timing=timing)
    own = _cpu(resource.RUSAGE_SELF) - self_before
    child = _cpu(resource.RUSAGE_CHILDREN) - children_before
    assert len(plan['samples']) == 20000
    assert (timing['records_from'], timing['samples_from']) == ('compiled', 'compiled'), timing
    assert child > 0.1, f'자식 프로세스 CPU {child:.3f} s'
    assert own < child * 0.5, f'이 프로세스 CPU {own:.3f} s · 자식 {child:.3f} s'


def test_a_restarted_service_reads_the_artifact_without_parsing_or_children(tmp_path, monkeypatch):
    project_dir = _project(tmp_path, 3000)
    first = _project_manager(project_dir, _mapping())._plan_builder.build(_check_payload())

    def forbidden(*_args, **_kwargs):
        raise AssertionError('다시 뜬 서비스가 파일을 읽거나 변환했습니다')

    monkeypatch.setattr(MotionRunManager, '_parse_motion_records', forbidden)
    monkeypatch.setattr(plan_artifact, '_run_child', forbidden)
    monkeypatch.setattr(plan_builder_mod, '_sample_plan', forbidden)
    restarted = _project_manager(project_dir, _mapping())
    # 위치 · 알람이 그때와 달라도 같은 변환본(키에 안 든다)
    restarted.motors = [{**motor, 'position_rad': 0.4, 'alarm': True} for motor in restarted.motors]
    timing = {}
    plan = restarted._plan_builder.build(_check_payload(), timing=timing)
    assert timing['records_from'] == 'artifact' and timing['samples_from'] == 'artifact'
    assert _column_bytes(plan['samples']) == _column_bytes(first['samples'])


# --------------------------------------------------------------------------- #
# 깨진 변환본
# --------------------------------------------------------------------------- #

def _truncate(path):
    path.write_bytes(path.read_bytes()[:-17])


def _flip(path):
    data = bytearray(path.read_bytes())
    data[-9] ^= 0x40
    path.write_bytes(bytes(data))


def _garbage(path):
    path.write_bytes(b'not an artifact at all')


def _empty(path):
    path.write_bytes(b'')


@pytest.mark.parametrize('damage', [_truncate, _flip, _garbage, _empty], ids=['truncated', 'flipped', 'garbage', 'empty'])
def test_a_damaged_artifact_is_detected_and_rebuilt(tmp_path, monkeypatch, damage):
    monkeypatch.setattr(plan_artifact, 'COMPILE_IN_SUBPROCESS', False)
    project_dir = _project(tmp_path, 800)
    expected = _project_manager(project_dir, _mapping())._plan_builder.build(_check_payload())
    for path in _artifacts(project_dir):
        damage(path)

    manager = _project_manager(project_dir, _mapping())
    timing = {}
    plan = manager._plan_builder.build(_check_payload(), timing=timing)
    assert (timing['records_from'], timing['samples_from']) == ('parsed', 'computed'), timing
    assert _column_bytes(plan['samples']) == _column_bytes(expected['samples'])
    assert sum('깨져' in line for line in _warnings(manager)) == 2, _warnings(manager)

    timing = {}
    _project_manager(project_dir, _mapping())._plan_builder.build(_check_payload(), timing=timing)
    assert (timing['records_from'], timing['samples_from']) == ('artifact', 'artifact')


def test_a_half_written_temp_file_is_ignored_and_cleaned(tmp_path, monkeypatch):
    """전원이 꺼져 이름 바꾸기 전에 멈춘 임시 파일 · 읽지 않는다 · 오래되면 다음 저장 때 지운다"""
    monkeypatch.setattr(plan_artifact, 'COMPILE_IN_SUBPROCESS', False)
    project_dir = _project(tmp_path, 300)
    folder = project_dir / 'runtime' / 'plan_artifacts' / 'a.json'
    folder.mkdir(parents=True)
    stale = folder / f'{plan_artifact.TEMP_PREFIX}samples-123-abc'
    stale.write_bytes(plan_artifact.MAGIC + b'\x00' * 3)
    old = 1_000_000_000
    os.utime(stale, (old, old))
    fresh = folder / f'{plan_artifact.TEMP_PREFIX}tracks-456-def'
    fresh.write_bytes(b'')

    _project_manager(project_dir, _mapping())._plan_builder.build(_check_payload())

    assert not stale.exists(), '오래된 임시 파일이 남았습니다'
    assert fresh.exists(), '쓰는 중일 수 있는 새 임시 파일을 지웠습니다'
    assert _kinds(project_dir) == ['samples', 'tracks']


# --------------------------------------------------------------------------- #
# 키
# --------------------------------------------------------------------------- #

def test_the_key_follows_mapping_file_limits_and_code_and_keeps_few_files(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_artifact, 'COMPILE_IN_SUBPROCESS', False)
    project_dir = _project(tmp_path, 300)
    parses, samplings = [], []
    real_parse = MotionRunManager._parse_motion_records
    real_sample = plan_builder_mod._sample_plan
    monkeypatch.setattr(
        MotionRunManager, '_parse_motion_records',
        lambda self, path, *rest: parses.append(1) or real_parse(self, path, *rest),
    )
    monkeypatch.setattr(plan_builder_mod, '_sample_plan', lambda *a, **k: samplings.append(1) or real_sample(*a, **k))

    def build(mapping=None, motors=None):
        _project_manager(project_dir, mapping or _mapping(), motors)._plan_builder.build(_check_payload())
        return len(parses), len(samplings)

    assert build() == (1, 1)
    assert build() == (1, 1), '같은 키인데 다시 변환했습니다'
    assert build(motors=[{**m, 'position_rad': 1.0, 'alarm': True} for m in _motors()]) == (1, 1)
    assert build(mapping=_mapping(gear_ratio=80.0)) == (1, 2), '매핑 줄이 바뀌었는데 재샘플을 다시 안 했습니다'
    assert build(motors=_motors(upper_deg=400.0)) == (1, 3), '모터 한계가 바뀌었는데 재샘플을 다시 안 했습니다'
    path = project_dir / 'motions' / 'a.json'
    stat = path.stat()
    _write_motion(path, 300, phase=0.25)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert build() == (2, 4), '파일이 바뀌었는데 다시 읽지 않았습니다'
    monkeypatch.setattr(plan_artifact, '_fingerprint', 'another-version')
    monkeypatch.setattr(plan_artifact, '_fingerprint_done', True)
    assert build() == (3, 5), '계산 코드가 바뀌었는데(업데이트) 옛 변환본을 썼습니다'
    kinds = _kinds(project_dir)
    assert kinds.count('tracks') <= plan_artifact.KEEP['tracks']
    assert kinds.count('samples') <= plan_artifact.KEEP['samples']


def test_segments_do_not_push_out_the_whole_file_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(plan_artifact, 'COMPILE_IN_SUBPROCESS', False)
    project_dir = _project(tmp_path, 500)
    _project_manager(project_dir, _mapping())._plan_builder.build(_check_payload())
    for start in (1.0, 2.0, 3.0, 4.0):
        _project_manager(project_dir, _mapping())._plan_builder.build(_check_payload(segment_start_sec=start))
    kinds = _kinds(project_dir)
    assert kinds.count('samples') == 1 and kinds.count('segment') == plan_artifact.KEEP['segment']
    timing = {}
    _project_manager(project_dir, _mapping())._plan_builder.build(_check_payload(), timing=timing)
    assert timing['samples_from'] == 'artifact'


# --------------------------------------------------------------------------- #
# 자식 프로세스가 안 될 때 · 읽기 오류 · 자리 없는 파일
# --------------------------------------------------------------------------- #

def test_a_child_that_cannot_start_falls_back_to_this_process(tmp_path, monkeypatch):
    project_dir = _project(tmp_path, 400)
    with monkeypatch.context() as patch:
        patch.setattr(plan_artifact, 'store_for', lambda _path: None)
        expected = _project_manager(project_dir, _mapping())._plan_builder.build(_check_payload())
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'no-such-python'))
    manager = _project_manager(project_dir, _mapping())
    timing = {}
    plan = manager._plan_builder.build(_check_payload(), timing=timing)
    assert (timing['records_from'], timing['samples_from']) == ('parsed', 'computed')
    assert _column_bytes(plan['samples']) == _column_bytes(expected['samples'])
    assert any('자식 프로세스 실행 실패' in line for line in _warnings(manager)), _warnings(manager)
    assert _kinds(project_dir) == ['samples', 'tracks'], '이 프로세스에서 계산한 것도 변환본으로 남겨야 합니다'


def test_an_unreadable_file_reports_the_same_error_and_leaves_no_artifact(tmp_path):
    project_dir = _project(tmp_path, 10)
    (project_dir / 'motions' / 'a.json').write_text(
        '{"type":"motion_header","fields":["frame","time_sec","id","value"]}\n', encoding='utf-8',
    )
    manager = _project_manager(project_dir, _mapping())
    with pytest.raises(ValueError, match='no valid records'):
        manager._plan_builder.build(_check_payload())
    assert _artifacts(project_dir) == []
    # 읽기 오류는 알릴 것이 아니다(자식 프로세스 실패 경고 없음)
    assert _warnings(manager) == []


def test_only_project_animations_get_artifacts(tmp_path):
    project_dir = _project(tmp_path, 10)
    assert plan_artifact.store_for(project_dir / 'motions' / 'a.json') is not None
    assert plan_artifact.store_for(tmp_path / 'a.json') is None
    assert plan_artifact.store_for(project_dir / 'runtime' / 'studio_runtime' / '__studio_x.json') is None
    other = tmp_path / 'not_a_project' / 'motions'
    other.mkdir(parents=True)
    assert plan_artifact.store_for(other / 'a.json') is None
    assert plan_artifact.store_for(None) is None


def test_artifact_location_is_the_shared_path_helper(tmp_path):
    from motion_common.paths import plan_artifacts_dir

    project_dir = _project(tmp_path, 10)
    store = plan_artifact.store_for(project_dir / 'motions' / 'a.json')
    assert store.directory == plan_artifacts_dir(project_dir) / 'a.json'


def test_memory_plan_rules_are_untouched_for_files_without_a_project(tmp_path, monkeypatch):
    """시험 · 스튜디오 파일 · 변환본 없이 지금까지처럼(계획 캐시도 그대로)"""
    _write_motion(tmp_path / 'a.json', 200)
    manager = _manager(tmp_path, _mapping())
    timing = {}
    manager._plan_builder.build(_check_payload(), timing=timing)
    assert timing['records_from'] == 'file' and timing['samples_from'] == 'computed'
    assert not (tmp_path / 'runtime').exists()
    assert motion_run_rules  # 고정물 `_patched_rules` 가 같은 모듈을 고친다
