/** 서버 값(rad) ↔ 화면 값(deg) · 경계 한 곳 · 수정 목록 6 (2026-10-06)
 *
 * 서버는 조인트 매핑 · 재생 계획 · 조인트 값을 rad 로 주고받는다 · 화면은 deg 로만
 * 보여 주고 입력받는다. 받는 순간 deg 모양으로 바꾸고(`inDegView`), 보내는 순간
 * rad 모양으로 바꾼다(`inRadPayload`) · 그래서 화면 코드는 예전처럼 `*_deg` 칸만 본다.
 *
 * 이름 규칙 · `<이름>_rad` ↔ `<이름>_deg` · `_rad_s` ↔ `_deg_s` · `_rad_s2` ↔ `_deg_s2`.
 * 화면 값은 소수 9자리로 반올림한다 · rad → deg 에서 생기는 13.000000000000002 같은
 * 끝자리가 입력칸에 보이지 않게 · 그대로 다시 보내면 원래 rad 값과 같다.
 */

import { degToRad, radToDeg } from './format.js';

const SUFFIXES = [
  ['_rad_s2', '_deg_s2'],
  ['_rad_s', '_deg_s'],
  ['_rad', '_deg'],
];

function roundView(value) {
  return Math.round(value * 1e9) / 1e9;
}

function valueInDeg(item) {
  if (item === null || item === undefined || item === '') return item;
  const deg = radToDeg(item);
  return deg === null ? item : roundView(deg);
}

function renamed(key, from, to) {
  for (const pair of SUFFIXES) {
    const source = pair[from];
    if (key.endsWith(source)) return key.slice(0, -source.length) + pair[to];
  }
  return null;
}

function convertTree(value, from, to, convertNumber) {
  if (Array.isArray(value)) return value.map((item) => convertTree(item, from, to, convertNumber));
  if (!value || typeof value !== 'object') return value;
  const out = {};
  for (const [key, item] of Object.entries(value)) {
    const target = renamed(key, from, to);
    if (target === null) {
      out[key] = convertTree(item, from, to, convertNumber);
      continue;
    }
    // 같은 이름의 화면 칸이 이미 있으면(서버가 deg 사본을 함께 준 경우) 바꾼 값이 이긴다
    out[target] = item === null || item === undefined || item === '' ? item : convertNumber(item);
  }
  return out;
}

/** 서버 응답 → 화면 모양 · `*_rad` 칸을 `*_deg` 로 · 다른 칸은 그대로 */
export function inDegView(value) {
  return convertTree(value, 0, 1, valueInDeg);
}

/** 화면 값 → 서버 요청 · `*_deg` 칸을 `*_rad` 로 */
export function inRadPayload(value) {
  return convertTree(value, 1, 0, (item) => {
    const rad = degToRad(item);
    return rad === null ? item : rad;
  });
}

function clampInDeg(overrides) {
  if (!overrides || typeof overrides !== 'object') return overrides;
  const out = {};
  for (const [motionId, entry] of Object.entries(overrides)) {
    const clamp = Array.isArray(entry?.clamp) ? entry.clamp.map(valueInDeg) : entry?.clamp;
    out[motionId] = entry && typeof entry === 'object' ? { ...entry, ...(entry.clamp ? { clamp } : {}) } : entry;
  }
  return out;
}

/** 재생 상태 · 축 칸과 라이브 리밋(`live_overrides[].clamp` · 이름에 단위 없음) */
export function motionRunStatusInDeg(status) {
  if (!status || typeof status !== 'object') return status;
  const view = inDegView(status);
  if (status.live_overrides) view.live_overrides = clampInDeg(status.live_overrides);
  return view;
}

/** 재생 응답(`status`·`result` 안의 재생 상태) */
export function motionRunResponseInDeg(payload) {
  if (!payload || typeof payload !== 'object') return payload;
  const view = inDegView(payload);
  if (payload.status) view.status = motionRunStatusInDeg(payload.status);
  if (payload.live_overrides) view.live_overrides = clampInDeg(payload.live_overrides);
  return view;
}

/** 라이브 리밋 요청 · 화면 deg → rad */
export function liveOverridePayloadInRad(payload) {
  if (!payload || !Array.isArray(payload.clamp)) return payload;
  return { ...payload, clamp: payload.clamp.map((item) => degToRad(item)) };
}

const analysisCache = new WeakMap();

/** 애니메이션 분석 · 값 칸(첫·끝·최소·최대·그래프·미리보기)은 `value_unit` 단위 */
export function analysisInDeg(analysis) {
  if (!analysis || typeof analysis !== 'object' || analysis.value_unit !== 'rad') return analysis || {};
  const cached = analysisCache.get(analysis);
  if (cached) return cached;
  const view = { ...analysis, value_unit: 'deg' };
  if (Array.isArray(analysis.motion_ids)) {
    view.motion_ids = analysis.motion_ids.map((item) => ({
      ...item,
      first_value: valueInDeg(item.first_value),
      last_value: valueInDeg(item.last_value),
      min_value: valueInDeg(item.min_value),
      max_value: valueInDeg(item.max_value),
    }));
  }
  if (Array.isArray(analysis.preview_records)) {
    view.preview_records = analysis.preview_records.map((item) => ({ ...item, value: valueInDeg(item.value) }));
  }
  if (Array.isArray(analysis.graph_series)) {
    view.graph_series = analysis.graph_series.map((series) => ({
      ...series,
      points: Array.isArray(series.points)
        ? series.points.map((point) => ({ ...point, value: valueInDeg(point.value) }))
        : series.points,
    }));
  }
  analysisCache.set(analysis, view);
  return view;
}
