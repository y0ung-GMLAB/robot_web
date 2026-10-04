#!/usr/bin/env python3
"""웹 3D 순방향 운동학 기준값 · MuJoCo 로 만든다 · 수정 목록 7-a

    uv run --no-project --with mujoco --with numpy --with pyyaml python \\
        src/web_ui/test/fixtures/make_sim3d_fixture.py

작은 모델(자유·힌지·슬라이드·볼 관절 · 상자·캡슐·메쉬 지옴)을 임시 팩으로 만들고
`scripts/sim/export_scene.py` 로 장면 JSON 을 뽑은 뒤, 무작위 qpos 몇 벌에 대해
`mj_kinematics` 가 낸 바디 위치·자세를 함께 적는다 · `sim3d_fk.test.mjs` 가
`static/js/sim3d_math.js` 의 결과와 비교한다 · MuJoCo 가 없는 PC 에서는 이 파일을
다시 만들 필요가 없다 (JSON 이 저장소에 있다).
"""

from __future__ import annotations

import json
import struct
import sys
import tempfile
from pathlib import Path

import mujoco
import numpy as np

ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT / 'scripts' / 'sim'))
from export_scene import export_scene  # noqa: E402

MODEL = """
<mujoco model="fixture">
  <compiler angle="degree" meshdir="meshes"/>
  <option timestep="0.002"/>
  <asset>
    <mesh name="tetra" file="tetra.stl" scale="0.1 0.1 0.1"/>
    <material name="red" rgba="0.8 0.2 0.2 1"/>
  </asset>
  <worldbody>
    <geom type="plane" size="2 2 0.1" rgba="0.5 0.5 0.5 1"/>
    <body name="base" pos="0 0 0.5" quat="0.9659258 0 0 0.2588190">
      <freejoint name="root"/>
      <geom type="box" size="0.1 0.15 0.05" rgba="0.3 0.3 0.9 1"/>
      <body name="neck" pos="0 0 0.1" euler="0 0 15">
        <joint name="neck_yaw" type="hinge" axis="0 0 1" pos="0 0 -0.02"/>
        <geom type="capsule" fromto="0 0 0 0 0 0.2" size="0.03"/>
        <body name="head" pos="0 0 0.25">
          <joint name="head_pitch" type="hinge" axis="0 1 0" pos="0.01 0 0"/>
          <geom type="mesh" mesh="tetra" material="red"/>
          <body name="eye" pos="0.05 0.03 0.02">
            <joint name="eye_ball" type="ball"/>
            <geom type="sphere" size="0.015"/>
          </body>
        </body>
      </body>
      <body name="rail" pos="0.3 0 0">
        <joint name="rail_slide" type="slide" axis="1 0 0" range="-0.2 0.2"/>
        <geom type="cylinder" size="0.02 0.05" quat="0.7071068 0.7071068 0 0"/>
      </body>
    </body>
  </worldbody>
</mujoco>
"""

ROBOT = """
axes:
  - {joint: neck_yaw, motion_id: Neck_Yaw, motor: MSMF011L1, reducer: null, ratio: 1.0, range_deg: [-90, 90], servo_bw_hz: 10}
  - {joint: head_pitch, motion_id: Head_Pitch, motor: MSMF011L1, reducer: null, ratio: 1.0, range_deg: [-45, 45], servo_bw_hz: 10}
drive: {profile_velocity_deg_s: 90, profile_accel_deg_s2: 180}
env:
  settle_body: base
  settle_s: 3.0
  torsion_k: 50.0
  torsion_c: 1.0
  camera: {lookat: [0, 0, 0.7], distance: 1.8, azimuth: 120, elevation: -15}
"""


def write_stl(path: Path) -> None:
    """정사면체 · 이진 STL."""
    v = np.array([[1, 1, 1], [1, -1, -1], [-1, 1, -1], [-1, -1, 1]], dtype=float)
    faces = [(0, 1, 2), (0, 3, 1), (0, 2, 3), (1, 3, 2)]
    with path.open('wb') as f:
        f.write(b'\0' * 80)
        f.write(struct.pack('<I', len(faces)))
        for a, b, c in faces:
            n = np.cross(v[b] - v[a], v[c] - v[a])
            n = n / np.linalg.norm(n)
            f.write(struct.pack('<3f', *n))
            for i in (a, b, c):
                f.write(struct.pack('<3f', *v[i]))
            f.write(struct.pack('<H', 0))


def main() -> int:
    out = Path(__file__).with_name('sim3d_fk.json')
    with tempfile.TemporaryDirectory() as tmp:
        pack = Path(tmp) / 'pack'
        (pack / 'meshes').mkdir(parents=True)
        (pack / 'model.xml').write_text(MODEL, encoding='utf-8')
        (pack / 'robot.yaml').write_text(ROBOT, encoding='utf-8')
        write_stl(pack / 'meshes' / 'tetra.stl')
        scene = export_scene(pack)
        model = mujoco.MjModel.from_xml_path(str(pack / 'model.xml'))
        data = mujoco.MjData(model)
        rng = np.random.default_rng(7)
        cases = []
        for _ in range(6):
            q = np.zeros(model.nq)
            q[0:3] = rng.uniform(-0.3, 0.3, 3)
            quat = rng.normal(size=4)
            q[3:7] = quat / np.linalg.norm(quat)
            for j in range(model.njnt):
                t = int(model.jnt_type[j])
                adr = int(model.jnt_qposadr[j])
                if t == mujoco.mjtJoint.mjJNT_HINGE:
                    q[adr] = rng.uniform(-2.5, 2.5)
                elif t == mujoco.mjtJoint.mjJNT_SLIDE:
                    q[adr] = rng.uniform(-0.2, 0.2)
                elif t == mujoco.mjtJoint.mjJNT_BALL:
                    b = rng.normal(size=4)
                    q[adr:adr + 4] = b / np.linalg.norm(b)
            data.qpos[:] = q
            mujoco.mj_kinematics(model, data)
            cases.append({
                'qpos': [round(float(x), 9) for x in q],
                'xpos': [[round(float(x), 9) for x in data.xpos[b]] for b in range(model.nbody)],
                'xquat': [[round(float(x), 9) for x in data.xquat[b]] for b in range(model.nbody)],
            })
    out.write_text(json.dumps({'scene': scene, 'cases': cases}, ensure_ascii=False, indent=0), encoding='utf-8')
    print(f'{out} · bodies {len(scene["bodies"])} · joints {len(scene["joints"])} · geoms {len(scene["geoms"])} · cases {len(cases)}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
