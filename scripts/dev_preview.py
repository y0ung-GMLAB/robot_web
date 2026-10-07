"""UI 개발 프리뷰 서버 · 로봇·ROS 없이 화면만 띄운다 (개발 전용).

미니PC 에 가기 전에 화면을 보면서 고치기 위한 것이다 · 실제 브리지는
rclpy 가 필요해 개발 PC(Windows)에서 못 뜬다 · 여기는:

    /            실제 서버와 같은 규칙(IndexComposer)으로 조각을 합쳐 준다
    /static/*    src/web_ui/static 그대로
    /ws/status   가짜 스냅샷 2Hz · 플로팅 헤드 5축이 살아 있는 척한다
    /ws/manual-stream   페이더 규약(hello → hello_ok → target/release)을 흉내
    /api/*       그럴듯한 기본값 · 운전 모드는 메모리에 저장돼 세그먼트가 동작

가짜 모터는 명령(페이더·재생 흉내)을 따라 스르르 움직이므로 상호작용
감각까지 확인할 수 있다 · **배포와 무관** · 서비스·install.sh 는 이 파일을
모른다.

실행 (저장소 뿌리에서):

    python scripts/dev_preview.py          # http://localhost:8010
    python scripts/dev_preview.py 8020     # 다른 포트
"""

from __future__ import annotations

import asyncio
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src' / 'web_bridge'))
sys.path.insert(0, str(ROOT / 'src' / 'motion_common'))

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse  # noqa: E402
import uvicorn  # noqa: E402

from motion_web_bridge.index_composer import IndexComposer  # noqa: E402

STATIC = ROOT / 'src' / 'web_ui' / 'static'

# --------------------------------------------------------------------------- #
# 가짜 장비 · 플로팅 헤드 5축
# --------------------------------------------------------------------------- #

JOINTS = [
    # (모션 ID, 축, 감속비, 최소, 최대)
    ('Neck_Pitch', 0, 150.0, -10.0, 13.0),
    ('Neck_Yaw', 1, 100.0, -15.0, 15.0),
    ('Eye_Pitch', 2, 50.0, -10.0, 10.0),
    ('Eye_Yaw_L', 3, 35.0, -12.0, 12.0),
    ('Eye_Yaw_R', 4, 35.0, -12.0, 12.0),
]

state = {
    'run_mode': 'manual',
    'positions': {axis: 0.0 for _, axis, *_ in JOINTS},   # 모터 deg
    'targets': {axis: 0.0 for _, axis, *_ in JOINTS},
    'servo_on': True,
    'generation': 1,
    # 재생 목록 흉내 · 수정 목록 35 · 「재생 등록」·「목록에 추가」·↑↓ 가 여기를 바꾼다
    'playlist': [
        'floating_no1_motion1.json',
        'floating_no2_motion1.json',
        'floating_animation_sample.json',
    ],
    'group_sync_mode': 'lockstep',
    'run_started': None,
    'live_overrides': {},
}


def mapping_rows():
    return [
        {
            'motion_id': name,
            'enabled': True,
            'motor_ref': '',
            'motor_axis': axis,
            'gear_ratio': gear,
            'invert': False,
            # 서버처럼 각도 칸은 rad · 화면이 deg 로 바꿔 보여 준다 · 수정 목록 6
            'offset_rad': 0.0,
            'scale': 1.0,
            'reference_position_rad': 0.0,
            'reference_enabled': True,
            'motion_lower_rad': math.radians(lower),
            'motion_upper_rad': math.radians(upper),
            'initial_mode': 'first_frame',
            'initial_motion_position_rad': 0.0,
            'initial_move_time_sec': 5.0,
        }
        for name, axis, gear, lower, upper in JOINTS
    ]


FAKE_ITEM_SEC = 6.0      # 재생 목록 흉내 · 항목마다 초기 이동 2초 + 재생 4초


