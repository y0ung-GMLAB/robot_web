"""애니메이션(motion_web JSON)을 로봇 팩의 MuJoCo 모델로 계산 · 결과 CSV + npz + 요약 출력

사용:
    uv run --no-project --with mujoco --with numpy --with pyyaml python sim_run.py PACK_DIR MOTION.json [OUT.csv]
    uv run --no-project --with mujoco --with numpy --with pyyaml python sim_run.py --check PACK_DIR

OUT 생략 시 <애니메이션 경로에서 .json 뺀 것>.sim.csv · npz 는 csv 옆 같은 이름.
--check  팩 형식 + model.xml 로드 + 축 이름 대조만 · 통과 0 / 실패 1 (이유는 한 줄씩 stdout).
환경변수 · sim_core 참고 + FH_REC_HZ (CSV 기록 Hz · 기본 50).
"""

import csv
import math
import os
import sys
from pathlib import Path

import numpy as np

import sim_core
from sim_core import SETPOINT_S, Sim, env_float, load_motion
from motion_common.robot_pack import load_robot


def check(pack_dir) -> int:
    try:
        robot = load_robot(Path(pack_dir))
    except ValueError as exc:
        lines = str(exc).splitlines()[1:]
        print('\n'.join(line.strip() for line in lines))
        return 1
    errors = sim_core.check_model(robot)
    if errors:
        print('\n'.join(errors))
        return 1
    print('OK %s %s · axes %s' % (robot.name, robot.version, ', '.join(a.joint for a in robot.axes)))
    return 0


