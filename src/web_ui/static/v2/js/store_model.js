/** UI v2 · 매장 PC 화면이 보는 값 · 화면 없이 시험되는 함수만 (설계안 2026-10-09 · 매장 PC)
 *
 * 같은 망 표(network_pcs)가 바탕 · 그룹 사람 표(peers)에서 재생 상태를 얹는다.
 */
import { pcName } from './model.js';

const SAFE_URL = /^https?:\/\/[0-9A-Za-z.\-]+(:\d+)?$/;

/** 같은 망 주소 · 터미널은 같은 호스트 8081 (설치 스크립트가 띄우는 ttyd) */
export function pcLinks(pc) {
  const url = String(pc?.web_url || '').replace(/\/+$/, '');
  if (!SAFE_URL.test(url)) return { web: '', terminal: '' };
  const host = url.replace(/:\d+$/, '');
  // 새 화면에서 연 다른 로봇 PC 도 새 화면으로 · 스피커는 자기 앱 화면 그대로 (2026-10-12)
  return { web: pc?.role === 'speaker' ? url : `${url}/v2`, terminal: `${host}:8081` };
}

export function shortHash(hash) {
  return String(hash || '').slice(0, 7);
}

/** 연동 약속 번호가 다른 PC · 그룹 재생에서 빠진다 · 숫자까지 보여 어느 쪽이 옛것인지 알게 (2026-10-13) */
export function protocolNote(theirs, mine) {
  const them = Number(theirs) > 0 ? String(theirs) : '없음(옛 프로그램)';
  const me = Number(mine) > 0 ? ` · 이 PC ${mine}` : '';
  return `그룹 재생에서 빠집니다(연동 약속 번호 ${them}${me}). 「모든 PC 업데이트」로 같은 버전으로 맞추세요.`;
}

/** PC 한 줄 · 상태 글과 색 · 그룹 사람 표의 「재생 중」 같은 말을 쓴다 */
export function storeRows(snap) {
  const runtime = snap?.coordination?.runtime || {};
  const pcs = Array.isArray(runtime.network_pcs) ? runtime.network_pcs : [];
  const peers = new Map([...(Array.isArray(runtime.peers) ? runtime.peers : []), runtime.local].filter(Boolean)
    .map((peer) => [String(peer.pc_id), peer]));
  const mine = pcs.find((pc) => pc.is_local)?.protocol_version;
  return pcs.map((pc) => {
    const id = String(pc.pc_id || '');
    const peer = peers.get(id) || {};
    const speaker = pc.role === 'speaker';
    let status = speaker ? '스피커' : String(peer.motion_step || (pc.joined ? '그룹 대기' : '단독'));
    let tone = 'ok';
    let note = '';
    if (pc.online === false) { status = '연결 안 됨'; tone = 'bad'; note = 'PC가 꺼져 있거나 Wi-Fi 연결이 끊겼을 수 있습니다'; }
    else if (pc.protocol_mismatch) { status = '연동 버전 다름'; tone = 'bad'; note = protocolNote(pc.protocol_version, mine); }
    // 커밋만 다르다 · 연동 약속 번호가 같으면 그룹에서 빠지지 않는다(participant_rules) · 2026-10-13
    else if (pc.version_differs && !speaker) { status = '버전 다름'; tone = 'warn'; note = '코드 버전(커밋)이 다릅니다. 그룹 재생은 되지만 「모든 PC 업데이트」로 같은 버전으로 맞추세요.'; }
    else if (Number(peer.servo_alarm_grade || 0) > 0) { status = '알람'; tone = 'bad'; }
    const role = speaker ? '스피커' : pc.is_master ? '마스터' : '슬레이브';
    const group = speaker ? (pc.same_group ? '같은 그룹' : '') : pc.joined ? '그룹 참여' : '그룹 미참여';
    return {
      id,
      name: pcName(pc),
      local: pc.is_local === true,
      online: pc.online !== false,
      speaker,
      status,
      tone,
      note,
      meta: [String(pc.address || ''), shortHash(pc.git_hash)].filter(Boolean).join(' · '),
      role: [role, group].filter(Boolean).join(' · '),
      links: pcLinks(pc),
    };
  });
}

/** 버전이 다른 로봇 PC 수 · 스피커는 따로 업데이트라 뺀다 */
export function versionSummary(snap) {
  const pcs = (snap?.coordination?.runtime?.network_pcs || []).filter((pc) => pc.role !== 'speaker');
  const differ = pcs.filter((pc) => pc.version_differs || pc.protocol_mismatch).length;
  return { total: pcs.length, differ };
}

const UPDATE_STATE = {
  idle: ['업데이트 기록 없음', 'idle'],
  running: ['업데이트 중', 'info'],
  done: ['완료', 'ok'],
  failed: ['실패 · 이전 버전으로 복구함', 'bad'],
  unreachable: ['응답 없음', 'warn'],
  offline: ['연결 안 됨', 'bad'],
  manual: ['해당 PC에서 직접 업데이트 필요', 'warn'],
};

function when(epochSec) {
  const value = Number(epochSec);
  if (!Number.isFinite(value) || value <= 0) return '';
  const date = new Date(value * 1000);
  const today = new Date();
  const hm = `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`;
  return date.toDateString() === today.toDateString() ? `오늘 ${hm}` : `${date.getMonth() + 1}/${date.getDate()} ${hm}`;
}

/** 업데이트 표 한 줄 · 서버 status_all 의 pcs */
export function updateRows(data) {
  return (Array.isArray(data?.pcs) ? data.pcs : []).map((row) => {
    const [label, tone] = UPDATE_STATE[row.state] || [String(row.state || '-'), 'idle'];
    const at = when(row.finished_at || row.started_at);
    const before = shortHash(row.before_hash);
    const after = shortHash(row.after_hash || row.git_hash);
    const tail = Array.isArray(row.tail) && row.tail.length ? String(row.tail[row.tail.length - 1]) : '';
    return {
      id: String(row.pc_id || ''),
      name: pcName(row),
      state: at && (row.state === 'done' || row.state === 'failed') ? `${label} · ${at}` : label,
      tone,
      version: before && after && before !== after ? `${before} → ${after}` : after || before || '-',
      note: String(row.message || (row.state === 'running' ? tail : row.state === 'done' ? '설치 완료' : '')),
    };
  });
}

/** 필수 명단 후보 · 지금 보이는 같은 그룹 로봇 PC (이 PC 포함) */
export function rosterCandidates(snap) {
  const pcs = snap?.coordination?.runtime?.network_pcs || [];
  return pcs.filter((pc) => pc.role !== 'speaker' && pc.online !== false && (pc.same_group !== false || pc.is_local))
    .map((pc) => String(pc.pc_id)).filter(Boolean).sort();
}
