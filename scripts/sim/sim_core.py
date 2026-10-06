"""공용 sim 실행기 핵심 · 로봇 값은 전부 로봇 팩(robot.yaml)에서

sim_run(계산) · view_run(실시간 뷰어)가 같은 드라이브·서보 모델을 쓴다:

    드라이브 에뮬   pp      MINAS Profile Position · 20 ms 설정점 · 모터축 속도·가속 한계
                    interp  설정점 사이 선형 보간 (CSP 같은 이상 추종)
    서보            관절 PID · 정지 자세의 부하 관성(아마추어 포함)으로 대역폭 맞춤 · 토크 제한
    정착            settle_body 아래 free joint 를 강한 감쇠로 settle_s 동안 가라앉힌 뒤 놓는다
    비틀림          settle_body 의 z 비틀림에 torsion_k / torsion_c 외력 (0 = 와이어만)

환경변수 덮어쓰기 (팩 값보다 우선): FH_REF, FH_VMAX, FH_AMAX, FH_BASE_IZZ,
FH_TORSION_K, FH_TORSION_C · FH_REC_HZ 는 sim_run 몫.
실행: uv run --no-project --with mujoco --with numpy --with pyyaml python ...
"""

from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

import numpy as np
import mujoco

STACK_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(STACK_ROOT / 'src' / 'motion_common'))

from motion_common import motion_table  # noqa: E402
from motion_common.robot_pack import Robot, load_robot  # noqa: E402

#: 모션 파일 한 행 = 20 ms (motion_web 형식 · 50 fps 고정)
SETPOINT_S = 0.02
#: 정착 중 free joint 감쇠 · 놓은 뒤 남기는 구조·공기 감쇠 (병진 3 · 회전 3)
SETTLE_DAMPING = 2000.0
FREE_DAMPING = [5.0, 5.0, 5.0, 2.0, 2.0, 2.0]

try:
    sys.stdout.reconfigure(encoding='utf-8')
except AttributeError:  # pragma: no cover
    pass


def env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    return float(value) if value not in (None, '') else float(default)


def load_motion(motion_path, robot: Robot):
    """motion_web JSON Lines → 축별 설정점(deg) · motion_id 완전 일치 · 없으면 0 + 경고.

    헤더 `rotation_unit` 이 rad 면 deg 로 바꾼다 · 재생 파서와 같은 함수 · 수정 목록 6-2
    시간 열로 20 ms 마다 선형 보간한다 · 실물 재생(`plan_builder`)과 같은 방식 ·
    전에는 줄 순서만 보고 줄 = 20 ms 로 쳤다 · 시간 간격이 고르지 않은 파일이면
    시뮬과 실물이 어긋났다 · 수정 목록 8 (2026-10-06)
    """
    content = open(motion_path, encoding='utf-8').read()
    scale = motion_table.rotation_unit_scale(
        motion_table.rotation_unit_from_content(content), 'deg',
    )
    lines = content.splitlines()[1:]
    rows = [json.loads(line) for line in lines if line.strip()]
    seen = set()
    times = []
    values = {axis.joint: [] for axis in robot.axes}
    for index, row in enumerate(rows):
        vals = {row[i]: row[i + 1] for i in range(2, len(row), 2)}
        seen.update(vals)
        try:
            times.append(float(row[1]))
        except (TypeError, ValueError, IndexError):
            times.append(index * SETPOINT_S)
        for axis in robot.axes:
            values[axis.joint].append(float(vals.get(axis.motion_id, 0.0)) * scale)
    missing = [a.motion_id for a in robot.axes if a.motion_id not in seen]
    if missing:
        print('warning: motion file has no %s -> held at 0 deg' % ', '.join(missing), file=sys.stderr)
    if not rows:
        return {axis.joint: [] for axis in robot.axes}, 0
    order = np.argsort(np.asarray(times), kind='stable')
    time_axis = np.asarray(times, dtype=float)[order]
    start, end = float(time_axis[0]), float(time_axis[-1])
    count = max(1, int(math.floor((end - start) / SETPOINT_S + 1e-9)) + 1)
    if end - (start + (count - 1) * SETPOINT_S) > 0.001:
        count += 1
    grid = np.minimum(start + np.arange(count) * SETPOINT_S, end)
    tgt = {
        joint: [float(v) for v in np.interp(grid, time_axis, np.asarray(series, dtype=float)[order])]
        for joint, series in values.items()
    }
    return tgt, count


