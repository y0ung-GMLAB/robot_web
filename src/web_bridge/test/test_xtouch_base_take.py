"""X-Touch 바탕 위 녹화 · 추가 녹화(⑨) · 구간 덮어쓰기(⑨-2) · 수정 목록 156

    바탕은 안 바뀜 · 새 파일 · 바탕의 다른 조인트(다른 로봇 것)도 그대로
    덮어쓴 구간 = 재생 노드가 보낸 값 · 밖 = 원본
    새 조인트 = X-Touch 램프 값을 재생 프레임에 맞춤
    끝까지 = 바탕 길이 · 중간 정지 = 거기까지 · 잇기 상한 못 맞춤 = 저장 안 함
"""

import json
import math
from types import SimpleNamespace

from motion_web_bridge.xtouch_base_take import BaseTake, load_base, punchable
from motion_web_bridge.xtouch_recording import RecordingService, TakeAxis

R = math.radians
DT = 0.02


def _base_text(count=100, ids=('neck_yaw', 'f9_other'), unit='rad'):
    header = {'title': 'base', 'type': 'motion_header', 'rotation_unit': unit, 'fields': ['frame', 'time_sec', 'id', 'value']}
    lines = [json.dumps(header)]
    for k in range(count):
        row = [k + 1, round((k + 1) * DT, 9)]
        for index, motion_id in enumerate(ids):
            row += [motion_id, 0.001 * k * (index + 1)]
        lines.append(json.dumps(row))
    return '\n'.join(lines) + '\n'


def _row(motion_id, axis, velocity=9.0, acceleration=14.0):
    row = {'motion_id': motion_id, 'enabled': True, 'motor_axis': axis, 'motor_ref': '', 'gear_ratio': 100.0,
           'scale': 1.0, 'invert': False, 'reference_position_rad': 0.0,
           'motion_lower_rad': R(-15), 'motion_upper_rad': R(15), 'range_confirmed': True}
    if velocity:
        row['max_velocity_rad_s'] = R(velocity)
        row['max_acceleration_rad_s2'] = R(acceleration)
    return row


def test_load_base_reads_the_playback_grid_and_keeps_every_id():
    base = load_base('base.json', _base_text())
    assert base.ids == ['neck_yaw', 'f9_other']
    assert base.count == 100 and base.start == DT
    assert base.values['neck_yaw'][10] == 0.010
    deg = load_base('d.json', _base_text(unit='deg'))
    assert abs(deg.values['neck_yaw'][10] - R(0.010)) < 1e-12


def test_punched_frames_replace_the_original_and_the_rest_is_untouched():
    base = load_base('base.json', _base_text())
    take = BaseTake(take_id='t', base=base, punch_rows=punchable(base, [_row('neck_yaw', 1)]))
    for frame in range(100):
        values = {'neck_yaw': 0.5} if 40 <= frame < 50 else {}
        take.on_frame({'take_id': 't', 'frame': frame, 't': 1000.0 + frame * DT + 0.003, 'values': values})
    joints, count = take.compose()
    assert count == 100
    neck = dict((j[0], j[2]) for j in joints)['neck_yaw']
    assert neck[39] == base.values['neck_yaw'][39] and neck[50] == base.values['neck_yaw'][50]
    assert neck[40:50] == [0.5] * 10
    other = dict((j[0], j[2]) for j in joints)['f9_other']
    assert other == base.values['f9_other']                       # 다른 로봇 조인트 그대로
    assert take.t0 == 1000.003


def test_stopping_early_cuts_the_file_where_it_stopped():
    base = load_base('base.json', _base_text())
    take = BaseTake(take_id='t', base=base, punch_rows={})
    for frame in range(30):
        take.on_frame({'take_id': 't', 'frame': frame, 't': 10.0 + frame * DT})
    take.on_frame({'take_id': 't', 'end': True})
    assert take.ended and take.compose()[1] == 30