def _fake_run_status():
    """연속 시작을 누르면 목록을 차례로 도는 척한다 · 「2/3 · B · 다음 C」 확인용"""
    playlist = list(state['playlist'])
    if state['run_started'] is None or not playlist:
        return {'state': 'ready', 'message': '프리뷰 · 실행 준비 검사 흉내',
                'motion_file_id': playlist[0] if playlist else ''}
    elapsed = time.time() - state['run_started']
    cycle = int(elapsed // FAKE_ITEM_SEC)
    within = elapsed - cycle * FAKE_ITEM_SEC
    index = cycle % len(playlist)
    initializing = within < 2.0 and cycle > 0
    return {
        'state': 'initializing' if initializing else 'running',
        'phase': 'initializing' if initializing else 'running',
        'message': '프리뷰 · 목록 재생 흉내',
        'run_mode': 'continuous',
        'motion_file_id': playlist[index],
        'motion_playlist': playlist if len(playlist) > 1 else [],
        'playlist_index': index,
        'playlist_length': len(playlist) if len(playlist) > 1 else 0,
        'cycle_count': cycle,
        'current_cycle': cycle + 1,
        'progress': {
            'elapsed_sec': within if initializing else within - (0.0 if cycle == 0 else 2.0),
            'duration_sec': 2.0 if initializing else 4.0,
            'ratio': 0.0,
            'sample_index': 0,
            'active_axis_count': len(JOINTS),
        },
        'summary': {'target_cycle_count': 0},
    }


def _mapping_doc():
    playlist = list(state['playlist'])
    mapping = {
        'name': 'motion_axis',
        'file_id': 'motion_axis.yaml',
        'angle_unit': 'rad',
        'motion_file_id': playlist[0] if playlist else '',
        'mappings': mapping_rows(),
    }
    if len(playlist) > 1:
        mapping['motion_playlist'] = playlist
    return mapping


def snapshot():
    motors = []
    for name, axis, gear, lower, upper in JOINTS:
        position = state['positions'][axis]
        motors.append({
            'controller_index': axis,
            'display_name': f'{axis}번 모터',
            'name': name,
            'motor_type': 'ac_servo',
            'motor_type_label': 'AC Servo',
            'state': 'detected',
            'servo_on': state['servo_on'],
            'fault': False,
            # 서버처럼 rad · 화면이 deg 로 바꿔 보여 준다 · 수정 목록 6-5
            'position_rad': math.radians(position),
            'velocity_rad_s': 0.0,
            # 서버가 매핑 식으로 되돌린 실제 조인트 각도 흉내(기준점 0 · 감속비만) · 7-c
            'motion_actual_rad': math.radians(position / gear),
            'torque_percent': 3.0,
            'motion_id': name,
            'lower': -36000.0,
            'upper': 36000.0,
            'profile_velocity': 18000.0,
        })
    # 실제 브리지 스냅샷 모양을 따른다 · 화면은 `motion_state` 아래를 읽는다
    # (main.js motionStateFromPayload · 최상위에 두면 전부 버려진다)
    return {
        'project_generation': state['generation'],
        'bridge_state': 'ok',
        'selected_project_id': 'preview',
        'motion_state': {
            'project_id': 'preview',
            'selected_project_id': 'preview',
            'project_generation': state['generation'],
            'motors': motors,
            'runtime_status': {'ready': True, 'message': '프리뷰 · 가짜 장비'},
            'motor_identity': {'ok': True},
        },
        'motion_state_age_sec': 0.0,
        'motion_run_status': {
            **_fake_run_status(),
            'live_overrides': state['live_overrides'],
            'automation': {
                'repeat_mode': 'reinitialize',
                'group_sync_mode': state['group_sync_mode'],
            },
            'axes': [
                {
                    'motion_id': name,
                    'motor_axis': axis,
                    'motor_type': 'ac_servo',
                    'motion_limit_lower_rad': math.radians(lower),
                    'motion_limit_upper_rad': math.radians(upper),
                    'initial_motor_target_rad': 0.0,
                    'target_min_rad': math.radians(lower * gear),
                    'target_max_rad': math.radians(upper * gear),
                    'loop_start_motion_rad': 0.0,
                    'loop_end_motion_rad': 0.0,
                    'loop_delta_rad': 0.0,
                    'loop_tolerance_rad': math.radians(5.0),
                    'motion_clamped': False,
                }
                for name, axis, gear, lower, upper in JOINTS
            ],
        },
        'motor_activity': {},
        'execution_context': {},
        'service_management': {},
        'motion_test_limits': {},
        'project_scope': {'runtime_matches_selected': True, 'motor_config_applied': True},
        'safety_status': {
            'commands_blocked': False,
            'servo_alarm_blocked_axes': [],
            'emergency_latched': False,
        },
    }


def tick(dt: float) -> None:
    """목표를 향해 스르르 · 페이더 감각 확인용."""
    for axis, target in state['targets'].items():
        current = state['positions'][axis]
        step = (target - current) * min(1.0, dt * 8.0)
        state['positions'][axis] = current + step


# --------------------------------------------------------------------------- #
# 서버
# --------------------------------------------------------------------------- #

app = FastAPI()
composer = IndexComposer(STATIC / 'index.html')


@app.get('/')
async def index():
    html, _etag = composer.compose()
    return HTMLResponse(html)


@app.get('/favicon.ico')
async def favicon():
    return JSONResponse({}, status_code=404)


@app.get('/static/{asset_path:path}')
async def static_asset(asset_path: str):
    target = (STATIC / asset_path).resolve()
    if not str(target).startswith(str(STATIC.resolve())) or not target.is_file():
        return JSONResponse({'detail': 'not found'}, status_code=404)
    return FileResponse(target)


@app.websocket('/ws/status')
async def ws_status(websocket: WebSocket):
    await websocket.accept()
    last = time.monotonic()
    try:
        while True:
            now = time.monotonic()
            tick(now - last)
            last = now
            await websocket.send_text(json.dumps(snapshot()))
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, ConnectionError, RuntimeError):
        return


