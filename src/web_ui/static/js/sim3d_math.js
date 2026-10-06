/** 웹 3D 표시 · 순방향 운동학 · MuJoCo 와 같은 수식 · 수정 목록 7-a (2026-10-04)
 *
 * 장면 JSON(`scripts/sim/export_scene.py`)의 바디·관절과 프레임의 qpos 로 바디마다
 * 자세를 낸다 · three.js 없이 순수 수학만 · `sim3d_fk.test.mjs` 가 MuJoCo
 * `mj_kinematics` 결과(고정 기준값)와 비교한다.
 *
 * 쿼터니언은 MuJoCo 순서 (w, x, y, z) · three.js 로 넘길 때만 (x, y, z, w) 로 바꾼다.
 *
 * MuJoCo 규칙 (engine_core_smooth.c · mj_kinematics)
 *   바디 시작   pos = parent.pos + rot(parent.quat, body.pos) · quat = parent.quat ⊗ body.quat
 *   free        pos = qpos[0:3] · quat = qpos[3:7]  (월드 기준 · body.pos/quat 무시)
 *   hinge/ball  anchor = pos + rot(quat, jnt.pos) · quat = quat ⊗ qloc · pos = anchor − rot(quat, jnt.pos)
 *   slide       pos += rot(quat, jnt.axis) × q
 * 같은 바디의 관절은 선언 순서대로 겹쳐 적용한다.
 */

export function quatMul(a, b) {
  const [aw, ax, ay, az] = a;
  const [bw, bx, by, bz] = b;
  return [
    aw * bw - ax * bx - ay * by - az * bz,
    aw * bx + ax * bw + ay * bz - az * by,
    aw * by - ax * bz + ay * bw + az * bx,
    aw * bz + ax * by - ay * bx + az * bw,
  ];
}

function quatNormalize(q) {
  const n = Math.hypot(q[0], q[1], q[2], q[3]) || 1;
  return [q[0] / n, q[1] / n, q[2] / n, q[3] / n];
}

export function rotVec(q, v) {
  // v' = q v q*  · 전개식
  const [w, x, y, z] = q;
  const [vx, vy, vz] = v;
  const tx = 2 * (y * vz - z * vy);
  const ty = 2 * (z * vx - x * vz);
  const tz = 2 * (x * vy - y * vx);
  return [
    vx + w * tx + (y * tz - z * ty),
    vy + w * ty + (z * tx - x * tz),
    vz + w * tz + (x * ty - y * tx),
  ];
}

export function axisAngleQuat(axis, angle) {
  const n = Math.hypot(axis[0], axis[1], axis[2]) || 1;
  const s = Math.sin(angle / 2);
  return [Math.cos(angle / 2), (axis[0] / n) * s, (axis[1] / n) * s, (axis[2] / n) * s];
}

const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const scale = (a, k) => [a[0] * k, a[1] * k, a[2] * k];

/** 바디별 관절 목록 · 선언 순서 · {bodyId: joint[]} */
export function jointsByBody(scene) {
  const map = new Map();
  for (const joint of scene.joints || []) {
    if (!map.has(joint.body)) map.set(joint.body, []);
    map.get(joint.body).push(joint);
  }
  return map;
}

/** 한 바디의 **부모 기준** 자세 · {pos, quat} · qpos 가 없으면 기본 자세 */
export function bodyLocalPose(body, joints, qpos) {
  let pos = [...body.pos];
  let quat = [...body.quat];
  for (const joint of joints || []) {
    const a = joint.qposadr;
    if (joint.type === 'free') {
      if (qpos && qpos.length >= a + 7) {
        pos = [qpos[a], qpos[a + 1], qpos[a + 2]];
        quat = quatNormalize([qpos[a + 3], qpos[a + 4], qpos[a + 5], qpos[a + 6]]);
      }
      continue;
    }
    if (joint.type === 'slide') {
      const q = qpos && qpos.length > a ? qpos[a] : 0;
      pos = add(pos, scale(rotVec(quat, joint.axis), q));
      continue;
    }
    let qloc;
    if (joint.type === 'ball') {
      qloc = qpos && qpos.length >= a + 4
        ? quatNormalize([qpos[a], qpos[a + 1], qpos[a + 2], qpos[a + 3]])
        : [1, 0, 0, 0];
    } else {
      const q = qpos && qpos.length > a ? qpos[a] : 0;
      qloc = axisAngleQuat(joint.axis, q);
    }
    const anchor = add(pos, rotVec(quat, joint.pos));
    quat = quatNormalize(quatMul(quat, qloc));
    pos = sub(anchor, rotVec(quat, joint.pos));
  }
  return { pos, quat };
}

/** 모든 바디의 **월드** 자세 · 배열(id 순) · 시험용 · 렌더러는 local 만 쓴다 */
export function forwardKinematics(scene, qpos) {
  const byBody = jointsByBody(scene);
  const world = [];
  for (const body of scene.bodies) {
    if (body.parent < 0) {
      world.push({ pos: [0, 0, 0], quat: [1, 0, 0, 0] });
      continue;
    }
    const parent = world[body.parent];
    const local = bodyLocalPose(body, byBody.get(body.id), qpos);
    world.push({
      pos: add(parent.pos, rotVec(parent.quat, local.pos)),
      quat: quatNormalize(quatMul(parent.quat, local.quat)),
    });
  }
  return world;
}

/** MuJoCo 카메라(lookat · distance · azimuth · elevation) → 카메라 위치 */
export function cameraPosition(camera) {
  const az = ((camera?.azimuth ?? 90) * Math.PI) / 180;
  const el = ((camera?.elevation ?? -20) * Math.PI) / 180;
  const d = camera?.distance ?? 2;
  const lookat = camera?.lookat ?? [0, 0, 0];
  const forward = [Math.cos(el) * Math.cos(az), Math.cos(el) * Math.sin(az), Math.sin(el)];
  return sub(lookat, scale(forward, d));
}

/** 시각 → 프레임 번호 · t 는 오름차순 · 범위 밖은 양 끝 */
export function frameIndexAt(times, seconds) {
  if (!times || !times.length) return 0;
  if (seconds <= times[0]) return 0;
  if (seconds >= times[times.length - 1]) return times.length - 1;
  let lo = 0;
  let hi = times.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (times[mid] <= seconds) lo = mid; else hi = mid;
  }
  return seconds - times[lo] < times[hi] - seconds ? lo : hi;
}

/** 실물 따라가기 · 「새 회차가 시작됐나」 를 가리는 열쇠 · 수정 목록 8 (2026-10-06)
 *
 * 전에는 상태가 running 으로 **바뀔 때만** 처음부터 다시 그렸다 · 「바로 다음
 * 회차」 반복은 상태가 running 그대로라 두 번째 회차부터 3D 가 멈춰 있었다 ·
 * 회차 번호·재생 파일(재생 목록)이 바뀌어도 새로 시작한다.
 */
export function followRunKey(status = {}) {
  const state = String(status?.state || '');
  if (state !== 'running') return state;
  return `running|${Number(status?.current_cycle) || 0}|${String(status?.motion_file_id || '')}`;
}

/** 실물 따라가기에서 한 회차의 끝 · 계산 결과 끝의 정착 3초는 빼고 애니메이션 길이만 */
export function followEndSec(frames = {}) {
  const motion = Number(frames?.motion_sec);
  const total = Number(frames?.duration_sec) || 0;
  return Number.isFinite(motion) && motion > 0 ? Math.min(motion, total || motion) : total;
}
