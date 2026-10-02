"""계산 결과(sim_run 의 npz)를 MuJoCo 뷰어에서 실시간으로 재생

사용:
    uv run --no-project --with mujoco --with numpy --with pyyaml python replay_run.py RUN.npz [FPS=60] [--pack PACK_DIR]

모델은 npz 안의 경로 · 카메라는 팩 env.camera (--pack 없으면 모델 옆 robot.yaml · 없으면 기본).
키: Space 일시정지 · 좌우 ±5 s · 상하 배속 ×2 / ×0.5 · Home 처음부터
"""
import sys
import time
from pathlib import Path

import numpy as np
import mujoco
import mujoco.viewer

import sim_core  # noqa: F401 · 스택 src/motion_common 을 import 경로에 넣는다
from sim_core import SETPOINT_S
from motion_common.robot_pack import load_robot

DEFAULT_CAMERA = {'lookat': [0.0, -0.2, 3.5], 'distance': 5.5, 'azimuth': -60, 'elevation': -5}


def _args(argv):
    pack = None
    if '--pack' in argv:
        k = argv.index('--pack')
        pack = argv[k + 1]
        argv = argv[:k] + argv[k + 2:]
    if not argv:
        print(__doc__)
        sys.exit(2)
    return argv[0], (float(argv[1]) if len(argv) > 1 else 60.0), pack


def _camera(pack, model_path):
    for candidate in ([pack] if pack else []) + [str(Path(model_path).parent)]:
        try:
            return load_robot(Path(candidate)).camera
        except ValueError:
            continue
    return DEFAULT_CAMERA


run_path, FPS, pack = _args(sys.argv[1:])
run = np.load(run_path)
model_path = str(run['model'])
m = mujoco.MjModel.from_xml_path(model_path)
d = mujoco.MjData(m)
Q, T, TW = run['qpos'], run['t'], run['twist']
if Q.shape[1] != m.nq:
    sys.exit('결과와 모델이 맞지 않습니다 (qpos %d ≠ 모델 nq %d) · 팩이 바뀌었으면 다시 계산하세요' % (Q.shape[1], m.nq))
n_frames = int(run['n_frames'])
dur = float(T[-1])
m.light_castshadow[:] = 0
camera = _camera(pack, model_path)

state = dict(t=0.0, paused=False, speed=1.0)


def key(k):
    if k == 32:  # space
        state['paused'] = not state['paused']
    elif k == 262:  # right
        state['t'] = min(dur, state['t'] + 5.0)
    elif k == 263:  # left
        state['t'] = max(0.0, state['t'] - 5.0)
    elif k == 265:  # up
        state['speed'] = min(8.0, state['speed'] * 2)
    elif k == 264:  # down
        state['speed'] = max(0.125, state['speed'] / 2)
    elif k == 268:  # home
        state['t'] = 0.0


print('replaying %s (%s, %.0f s, %d frames) - close the window to stop' % (run_path.replace('\\', '/').split('/')[-1], str(run['ref']), dur, n_frames), flush=True)
with mujoco.viewer.launch_passive(m, d, key_callback=key) as v:
    v.cam.lookat[:] = [float(x) for x in camera['lookat']]
    v.cam.distance = float(camera['distance'])
    v.cam.azimuth = float(camera['azimuth'])
    v.cam.elevation = float(camera['elevation'])
    v.opt.flags[mujoco.mjtVisFlag.mjVIS_TENDON] = True
    last = time.perf_counter()
    loop = 1
    while v.is_running():
        now = time.perf_counter()
        dt = now - last
        last = now
        if not state['paused']:
            state['t'] += dt * state['speed']
            if state['t'] > dur:
                state['t'] = 0.0
                loop += 1
        k = min(len(T) - 1, int(np.searchsorted(T, state['t'])))
        with v.lock():
            d.qpos[:] = Q[k]
            mujoco.mj_kinematics(m, d)
        frame = min(n_frames, int(state['t'] / SETPOINT_S) + 1)
        v.set_texts((mujoco.mjtFontScale.mjFONTSCALE_150, mujoco.mjtGridPos.mjGRID_TOPLEFT,
                     'Frame\nTime\nLoop\nSpeed\nBase twist',
                     '%d / %d\n%.2f / %.2f s\n%d\nx%g%s\n%+.1f deg' % (frame, n_frames, state['t'], (n_frames - 1) * SETPOINT_S, loop,
                                                                   state['speed'], '  (paused)' if state['paused'] else '', TW[k])))
        v.sync()
        time.sleep(max(0.0, 1.0 / FPS - (time.perf_counter() - now)))
