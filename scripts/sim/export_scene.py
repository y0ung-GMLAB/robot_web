#!/usr/bin/env python3
"""로봇 팩 → 웹 3D 장면 JSON · 수정 목록 7-a (2026-10-04)

브라우저(three.js)가 그릴 수 있게 MuJoCo 가 **이미 읽어 둔** 모델을 그대로
내보낸다 · MJCF 를 따로 해석하지 않는다 (default · include · fromto · material
전부 MuJoCo 몫) · 메쉬도 STL/OBJ 파일이 아니라 MuJoCo 가 올린 꼭짓점·면을 쓴다.

    uv run --no-project --with mujoco --with numpy --with pyyaml python \\
        scripts/sim/export_scene.py PACK_DIR OUT.json

출력 (JSON · 좌표는 MuJoCo 그대로 · 미터 · 쿼터니언 (w, x, y, z)):

    version      1
    nq           qpos 길이
    bodies[]     {id, name, parent, pos[3], quat[4]}         · id 순 = 부모가 먼저
    joints[]     {id, name, body, type, qposadr, axis[3], pos[3]} · type free|ball|slide|hinge
    geoms[]      {body, type, size[3], pos[3], quat[4], rgba[4], mesh, group}
    meshes{}     이름 → {vertices[3n], faces[3m]}
    axes[]       robot.yaml axes 순서 · {joint, motion_id}
    camera       robot.yaml env.camera · {lookat, distance, azimuth, elevation}

브라우저는 bodies 를 트리로 세우고 프레임마다 qpos 로 관절 변환을 적용한다
(순방향 운동학 · `static/js/sim3d_math.js`) · 그 수식이 MuJoCo 와 같은지는
`src/web_ui/test/sim3d_fk.test.mjs` 가 MuJoCo 로 만든 기준값으로 확인한다.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import mujoco
import yaml

GEOM_TYPES = {
    mujoco.mjtGeom.mjGEOM_PLANE: 'plane',
    mujoco.mjtGeom.mjGEOM_HFIELD: 'hfield',
    mujoco.mjtGeom.mjGEOM_SPHERE: 'sphere',
    mujoco.mjtGeom.mjGEOM_CAPSULE: 'capsule',
    mujoco.mjtGeom.mjGEOM_ELLIPSOID: 'ellipsoid',
    mujoco.mjtGeom.mjGEOM_CYLINDER: 'cylinder',
    mujoco.mjtGeom.mjGEOM_BOX: 'box',
    mujoco.mjtGeom.mjGEOM_MESH: 'mesh',
}
JOINT_TYPES = {
    mujoco.mjtJoint.mjJNT_FREE: 'free',
    mujoco.mjtJoint.mjJNT_BALL: 'ball',
    mujoco.mjtJoint.mjJNT_SLIDE: 'slide',
    mujoco.mjtJoint.mjJNT_HINGE: 'hinge',
}


def _round(values, digits=6):
    return [round(float(v), digits) for v in values]


def export_scene(pack_dir: Path) -> dict:
    pack_dir = Path(pack_dir)
    model = mujoco.MjModel.from_xml_path(str(pack_dir / 'model.xml'))
    robot = yaml.safe_load((pack_dir / 'robot.yaml').read_text(encoding='utf-8')) or {}

    bodies = []
    for b in range(model.nbody):
        bodies.append({
            'id': b,
            'name': model.body(b).name,
            'parent': int(model.body_parentid[b]) if b > 0 else -1,
            'pos': _round(model.body_pos[b]),
            'quat': _round(model.body_quat[b]),
        })

    joints = []
    for j in range(model.njnt):
        joints.append({
            'id': j,
            'name': model.joint(j).name,
            'body': int(model.jnt_bodyid[j]),
            'type': JOINT_TYPES[mujoco.mjtJoint(int(model.jnt_type[j]))],
            'qposadr': int(model.jnt_qposadr[j]),
            'axis': _round(model.jnt_axis[j]),
            'pos': _round(model.jnt_pos[j]),
        })

    used_meshes = set()
    geoms = []
    for g in range(model.ngeom):
        gtype = GEOM_TYPES.get(mujoco.mjtGeom(int(model.geom_type[g])), 'other')
        if gtype in ('hfield', 'other'):
            continue
        mat = int(model.geom_matid[g])
        rgba = model.mat_rgba[mat] if mat >= 0 else model.geom_rgba[g]
        mesh_name = ''
        if gtype == 'mesh':
            mesh_name = model.mesh(int(model.geom_dataid[g])).name
            used_meshes.add(int(model.geom_dataid[g]))
        geoms.append({
            'body': int(model.geom_bodyid[g]),
            'type': gtype,
            'size': _round(model.geom_size[g]),
            'pos': _round(model.geom_pos[g]),
            'quat': _round(model.geom_quat[g]),
            'rgba': _round(rgba, 4),
            'mesh': mesh_name,
            'group': int(model.geom_group[g]),
        })

    meshes = {}
    for m in sorted(used_meshes):
        vstart, vcount = int(model.mesh_vertadr[m]), int(model.mesh_vertnum[m])
        fstart, fcount = int(model.mesh_faceadr[m]), int(model.mesh_facenum[m])
        meshes[model.mesh(m).name] = {
            'vertices': _round(model.mesh_vert[vstart:vstart + vcount].reshape(-1), 5),
            'faces': [int(v) for v in model.mesh_face[fstart:fstart + fcount].reshape(-1)],
        }

    env = robot.get('env') if isinstance(robot.get('env'), dict) else {}
    camera = env.get('camera') if isinstance(env.get('camera'), dict) else {}
    axes = [
        {'joint': str(a.get('joint') or ''), 'motion_id': str(a.get('motion_id') or '')}
        for a in (robot.get('axes') or []) if isinstance(a, dict)
    ]
    return {
        'version': 1,
        'nq': int(model.nq),
        'bodies': bodies,
        'joints': joints,
        'geoms': geoms,
        'meshes': meshes,
        'axes': axes,
        'camera': {
            'lookat': _round(camera.get('lookat') or [0.0, 0.0, 0.0]),
            'distance': float(camera.get('distance') or 2.0),
            'azimuth': float(camera.get('azimuth') or 90.0),
            'elevation': float(camera.get('elevation') or -20.0),
        },
    }


def main(argv) -> int:
    if len(argv) != 3:
        print('usage: export_scene.py PACK_DIR OUT.json', file=sys.stderr)
        return 2
    scene = export_scene(Path(argv[1]))
    out = Path(argv[2])
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + '.tmp')
    tmp.write_text(json.dumps(scene, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    tmp.replace(out)
    print(f'scene: {out} · bodies {len(scene["bodies"])} · geoms {len(scene["geoms"])} · meshes {len(scene["meshes"])}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
