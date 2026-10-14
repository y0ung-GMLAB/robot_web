/** UI v2 · 매장 PC 화면 값 · PC 줄 · 주소 · 업데이트 표 · 필수 명단 후보 (설계안 2026-10-09) */
import assert from 'node:assert/strict';
import test from 'node:test';
import { pcLinks, rosterCandidates, storeRows, updateRows, versionSummary } from '../static/v2/js/store_model.js';

const snap = { coordination: { runtime: {
  local: { pc_id: 'f1', motion_step: '재생 중' },
  peers: [{ pc_id: 'f2', motion_step: '그룹 대기', servo_alarm_grade: 2 }],
  network_pcs: [
    { pc_id: 'f1', is_local: true, is_master: true, joined: true, address: '10.0.0.1', git_hash: 'a9a69dd123', web_url: 'http://10.0.0.1:8000' },
    { pc_id: 'f2', joined: true, web_url: 'http://10.0.0.2:8000', same_group: true },
    { pc_id: 'f3', joined: false, version_differs: true, same_group: true },
    { pc_id: 'f4', online: false },
    { pc_id: 'sp', role: 'speaker', web_url: 'http://10.0.0.9:8100', same_group: true },
  ],
} } };

test('PC 줄 · 재생 상태는 그룹 표에서 · 알람 · 버전 다름 · 연결 안 됨 · 스피커', () => {
  const rows = storeRows(snap);
  assert.deepEqual(rows.map((r) => [r.id, r.status, r.tone]), [
    ['f1', '재생 중', 'ok'], ['f2', '알람', 'bad'], ['f3', '버전 다름', 'warn'], ['f4', '연결 안 됨', 'bad'], ['sp', '스피커', 'ok'],
  ]);
  assert.equal(rows[0].meta, '10.0.0.1 · a9a69dd');
  assert.equal(rows[0].role, '마스터 · 그룹 참여');
  assert.equal(rows[2].role, '슬레이브 · 그룹 미참여');
  assert.equal(rows[4].role, '스피커 · 같은 그룹');
});

test('주소 · 터미널은 같은 호스트 8081 · 이상한 주소는 링크 안 만듦', () => {
  assert.deepEqual(pcLinks({ web_url: 'http://10.0.0.2:8000/' }), { web: 'http://10.0.0.2:8000/v2', terminal: 'http://10.0.0.2:8081' });
  assert.deepEqual(pcLinks({ role: 'speaker', web_url: 'http://10.0.0.9:8090' }), { web: 'http://10.0.0.9:8090', terminal: 'http://10.0.0.9:8081' });
  assert.deepEqual(pcLinks({ web_url: 'javascript:alert(1)' }), { web: '', terminal: '' });
  assert.deepEqual(pcLinks({}), { web: '', terminal: '' });
});

test('버전 요약 · 스피커 빼고', () => {
  assert.deepEqual(versionSummary(snap), { total: 4, differ: 1 });
});

test('업데이트 표 · 상태 글 · 버전 바뀜 · 실패 이유', () => {
  const rows = updateRows({ pcs: [
    { pc_id: 'f1', state: 'done', before_hash: '6609890aa', after_hash: 'a9a69ddbb', git_hash: 'a9a69ddbb' },
    { pc_id: 'f2', state: 'failed', before_hash: '6609890', git_hash: '6609890', message: '새 시스템 패키지 필요' },
    { pc_id: 'f3', state: 'running', git_hash: 'x', tail: ['== 8. 전체 빌드', '2/2'] },
    { pc_id: 'sp', state: 'manual', message: '그 PC 터미널에서' },
  ] });
  assert.deepEqual(rows.map((r) => [r.state.split(' · ')[0], r.version, r.note]), [
    ['완료', '6609890 → a9a69dd', '설치 완료'], ['실패', '6609890', '새 시스템 패키지 필요'], ['업데이트 중', 'x', '2/2'], ['해당 PC에서 직접 업데이트 필요', '-', '그 PC 터미널에서'],
  ]);
  assert.deepEqual(updateRows(null), []);
});

test('필수 명단 후보 · 보이는 같은 그룹 로봇만 · 이름 순', () => {
  assert.deepEqual(rosterCandidates(snap), ['f1', 'f2', 'f3']);
});
