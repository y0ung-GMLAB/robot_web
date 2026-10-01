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

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse  # noqa: E402
import uvicorn  # noqa: E402

from motion_web_bridge.index_composer import IndexComposer  # noqa: E402

STATIC = ROOT / 'src' / 'web_ui' / 'static'

# --------------------------------------------------------------------------- #
# 가짜 장비 · 플로팅 헤드 5축
# --------------------------------------------------------------------------- #

JOINTS = [
    # (조인트, 축, 감속비, 최소, 최대)
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
            'offset_deg': 0.0,
            'scale': 1.0,
            'reference_position_deg': 0.0,
            'reference_enabled': True,
            'motion_lower_deg': lower,
            'motion_upper_deg': upper,
            'initial_mode': 'first_frame',
            'initial_position_deg': 0.0,
            'initial_move_time_sec': 5.0,
        }
        for name, axis, gear, lower, upper in JOINTS
    ]


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
            'position_deg': round(position, 3),
            'position': round(position, 3),
            'velocity_deg_s': 0.0,
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
            'state': 'ready',
            'message': '프리뷰 · 실행 준비 검사 흉내',
            'live_overrides': state['live_overrides'],
            'automation': {'repeat_mode': 'reinitialize'},
            'axes': [
                {
                    'motion_id': name,
                    'motor_axis': axis,
                    'motor_type': 'ac_servo',
                    'motion_limit_lower_deg': lower,
                    'motion_limit_upper_deg': upper,
                    'initial_motor_target_deg': 0.0,
                    'target_min_deg': lower * gear,
                    'target_max_deg': upper * gear,
                    'loop_start_motion_deg': 0.0,
                    'loop_end_motion_deg': 0.0,
                    'loop_delta_deg': 0.0,
                    'loop_tolerance_deg': 5.0,
                    'motion_clamped': False,
                }
                for name, axis, gear, lower, upper in JOINTS
            ],
        },
        'motor_activity': {},
        'execution_context': {},
        'service_management': {},
        'motion_test_limits': {},
        'project_scope': {},
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
    if state['run_mode'] == 'off':
        await websocket.send_text(json.dumps({
            'type': 'error',
            'message': '오프 모드 · 명령이 차단되어 있습니다 (상단에서 모드를 바꾸세요)',
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
                state['targets'][axis] = float(message.get('target_deg'))
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


@app.post('/api/motion-run/start')
async def start_motion_run(request: Request):
    """가짜 재생 · with_mujoco 면 그 자리에서 뷰어를 같이 띄워 흐름을 보여 준다."""
    body = await request.json()
    message = '프리뷰 · 재생 흉내'
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

CANNED = {
    ('GET', '/api/status'): snapshot,
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
        'message': '프리뷰 조인트 연결',
    },
    ('GET', '/api/motion-mappings/motion_axis.yaml'): lambda: {
        'success': True,
        'file': MAPPING_FILE,
        'files': [MAPPING_FILE],
        'mapping': {
            'name': 'motion_axis',
            'file_id': 'motion_axis.yaml',
            'motion_file_id': 'floating_no1_motion1.json',
            'mappings': mapping_rows(),
        },
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