@app.websocket('/ws/manual-stream')
async def ws_manual_stream(websocket: WebSocket):
    await websocket.accept()
    if state['run_mode'] in ('off', 'schedule'):
        await websocket.send_text(json.dumps({
            'type': 'error',
            'message': ('오프 모드 · 명령이 차단되어 있습니다 (상단에서 모드를 바꾸세요)'
                        if state['run_mode'] == 'off' else
                        '스케줄 모드 · 수동 조작은 「수동」 모드에서만 됩니다 (상단에서 모드를 바꾸세요)'),
        }, ensure_ascii=False))
        await websocket.close()
        return
    try:
        hello = json.loads(await websocket.receive_text())
    except (WebSocketDisconnect, ConnectionError, RuntimeError, ValueError):
        return
    if hello.get('type') != 'hello':
        await websocket.close()
        return
    await websocket.send_text(json.dumps({'type': 'hello_ok'}))
    try:
        while True:
            message = json.loads(await websocket.receive_text())
            kind = message.get('type')
            if kind == 'target':
                axis = int(message.get('axis'))
                state['targets'][axis] = math.degrees(float(message.get('target_rad')))
            elif kind == 'release':
                for axis in message.get('axes') or []:
                    state['targets'][int(axis)] = state['positions'][int(axis)]
                await websocket.send_text(json.dumps({
                    'type': 'result', 'success': True,
                    'axes': message.get('axes'), 'message': '프리뷰 · 그 자리에 섰습니다',
                }, ensure_ascii=False))
    except (WebSocketDisconnect, ConnectionError, RuntimeError, ValueError, KeyError):
        return


# ---- REST · 그럴듯한 기본값 ------------------------------------------------ #

# 개발 PC 의 실제 export 폴더 · 프리뷰에서 진짜 애니메이션을 고르고
# 「미리보기」로 MuJoCo(물리 없는 kinematic)를 바로 띄운다
EXPORT_DIR = Path(r'D:/my_ws/floating/floating_1800/export')
SIM_SCRIPTS = Path(r'D:/my_ws/floating/floating_1800/sim/scripts')
SIM_MODEL = '../fh_1800_wires_R011.xml'
UV = ['uv', 'run', '--no-project', '--with=mujoco', '--with=numpy', 'python']

#: 도는 무조코 계산 · {npz 경로: Popen}
computing: dict = {}


def _npz_for(motion: Path) -> Path:
    return motion.with_name(motion.stem + '.sim.npz')


def _mujoco_state(motion: Path) -> str:
    npz = _npz_for(motion)
    handle = computing.get(str(npz))
    if handle is not None:
        if handle.poll() is None:
            return 'computing'
        del computing[str(npz)]
    return 'ready' if npz.is_file() else 'missing'


def export_files():
    if not EXPORT_DIR.is_dir():
        return []
    return [
        {
            'id': path.name, 'filename': path.name,
            'size_bytes': path.stat().st_size,
            'updated_at': path.stat().st_mtime,
            'valid': True, 'message': '',
            'preview': {'state': _mujoco_state(path)},
        }
        for path in sorted(EXPORT_DIR.glob('*.json'))
    ]


@app.get('/api/motion-files')
async def motion_files():
    files = export_files()
    return {'success': True, 'files': files,
            'project_generation': state['generation']}