def run(pack_dir, motion_path, out_csv=None):
    robot = sim_core.load_pack_or_exit(pack_dir)
    if out_csv is None:
        stem = str(motion_path)
        if stem.lower().endswith('.json'):
            stem = stem[:-len('.json')]
        out_csv = stem + '.sim.csv'
    rec_hz = env_float('FH_REC_HZ', 50)
    sim = Sim(robot)
    m, d, dt = sim.m, sim.d, sim.dt
    joints, base_bid = sim.joints, sim.base_bid
    qadr, act = sim.qadr, sim.act
    tgt, n_sp = load_motion(motion_path, robot)

    sim.settle()
    base0 = d.xpos[base_bid].copy()
    yaw0 = sim.yaw0
    com0 = d.subtree_com[base_bid].copy()
    static_tau = {j: float(d.actuator_force[act[j]]) for j in joints}

    rec = []
    steps_per_sp = sim.steps_per_sp
    rec_every = max(1, int(round(1.0 / rec_hz / dt)))

    def snapshot(t, sp):
        bp_ = d.xpos[base_bid] - base0
        byaw_ = math.degrees(sim.base_yaw() - yaw0)
        cxy_ = d.subtree_com[base_bid][:2] - com0[:2]
        row_ = [t]
        for j in joints:
            row_ += [sp[j], math.degrees(d.qpos[qadr[j]]), float(d.actuator_force[act[j]])]
        return row_ + [bp_[0] * 1000, bp_[1] * 1000, bp_[2] * 1000, byaw_, cxy_[0] * 1000, cxy_[1] * 1000]

    qrec_every = max(1, int(round(0.01 / dt)))
    q_log, t_log, tw_log = [], [], []
    peak = {j: dict(err=0.0, tau=0.0) for j in joints}
    sway = dict(xy=0.0, yaw=0.0, z=0.0, com_xy=0.0)
    for i in range(n_sp + 150):                       # 마지막 설정점 뒤 3 s
        sp = {j: tgt[j][min(i, n_sp - 1)] for j in joints}
        nxt = {j: tgt[j][min(i + 1, n_sp - 1)] for j in joints}

        def on_substep(s_):
            if (s_ + 1) % qrec_every == 0:                       # 재생용 전체 상태 (100 Hz)
                q_log.append(d.qpos.copy())
                t_log.append(i * SETPOINT_S + (s_ + 1) * dt)
                tw_log.append(math.degrees(sim.base_yaw() - yaw0))
            if rec_hz > 50 and (s_ + 1) % rec_every == 0 and s_ != steps_per_sp - 1:
                rec.append(snapshot(i * SETPOINT_S + (s_ + 1) * dt, sp))

        sim.run_setpoint(sp, nxt, on_substep)
        bp = d.xpos[base_bid] - base0
        byaw = math.degrees(sim.base_yaw() - yaw0)
        cxy = d.subtree_com[base_bid][:2] - com0[:2]
        sway['xy'] = max(sway['xy'], float(np.hypot(*bp[:2])))
        sway['yaw'] = max(sway['yaw'], abs(byaw))
        sway['z'] = max(sway['z'], abs(float(bp[2])))
        sway['com_xy'] = max(sway['com_xy'], float(np.hypot(*cxy)))
        row = [i * SETPOINT_S]
        for j in joints:
            q = math.degrees(d.qpos[qadr[j]])
            tau = float(d.actuator_force[act[j]])
            cmd = sp[j]
            peak[j]['err'] = max(peak[j]['err'], abs(cmd - q) if i < n_sp else 0.0)
            peak[j]['tau'] = max(peak[j]['tau'], abs(tau))
            row += [cmd, q, tau]
        row += [bp[0] * 1000, bp[1] * 1000, bp[2] * 1000, byaw, cxy[0] * 1000, cxy[1] * 1000]
        rec.append(row)

    with open(out_csv, 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['t'] + sum([[j + '_cmd_deg', j + '_act_deg', j + '_tau_Nm'] for j in joints], []) +
                   ['base_dx_mm', 'base_dy_mm', 'base_dz_mm', 'base_yaw_deg', 'com_dx_mm', 'com_dy_mm'])
        w.writerows(rec)

    np.savez_compressed(os.path.splitext(out_csv)[0] + '.npz', qpos=np.array(q_log), t=np.array(t_log), twist=np.array(tw_log),
                        n_frames=n_sp, model=os.path.abspath(robot.model_path), motion=os.path.abspath(motion_path), ref=sim.ref)

    # 매달린 몸통의 주 진동수 · 행 간격 20 ms 가정 (FH_REC_HZ > 50 이면 어긋남 · 원본과 같음)
    bx = np.array([r[-6] for r in rec])
    by = np.array([r[-5] for r in rec])
    byw = np.array([r[-3] for r in rec])

    def fdom(s):
        s = s - s.mean()
        F = np.abs(np.fft.rfft(s))
        fr = np.fft.rfftfreq(len(s), SETPOINT_S)
        k = 1 + int(np.argmax(F[1:]))
        return fr[k]

    def pct(j):
        t2n = sim.reducer[j][0]
        return '(%3.0f%% of T2N)' % (100 * peak[j]['tau'] / t2n) if t2n else '(no reducer)'

    def num(v):
        return '%8.1f' % v if v is not None else '%8s' % '-'

    print('PACK', robot.name, robot.version, '| MODEL', os.path.basename(str(robot.model_path)), '| REF', sim.ref,
          '| +Izz %g k %g c %g' % (sim.extra_izz, sim.torsion_k, sim.torsion_c),
          '| MOTION', os.path.basename(str(motion_path)), '| total mass %.1f kg' % sum(m.body_mass))
    print('  load inertia / coupled inertia (kg m^2): ' + ', '.join(
        '%s %.2f/%.2f' % (j, sim.gain[j][3], 1 / sim.Minv[sim.dof[j], sim.dof[j]]) for j in joints))
    print('  static servo torque at rest (gravity): ' + ', '.join('%s %.1f Nm' % (j, static_tau[j]) for j in joints))
    print('  %-11s %10s %10s %10s %10s' % ('axis', 'max err', 'peak tau', 'reducer T2N', 'T2B'))
    for j in joints:
        print('  %-11s %9.3f° %8.1f Nm %s %s   %s' % (j, peak[j]['err'], peak[j]['tau'], num(sim.reducer[j][0]), num(sim.reducer[j][1]), pct(j)))
    print('  suspension: max base sway %.1f mm, head COM sway %.1f mm, base twist %.2f°, bounce %.2f mm | dominant freq sway x %.2f Hz, y %.2f Hz, twist %.3f Hz'
          % (sway['xy'] * 1000, sway['com_xy'] * 1000, sway['yaw'], sway['z'] * 1000, fdom(bx), fdom(by), fdom(byw)))


def main(argv):
    if len(argv) >= 2 and argv[0] == '--check':
        return check(argv[1])
    if len(argv) not in (2, 3):
        print(__doc__)
        return 2
    run(*argv)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
