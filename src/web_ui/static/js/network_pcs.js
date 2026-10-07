/** 같은 공유기 망의 PC 표 · 핵심 요구 4
 *
 * 각 PC(로봇 · 스피커)가 그룹 참가와 상관없이 2초마다 이름 · IP · 웹 주소를 알린다
 * (`/motion_group/presence`) · 연동 노드가 모아 `runtime.network_pcs` 로 준다 ·
 * 마스터에서 이 표를 보고 「열기」로 각 PC 화면을 새 탭에 연다.
 * 같은 DDS 도메인이어야 보인다 · 도메인이 다르면 같은 공유기여도 안 보인다.
 */
import { escapeHtml } from './format.js';

const WEB_URL = /^http:\/\/[0-9.]+:\d+$/;

function text(value) {
  return escapeHtml(value ?? '');
}

function roleText(pc) {
  if (pc.role === 'speaker') return '스피커';
  return pc.is_master ? '로봇 · 마스터' : '로봇';
}

function groupText(pc) {
  if (!pc.group_id) return pc.role === 'speaker' ? '그룹 없음' : '연동 안 함';
  if (pc.role === 'speaker') return `${pc.group_id} 듣는 중`;
  return `${pc.group_id} · ${pc.joined ? '참가' : '나감'}`;
}

function stateCell(pc) {
  if (pc.online) return '<td class="coordination-state-ok">연결됨</td>';
  return `<td class="coordination-state-bad">끊김 · ${Math.round(Number(pc.age_sec) || 0)}초 전</td>`;
}

function versionCell(pc, localProtocol) {
  const notes = [];
  if (pc.version_differs) notes.push('이 PC 와 다름');
  if (pc.protocol_mismatch) notes.push(`약속 번호 ${Number(pc.protocol_version) || 0} (이 PC ${localProtocol})`);
  const cls = notes.length ? 'coordination-state-bad' : '';
  return `<td class="${cls}">${text(pc.git_hash || '-')}${notes.length ? ` · ${text(notes.join(' · '))}` : ''}</td>`;
}

function openCell(pc) {
  if (pc.is_local) return '<td>지금 이 화면</td>';
  const url = String(pc.web_url || '');
  if (!WEB_URL.test(url)) return '<td>-</td>';
  const label = pc.role === 'speaker' ? '스피커 화면 열기' : '화면 열기';
  return `<td><a class="network-pc-open" href="${text(url)}" target="_blank" rel="noopener" title="${text(url)} 을 새 탭으로 엽니다">${label}</a></td>`;
}

export function networkPcRows(pcs) {
  const list = Array.isArray(pcs) ? pcs : [];
  if (list.length <= 1) {
    const local = list[0];
    const head = local ? networkPcRow(local, local.protocol_version) : '';
    return `${head}<tr><td colspan="7" class="empty">다른 PC 의 알림을 기다리는 중 · 같은 공유기 · 같은 DDS Domain ID 여야 보입니다 · 다른 PC 도 이 버전 이상이어야 합니다</td></tr>`;
  }
  const localProtocol = Number(list.find((pc) => pc.is_local)?.protocol_version) || 0;
  return list.map((pc) => networkPcRow(pc, localProtocol)).join('');
}

function networkPcRow(pc, localProtocol) {
  const name = pc.display_name || pc.pc_id || '-';
  const sub = pc.display_name && pc.display_name !== pc.pc_id ? `<small>${text(pc.pc_id)}</small>` : '';
  const local = pc.is_local ? ' <small>(이 PC)</small>' : '';
  return `<tr>
      <td><strong>${text(name)}</strong>${local}${sub}</td>
      <td>${text(roleText(pc))}</td>
      <td class="network-pc-address">${text(pc.address || '-')}</td>
      <td>${text(groupText(pc))}</td>
      ${stateCell(pc)}
      ${versionCell(pc, localProtocol)}
      ${openCell(pc)}
    </tr>`;
}