@app.get('/api/motion-files/{file_id}')
async def motion_file_detail(file_id: str):
    motion = (EXPORT_DIR / Path(file_id).name)
    if not motion.is_file():
        return {'success': False, 'message': f'파일이 없습니다: {file_id}',
                'files': export_files(), 'project_generation': state['generation']}
    return {
        'success': True,
        'file': {
            'id': motion.name, 'filename': motion.name,
            'size_bytes': motion.stat().st_size,
            'updated_at': motion.stat().st_mtime,
            'valid': True, 'message': '',
            'preview': {'state': _mujoco_state(motion)},
        },
        'files': export_files(),
        'project_generation': state['generation'],
    }


@app.post('/api/motion-files/{file_id}/preview-precompute')
async def precompute_motion_file(file_id: str):
    motion = (EXPORT_DIR / Path(file_id).name)
    if not motion.is_file():
        return {'success': False, 'message': f'파일이 없습니다: {file_id}',
                'project_generation': state['generation']}
    npz = _npz_for(motion)
    if str(npz) in computing and computing[str(npz)].poll() is None:
        return {'success': True, 'message': f'이미 계산 중입니다: {motion.name}',
                'project_generation': state['generation']}
    import subprocess
    out_csv = motion.with_name(motion.stem + '.sim.csv')
    computing[str(npz)] = subprocess.Popen(
        UV + ['sim_run.py', SIM_MODEL, str(motion), str(out_csv)],
        cwd=str(SIM_SCRIPTS),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False,
    )
    return {'success': True,
            'message': f'무조코 계산 시작: {motion.name} · 수십 초 걸립니다 (진짜 물리 시뮬)',
            'project_generation': state['generation']}


def _launch_replay(motion: Path, fps) -> dict:
    npz = _npz_for(motion)
    state_now = _mujoco_state(motion)
    if state_now == 'computing':
        return {'success': False, 'message': '무조코 계산 중입니다 · 끝나면 틀 수 있습니다'}
    if state_now != 'ready':
        return {'success': False, 'message': '계산 결과가 없습니다 · 「무조코 계산」을 먼저 누르세요'}
    import subprocess
    fps = fps if fps in (30, 60, 120, 144) else 60
    subprocess.Popen(
        UV + ['replay_run.py', str(npz), str(fps)],
        cwd=str(SIM_SCRIPTS),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, shell=False,
    )
    return {'success': True, 'message': f'무조코 재생: {motion.name} ({fps} fps · 와이어 흔들림 포함 · Space 일시정지, ←→ 탐색, ↑↓ 배속)'}


@app.post('/api/motion-files/{file_id}/preview')
async def preview_motion_file(file_id: str, request: Request):
    motion = (EXPORT_DIR / Path(file_id).name)
    if not motion.is_file():
        return {'success': False, 'message': f'파일이 없습니다: {file_id}',
                'project_generation': state['generation']}
    try:
        body = await request.json()
    except Exception:
        body = {}
    result = _launch_replay(motion, body.get('fps'))
    result['project_generation'] = state['generation']
    return result


@app.post('/api/motion-mappings/motion-file')
async def save_registered_playlist(request: Request):
    """재생 등록 · 재생 목록 흉내 · 메모리에만 · 수정 목록 35"""
    body = await request.json()
    if 'motion_playlist' in body:
        playlist = [str(item) for item in body.get('motion_playlist') or [] if str(item)]
    else:
        single = str(body.get('motion_file_id') or '')
        playlist = [single] if single else []
    state['playlist'] = playlist
    MAPPING_FILE['motion_file_id'] = playlist[0] if playlist else ''
    message = (
        f'재생 목록 등록 완료: {len(playlist)}개 · ' + ' → '.join(playlist)
        if len(playlist) > 1
        else (f'재생 등록 완료: {playlist[0]}' if playlist else '재생 등록을 해제했습니다')
    )
    return {'success': True, 'message': message, 'file': MAPPING_FILE,
            'motion_file_id': MAPPING_FILE['motion_file_id'],
            'motion_playlist': playlist,
            'project_generation': state['generation']}


@app.put('/api/motion-run/automation')
async def configure_automation(request: Request):
    body = await request.json()
    if body.get('group_sync_mode') in ('lockstep', 'independent'):
        state['group_sync_mode'] = body['group_sync_mode']
    return {'success': True, 'message': '프리뷰 · 자동 반복 설정 저장',
            'status': snapshot()['motion_run_status'],
            'project_generation': state['generation']}