def test_overdub_axis_samples_land_on_playback_frames():
    base = load_base('base.json', _base_text(ids=('neck_yaw',)))
    row = _row('eye_pitch', 2)
    take = BaseTake(take_id='t', base=base, punch_rows={},
                    overdub={2: TakeAxis(axis=2, rows=[row], start_motor=0.0)})
    for frame in range(100):
        take.on_frame({'take_id': 't', 'frame': frame, 't': 50.0 + frame * DT + 0.002})
    # 프레임 20 부터 램프 값 (모터 rad · 이득 100)
    for k in range(10):
        take.samples.append((k + 1, 50.0 + (20 + k) * DT + 0.009, 2, 0.01 * (k + 1)))
    joints, _ = take.compose()
    eye = dict((j[0], j[2]) for j in joints)['eye_pitch']
    assert eye[19] == 0.0 and abs(eye[20] - 0.01 / 100) < 1e-12 and abs(eye[29] - 0.1 / 100) < 1e-12
    assert eye[99] == eye[29]                                       # 그 뒤는 그대로


class _Repo:
    def __init__(self):
        self.files = {}
        self.trash = []

    def require_selected_project_id(self):
        return 'p'

    def import_text(self, project_id, category, name, text):
        if name in self.files:
            raise ValueError(f'같은 이름의 파일이 이미 있습니다: {name}')
        self.files[name] = text

    def copy_to_trash(self, project_id, category, name):
        if name not in self.files:
            raise ValueError(f'프로젝트 파일을 찾을 수 없습니다: {name}')
        self.trash.append((name, self.files[name]))
        return f'trash/{len(self.trash)}-{name}'

    def save_file(self, project_id, category, name, text):
        self.files[name] = text


def _service(rows, *, playback_ok=True):
    bridge = SimpleNamespace(manual_range_blocker=lambda: '', project_repository=_Repo())
    calls = {'start': [], 'stop': 0, 'punch': []}
    motors = [{'controller_index': row['motor_axis'], 'position_rad': 0.0} for row in rows]

    def start(payload):
        calls['start'].append(payload)
        return {'success': playback_ok, 'message': '' if playback_ok else '범위 미확인'}

    def stop():
        calls['stop'] += 1

    service = RecordingService(
        bridge, mapping=lambda: (rows, motors), read_motion=lambda name: _base_text(),
        start_playback=start, stop_playback=stop, publish_punch=calls['punch'].append,
        sleep=lambda _s: None,
    )
    return service, bridge, calls


def _frames(service, take_id, count, end=True):
    for frame in range(count):
        service.take_frames_callback(SimpleNamespace(data=json.dumps(
            {'take_id': take_id, 'frame': frame, 't': 5.0 + frame * DT, 'values': {}})))
    if end:
        service.take_frames_callback(SimpleNamespace(data=json.dumps({'take_id': take_id, 'end': True})))


def test_base_take_starts_playback_with_punchable_joints_and_saves_a_new_file():
    rows = [_row('neck_yaw', 1), _row('eye_pitch', 2)]
    service, bridge, calls = _service(rows)
    owner = object()
    started = service.start(owner, [1, 2], 'take', 'base.json')
    assert started['success'], started
    payload = calls['start'][0]
    assert payload['motion_file_id'] == 'base.json' and payload['xtouch_take'] is True
    assert payload['xtouch_punch_ids'] == ['neck_yaw']              # 바탕에 있는 것만
    assert started['axes'] == [2]                                   # 바탕에 없는 축 = 추가 녹화
    assert started['state'] == 'countdown'
    take_id = payload['xtouch_take_id']
    assert service.punch(owner, 'neck_yaw', 0.1)['success']
    assert calls['punch'][-1] == {'motion_id': 'neck_yaw', 'target_rad': 0.1}
    assert service.punch(owner, 'eye_pitch', 0.1)['success'] is False
    assert service.punch(object(), 'neck_yaw', 0.1)['success'] is False
    _frames(service, take_id, 100, end=False)
    assert service.status()['state'] == 'recording'
    result = service.stop(owner)                                    # 끝 알림 못 받아도 기다린 뒤 저장
    assert calls['stop'] == 1
    assert result['success'] and result['file'] == 'take.json'
    header = json.loads(bridge.project_repository.files['take.json'].splitlines()[0])
    assert header['base_file'] == 'base.json'
    assert service.status()['state'] == 'idle'
    assert service.status()['last_result']['file'] == 'take.json'


