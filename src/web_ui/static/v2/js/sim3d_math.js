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

/** Blender 뷰 카메라 방향 · 로봇마다 맨 위 노드(리그)의 정면을 평균한 수평 방향(glTF) ·
 * 리그 약속 · Blender 정면 −Y = glTF 리그 +Z · `rigQuats` = 리그 월드 회전 [w, x, y, z] 목록 ·
 * 매장 배치로 로봇마다 돌아 있어 장면 +Z 에서 보면 얼굴을 옆에서 봤다 · 없거나 서로 지워지면 +Z */
export function sceneFrontDir(rigQuats) {
  let x = 0;
  let z = 0;
  for (const q of rigQuats || []) {
    const f = rotVec(q, [0, 0, 1]);
    const n = Math.hypot(f[0], f[2]);
    if (n > 1e-6) { x += f[0] / n; z += f[2] / n; }
  }
  const n = Math.hypot(x, z);
  return n > 1e-6 ? [x / n, 0, z / n] : [0, 0, 1];
}

/** 팩 `scene_glb.joints` 노드 → 그 로봇의 맨 위 노드(glTF 장면 바로 아래) 회전 [w, x, y, z] 목록 ·
 * three 객체의 `parent` · `quaternion` 만 본다 · `find(이름)` 은 노드 찾기 · 로봇 하나에 하나 */