@app.post('/api/motion-run/stop')
@app.post('/api/motion-run/stop-after-cycle')
async def stop_motion_run():
    state['run_started'] = None
    return {'success': True, 'message': '프리뷰 · 정지',
            'status': {'state': 'stopped'},
            'project_generation': state['generation']}


@app.post('/api/motion-run/start')
async def start_motion_run(request: Request):
    """가짜 재생 · with_mujoco 면 그 자리에서 뷰어를 같이 띄워 흐름을 보여 준다."""
    body = await request.json()
    message = '프리뷰 · 재생 흉내'
    if body.get('run_mode') == 'continuous':
        state['run_started'] = time.time()
    if body.get('with_mujoco'):
        motion = EXPORT_DIR / str(body.get('motion_file_id') or '')
        result = _launch_replay(motion, body.get('mujoco_fps'))
        message = f"프리뷰 재생 흉내 · {result['message']}"
    return {'success': True, 'message': message,
            'status': {'state': 'running'},
            'project_generation': state['generation']}


MAPPING_FILE = {
    'id': 'motion_axis.yaml',
    'filename': 'motion_axis.yaml',
    'valid': True,
    'message': '',
    'revision': 'preview-rev-1',
    'mapping_revision': 'preview-rev-1',
    'name': 'motion_axis',
    'motion_file_id': 'floating_no1_motion1.json',
    'mapping_count': len(JOINTS),
    'enabled_count': len(JOINTS),
    'mapped_count': len(JOINTS),
}

def _preview_network_pcs():
    """같은 망 PC 표 · 로봇 3대 + 스피커 · 하나는 끊김 · 핵심 요구 4"""
    def pc(pc_id, address, **extra):
        row = {
            'pc_id': pc_id, 'display_name': pc_id, 'role': 'robot', 'address': address,
            'web_url': f'http://{address}:8000', 'group_id': 'stage-a', 'joined': True,
            'is_master': False, 'git_hash': 'cadddb6', 'protocol_version': 5,
            'is_local': False, 'online': True, 'age_sec': 0.4, 'same_group': True,
            'version_differs': False, 'protocol_mismatch': False,
        }
        row.update(extra)
        return row
    return [
        pc('floating1', '192.168.0.11', is_master=True, is_local=True, age_sec=0.0),
        pc('floating2', '192.168.0.12'),
        pc('floating3', '192.168.0.13', joined=False, git_hash='454d49b', version_differs=True),
        pc('floating4', '192.168.0.14', online=False, age_sec=42.0),
        pc('speaker', '192.168.0.20', role='speaker', web_url='http://192.168.0.20:8100',
           protocol_version=0, joined=False),
    ]


CANNED = {
    ('GET', '/api/status'): snapshot,
    ('GET', '/api/coordination'): lambda: {
        'success': True, 'node_connected': True, 'config_error': '',
        'config': {'pc_id': 'floating1', 'display_name': 'floating1', 'enabled': False,
                   'group_id': '', 'dds_domain_id': 21, 'is_master': False, 'required_peers': []},
        'runtime': {'node_connected': True, 'joined': False, 'peers': [],
                    'config': {'pc_id': 'floating1', 'enabled': False},
                    'execution': {'state': 'idle'}, 'network_pcs': _preview_network_pcs()},
    },
    ('GET', '/api/schedule/status'): lambda: {
        'run_mode': state['run_mode'],
        'schedules': [],
        'enabled': True,
        'active_schedule_id': '',
        'coordination_enabled': False,
        'coordination_joined': False,
        'is_master': True,
        'clock': {
            'local_time': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'utc_offset': '+0900',
            'timezone': 'Asia/Seoul',
        },
    },
    ('GET', '/api/schedule/list'): lambda: {'schedules': []},
    ('GET', '/api/motion-mappings'): lambda: {
        'success': True,
        'files': [MAPPING_FILE],
        'active_file_id': 'motion_axis.yaml',
        'message': '프리뷰 모션축 설정',
    },
    ('GET', '/api/motion-mappings/motion_axis.yaml'): lambda: {
        'success': True,
        'file': MAPPING_FILE,
        'files': [MAPPING_FILE],
        'mapping': _mapping_doc(),
        'validation': None,
    },
    ('GET', '/api/projects'): lambda: {
        'projects': [{
            'project_id': 'preview', 'name': '프리뷰',
            'counts': {'motions': 1, 'motion_axis_matching': 1, 'motor_axes': 1},
        }],
        'selected_project_id': 'preview',
        'project': {'project_id': 'preview', 'name': '프리뷰'},
        'tree': [],
        'project_generation': state['generation'],
    },
}


