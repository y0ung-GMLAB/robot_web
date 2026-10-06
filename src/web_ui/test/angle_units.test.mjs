// 각도 단위 변환 · 화면 deg ↔ 서버 rad · 수정 목록 6
import assert from 'node:assert/strict';
import test from 'node:test';

import { degToRad, radToDeg } from '../static/js/format.js';

test('degrees and radians convert both ways', () => {
  assert.equal(radToDeg(Math.PI), 180);
  assert.equal(degToRad(180), Math.PI);
  assert.ok(Math.abs(radToDeg(degToRad(12.345)) - 12.345) < 1e-12);
  assert.equal(radToDeg(null), 0);   // Number(null) = 0
  assert.equal(radToDeg('x'), null);
  assert.equal(degToRad(undefined), null);
});

// 조인트 매핑 식 · 화면 원본 하나 · 수정 목록 6
import { jointToMotor, mappingAngle, motorToJoint } from '../static/js/joint_mapping.js';

test('one mapping formula in the browser · same as the server formula', () => {
  const row = {
    reference_position_deg: 1234.5, offset_deg: 2, scale: 1, gear_ratio: 150, invert: true,
    motion_lower_deg: -10, motion_upper_deg: 13,
  };
  // 모터 = 1234.5 + (10 + 2) × 1 × (−1) × 150 = −565.5
  assert.equal(jointToMotor(row, 10), -565.5);
  assert.equal(motorToJoint(row, -565.5), 10);
  // rad 로 물어도 같은 자세
  const inRad = jointToMotor(row, (10 * Math.PI) / 180, 'rad');
  assert.ok(Math.abs((inRad * 180) / Math.PI - -565.5) < 1e-9);
  // _rad 칸이 있으면 그것이 먼저 · 없으면 기본값(±180°)
  assert.equal(mappingAngle({ offset_rad: 0.5, offset_deg: 99 }, 'offset', 'rad'), 0.5);
  assert.equal(mappingAngle({}, 'motion_upper', 'deg'), 180);
  assert.equal(motorToJoint({ gear_ratio: 0 }, 1), null);
});

// 서버 rad ↔ 화면 deg 경계 · `unit_view.js` · 수정 목록 6
import {
  analysisInDeg,
  inDegView,
  inRadPayload,
  liveOverridePayloadInRad,
  motionRunStatusInDeg,
} from '../static/js/unit_view.js';

const PY_RAD = (deg) => deg * (Math.PI / 180);   // Python math.radians 와 같은 곱셈

test('mapping rows from the server become deg rows and go back as the same rad values', () => {
  const server = {
    mapping: {
      name: 'm',
      angle_unit: 'rad',
      mappings: [{
        motion_id: 'Neck_Pitch', gear_ratio: 150, invert: false,
        reference_position_rad: PY_RAD(1234.5), motion_lower_rad: PY_RAD(-10), motion_upper_rad: PY_RAD(13),
        offset_rad: 0, initial_motion_position_rad: null, max_velocity_rad_s: PY_RAD(80),
      }],
    },
    validation: { rows: { Neck_Pitch: { motion_motor_target_min_rad: PY_RAD(-100) } } },
  };
  const view = inDegView(server);
  const row = view.mapping.mappings[0];
  assert.equal(row.motion_upper_deg, 13);          // 끝자리 반올림 · 13.000000000000002 아님
  assert.equal(row.reference_position_deg, 1234.5);
  assert.equal(row.max_velocity_deg_s, 80);
  assert.equal(row.initial_motion_position_deg, null);
  assert.equal(row.gear_ratio, 150);
  assert.equal('motion_upper_rad' in row, false);
  assert.equal(view.validation.rows.Neck_Pitch.motion_motor_target_min_deg, -100);

  // 손대지 않고 다시 보내면 서버가 준 rad 값 그대로
  const back = inRadPayload({ mapping: view.mapping }).mapping.mappings[0];
  assert.equal(back.motion_upper_rad, server.mapping.mappings[0].motion_upper_rad);
  assert.equal(back.reference_position_rad, server.mapping.mappings[0].reference_position_rad);
  assert.equal(back.max_velocity_rad_s, server.mapping.mappings[0].max_velocity_rad_s);
  assert.equal('motion_upper_deg' in back, false);
});

test('run status axes and live limits are shown in deg and sent in rad', () => {
  const status = motionRunStatusInDeg({
    state: 'running',
    axes: [{ motion_id: 'j', initial_motor_target_rad: PY_RAD(100), loop_tolerance_rad: PY_RAD(5) }],
    live_overrides: { j: { muted: false, clamp: [PY_RAD(-5), PY_RAD(5)] } },
  });
  assert.equal(status.axes[0].initial_motor_target_deg, 100);
  assert.equal(status.axes[0].loop_tolerance_deg, 5);
  assert.deepEqual(status.live_overrides.j.clamp, [-5, 5]);
  assert.deepEqual(liveOverridePayloadInRad({ motion_id: 'j', clamp: [-5, 5] }).clamp, [PY_RAD(-5), PY_RAD(5)]);
  assert.equal(liveOverridePayloadInRad({ motion_id: 'j', clamp: null }).clamp, null);
});

test('animation analysis values are shown in deg only when the server says rad', () => {
  const analysis = {
    value_unit: 'rad',
    motion_ids: [{ motion_id: 'j', first_value: PY_RAD(10), last_value: 0, min_value: PY_RAD(-30), max_value: PY_RAD(90) }],
    graph_series: [{ motion_id: 'j', points: [{ time_sec: 0, value: PY_RAD(10) }] }],
    preview_records: [{ motion_id: 'j', value: PY_RAD(20) }],
  };
  const view = analysisInDeg(analysis);
  assert.equal(view.motion_ids[0].first_value, 10);
  assert.equal(view.motion_ids[0].max_value, 90);
  assert.equal(view.graph_series[0].points[0].value, 10);
  assert.equal(view.preview_records[0].value, 20);
  assert.equal(analysisInDeg(analysis), view);   // 같은 객체는 한 번만 바꾼다
  const legacy = { value_unit: undefined, motion_ids: [{ first_value: 10 }] };
  assert.equal(analysisInDeg(legacy), legacy);
  assert.deepEqual(analysisInDeg(undefined), {});
});
