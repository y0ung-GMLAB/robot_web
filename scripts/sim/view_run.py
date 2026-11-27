"""실시간 MuJoCo 뷰어 · 애니메이션을 로봇 팩 모델에서 바로 돌린다 (sim_run 과 같은 드라이브·서보 모델)

사용:
    uv run --no-project --with mujoco --with numpy --with pyyaml python view_run.py PACK_DIR MOTION.json [interp|pp] [FPS=100] [kinematic]

kinematic: 물리 없음 (정착·와이어 흔들림 없음) · 관절각을 바로 넣는다 · 즉시 시작 · 미니 PC 용.
"""
import math
import sys
import time

import mujoco
import mujoco.viewer

import sim_core
from sim_core import SETPOINT_S, Sim, apply_camera, load_motion

if len(sys.argv) < 3:
    print(__doc__)
    sys.exit(2)
pack_dir, motion_path = sys.argv[1], sys.argv[2]
_extra = [a.lower() for a in sys.argv[3:]]
KINEMATIC = 'kinematic' in _extra
REF = next((a for a in _extra if a in ('interp', 'pp')), 'interp')
_fps = [a for a in _extra if a.replace('.', '', 1).isdigit()]
FPS = float(_fps[0]) if _fps else 100.0
robot = sim_core.load_pack_or_exit(pack_dir)
tgt, n_sp = load_motion(motion_path, robot)
name = motion_path.split('\\')[-1].split('/')[-1]

if KINEMATIC:                                        # 물리 없이 동작만 · 즉시 시작
    m = mujoco.MjModel.from_xml_path(str(robot.model_path))
    d = mujoco.MjData(m)
    errors = sim_core.check_model(robot, m)
    if errors:
        sys.exit('\n'.join(errors))
    qadr = {a.joint: m.jnt_qposadr[m.joint(a.joint).id] for a in robot.axes}
    sync_every = max(1, int(round(50.0 / max(FPS, 1.0))))
    print('playing %s (kinematic, %.0f s) - close the window to stop' % (name, n_sp * SETPOINT_S))
    m.light_castshadow[:] = 0
    with mujoco.viewer.launch_passive(m, d) as v:
        apply_camera(v, robot)
        v.opt.flags[mujoco.mjtVisFlag.mjVIS_TENDON] = True
        i = 0
        t0 = time.perf_counter()
        while v.is_running():
            k = i % n_sp
            for j in qadr:
                d.qpos[qadr[j]] = math.radians(tgt[j][k])
            mujoco.mj_forward(m, d)
            if i % sync_every == 0:
                wall = time.perf_counter() - t0
                v.set_texts((mujoco.mjtFontScale.mjFONTSCALE_150, mujoco.mjtGridPos.mjGRID_TOPLEFT,
                             'Frame\nTime\nLoop\nSpeed',
                             '%d / %d\n%.2f / %.2f s\n%d\nx%.2f' % (
                                 k + 1, n_sp, k * SETPOINT_S, (n_sp - 1) * SETPOINT_S, i // n_sp + 1,
                                 (i * SETPOINT_S) / max(wall, 1e-6))))
                v.sync()
            lag = t0 + (i + 1) * SETPOINT_S - time.perf_counter()
            if lag > 0:
                time.sleep(lag)
            i += 1
    sys.exit(0)

sim = Sim(robot, ref=REF)
m, d, dt = sim.m, sim.d, sim.dt
print('settling the suspension (%g s sim time)...' % sim.settle_s)
sim.settle()
steps = sim.steps_per_sp
sync_every = max(1, int(round(1.0 / FPS / dt)))
print('playing %s (%s, %.0f s) - close the window to stop' % (name, sim.ref, n_sp * SETPOINT_S))
m.light_castshadow[:] = 0                                        # 가벼운 렌더 (그림자 없음)
with mujoco.viewer.launch_passive(m, d) as v:
    apply_camera(v, robot)
    v.opt.flags[mujoco.mjtVisFlag.mjVIS_TENDON] = True
    i = 0
    t0 = time.perf_counter()
    while v.is_running():
        k = i % n_sp
        sp = {j: tgt[j][k] for j in sim.joints}
        nx = {j: tgt[j][min(k + 1, n_sp - 1)] for j in sim.joints}

        def on_substep(s):
            if (s + 1) % sync_every == 0 or s == steps - 1:          # FPS 로 다시 그림
                wall = time.perf_counter() - t0
                tw = math.degrees(sim.base_yaw() - sim.yaw0)
                v.set_texts((mujoco.mjtFontScale.mjFONTSCALE_150, mujoco.mjtGridPos.mjGRID_TOPLEFT,
                             'Frame\nTime\nLoop\nSpeed\nBase twist',
                             '%d / %d\n%.2f / %.2f s\n%d\nx%.2f\n%+.1f deg' % (
                                 k + 1, n_sp, k * SETPOINT_S + (s + 1) * dt, (n_sp - 1) * SETPOINT_S, i // n_sp + 1,
                                 (i * steps + s + 1) * dt / max(wall, 1e-6), tw)))
                v.sync()
                lag = t0 + (i * steps + s + 1) * dt - time.perf_counter()
                if lag > 0:
                    time.sleep(lag)

        sim.run_setpoint(sp, nx, on_substep)
        i += 1
        if i % 500 == 0:                                            # 모션 시간 10 s 마다
            wall = time.perf_counter() - t0
            print('motion %6.1f s | wall %6.1f s | speed x%.2f' % (i * SETPOINT_S, wall, i * SETPOINT_S / wall), flush=True)