@app.post('/api/motion-run/live-override')
async def set_live_override(request: Request):
    body = await request.json()
    motion_id = str(body.get('motion_id') or '')
    entry = dict(state['live_overrides'].get(motion_id) or {})
    if 'muted' in body:
        entry['muted'] = bool(body['muted'])
    if 'clamp' in body:
        if body['clamp'] is None:
            entry.pop('clamp', None)
        else:
            entry['clamp'] = [float(body['clamp'][0]), float(body['clamp'][1])]
    if entry.get('muted') or entry.get('clamp'):
        state['live_overrides'][motion_id] = entry
    else:
        state['live_overrides'].pop(motion_id, None)
    return {'success': True, 'live_overrides': state['live_overrides'],
            'project_generation': state['generation']}


@app.post('/api/motion-test/ac-servo/jog')
@app.post('/api/motion-test/dynamixel/jog')
async def fake_jog(request: Request):
    """가짜 조그 · 목표에 상대 이동을 더한다 · 앞 조그가 덜 끝났으면 거절(실물과 같게)"""
    body = await request.json()
    axis = int(body.get('axis'))
    delta = math.degrees(float(body.get('relative_rad') or 0.0))
    if state['run_mode'] == 'off':
        return {'success': False, 'message': '오프 모드 · 명령이 차단되어 있습니다',
                'project_generation': state['generation']}
    if state['run_mode'] == 'schedule':
        return {'success': False,
                'message': '스케줄 모드 · 수동 조작은 「수동」 모드에서만 됩니다 (상단에서 모드를 바꾸세요)',
                'project_generation': state['generation']}
    if abs(state['targets'][axis] - state['positions'][axis]) > 0.05:
        return {'success': False,
                'message': f'{axis}번 모터의 이전 조그가 아직 돌고 있습니다 · 끝난 뒤 다시',
                'project_generation': state['generation']}
    state['targets'][axis] = state['positions'][axis] + delta
    return {'success': True, 'message': f'프리뷰 조그 {delta:+.2f}°',
            'project_generation': state['generation']}


# --------------------------------------------------------------------------- #
# 로봇 팩 · 진짜 서비스(robot_pack_service)를 그대로 · 놓는 곳만 runtime/ 아래
# --------------------------------------------------------------------------- #

DEV_PACK_WORKSPACE = ROOT / 'runtime' / 'dev_preview'


def _pack_checker(workspace_root, pack_dir):
    from motion_web_bridge import robot_pack_service
    return robot_pack_service.run_checker(ROOT, pack_dir)   # 실행기는 저장소의 scripts/sim


@app.get('/api/robot-pack')
async def robot_pack_status():
    from motion_web_bridge import robot_pack_service
    return robot_pack_service.pack_status(DEV_PACK_WORKSPACE)


@app.put('/api/robot-pack')
async def upload_robot_pack(request: Request):
    from motion_web_bridge import robot_pack_service
    DEV_PACK_WORKSPACE.mkdir(parents=True, exist_ok=True)
    data = await request.body()
    return await asyncio.to_thread(
        robot_pack_service.install_pack, DEV_PACK_WORKSPACE, data, checker=_pack_checker,
    )


@app.post('/api/robot-pack/rollback')
async def rollback_robot_pack():
    from motion_web_bridge import robot_pack_service
    return robot_pack_service.rollback_pack(DEV_PACK_WORKSPACE)


@app.get('/api/robot-pack/mapping-diff')
async def robot_pack_mapping_diff():
    from motion_web_bridge import robot_pack_service
    result = robot_pack_service.mapping_diff(DEV_PACK_WORKSPACE, {'mappings': mapping_rows()})
    result['mapping_file'] = 'dev_preview (가짜 모션축 설정)'
    return result


# --------------------------------------------------------------------------- #
# 웹 3D 「Blender 뷰」 흉내 · 수정 목록 50 · 상자 헤드 4개가 4초 동안 고개를 돌리는 glb
# --------------------------------------------------------------------------- #

