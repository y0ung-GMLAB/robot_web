/** 조인트 매핑 식 · 화면 쪽 원본 하나 · 수정 목록 6 (2026-10-06)
 *
 *     모터 = 기준점 + (조인트 + offset) × scale × 방향 × 감속·기어비
 *
 * 서버 원본은 `motion_common/joint_mapping.py` · 같은 규칙이다 ·
 * 매핑 줄의 각도 칸은 `<이름>_rad` 가 있으면 그것, 없으면 `<이름>_deg` ·
 * 돌려주는 단위는 부르는 쪽이 정한다 (`unit`) · reference_position 만 모터 쪽 값.
 */

import { degToRad, radToDeg } from './format.js';

const ANGLE_DEFAULTS_DEG = {
  offset: 0,
  reference_position: 0,
  motion_lower: -180,
  motion_upper: 180,
  initial_motion_position: 0,
};

function finite(value) {
  // null·빈 칸은 「없음」 · Number(null) = 0 으로 새지 않게
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function inUnit(value, source, unit) {
  if (source === unit) return value;
  return unit === 'rad' ? degToRad(value) : radToDeg(value);
}

export function mappingAngle(row, name, unit = 'deg') {
  const rad = finite(row?.[`${name}_rad`]);
  if (rad !== null) return inUnit(rad, 'rad', unit);
  const deg = finite(row?.[`${name}_deg`]);
  if (deg !== null) return inUnit(deg, 'deg', unit);
  const fallback = ANGLE_DEFAULTS_DEG[name];
  return fallback === undefined ? null : inUnit(fallback, 'deg', unit);
}

/** 조인트 1 → 모터 몇 · 0 은 0 그대로(화면이 「환산할 수 없음」 을 알린다) */
export function mappingGain(row) {
  const scale = finite(row?.scale);
  const gear = finite(row?.gear_ratio);
  return (scale === null ? 1 : scale) * (gear === null ? 1 : gear) * (row?.invert ? -1 : 1);
}

export function mappingReference(row, unit = 'deg') {
  return row?.reference_enabled === false ? 0 : mappingAngle(row, 'reference_position', unit);
}

export function jointToMotor(row, joint, unit = 'deg') {
  return mappingReference(row, unit) + (Number(joint) + mappingAngle(row, 'offset', unit)) * mappingGain(row);
}

export function motorToJoint(row, motor, unit = 'deg') {
  const factor = mappingGain(row);
  if (!factor) return null;
  return (Number(motor) - mappingReference(row, unit)) / factor - mappingAngle(row, 'offset', unit);
}
