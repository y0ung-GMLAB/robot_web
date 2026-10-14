/** UI v2 · 저장 충돌 때 「새로 받아서 내가 고친 칸만 얹기」 (사용자 결정 2026-10-12)
 *
 * 화면을 연 뒤 다른 곳(다른 브라우저 · 이전 UI · 매핑 저장이 고친 운전 한계 등)이 파일을 바꿨으면
 * 서버가 저장을 거절한다 · 그때 최신 파일을 받아, 이 화면에서 **바꾼 칸만** 최신 위에 다시 얹는다.
 * 다른 곳도 같은 칸을 다르게 바꿨을 때만 충돌로 알린다(값은 내 것으로 · 저장 전에 사람이 확인).
 *
 *   base   · 이 화면이 처음 받은 것(고치기 전)
 *   draft  · 이 화면에서 고친 것
 *   latest · 지금 파일
 */

function strip(record) {
  const { _key, ...rest } = record || {};
  return rest;
}

function isPlain(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function same(a, b) {
  if (a === b) return true;
  if ((a === undefined || a === null || a === '') && (b === undefined || b === null || b === '')) return true;
  if (typeof a === 'number' || typeof b === 'number') {
    const na = Number(a);
    const nb = Number(b);
    if (a !== '' && b !== '' && Number.isFinite(na) && Number.isFinite(nb)) return na === nb;
  }
  return JSON.stringify(a) === JSON.stringify(b);
}

/** 한 레코드 · 칸마다 3방향 · 객체 칸은 한 단계 더 내려가 본다 */
function mergeObject(base, draft, latest, path, conflicts) {
  const out = { ...latest };
  const keys = new Set([...Object.keys(base || {}), ...Object.keys(draft || {})]);
  for (const key of keys) {
    if (key === '_key') continue;
    const b = base?.[key];
    const d = draft?.[key];
    const l = latest?.[key];
    if (same(b, d)) continue;
    if (isPlain(b) && isPlain(d) && isPlain(l)) {
      out[key] = mergeObject(b, d, l, [...path, key], conflicts);
      continue;
    }
    if (!same(l, b) && !same(l, d)) conflicts.push({ path: [...path, key], mine: d, theirs: l });
    if (d === undefined) delete out[key];
    else out[key] = d;
  }
  return out;
}

/**
 * 레코드 목록 3방향 합치기 · keyOf 로 같은 레코드를 짝짓는다
 * 돌려줌 · { records(최신 순서 + 새로 넣은 것), conflicts: [{ key, path, mine, theirs }] }
 */
export function threeWayMerge(base, draft, latest, keyOf) {
  const B = new Map((base || []).map((r) => [keyOf(r), r]));
  const D = new Map((draft || []).map((r) => [keyOf(r), r]));
  const result = new Map((latest || []).map((r) => [keyOf(r), r]));
  const conflicts = [];
  for (const [key, b] of B) {
    if (D.has(key)) continue;
    const l = result.get(key);
    if (!l) continue;
    // 내가 지웠는데 다른 곳이 고쳤다
    if (same(strip(l), strip(b))) result.delete(key);
    else conflicts.push({ key, path: ['(삭제)'], mine: '삭제', theirs: '다른 곳에서 고침' });
  }
  for (const [key, d] of D) {
    const b = B.get(key);
    const l = result.get(key);
    if (!b) {
      if (l && !same(strip(l), strip(d))) conflicts.push({ key, path: ['(추가)'], mine: '추가', theirs: '다른 곳에서도 추가' });
      result.set(key, d);
      continue;
    }
    const sub = [];
    if (!l) {
      if (!same(strip(b), strip(d))) {
        conflicts.push({ key, path: ['(다른 곳에서 삭제)'], mine: '고침', theirs: '삭제' });
        result.set(key, d);
      }
      continue;
    }
    const merged = mergeObject(b, d, l, [], sub);
    if ('_key' in d) merged._key = d._key;
    result.set(key, merged);
    for (const c of sub) conflicts.push({ key, ...c });
  }
  return { records: [...result.values()], conflicts };
}