def _demo_glb() -> bytes:
    """진짜 Blender 장면 대신 · glTF 2.0 바이너리를 손으로 짠다 (Y-up · 정면 +Z)"""
    import struct
    vertices = [(x, y, z) for x in (-0.2, 0.2) for y in (-0.2, 0.2) for z in (-0.2, 0.2)]
    faces = [(0, 1, 3), (0, 3, 2), (4, 6, 7), (4, 7, 5), (0, 4, 5), (0, 5, 1),
             (2, 3, 7), (2, 7, 6), (0, 2, 6), (0, 6, 4), (1, 5, 7), (1, 7, 3)]
    half = math.sqrt(0.5)
    times = [0.0, 2.0, 4.0]
    turns = [(0, 0, 0, 1), (0, half, 0, half), (0, 0, 0, 1)]
    blobs = [
        b''.join(struct.pack('<3f', *v) for v in vertices),
        b''.join(struct.pack('<3H', *f) for f in faces),   # 72 바이트
        struct.pack('<3f', *times),
        b''.join(struct.pack('<4f', *q) for q in turns),
    ]
    views, offset = [], 0
    for blob in blobs:
        views.append({'buffer': 0, 'byteOffset': offset, 'byteLength': len(blob)})
        offset += len(blob)
    accessors = [
        {'bufferView': 0, 'componentType': 5126, 'count': 8, 'type': 'VEC3',
         'min': [-0.2, -0.2, -0.2], 'max': [0.2, 0.2, 0.2]},
        {'bufferView': 1, 'componentType': 5123, 'count': 36, 'type': 'SCALAR'},
        {'bufferView': 2, 'componentType': 5126, 'count': 3, 'type': 'SCALAR', 'min': [0.0], 'max': [4.0]},
        {'bufferView': 3, 'componentType': 5126, 'count': 3, 'type': 'VEC4'},
    ]
    nodes = [{'name': f'Head_{i + 1}', 'mesh': 0, 'translation': [(i - 1.5) * 0.8, 1.5, 0.0]} for i in range(4)]
    nodes.append({'name': 'Store_Floor', 'mesh': 0, 'scale': [10.0, 0.05, 6.0]})
    gltf = {
        'asset': {'version': '2.0', 'generator': 'robot_web dev_preview'},
        'scene': 0, 'scenes': [{'nodes': list(range(len(nodes)))}],
        'nodes': nodes,
        'meshes': [{'primitives': [{'attributes': {'POSITION': 0}, 'indices': 1, 'material': 0}]}],
        'materials': [{'pbrMetallicRoughness': {'baseColorFactor': [0.8, 0.7, 0.6, 1.0], 'roughnessFactor': 0.8}}],
        'animations': [{'name': 'Look_Around', 'samplers': [{'input': 2, 'output': 3}],
                        'channels': [{'sampler': 0, 'target': {'node': i, 'path': 'rotation'}} for i in range(4)]}],
        'buffers': [{'byteLength': offset}], 'bufferViews': views, 'accessors': accessors,
    }
    body = json.dumps(gltf).encode('utf-8')
    body += b' ' * ((4 - len(body) % 4) % 4)
    binary = b''.join(blobs)
    binary += b'\x00' * ((4 - len(binary) % 4) % 4)
    total = 12 + 8 + len(body) + 8 + len(binary)
    return (b'glTF' + struct.pack('<II', 2, total) + struct.pack('<I', len(body)) + b'JSON' + body
            + struct.pack('<I', len(binary)) + b'BIN\x00' + binary)


DEMO_GLB = _demo_glb()