def check_model(robot: Robot, model=None):
    """모델 로드 + 축 이름 대조 · 오류 목록 (비면 통과)."""
    errors = []
    if model is None:
        try:
            model = mujoco.MjModel.from_xml_path(str(robot.model_path))
        except ValueError as exc:  # mujoco 는 XML·메쉬 오류를 ValueError 로 알린다
            return ['model.xml · 로드 실패: %s' % ' '.join(str(exc).strip().splitlines()[:3])]
    for axis in robot.axes:
        if mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, axis.joint) < 0:
            errors.append('model.xml · joint 없음: %s' % axis.joint)
        if mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_ACTUATOR, 'act_' + axis.joint) < 0:
            errors.append('model.xml · actuator 없음: act_%s' % axis.joint)
    if mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, robot.settle_body) < 0:
        errors.append('model.xml · body 없음 (env.settle_body): %s' % robot.settle_body)
    return errors


def apply_camera(viewer, robot: Robot):
    cam = robot.camera
    viewer.cam.lookat[:] = [float(v) for v in cam['lookat']]
    viewer.cam.distance = float(cam['distance'])
    viewer.cam.azimuth = float(cam['azimuth'])
    viewer.cam.elevation = float(cam['elevation'])


class Sim:
    """한 팩 · 한 모델 · 드라이브 에뮬 + 서보 + 매달림."""

    def __init__(self, robot: Robot, *, ref=None):
        self.robot = robot
        self.joints = [axis.joint for axis in robot.axes]
        self.ratio = {axis.joint: axis.ratio for axis in robot.axes}
        self.bw_hz = {axis.joint: axis.servo_bw_hz for axis in robot.axes}
        self.reducer = {
            axis.joint: (axis.reducer_spec.get('t2n_nm'), axis.reducer_spec.get('t2b_nm'))
            for axis in robot.axes
        }
        self.ref = (ref or os.environ.get('FH_REF') or 'pp').lower()
        self.vmax_motor = env_float('FH_VMAX', robot.profile_velocity_deg_s)
        self.amax_motor = env_float('FH_AMAX', robot.profile_accel_deg_s2)
        self.extra_izz = env_float('FH_BASE_IZZ', 0.0)
        self.torsion_k = env_float('FH_TORSION_K', robot.torsion_k)
        self.torsion_c = env_float('FH_TORSION_C', robot.torsion_c)
        self.settle_s = robot.settle_s

        m = self.m = mujoco.MjModel.from_xml_path(str(robot.model_path))
        d = self.d = mujoco.MjData(m)
        errors = check_model(robot, m)
        if errors:
            raise ValueError('\n'.join(errors))
        self.base_bid = m.body(robot.settle_body).id
        if self.extra_izz > 0:
            _b = self.base_bid
            m.body_inertia[_b][2] += self.extra_izz
            m.body_inertia[_b][0] += self.extra_izz / 2
            m.body_inertia[_b][1] += self.extra_izz / 2
        jid = {j: m.joint(j).id for j in self.joints}
        self.dof = {j: m.jnt_dofadr[jid[j]] for j in self.joints}
        self.qadr = {j: m.jnt_qposadr[jid[j]] for j in self.joints}
        self.act = {j: m.actuator('act_' + j).id for j in self.joints}
        self.tmax = {j: m.actuator_ctrlrange[self.act[j]][1] for j in self.joints}
        #: 매달린 몸통(free joint)의 dof · 고정 베이스 로봇이면 비어 있다 (정착 생략)
        self.free_dofs = self._free_dofs()
        self.dt = m.opt.timestep
        self.steps_per_sp = int(round(SETPOINT_S / self.dt))

        # 게인 · 정지 자세 관절공간 관성 (M * e_i · API 무관)
        mujoco.mj_forward(m, d)
        Mfull = np.zeros((m.nv, m.nv))
        for _i in range(m.nv):
            _e = np.zeros(m.nv)
            _e[_i] = 1.0
            _r = np.zeros(m.nv)
            mujoco.mj_mulM(m, d, _r, _e)
            Mfull[:, _i] = _r
        self.Minv = np.linalg.inv(Mfull)
        self.gain = {}
        for j in self.joints:
            inertia = Mfull[self.dof[j], self.dof[j]]  # 드라이브를 부하에 맞춤
            w = 2 * math.pi * self.bw_hz[j]
            self.gain[j] = (inertia * w * w, 2 * 0.9 * inertia * w, inertia * w * w * w / 10.0, inertia)

        self.pp = {j: [0.0, 0.0] for j in self.joints}      # 기준 위치·속도 (관절 deg, deg/s)
        self.integ = {j: 0.0 for j in self.joints}
        self.yaw0 = 0.0

    def _free_dofs(self):
        m = self.m
        bid = self.base_bid
        while bid > 0:
            for k in range(m.body_jntnum[bid]):
                jnt = m.body_jntadr[bid] + k
                if m.jnt_type[jnt] == mujoco.mjtJoint.mjJNT_FREE:
                    start = m.jnt_dofadr[jnt]
                    return slice(start, start + 6)
            bid = m.body_parentid[bid]
        return None

    # -- 드라이브 · 서보 ---------------------------------------------------- #

    def pp_step(self, j, target, dt):
        vmax = self.vmax_motor / self.ratio[j]
        amax = self.amax_motor / self.ratio[j]
        x, v = self.pp[j]
        e = target - x
        vd = math.copysign(min(vmax, math.sqrt(2 * amax * abs(e))), e) if abs(e) > 1e-9 else 0.0
        v += max(-amax * dt, min(amax * dt, vd - v))
        x += v * dt
        self.pp[j] = [x, v]
        return x, v

    def control(self, dt, settle=False):
        d = self.d
        for j in self.joints:
            q = d.qpos[self.qadr[j]]
            qd = d.qvel[self.dof[j]]
            xr, vr = (0.0, 0.0) if settle else (math.radians(self.pp[j][0]), math.radians(self.pp[j][1]))
            kp, kd, ki, _ = self.gain[j]
            e = xr - q
            self.integ[j] += e * dt
            u = kp * e + kd * (vr - qd) + ki * self.integ[j]
            d.ctrl[self.act[j]] = max(-self.tmax[j], min(self.tmax[j], u))

    def base_yaw(self):
        x = self.d.xmat[self.base_bid]
        return math.atan2(x[3], x[0])

    # -- 단계 --------------------------------------------------------------- #

    def settle(self):
        """매달림을 강한 감쇠로 가라앉히고 놓는다 · 고정 베이스면 서보만 0 자세로."""
        m, d, dt = self.m, self.d, self.dt
        if self.free_dofs is not None:
            m.dof_damping[self.free_dofs] = SETTLE_DAMPING
        for _ in range(int(self.settle_s / dt)):
            self.control(dt, settle=True)
            mujoco.mj_step(m, d)
        if self.free_dofs is not None:
            m.dof_damping[self.free_dofs] = FREE_DAMPING
        self.yaw0 = self.base_yaw()

    def run_setpoint(self, sp, nxt, on_substep=None):
        """설정점 하나(20 ms)를 substep 으로 · on_substep(s) 은 mj_step 직후."""
        m, d, dt = self.m, self.d, self.dt
        steps = self.steps_per_sp
        torsion = self.torsion_k > 0 or self.torsion_c > 0
        for s_ in range(steps):
            if self.ref == 'interp':
                a_ = (s_ + 1) / steps
                for j in self.joints:
                    self.pp[j] = [sp[j] + (nxt[j] - sp[j]) * a_, (nxt[j] - sp[j]) / SETPOINT_S]
            else:
                for j in self.joints:
                    self.pp_step(j, sp[j], dt)
            if torsion:
                _yaw = self.base_yaw() - self.yaw0
                d.xfrc_applied[self.base_bid][5] = -self.torsion_k * _yaw - self.torsion_c * d.cvel[self.base_bid][2]
            self.control(dt)
            mujoco.mj_step(m, d)
            if on_substep is not None:
                on_substep(s_)


def load_pack_or_exit(pack_dir):
    try:
        return load_robot(Path(pack_dir))
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)
