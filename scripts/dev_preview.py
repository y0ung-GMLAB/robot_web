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
import tempfile
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
    'repeat_mode': 'reinitialize',
    'dwell_sec': 0.0,
    'schedule_end_action': 'park_servo_off',
    'run_started': None,
    # 새 UI(v2) 공연 · 매장 전체로 시작했나 · 돌던 중 다시 켠 축(다음 회차부터)
    'group_run': False,
    # 새 UI(v2) 모터·드라이브 · 설정 이름·속도 · 앱솔루트 설정 흉내
    'motor_registry': None,
    'abs_done': False,
    'abs_job': {'state': 'idle'},
    # 새 UI(v2) 매장 PC · 그룹 참여 스위치 · 필수 명단
    'joined': True,
    'required_peers': ['floating1', 'floating2', 'floating3', 'floating4'],
    'held': set(),
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
        # 새 UI(v2) 조인트 매핑에서 저장하면 메모리의 줄로
        'mappings': state.get('mapping_rows_saved') or mapping_rows(),
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
            # 서버 칸 이름 그대로 · 과부하율 · 오류 (state_publisher.py)
            'overload_ratio_pct': 3.0,
            'errorcode': 0,
            'error_text': 'No error',
            'motion_id': name,
            # 드라이브 고유 이름(motor_ref) 재료 · 새 UI(v2) 조인트 매핑
            'ethercat_master_index': 0, 'alias': 100 + axis, 'slave_position': axis,
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
            # 새 UI(v2) 모터·드라이브 · 앱솔루트 확인 흉내(서버 minas_absolute 모양)
            'minas_absolute': {'state': 'ok', 'drives': [
                {'axis': axis, 'master_index': 0, 'slave_position': axis,
                 'absolute_mode': 0 if axis != 4 or state['abs_done'] else 1,
                 'status': 'ok' if axis != 4 or state['abs_done'] else 'not_absolute',
                 'problem': '' if axis != 4 or state['abs_done'] else 'Pr0.15=1(인크리멘털)'}
                for _, axis, *_ in JOINTS]},
            'project_id': 'preview',
            'selected_project_id': 'preview',
            'project_generation': state['generation'],
            'motors': motors,
            'runtime_status': {'ready': True, 'message': '프리뷰 · 가짜 장비'},
            'motor_identity': {'ok': True},
        },
        'motion_state_age_sec': 0.0,
        # 새 UI(v2) 상단 바 · 홈이 읽는다 · 실제 브리지 스냅샷과 같은 자리
        'system_info': {'hostname': 'floating1'},
        'supervisor_watchdog': {},
        'mapping_range_blocker': _preview_range_blocker(),
        'minas_absolute_blocker': '' if state['abs_done'] else '앱솔루트 미확인 · 4번 모터 Pr0.15=1(인크리멘털) · 모터 관리에서 앱솔루트 설정',
        'coordination': {
            'node_connected': True,
            'config': {'pc_id': 'floating1', 'enabled': True, 'group_id': 'stage-a', 'is_master': True,
                       'dds_domain_id': 21, 'required_peers': list(state['required_peers'])},
            'runtime': {'joined': state['joined'], 'network_pcs': _preview_network_pcs(), 'coordination_error': {},
                        **_preview_group_runtime()},
        },
        'motion_run_status': {
            **_fake_run_status(),
            'live_overrides': state['live_overrides'],
            'held_motion_ids': sorted(state['held']),
            'group_execution': state['group_run'] and state['run_started'] is not None,
            'automation': {
                'repeat_mode': state['repeat_mode'],
                'dwell_sec': state['dwell_sec'],
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
        'service_management': {'managed': True, 'mode': 'automatic',
                               'runtime': {'phase': 'ready', 'message': '모터 피드백 정상'}},
        'web_access': {'url': 'http://192.168.0.11:8000', 'lan_ip': '192.168.0.11', 'port': 8000},
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


@app.get('/v2')
@app.get('/v2/')
async def index_v2():
    # 새 UI · 뼈대 + 홈 · 설계안 2026-10-09
    return FileResponse(STATIC / 'v2' / 'index.html', headers={'Cache-Control': 'no-cache'})


@app.get('/favicon.ico')
async def favicon():
    return JSONResponse({}, status_code=404)


@app.get('/static/{asset_path:path}')
async def static_asset(asset_path: str):
    target = (STATIC / asset_path).resolve()
    if not str(target).startswith(str(STATIC.resolve())) or not target.is_file():
        return JSONResponse({'detail': 'not found'}, status_code=404)
    # 서버처럼 매번 물어본다 · 옛 모듈이 캐시에 남아 화면이 「불러오는 중」 에서 멈추지 않게
    return FileResponse(target, headers={'Cache-Control': 'no-cache'})


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


def _motion_duration(path):
    """마지막 줄 [frame, time_sec, ...] 의 시간 · 못 읽으면 None"""
    try:
        lines = path.read_text(encoding='utf-8').strip().splitlines()
        return float(json.loads(lines[-1])[1])
    except (OSError, ValueError, IndexError, TypeError, KeyError):
        return None


#: 새 UI(v2) 애니메이션 · 프리뷰에서 올린 파일은 여기에만 · 원본 내보내기 폴더는 건드리지 않는다
UPLOAD_DIR = Path(tempfile.gettempdir()) / 'robot_web_preview_uploads'
_ANALYSIS_CACHE = {}


def _motion_paths():
    dirs = [d for d in (EXPORT_DIR, UPLOAD_DIR) if d.is_dir()]
    return sorted((p for d in dirs for p in d.glob('*.json')), key=lambda p: p.name)


def _find_motion(file_id):
    name = Path(str(file_id)).name
    return next((p for p in _motion_paths() if p.name == name), None)


def _preview_analysis(path, detail=False):
    """서버 analyze_motion_json 흉내 · 조인트별 최소·최대(rad) · 길이 · 그래프 · mtime 캐시"""
    key = (str(path), path.stat().st_mtime_ns)
    if key not in _ANALYSIS_CACHE:
        groups, times, unit, error = {}, [], 'deg', ''
        try:
            with path.open(encoding='utf-8') as handle:
                header = json.loads(handle.readline())
                unit = str(header.get('rotation_unit') or 'deg')
                scale = 1.0 if unit == 'rad' else math.pi / 180.0
                for line in handle:
                    if not line.strip():
                        continue
                    row = json.loads(line)
                    t = float(row[1])
                    times.append(t)
                    for i in range(2, len(row) - 1, 2):
                        groups.setdefault(str(row[i]), []).append((t, float(row[i + 1]) * scale))
        except (OSError, ValueError, IndexError, TypeError, AttributeError) as exc:
            error = f'형식 · {exc}'
        stats = [{'motion_id': mid, 'count': len(v), 'first_value': v[0][1], 'last_value': v[-1][1],
                  'min_value': min(x for _, x in v), 'max_value': max(x for _, x in v)} for mid, v in sorted(groups.items())]
        series = []
        for mid, v in sorted(groups.items())[:12]:
            stride = max(1, math.ceil(len(v) / 300))
            series.append({'motion_id': mid, 'points': [{'time_sec': t, 'value': x} for t, x in v[::stride]]})
        duration = (max(times) - min(times)) if times else 0.0
        _ANALYSIS_CACHE[key] = {
            'valid': not error and bool(groups), 'message': error or ('motion data valid' if groups else '데이터 줄 없음'),
            'errors': [error] if error else [], 'warnings': [], 'value_unit': 'rad', 'source_unit': unit,
            'motion_ids': stats, 'motion_id_count': len(stats),
            'time': {'start_sec': min(times) if times else 0.0, 'end_sec': max(times) if times else 0.0, 'duration_sec': duration},
            'interpolation': {'period_sec': 0.02, 'sample_count': int(duration / 0.02) + 1 if times else 0},
            'graph_series': series,
        }
    result = dict(_ANALYSIS_CACHE[key])
    if not detail:
        result.pop('graph_series', None)
    return result


def _file_entry(path, detail=False):
    analysis = _preview_analysis(path, detail)
    return {
        'id': path.name, 'filename': path.name,
        'size_bytes': path.stat().st_size,
        'updated_at': path.stat().st_mtime,
        'valid': analysis['valid'], 'message': analysis['message'],
        # 서버 모양 · 검사 결과와 길이는 analysis 아래 · 새 UI(v2) 가 여기서 읽는다
        'analysis': analysis,
        'preview': {'state': _mujoco_state(path)},
    }


def export_files():
    return [_file_entry(path) for path in _motion_paths()]


@app.post('/api/projects/{project_id}/files')
async def preview_import_file(project_id: str, request: Request):
    """올리기 흉내 · 임시 폴더에만 · 이름이 겹치면 서버처럼 거절"""
    body = await request.json()
    name = Path(str(body.get('file_name') or '')).name
    if not name.lower().endswith('.json'):
        return JSONResponse({'detail': '애니메이션은 .json 만 받습니다'}, status_code=400)
    if _find_motion(name):
        return JSONResponse({'detail': f'같은 이름이 이미 있습니다: {name}'}, status_code=409)
    content = str(body.get('content') or '')
    try:
        json.loads(content.splitlines()[0])
    except (ValueError, IndexError):
        return JSONResponse({'detail': '첫 줄이 motion_header JSON 이 아닙니다'}, status_code=400)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    (UPLOAD_DIR / name).write_text(content, encoding='utf-8', newline='')
    return {'success': True, 'message': f'올림: {name}'}


@app.delete('/api/motion-files/{file_id}')
async def preview_delete_motion(file_id: str):
    path = _find_motion(file_id)
    if path is None:
        return {'success': False, 'message': f'파일이 없습니다: {file_id}'}
    if path.name in state['playlist']:
        return {'success': False, 'message': f'재생 등록된 애니메이션입니다: {path.name} · 재생 등록을 해제한 뒤 삭제하세요'}
    if path.parent != UPLOAD_DIR:
        return {'success': False, 'message': '프리뷰 · 원본 내보내기 폴더 파일은 지우지 않습니다(프리뷰에서 올린 것만)'}
    path.unlink()
    return {'success': True, 'message': f'애니메이션 삭제 완료: {path.name}'}


@app.get('/api/projects/{project_id}/files/motions/{file_name}/download')
async def preview_download_motion(project_id: str, file_name: str):
    path = _find_motion(file_name)
    if path is None:
        return JSONResponse({'detail': 'Not Found'}, status_code=404)
    return FileResponse(str(path), filename=path.name, media_type='application/json')


@app.get('/api/motion-files')
async def motion_files():
    files = export_files()
    return {'success': True, 'files': files, 'project_id': 'preview',
            'project_generation': state['generation']}


@app.get('/api/motion-files/{file_id}')
async def motion_file_detail(file_id: str):
    motion = _find_motion(file_id)
    if motion is None:
        return {'success': False, 'message': f'파일이 없습니다: {file_id}',
                'files': export_files(), 'project_generation': state['generation']}
    return {
        'success': True,
        'file': _file_entry(motion, detail=True),
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
    if body.get('repeat_mode') in ('reinitialize', 'direct', 'dwell', 'dwell_reinitialize'):
        state['repeat_mode'] = body['repeat_mode']
    if 'dwell_sec' in body:
        state['dwell_sec'] = max(0.0, float(body['dwell_sec'] or 0))
    if body.get('schedule_end_action') in ('park_servo_off', 'hold'):
        state['schedule_end_action'] = body['schedule_end_action']
    return {'success': True, 'message': '프리뷰 · 자동 반복 설정 저장',
            'status': snapshot()['motion_run_status'],
            'project_generation': state['generation']}


@app.post('/api/motion-run/stop')
@app.post('/api/motion-run/stop-after-cycle')
async def stop_motion_run():
    state['run_started'] = None
    state['group_run'] = False
    state['held'].clear()
    return {'success': True, 'message': '프리뷰 · 정지',
            'status': {'state': 'stopped'},
            'project_generation': state['generation']}


@app.post('/api/coordination/control')
async def coordination_control(request: Request):
    """그룹 명령 흉내 · 시작이면 이 PC 재생 흉내도 같이 · 새 UI(v2) 공연"""
    body = await request.json()
    command = body.get('command')
    if command == 'start_group':
        state['run_started'] = time.time()
        state['group_run'] = True
        return {'success': True, 'message': '프리뷰 · 매장 전체 시작 · 2대 · floating3 빠짐(버전 다름)'}
    if command in ('stop_now', 'stop_after_cycle'):
        state['run_started'] = None
        state['group_run'] = False
        state['held'].clear()
        return {'success': True, 'message': '프리뷰 · 매장 전체 정지'}
    if command in ('join', 'leave'):
        state['joined'] = command == 'join'
    return {'success': True, 'message': f'프리뷰 · {command}'}


@app.put('/api/coordination/settings')
async def coordination_settings(request: Request):
    """설정 저장 흉내 · 보낸 칸만 · 새 UI(v2) 매장 PC"""
    body = await request.json()
    if isinstance(body.get('required_peers'), list):
        state['required_peers'] = [str(item) for item in body['required_peers']]
    if body.get('joined') is not None:
        state['joined'] = bool(body['joined'])
    return {'success': True, 'message': '프리뷰 · 연동 설정 저장'}


@app.post('/api/motion-run/start')
async def start_motion_run(request: Request):
    """가짜 재생 · with_mujoco 면 그 자리에서 뷰어를 같이 띄워 흐름을 보여 준다."""
    body = await request.json()
    message = '프리뷰 · 재생 흉내'
    if body.get('run_mode') in ('continuous', 'once'):
        state['run_started'] = time.time()
        state['group_run'] = False
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

def _preview_group_runtime():
    """그룹 실행 흉내 · 조정 노드 /status 의 peers · local · execution 모양 · 새 UI(v2) 공연"""
    running = state['group_run'] and state['run_started'] is not None
    cycle = int((time.time() - state['run_started']) // FAKE_ITEM_SEC) + 1 if running else 0

    def peer(pc_id, **extra):
        row = {'pc_id': pc_id, 'display_name': pc_id, 'state': 'online', 'servo_alarm_grade': 0,
               'motion_cycle_text': f'{cycle}회차' if running else '-',
               'motion_step': '재생 중' if running else '그룹 대기',
               'motion_progress': ''}
        row.update(extra)
        return row
    return {
        'local': peer('floating1', is_master=True),
        'peers': [peer('floating2'), peer('floating3', motion_cycle_text='-', motion_step='그룹 대기'),
                  peer('floating4', state='offline', motion_cycle_text='-', motion_step='-')],
        'execution': {
            'state': 'running' if running else 'idle',
            'execution_id': 'preview-exec' if running else '',
            'participants': ['floating1', 'floating2'] if running else [],
            'excluded': {'floating3': '버전 다름 · 업데이트하면 다음 실행부터'} if running else {},
            'joining': {},
            'start_spread_ms': 6.0 if running else None,
        },
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
        pc('floating1', '192.168.0.11', is_master=True, is_local=True, age_sec=0.0, joined=state['joined']),
        pc('floating2', '192.168.0.12'),
        pc('floating3', '192.168.0.13', joined=False, git_hash='454d49b', version_differs=True),
        pc('floating4', '192.168.0.14', online=False, age_sec=42.0),
        pc('speaker', '192.168.0.20', role='speaker', web_url='http://192.168.0.20:8100',
           protocol_version=0, joined=False),
    ]


_UPDATE = {'started': None}


def _preview_update_rows():
    """모든 PC 업데이트 흉내 · 누르면 업데이트 중 → 응답 없음 → 완료 (몇 초) · 2026-10-08"""
    started = _UPDATE['started']
    rows = []
    for index, pc in enumerate(_preview_network_pcs()):
        row = {k: pc[k] for k in ('pc_id', 'display_name', 'role', 'is_local', 'git_hash')}
        if pc['role'] == 'speaker':
            row.update(state='manual', message='스피커 PC 는 그 PC 터미널에서 · bash ~/robot_web/scripts/install_speaker.sh')
        elif not pc['online']:
            row.update(state='offline', message='연결 안 됨')
        elif started is None:
            row.update(state='idle')
        else:
            age = time.time() - started - index * 2
            if age < 4:
                row.update(state='running', before_hash=pc['git_hash'], tail=['== 8. 전체 빌드', '2/2 · 나머지 전부'])
            elif age < 7:
                row.update(state='unreachable', message='응답 없음 · 업데이트 중이면 잠시 뒤 돌아옵니다')
            else:
                row.update(state='done', before_hash=pc['git_hash'], git_hash='d00d123', exit_code=0, tail=['설치 완료'])
        rows.append(row)
    return {'success': True, 'pcs': rows, 'same_version': started is not None}


def _preview_update_start():
    _UPDATE['started'] = time.time()
    return {**_preview_update_rows(), 'message': '3대 업데이트 시작 · 이 PC 웹은 잠깐 끊겼다 돌아옵니다'}


_WIFI = {'ssid': 'shop-5G', 'pending': None}


def _preview_wifi_status():
    """Wi-Fi 흉내 · 수정 목록 81"""
    out = {'success': True, 'available': True, 'device': 'wlp2s0', 'state': 'connected',
           'connection': f"robot-wifi-{_WIFI['ssid']}", 'ssid': _WIFI['ssid'], 'signal': 78,
           'address': '192.168.0.11/24', 'gateway': '192.168.0.1', 'method': 'auto', 'powersave': '꺼짐'}
    pending = _WIFI['pending']
    if pending and pending['deadline'] > time.time():
        out['pending'] = {'ssid': pending['ssid'], 'seconds_left': round(pending['deadline'] - time.time())}
    return out


def _preview_wifi_connect():
    _WIFI['pending'] = {'ssid': 'office', 'deadline': time.time() + 60}
    _WIFI['ssid'] = 'office'
    return {**_preview_wifi_status(), 'message': 'office 연결됨 · 60초 안에 「유지」 를 누르세요'}


def _preview_wifi_confirm():
    _WIFI['pending'] = None
    return {**_preview_wifi_status(), 'message': 'office 유지'}


_TZ = {'zone': 'Asia/Seoul'}


def _preview_time():
    return {'clock': {'timezone': _TZ['zone'], 'utc_offset': '+0900' if _TZ['zone'] == 'Asia/Seoul' else '+0200',
                      'ntp_synced': True, 'local_time': time.strftime('%Y-%m-%dT%H:%M:%S')},
            'timezones': ['Asia/Seoul', 'Europe/Paris', 'America/New_York', 'Asia/Taipei']}


def _preview_tz_all():
    _TZ['zone'] = 'Europe/Paris'
    rows = [{'pc_id': pc['pc_id'], 'display_name': pc['pc_id'], 'role': pc['role'], 'is_local': pc['is_local'],
             'success': pc['online'] or pc['is_local'],
             'message': ('스피커 · 스케줄이 없어 시간대와 무관 · 건너뜀' if pc['role'] == 'speaker'
                         else ('Asia/Seoul → Europe/Paris · 2초 뒤 프로그램을 다시 띄웁니다' if pc['online'] else '연결 안 됨 · 건너뜀'))}
            for pc in _preview_network_pcs()]
    return {'success': False, 'message': '로봇 PC 3/4대 Europe/Paris', 'pcs': rows, 'clock': _preview_time()['clock']}


#: 새 UI(v2) 홈 「오늘 스케줄」 · 매일 10~18 · 금토 저녁
@app.post('/api/schedule/save')
async def save_preview_schedule(request: Request):
    """스케줄 저장 흉내 · 메모리에만 · 새 UI(v2) 스케줄"""
    body = await request.json()
    item = {k: body.get(k) for k in ('schedule_name', 'start_time', 'stop_time', 'repeat_type', 'repeat_days', 'run_date')}
    item['enabled'] = body.get('enabled', True) is not False
    item['saved_timezone'] = 'Asia/Seoul'
    item['schedule_id'] = body.get('schedule_id') or f'p{int(time.time() * 1000)}'
    for index, old in enumerate(_PREVIEW_SCHEDULES):
        if old['schedule_id'] == item['schedule_id']:
            _PREVIEW_SCHEDULES[index] = item
            break
    else:
        _PREVIEW_SCHEDULES.append(item)
    return {'status': 'ok', 'schedule': item}


@app.post('/api/schedule/{schedule_id}/{action}')
async def toggle_preview_schedule(schedule_id: str, action: str):
    for item in _PREVIEW_SCHEDULES:
        if item['schedule_id'] == schedule_id:
            item['enabled'] = action == 'enable'
    return {'status': 'ok', 'schedule_id': schedule_id, 'enabled': action == 'enable'}


@app.delete('/api/schedule/{schedule_id}')
async def delete_preview_schedule(schedule_id: str):
    _PREVIEW_SCHEDULES[:] = [item for item in _PREVIEW_SCHEDULES if item['schedule_id'] != schedule_id]
    return {'status': 'ok', 'deleted_id': schedule_id}


@app.get('/api/motion-run/status')
async def preview_motion_run_status():
    """서버 모양 · status + 운영 시간 끝 결과 · 새 UI(v2) 스케줄이 끝 동작을 읽는다"""
    status = snapshot()['motion_run_status']
    status['automation']['schedule_end_action'] = state['schedule_end_action']
    return {'success': True, 'message': '', 'status': status,
            'schedule_end': {'state': 'done', 'message': '어제 18:00 · 기준점 도착 → 서보 끔 · 정상'}}


@app.get('/api/servo-alarm-policy')
async def preview_alarm_policy():
    """진짜 카탈로그로 · 메모리에만 · 새 UI(v2) 알람 정책"""
    from motion_web_bridge import servo_alarm_policy as policy
    overrides = policy.normalize_overrides(state.get('alarm_overrides') or {})
    grades = policy.effective_grade_map(overrides)
    catalog = policy.catalog_payload(overrides)
    return {'success': True, 'project_id': 'preview', 'catalog_version': policy.CATALOG_VERSION,
            'grade_definitions': policy.GRADE_DEFINITIONS, 'overrides': overrides, 'effective_grades': grades,
            'policy_revision': policy.policy_revision(grades, policy.CATALOG_VERSION),
            'counts': policy.configured_counts(catalog), 'catalog': catalog}


@app.put('/api/servo-alarm-policy')
async def preview_save_alarm_policy(request: Request):
    body = await request.json()
    state['alarm_overrides'] = body.get('overrides') or {}
    payload = await preview_alarm_policy()
    return {**payload, 'saved': True, 'message': f"프리뷰 · 알람 정책 저장 · 바꾼 것 {len(payload['overrides'])}"}


@app.post('/api/system/timezone')
async def preview_timezone(request: Request):
    body = await request.json()
    return {'success': True, 'changed': False, 'message': f"프리뷰 · 이 PC 시간대 {body.get('zone')} (실제로는 안 바꿈)"}


@app.get('/api/system/version')
async def preview_version():
    return {'branch': 'ui-v2', 'hash': 'cadddb6', 'message': '프리뷰', 'is_main': False}


_PREVIEW_PROJECTS = [
    {'project_id': 'preview', 'name': '프리뷰', 'memo': '10-07 앱솔루트 설정 · 기준점 다시 캡처함',
     'counts': {'motions': 10, 'motion_axis_matching': 1, 'motor_axes': 1}},
    {'project_id': 'floating4_1800', 'name': 'floating4_1800', 'memo': '', 'counts': {'motions': 3}},
]
_PREVIEW_TRASH = [{'entry': 'old-1', 'project_id': 'old_test', 'name': 'old_test', 'deleted_at': '2026-10-08T11:20:00'}]
_SELF_UPDATE = {'started': None}


@app.get('/api/system/update')
async def preview_self_update():
    """이 PC 업데이트 흉내 · 누르면 몇 초 돌다 완료"""
    started = _SELF_UPDATE['started']
    if started is None:
        return {'success': True, 'git_hash': 'cadddb6', 'state': 'idle'}
    if time.time() - started < 6:
        return {'success': True, 'git_hash': 'cadddb6', 'state': 'running', 'before_hash': 'cadddb6',
                'tail': ['== 2. 코드 받기', '== 7. 의존성 확인', '== 8. 빌드 1/2']}
    return {'success': True, 'git_hash': 'd00d123', 'state': 'done', 'before_hash': 'cadddb6', 'after_hash': 'd00d123',
            'finished_at': started + 6}


@app.post('/api/system/update')
async def preview_self_update_start():
    _SELF_UPDATE['started'] = time.time()
    return {'success': True, 'state': 'running', 'message': '프리뷰 · 이 PC 업데이트 시작'}


@app.get('/api/projects')
async def preview_projects():
    return {'success': True, 'projects': _PREVIEW_PROJECTS, 'selected_project_id': 'preview'}


@app.post('/api/projects')
async def preview_create_project(request: Request):
    body = await request.json()
    name = str(body.get('name') or '').strip()
    _PREVIEW_PROJECTS.append({'project_id': name, 'name': name, 'memo': '', 'counts': {}})
    return {'success': True, 'message': f'프리뷰 · {name} 만듦'}


@app.patch('/api/projects/{project_id}')
async def preview_project_memo(project_id: str, request: Request):
    body = await request.json()
    for project in _PREVIEW_PROJECTS:
        if project['project_id'] == project_id:
            project['memo'] = str(body.get('memo') or '')
    return {'success': True}


@app.delete('/api/projects/{project_id}')
async def preview_delete_project(project_id: str):
    if project_id == 'preview':
        return {'success': False, 'message': '지금 고른 프로젝트는 지울 수 없습니다'}
    _PREVIEW_PROJECTS[:] = [p for p in _PREVIEW_PROJECTS if p['project_id'] != project_id]
    _PREVIEW_TRASH.append({'entry': f'{project_id}-t', 'project_id': project_id, 'name': project_id,
                           'deleted_at': time.strftime('%Y-%m-%dT%H:%M:%S')})
    return {'success': True}


@app.get('/api/project-backups')
async def preview_project_backups():
    return {'success': True, 'keep_days': 14, 'days': [
        {'day': d, 'projects': [{'project_id': 'preview', 'size_bytes': 18_400_000}]}
        for d in ('2026-10-12', '2026-10-11', '2026-10-10')]}


@app.get('/api/project-trash')
async def preview_project_trash():
    return {'success': True, 'keep_days': 7, 'entries': _PREVIEW_TRASH}


@app.post('/api/project-trash/{entry}/restore')
async def preview_restore_trash(entry: str):
    item = next((t for t in _PREVIEW_TRASH if t['entry'] == entry), None)
    if item is None:
        return {'success': False, 'message': '없는 항목'}
    _PREVIEW_TRASH.remove(item)
    _PREVIEW_PROJECTS.append({'project_id': item['project_id'], 'name': item['name'], 'memo': '', 'counts': {}})
    return {'success': True, 'message': f"프리뷰 · {item['name']} 되살림"}


_PREVIEW_EVENTS = [
    {'timestamp_text': '2026-10-12T14:27:01.000', 'category': 'coordination', 'event_type': 'group_cycle', 'content': '그룹 3회차 시작 · 2대 · 시작 편차 6 ms'},
    {'timestamp_text': '2026-10-12T10:03:12.000', 'category': 'error', 'event_type': 'motor_error', 'content': '2번 모터 0x1800 Err24.0 위치 편차 과대 · 자동 복구 1/3'},
    {'timestamp_text': '2026-10-12T10:00:02.000', 'category': 'initial_position', 'event_type': 'initial_move', 'content': '첫 자세로 천천히 · 5.0 s'},
    {'timestamp_text': '2026-10-12T10:00:00.000', 'category': 'motion', 'event_type': 'continuous_motion_started', 'content': '스케줄 매장 운영 시작 · 연속 재생'},
    {'timestamp_text': '2026-10-11T18:00:00.000', 'category': 'system', 'event_type': 'schedule_end', 'content': '운영 시간 끝 · 기준점 도착 → 서보 끔'},
]


@app.get('/api/motor-events')
async def preview_motor_events(category: str = 'all', limit: int = 200, file_name: str = 'all'):
    """운영 로그 흉내 · 카테고리 · 날짜 파일로 거른다 · 새 UI(v2) 기록"""
    rows = [e for e in _PREVIEW_EVENTS if category == 'all' or e['category'] == category]
    if file_name != 'all':
        rows = [e for e in rows if e['timestamp_text'].startswith(file_name.replace('.jsonl', ''))]
    return {'success': True, 'events': rows[:limit], 'category': category, 'files': [
        {'name': '2026-10-12.jsonl', 'size': 2048, 'record_count': 4}, {'name': '2026-10-11.jsonl', 'size': 512, 'record_count': 1}]}


def _preview_runs():
    def axes(scale):
        return [{'motion_id': name, 'motor_axis': axis, 'max_abs_error_deg': round(0.05 * scale * (axis + 1), 3),
                 'max_abs_error_at_sec': 1.2 + axis, 'rms_error_deg': 0.02} for name, axis, *_ in JOINTS]
    return [
        {'file': '142701_c3.csv', 'started_text': '2026-10-12T14:27:01+09:00', 'cycle': 3, 'motion_file_id': 'floating_no1_motion1.json',
         'result': 'completed', 'group_execution': True, 'axes': axes(1.0)},
        {'file': '141800_c2.csv', 'started_text': '2026-10-12T14:18:00+09:00', 'cycle': 2, 'motion_file_id': 'floating_1800_dir_test.json',
         'result': 'stopped', 'message': '회차 도중 정지', 'axes': axes(0.6)},
        {'file': '100000_c1.csv', 'started_text': '2026-10-12T10:00:00+09:00', 'cycle': 1, 'motion_file_id': 'floating_no1_motion1.json',
         'result': 'error', 'message': '2번 모터 도달 확인 실패 0.094°', 'axes': axes(2.0)},
    ]


@app.get('/api/motion-trace/days')
async def preview_trace_days():
    return {'success': True, 'days': [{'date': '2026-10-12', 'cycle_count': 3, 'file_count': 3, 'bytes': 120000},
                                      {'date': '2026-10-11', 'cycle_count': 0, 'file_count': 0, 'bytes': 0}]}


@app.get('/api/motion-trace/runs')
async def preview_trace_runs(date: str):
    return {'success': True, 'date': date, 'runs': _preview_runs() if date == '2026-10-12' else []}


@app.get('/api/motion-trace/trace')
async def preview_trace(date: str, file: str):
    """목표는 사인 · 실제는 조금 늦고 작게 · 축마다 다르게"""
    times = [i * 0.05 for i in range(400)]
    axes = []
    for name, axis, *_ in JOINTS:
        amp = 4.0 + axis * 2
        target = [round(amp * math.sin(t * (0.5 + axis * 0.15)), 4) for t in times]
        actual = [round(amp * 0.98 * math.sin((t - 0.04) * (0.5 + axis * 0.15)), 4) for t in times]
        axes.append({'motion_id': name, 'target': target, 'actual': actual,
                     'error': [round(a - b, 4) for a, b in zip(actual, target)]})
    record = next((r for r in _preview_runs() if r['file'] == file), {})
    return {'success': True, 'date': date, 'file': file, 'sample_count': 400, 'decimation': 1, 'time': times, 'axes': axes, 'record': record}


@app.get('/api/motion-trace/download')
async def preview_trace_download(date: str, file: str):
    return HTMLResponse('time_sec,Neck_Pitch_target_deg,Neck_Pitch_actual_deg\n0,0,0\n', media_type='text/csv')


def _preview_validate(body):
    rows = (body.get('mapping') or {}).get('mappings') or []
    out_rows, errors = {}, []
    for row in rows:
        mid = str(row.get('motion_id') or '')
        problems = []
        if float(row.get('motion_lower_rad') or 0) > float(row.get('motion_upper_rad') or 0):
            problems.append('motion_lower_rad must be <= motion_upper_rad')
        if not float(row.get('gear_ratio') or 0) > 0:
            problems.append('gear_ratio must be > 0')
        errors += [f'{mid}: {p}' for p in problems]
        out_rows[mid] = {'status': 'error' if problems else 'ok', 'messages': problems}
    return {'valid': not errors, 'message': 'ok' if not errors else 'motion mapping validation failed',
            'errors': errors, 'warnings': [], 'rows': out_rows}


@app.post('/api/motion-mappings/validate')
async def preview_validate_mapping(request: Request):
    body = await request.json()
    validation = _preview_validate(body)
    return {'success': validation['valid'], 'message': validation['message'], 'mapping': body.get('mapping'), 'validation': validation}


@app.post('/api/motion-mappings')
async def preview_save_mapping(request: Request):
    """저장 흉내 · 버전이 다르면 서버와 같은 문구로 거절"""
    body = await request.json()
    if body.get('base_mapping_revision') and body['base_mapping_revision'] != MAPPING_FILE['mapping_revision']:
        return {'success': False, 'message': 'motion mapping command failed: 조인트 매핑이 화면을 불러온 뒤 변경됐습니다 · 다시 불러오세요'}
    validation = _preview_validate(body)
    if not validation['valid']:
        return {'success': False, 'message': 'motion mapping validation failed', 'validation': validation}
    state['mapping_rows_saved'] = (body.get('mapping') or {}).get('mappings') or []
    state['mapping_rev'] = state.get('mapping_rev', 1) + 1
    MAPPING_FILE['revision'] = MAPPING_FILE['mapping_revision'] = f"preview-rev-{state['mapping_rev']}"
    return {'success': True, 'message': '프리뷰 · 조인트 매핑 저장 · 모터 운전 한계 갱신 · 드라이브 반영은 「장비에 적용 · 모터 재시작」',
            'file': MAPPING_FILE, 'mapping': _mapping_doc(), 'validation': validation}


@app.post('/api/motor-config/apply')
async def preview_apply_motor_config():
    return {'success': True, 'message': '프리뷰 · 장비에 적용 (실제로는 아무것도 안 함)'}


def _preview_range_blocker():
    """서버 joint_mapping.range_block_reason 흉내 · 수정 목록 97"""
    rows = state.get('mapping_rows_saved') or mapping_rows()
    ids = []
    for row in rows:
        if row.get('enabled') is False or not row.get('motion_id'):
            continue
        confirmed = row.get('range_confirmed')
        if confirmed is None:
            confirmed = not (abs(math.degrees(float(row.get('motion_lower_rad') or 0)) + 180) < 1e-6
                             and abs(math.degrees(float(row.get('motion_upper_rad') or 0)) - 180) < 1e-6)
        if not confirmed:
            ids.append(str(row['motion_id']))
    if not ids:
        return ''
    return f"조인트 범위 미확인 · {', '.join(ids)} · 모터 관리 → 조인트 매핑에서 실제 기계 범위(최소·최대)를 넣거나 「범위 확인」 을 체크하고 저장하세요"


def _preview_registry():
    if state['motor_registry'] is None:
        state['motor_registry'] = {'motors': [
            {'id': f'ac_servo_master_0_alias_{100 + axis}', 'enabled': True, 'axis': axis, 'name': name,
             'motor_type': 'ac_servo', 'driver_family': 'minas', 'transport': 'ethercat',
             'identity': {'ethercat_master_index': 0, 'ethercat_alias': 100 + axis, 'slave_position': axis, 'vendor_id': '0x066f'},
             'profile': {'driver_model': 'MINAS A6B', 'model_confirmed': True},
             'config': {'controller_index': axis, 'position': axis, 'profile_velocity': 18000, 'profile_acceleration': 180000,
                        'acceleration': 180000, 'max_speed_rpm': 3000, 'overload_monitor': 1}}
            for name, axis, *_ in JOINTS]}
    return state['motor_registry']


@app.get('/api/motor-config')
async def preview_motor_config():
    import hashlib
    registry = _preview_registry()
    revision = hashlib.sha256(json.dumps(registry, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {'success': True, 'saved': True, 'config_file': 'motor_axes/motor_axes.yaml', 'config_revision': revision, 'registry': registry}


@app.put('/api/motor-config')
async def preview_save_motor_config(request: Request):
    body = await request.json()
    current = await preview_motor_config()
    if body.get('base_revision') != current['config_revision']:
        return {'success': False, 'message': 'failed to save motor config YAML: 설정 파일이 화면을 불러온 뒤 변경됐습니다'}
    for motor in (body.get('registry') or {}).get('motors') or []:
        config = motor.get('config') or {}
        pv, rpm = float(config.get('profile_velocity') or 0), float(config.get('max_speed_rpm') or 0)
        if pv and rpm and pv > rpm * 6:
            return {'success': False, 'message': f"failed to save motor config YAML: {motor['axis']}번 모터 · 프로파일 속도 {pv:g} deg/s 가 최대 속도 {rpm:g} rpm ({rpm * 6:g} deg/s) 보다 큽니다"}
    state['motor_registry'] = body.get('registry')
    return {**(await preview_motor_config()), 'message': '프리뷰 · 모터 설정 저장 · 드라이브 반영은 「장비에 적용」'}


@app.post('/api/motion-test/ac-servo/control')
async def preview_servo_control(request: Request):
    body = await request.json()
    action = body.get('action')
    if action in ('servo_on', 'servo_off'):
        state['servo_on'] = action == 'servo_on'
    return {'success': True, 'message': {'servo_on': '서보 켬', 'servo_off': '서보 끔', 'fault_reset': '오류 초기화 · 서보는 꺼진 채'}.get(action, action)}


@app.post('/api/motor-config/drive-maintenance')
async def preview_drive_maintenance(request: Request):
    body = await request.json()
    action = body.get('action')
    return {'success': True, 'action': action, 'axis': body.get('axis'), 'power_cycle_required': action in ('absolute_mode', 'absolute_clear'),
            'message': f"프리뷰 · {body.get('axis')}번 {action} (실제로는 아무것도 안 함)"}


@app.get('/api/motor-config/absolute-setup')
async def preview_absolute_job():
    job = state['abs_job']
    if job.get('state') == 'running':
        step = min(7, int((time.time() - job['started']) // 2) + 1)
        labels = ['서보 끄기', '모드 쓰기 + EEPROM', '전원 껐다 켜기 1', '확인', '다회전 클리어', '전원 껐다 켜기 2', '검증']
        if step >= 7 and time.time() - job['started'] > 14:
            state['abs_done'] = True
            state['abs_job'] = {'state': 'done', 'message': '완료 · 위치 숫자가 바뀌어 기준점을 다시 캡처해야 합니다'}
            return state['abs_job']
        return {'state': 'running', 'step_index': step, 'step_count': 7, 'step_label': labels[step - 1],
                'message': '프리뷰 · 몇 초씩 지나갑니다'}
    return job


@app.post('/api/motor-config/absolute-setup/preview')
async def preview_absolute_preview(request: Request):
    targets = [] if state['abs_done'] else [{'label': '4번 · Eye_Yaw_R', 'axis': 4, 'problem': 'Pr0.15=1(인크리멘털)'}]
    skipped = [{'label': f'{axis}번 · {name}', 'axis': axis, 'reason': '이미 정상'} for name, axis, *_ in JOINTS if axis != 4 or state['abs_done']]
    return {'success': True, 'targets': targets, 'skipped': skipped,
            'steps': ['서보 끄기', 'Pr0.15 = 0 · EEPROM', '드라이브 전원 껐다 켜기', '확인', '다회전 클리어', '드라이브 전원 한 번 더', '검증']}


@app.post('/api/motor-config/absolute-setup')
async def preview_absolute_start(request: Request):
    state['abs_job'] = {'state': 'running', 'started': time.time()}
    return {'success': True, 'message': '프리뷰 · 앱솔루트 설정 시작'}


@app.post('/api/motor-config/absolute-setup/cancel')
async def preview_absolute_cancel():
    state['abs_job'] = {'state': 'failed', 'message': '취소함'}
    return {'success': True, 'message': '취소했습니다'}


@app.post('/api/motion-test/ac-servo/action')
async def preview_absolute_move(request: Request):
    """목표 위치로 · 가짜 모터가 스르르 · 수동 모드에서만(서버처럼)"""
    body = await request.json()
    if state['run_mode'] != 'manual':
        return {'success': False, 'message': '수동 조작은 「수동」 모드에서만 됩니다'}
    axis = int(body.get('axis'))
    state['targets'][axis] = math.degrees(float(body.get('target_rad') or 0))
    return {'success': True, 'message': f'{axis}번 · 목표 {state["targets"][axis]:.2f}° 로 천천히'}


@app.post('/api/safety/motion-stop')
async def preview_motion_stop():
    for axis, value in state['positions'].items():
        state['targets'][axis] = value
    state['run_started'] = None
    return {'success': True, 'message': '프리뷰 · 정지 · 서보는 켠 채', 'acknowledgement_pending': True}


_PREVIEW_DOCS = [
    {'id': 'usage', 'title': '사용법', 'subtitle': '화면 하나하나', 'path': 'docs/사용법.md'},
    {'id': 'install', 'title': '설치법', 'subtitle': 'README', 'path': 'README.md'},
]
_REPO = Path(__file__).resolve().parents[1]


@app.get('/api/docs')
async def preview_docs():
    """문서 목록 · 저장소 파일 그대로 · 새 UI(v2) 사용법"""
    out = []
    for doc in _PREVIEW_DOCS:
        path = _REPO / doc['path']
        out.append({**{k: doc[k] for k in ('id', 'title', 'subtitle')}, 'source': doc['path'],
                    'available': path.is_file(), 'modified': path.stat().st_mtime if path.is_file() else 0.0})
    return {'success': True, 'documents': out}


@app.get('/api/docs/images/{name:path}')
async def preview_doc_image(name: str):
    base = (_REPO / 'docs' / 'images').resolve()
    target = (base / name).resolve()
    if base not in target.parents or not target.is_file():
        return JSONResponse({'detail': 'Not Found'}, status_code=404)
    return FileResponse(str(target))


@app.get('/api/docs/{doc_id}')
async def preview_doc(doc_id: str):
    doc = next((d for d in _PREVIEW_DOCS if d['id'] == doc_id), None)
    if doc is None:
        return JSONResponse({'detail': '없는 문서'}, status_code=404)
    path = _REPO / doc['path']
    if not path.is_file():
        return {'success': False, 'id': doc_id, 'title': doc['title'], 'markdown': '', 'message': f"{doc['path']} 파일이 없습니다"}
    return {'success': True, 'id': doc_id, 'title': doc['title'], 'source': doc['path'], 'markdown': path.read_text(encoding='utf-8')}


_PREVIEW_SCHEDULES = [
    {'schedule_id': 'a', 'schedule_name': '매장 운영', 'start_time': '10:00:00', 'stop_time': '18:00:00',
     'repeat_type': 'daily', 'repeat_days': [], 'enabled': True},
    {'schedule_id': 'b', 'schedule_name': '저녁 시연', 'start_time': '19:00:00', 'stop_time': '21:00:00',
     'repeat_type': 'weekly', 'repeat_days': ['FRI', 'SAT'], 'enabled': True},
]


CANNED = {
    ('GET', '/api/system/time'): _preview_time,
    ('POST', '/api/system/timezone-all'): _preview_tz_all,
    ('GET', '/api/system/wifi'): _preview_wifi_status,
    ('POST', '/api/system/wifi/scan'): lambda: {'success': True, 'message': '3개 찾음', 'networks': [
        {'ssid': 'shop-5G', 'signal': 78, 'security': 'WPA2', 'in_use': True},
        {'ssid': 'office', 'signal': 55, 'security': 'WPA2 WPA3', 'in_use': False},
        {'ssid': 'guest', 'signal': 31, 'security': '--', 'in_use': False}]},
    ('POST', '/api/system/wifi/connect'): _preview_wifi_connect,
    ('POST', '/api/system/wifi/confirm'): _preview_wifi_confirm,
    ('POST', '/api/system/wifi/rollback'): _preview_wifi_confirm,
    ('GET', '/api/system/update-all'): _preview_update_rows,
    ('POST', '/api/system/update-all'): _preview_update_start,
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
        'active_schedule_id': 'a' if 10 <= time.localtime().tm_hour < 18 else '',
        'coordination_enabled': False,
        'coordination_joined': False,
        'is_master': True,
        'clock': {
            'local_time': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'utc_offset': '+0900',
            'timezone': 'Asia/Seoul',
            'ntp_synced': True,
        },
    },
    ('GET', '/api/schedule/list'): lambda: {'schedules': _PREVIEW_SCHEDULES},
    ('GET', '/api/motor-events-canned-old'): lambda: {'success': True, 'events': [
        {'timestamp_text': time.strftime('%Y-%m-%dT%H:%M:%S.000'), 'content': '3회차 시작 · 2대 · 시작 편차 6 ms'},
        {'timestamp_text': time.strftime('%Y-%m-%dT10:03:12.000'), 'content': '자동 복구 1/3 · 2번 모터 도달 확인 실패 0.094°'},
        {'timestamp_text': time.strftime('%Y-%m-%dT10:00:00.000'), 'content': '매장 운영 시작'},
    ]},
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
        # 돌던 중 다시 켜면 다음 회차부터 · 서버 held_motion_ids 흉내
        if not entry['muted'] and state['run_started'] is not None:
            state['held'].add(motion_id)
        elif entry['muted']:
            state['held'].discard(motion_id)
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