def _demo_scene() -> dict:
    """MuJoCo 장면 JSON 흉내 · 헤드 5축(목 좌우·상하 · 눈 상하 · 눈 좌우 둘) · z-up · m"""
    def body(i, name, parent, pos):
        return {'id': i, 'name': name, 'parent': parent, 'pos': pos, 'quat': [1, 0, 0, 0]}

    def hinge(i, name, body_id, adr, axis):
        return {'id': i, 'name': name, 'body': body_id, 'type': 'hinge', 'qposadr': adr,
                'axis': axis, 'pos': [0, 0, 0]}

    def geom(body_id, kind, size, pos, rgba):
        return {'body': body_id, 'type': kind, 'size': size, 'pos': pos, 'quat': [1, 0, 0, 0],
                'rgba': rgba, 'group': 0}

    gray, skin, white = [0.55, 0.58, 0.62, 1], [0.85, 0.75, 0.65, 1], [0.95, 0.95, 0.95, 1]
    return {
        'bodies': [
            body(0, 'world', -1, [0, 0, 0]), body(1, 'base', 0, [0, 0, 2.0]),
            body(2, 'yaw', 1, [0, 0, -0.3]), body(3, 'pitch', 2, [0, 0, -0.2]),
            body(4, 'eye_pitch', 3, [0, -0.32, 0.05]),
            body(5, 'eye_l', 4, [0.12, 0, 0]), body(6, 'eye_r', 4, [-0.12, 0, 0]),
        ],
        'joints': [
            hinge(0, 'neck_yaw', 2, 0, [0, 0, 1]), hinge(1, 'neck_pitch', 3, 1, [1, 0, 0]),
            hinge(2, 'eye_pitch', 4, 2, [1, 0, 0]), hinge(3, 'eye_yaw_l', 5, 3, [0, 0, 1]),
            hinge(4, 'eye_yaw_r', 6, 4, [0, 0, 1]),
        ],
        'geoms': [
            geom(0, 'plane', [3, 3, 0.01], [0, 0, 0], [0.4, 0.45, 0.5, 1]),
            geom(1, 'cylinder', [0.04, 0.15, 0], [0, 0, 0.15], gray),
            geom(2, 'box', [0.1, 0.1, 0.1], [0, 0, 0], gray),
            geom(3, 'box', [0.3, 0.3, 0.25], [0, 0, -0.1], skin),
            geom(5, 'sphere', [0.07, 0, 0], [0, 0, 0], white),
            geom(6, 'sphere', [0.07, 0, 0], [0, 0, 0], white),
            geom(5, 'sphere', [0.03, 0, 0], [0, -0.06, 0], [0.1, 0.1, 0.1, 1]),
            geom(6, 'sphere', [0.03, 0, 0], [0, -0.06, 0], [0.1, 0.1, 0.1, 1]),
        ],
        'meshes': {},
        'camera': {'lookat': [0, 0, 1.6], 'distance': 2.2, 'azimuth': -90, 'elevation': -10},
        'axes': [
            {'joint': 'neck_pitch', 'motion_id': 'Neck_Pitch'},
            {'joint': 'neck_yaw', 'motion_id': 'Neck_Yaw'},
            {'joint': 'eye_pitch', 'motion_id': 'Eye_Pitch'},
            {'joint': 'eye_yaw_l', 'motion_id': 'Eye_Yaw_L'},
            {'joint': 'eye_yaw_r', 'motion_id': 'Eye_Yaw_R'},
        ],
    }


@app.get('/api/preview/scene/data')
async def preview_scene_data():
    # 진짜 서버는 모든 응답 머리에 프로젝트 세대를 싣는다 · 화면이 그것으로 늦은 응답을 가린다
    return JSONResponse(_demo_scene(), headers={'X-Project-Generation': str(state['generation'])})


@app.get('/api/preview/scene')
async def preview_scene_state():
    # MuJoCo 장면(가짜 헤드 5축)과 Blender 뷰가 둘 다 있는 팩
    return {'state': 'ready', 'message': '프리뷰 · 가짜 MuJoCo 장면 · Blender 뷰도 있음',
            'blender': {'available': True, 'size_bytes': len(DEMO_GLB), 'fingerprint': 'devpreview000001'},
            'project_generation': state['generation']}


@app.get('/api/preview/blender-scene')
async def preview_blender_scene():
    from fastapi import Response
    return Response(DEMO_GLB, media_type='model/gltf-binary', headers={'Cache-Control': 'no-cache'})


@app.put('/api/schedule/mode')
async def set_mode(request: Request):
    body = await request.json()
    mode = str(body.get('run_mode') or 'schedule')
    state['run_mode'] = mode
    return {'success': True, 'run_mode': mode}


@app.api_route('/api/{rest:path}', methods=['GET', 'POST', 'PUT', 'DELETE', 'PATCH'])
async def api_catch_all(rest: str, request: Request):
    handler = CANNED.get((request.method, f'/api/{rest}'))
    if handler:
        payload = handler()
    else:
        payload = {'success': True, 'message': f'프리뷰 · /{rest} 은 가짜 응답'}
    payload.setdefault('project_generation', state['generation'])
    return JSONResponse(payload)


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8010
    print(f'UI 프리뷰 · http://localhost:{port}  (가짜 장비 · 배포와 무관)')
    uvicorn.run(app, host='127.0.0.1', port=port, log_level='warning')