def test_playback_end_saves_by_itself():
    import time as _time
    rows = [_row('neck_yaw', 1)]
    service, bridge, calls = _service(rows)
    owner = object()
    service.start(owner, [], '', 'base.json')
    _frames(service, calls['start'][0]['xtouch_take_id'], 100)
    for _ in range(100):
        if service.status()['state'] == 'idle':
            break
        _time.sleep(0.01)
    assert 'base_xtouch.json' in bridge.project_repository.files
    assert len(bridge.project_repository.files['base_xtouch.json'].splitlines()) == 101


def test_base_take_refuses_a_selected_base_joint_without_limits_and_failed_playback():
    service, _, _ = _service([_row('neck_yaw', 1, velocity=None)])
    assert '속도·가속도 상한' in service.start(object(), [1], '', 'base.json')['message']
    service, _, _ = _service([_row('neck_yaw', 1)], playback_ok=False)
    result = service.start(object(), [1], '', 'base.json')
    assert result['success'] is False and '범위 미확인' in result['message']
    assert service.status()['state'] == 'idle'


def test_blend_overrun_refuses_to_save():
    rows = [_row('neck_yaw', 1)]
    service, bridge, calls = _service(rows)
    owner = object()
    service.start(owner, [], 'x', 'base.json')
    take_id = calls['start'][0]['xtouch_take_id']
    service.take_frames_callback(SimpleNamespace(data=json.dumps(
        {'take_id': take_id, 'frame': 0, 't': 1.0, 'values': {}, 'blend_overrun': ['neck_yaw']})))
    result = service.stop(owner)
    assert result['success'] is False and '잇기' in result['message']
    assert bridge.project_repository.files == {}


def _wait_idle(service):
    import time as _time
    for _ in range(200):
        if service.status()['state'] == 'idle':
            return
        _time.sleep(0.01)


def test_playback_that_never_starts_ends_the_take_with_the_reason():
    """재생 노드가 시작도 못 함(등록 안 된 파일 거절 등 · floating4 2026-10-19) · 계속 기다리지 않음"""
    service, bridge, calls = _service([_row('neck_yaw', 1)])
    owner = object()
    service.start(owner, [], '', 'base.json')
    take_id = calls['start'][0]['xtouch_take_id']
    service.take_frames_callback(SimpleNamespace(data=json.dumps(
        {'take_id': take_id, 'end': True, 'error': '모션 실행 준비 실패: 재생 등록에 없는 애니메이션입니다'})))
    _wait_idle(service)
    last = service.status()['last_result']
    assert last['success'] is False
    assert '바탕 재생을 시작하지 못했습니다' in last['message'] and '재생 등록에 없는' in last['message']
    assert bridge.project_repository.files == {}


def test_overwrite_with_empty_name_saves_over_the_base_when_played_to_the_end():
    service, bridge, calls = _service([_row('neck_yaw', 1)])
    bridge.project_repository.files['base.json'] = 'old'
    owner = object()
    started = service.start(owner, [], '', 'base.json', True)
    assert started['name'] == 'base'
    _frames(service, calls['start'][0]['xtouch_take_id'], 100)
    _wait_idle(service)
    last = service.status()['last_result']
    assert last['success'] and last['file'] == 'base.json' and last['overwritten'] is True
    assert bridge.project_repository.trash == [('base.json', 'old')]
    assert len(bridge.project_repository.files['base.json'].splitlines()) == 101


def test_overwrite_of_the_base_is_skipped_when_stopped_before_the_end():
    """중간에 멈춘 것으로 바탕을 덮으면 바탕이 잘린다 · 새 이름으로"""
    service, bridge, calls = _service([_row('neck_yaw', 1)])
    bridge.project_repository.files['base.json'] = 'old'
    owner = object()
    service.start(owner, [], '', 'base.json', True)
    _frames(service, calls['start'][0]['xtouch_take_id'], 40, end=False)
    result = service.stop(owner)
    assert result['success'] and result['file'] == 'base_2.json'
    assert '바탕 끝까지 가지 않음' in result['message']
    assert bridge.project_repository.files['base.json'] == 'old' and bridge.project_repository.trash == []