export function rigQuatsFromJoints(root, joints, find) {
  const tops = new Set();
  for (const entry of Object.values(joints || {})) {
    let node = entry?.node ? find(entry.node) : null;
    while (node && node.parent && node.parent !== root) node = node.parent;
    if (node && node.parent === root) tops.add(node);
  }
  const rootQ = root?.quaternion ? [root.quaternion.w, root.quaternion.x, root.quaternion.y, root.quaternion.z] : [1, 0, 0, 0];
  return [...tops].map((top) => quatMul(rootQ, [top.quaternion.w, top.quaternion.x, top.quaternion.y, top.quaternion.z]));
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

/** 실물 위치 겹쳐 보기의 qpos · 수정 목록 7-c (2026-10-06)
 *
 * 팩의 축(`scene.axes` · {joint, motion_id})마다 같은 조인트 이름의 모터에서 실제 조인트
 * 각도(`motion_actual_deg` · 서버가 매핑 식으로 되돌린 값을 화면이 deg 로 바꾼 것)를 받아
 * 그 관절 칸에 넣는다 · 회전 관절만(rad) · 나머지 칸(바닥 자유 관절·비틀림)은 `base`
 * (지금 계획 로봇의 자세)를 빌린다 · 받지 못한 축은 0 이 아니라 `base` 그대로.
 */
export function actualQpos(scene, motors = [], base = null) {
  const joints = new Map((scene?.joints || []).map((joint) => [joint.name, joint]));
  const size = Math.max(0, ...(scene?.joints || []).map((joint) => (
    joint.qposadr + (joint.type === 'free' ? 7 : joint.type === 'ball' ? 4 : 1)
  )));
  const qpos = Array.from({ length: size }, (_, index) => (
    base && Number.isFinite(Number(base[index])) ? Number(base[index]) : 0
  ));
  // 자유·공 관절의 기본 자세는 단위 쿼터니언
  for (const joint of scene?.joints || []) {
    if (base) continue;
    if (joint.type === 'free') qpos[joint.qposadr + 3] = 1;
    if (joint.type === 'ball') qpos[joint.qposadr] = 1;
  }
  const byMotion = new Map();
  for (const motor of motors) {
    if (motor && motor.motion_id) byMotion.set(String(motor.motion_id), motor);
  }
  let matched = 0;
  const missing = [];
  for (const axis of scene?.axes || []) {
    const joint = joints.get(axis.joint);
    const raw = byMotion.get(String(axis.motion_id))?.motion_actual_deg;
    // 값이 없으면(null) 못 받은 것 · Number(null) = 0 으로 0° 에 그리지 않게
    const value = raw === null || raw === undefined || raw === '' ? NaN : Number(raw);
    if (!joint || joint.type !== 'hinge' || !Number.isFinite(value)) {
      missing.push(axis.motion_id || axis.joint);
      continue;
    }
    qpos[joint.qposadr] = (value * Math.PI) / 180;
    matched += 1;
  }
  return { qpos, matched, missing };
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

/** 서버 시계 − 브라우저 시계 (초) · 상태를 받을 때마다 · 수정 목록 92
 *
 * 받은 순간 기준이라 늘 전송 지연만큼 작게 나온다 · 최근 것 중 **가장 큰 값**(가장 덜 늦은 것)을 쓴다 ·
 * `samples` 는 최근 값 목록(바꿔서 돌려준다) · 30개까지.
 */
export function nextClockOffset(samples, serverTimeSec, receivedAtSec, keep = 30) {
  const list = Array.isArray(samples) ? samples.slice(-(keep - 1)) : [];
  const server = Number(serverTimeSec);
  const received = Number(receivedAtSec);
  if (Number.isFinite(server) && Number.isFinite(received) && server > 0) list.push(server - received);
  return { samples: list, offset: list.length ? Math.max(...list) : 0 };
}

/** 실물이 지금 그 회차 몇 초째인가 (서버 시계) · 모르면 null · 수정 목록 92
 *
 * 재생 상태의 `progress.elapsed_sec` 는 런타임이 `updated_at`(서버 시계) 에 적은 값 · 그 뒤 흐른 시간을 더한다 ·
 * 브라우저 시계는 서버와 다를 수 있어 `offsetSec`(서버 − 브라우저)으로 고친다.
 * 구간 재생이면 진행 시각은 구간 시작부터다 · 파일 시각으로 돌려준다(`segment_start_sec` 를 더함 · 2026-10-16).
 */
export function followPlayheadSec(status, browserNowSec, offsetSec = 0) {
  if (String(status?.state || '') !== 'running') return null;
  const elapsed = Number(status?.progress?.elapsed_sec);
  if (!Number.isFinite(elapsed)) return null;
  const updated = Number(status?.updated_at);
  const serverNow = Number(browserNowSec) + (Number(offsetSec) || 0);
  const since = Number.isFinite(updated) && updated > 0 ? Math.max(0, serverNow - updated) : 0;
  // 상태가 5초 넘게 안 오면 더 앞서 나가지 않는다
  return followRestSec(status) + elapsed + Math.min(since, 5);
}

/** 재생하지 않을 때 3D 가 서 있는 파일 시각 · 구간 재생이면 구간 시작(초기 위치 = 그 자세) · 아니면 0 · 2026-10-16 */
export function followRestSec(status) {
  const start = Number(status?.segment_start_sec);
  return Number.isFinite(start) && start > 0 ? start : 0;
}

/** 실물 따라가기에서 한 회차의 끝 · 계산 결과 끝의 정착 3초는 빼고 애니메이션 길이만 */
export function followEndSec(frames = {}) {
  const motion = Number(frames?.motion_sec);
  const total = Number(frames?.duration_sec) || 0;
  return Number.isFinite(motion) && motion > 0 ? Math.min(motion, total || motion) : total;
}


/* ---------- Blender 뷰 · json 값으로 노드 돌리기 · 수정 목록 98 ---------- */

/** 팩이 json 값으로 장면을 움직이나 · 조인트 → 노드(98) 또는 파생 관절 표(159) · 어떤 애니메이션이든 */
export function blenderUsesJoints(info) {
  if (!info?.available) return false;
  const joints = Boolean(info.joints) && Object.keys(info.joints).length > 0;
  return joints || info.derived === true;
}

/** Blender 뷰를 켤 수 있나 · 애니메이션 하나를 골랐고 팩이 json 값 방식이면 · glb 에 구운 클립(옛 60)은 159 에서 지움 */
export function blenderViewAllowed(info, file) {
  if (!info?.available || !file) return false;
  return blenderUsesJoints(info);
}

/** 그 시각의 조인트 값(rad) · 서버가 고른 시각표 · 두 점 사이 선형 · 끝 밖은 끝 값 */
export function sampleJointValues(payload, seconds) {
  const out = {};
  const joints = payload?.joints || {};
  const fps = Number(payload?.fps) || 25;
  const count = Number(payload?.sample_count) || 0;
  if (!count) return out;
  const position = Math.min(Math.max(Number(seconds) || 0, 0) * fps, count - 1);
  const index = Math.floor(position);
  const frac = position - index;
  for (const [name, values] of Object.entries(joints)) {
    const a = Number(values[index]);
    const b = Number(values[Math.min(index + 1, values.length - 1)]);
    if (Number.isFinite(a) && Number.isFinite(b)) out[name] = a + (b - a) * frac;
  }
  return out;
}

/** 축(단위 벡터) · 각도(rad) → 쿼터니언 [x, y, z, w] */
function axisAngleQuaternion(axis, angle) {
  const [x, y, z] = axis;
  const length = Math.hypot(x, y, z) || 1;
  const half = angle / 2;
  const s = Math.sin(half) / length;
  return [x * s, y * s, z * s, Math.cos(half)];
}

/** a × b · 노드 회전 = 기본 자세 × 축 회전 (노드 로컬 축) */
function multiplyQuaternion(a, b) {
  const [ax, ay, az, aw] = a;
  const [bx, by, bz, bw] = b;
  return [
    aw * bx + ax * bw + ay * bz - az * by,
    aw * by - ax * bz + ay * bw + az * bx,
    aw * bz + ax * by - ay * bx + az * bw,
    aw * bw - ax * bx - ay * by - az * bz,
  ];
}

/** 조인트 하나의 노드 회전 · json 에 없는 조인트는 0(기본 자세) */
export function jointNodeRotation(base, axis, values, name) {
  const angle = Number(values?.[name]);
  return multiplyQuaternion(base, axisAngleQuaternion(axis, Number.isFinite(angle) ? angle : 0));
}


/* ---------- Blender 뷰 · 파생 관절 표 · 수정 목록 159 ---------- */
// 형식 `scripts/sim/README.md` 「scene_glb.derived」 · 입력 1~3개(json 조인트 값 · rad) → 노드 로컬 TRS ·
// 정규 격자 · 격자 사이 다중선형 · 회전은 첫 모서리와 부호 맞춘 가중합 → 정규화(nlerp) · 격자 밖은 끝값

const DERIVED_WIDTH = Object.freeze({ trs: 10, r: 4 });

/** base64 → float32 (little-endian) */
export function decodeFloat32Base64(text) {
  const binary = atob(String(text || ''));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  if (bytes.length % 4) throw new Error('float32 길이가 아닙니다');
  const view = new DataView(bytes.buffer);
  const out = new Float32Array(bytes.length / 4);
  for (let i = 0; i < out.length; i += 1) out[i] = view.getFloat32(i * 4, true);
  return out;
}

/** derived.json → 보간에 쓰는 표 · 서버 팩 검사를 통과한 것만 오지만 모양이 틀리면 던진다 */
export function prepareDerived(document) {
  if (!document || document.version !== 1 || !Array.isArray(document.tables)) throw new Error('파생 관절 표 형식(version 1)이 아닙니다');
  return document.tables.map((table, index) => {
    const width = DERIVED_WIDTH[table?.channels];
    const inputs = Array.isArray(table?.inputs) ? table.inputs.map(String) : [];
    const grid = Array.isArray(table?.grid) ? table.grid.map((cell) => ({ min: Number(cell.min), max: Number(cell.max), n: Number(cell.n) })) : [];
    const nodes = Array.isArray(table?.nodes) ? table.nodes.map(String) : [];
    if (!width || !inputs.length || grid.length !== inputs.length || !nodes.length) throw new Error(`파생 관절 표 ${index} · 모양이 틀립니다`);
    const strides = new Array(grid.length);
    let points = 1;
    for (let axis = grid.length - 1; axis >= 0; axis -= 1) {
      strides[axis] = points;
      points *= grid[axis].n;
    }
    const values = decodeFloat32Base64(table.values_b64);
    if (values.length !== points * nodes.length * width) throw new Error(`파생 관절 표 ${index} · 값 개수가 틀립니다`);
    return { inputs, grid, nodes, channels: table.channels, width, strides, values };
  });
}

/** 표 하나 · json 값({조인트: rad}) → 노드마다 {t, q, s} · r 표는 t · s 가 null(glb 기본 그대로) */
export function sampleDerivedTable(table, jointValues) {
  const cells = table.grid.map((cell, axis) => {
    const raw = Number(jointValues?.[table.inputs[axis]]);
    const value = Number.isFinite(raw) ? raw : 0;
    const clamped = Math.min(Math.max(value, cell.min), cell.max);
    const position = (clamped - cell.min) / (cell.max - cell.min) * (cell.n - 1);
    const index = Math.min(Math.floor(position), cell.n - 2);
    return { index, frac: position - index };
  });
  const corners = [];
  for (let mask = 0; mask < (1 << cells.length); mask += 1) {
    let weight = 1;
    let point = 0;
    cells.forEach((cell, axis) => {
      const upper = (mask >> axis) & 1;
      weight *= upper ? cell.frac : 1 - cell.frac;
      point += (cell.index + upper) * table.strides[axis];
    });
    corners.push({ weight, base: point * table.nodes.length * table.width });
  }
  const trs = table.channels === 'trs';
  const qOffset = trs ? 3 : 0;
  return table.nodes.map((_name, node) => {
    const at = (corner, channel) => table.values[corner.base + node * table.width + channel];
    const ref = corners[0];
    const q = [0, 0, 0, 0];
    const t = trs ? [0, 0, 0] : null;
    const s = trs ? [0, 0, 0] : null;
    for (const corner of corners) {
      if (!corner.weight) continue;
      const dot = [0, 1, 2, 3].reduce((sum, k) => sum + at(corner, qOffset + k) * at(ref, qOffset + k), 0);
      const sign = dot < 0 ? -1 : 1;
      for (let k = 0; k < 4; k += 1) q[k] += corner.weight * sign * at(corner, qOffset + k);
      if (trs) {
        for (let k = 0; k < 3; k += 1) {
          t[k] += corner.weight * at(corner, k);
          s[k] += corner.weight * at(corner, 7 + k);
        }
      }
    }
    const length = Math.hypot(q[0], q[1], q[2], q[3]) || 1;
    return { t, q: q.map((value) => value / length), s };
  });
}
