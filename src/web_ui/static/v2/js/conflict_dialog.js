/** UI v2 · 저장 충돌 확인 창 · 같은 칸을 다른 곳에서도 다르게 바꿨을 때만 (2026-10-12) */
import { confirmBox } from './dialog.js';

function show(value) {
  if (value === undefined || value === null || value === '') return '-';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

/** conflicts · threeWayMerge 결과 · labelOf(key) · 사람이 읽는 이름 · 「내 값으로 저장」 이면 true */
export function confirmConflicts(conflicts, labelOf) {
  const lines = conflicts.slice(0, 6).map((c) => `· ${labelOf(c.key)} ${c.path.join('.')}: 다른 곳 ${show(c.theirs)} / 현재 화면 ${show(c.mine)}`);
  const more = conflicts.length > 6 ? `\n· 외 ${conflicts.length - 6}개` : '';
  return confirmBox({
    title: '다른 곳에서도 같은 칸을 변경했습니다',
    body: `아래 칸은 다른 곳에서 저장한 값과 현재 화면 값이 다릅니다.\n\n${lines.join('\n')}${more}\n\n「내 값으로 저장」: 위 칸은 현재 화면 값으로 저장하고, 나머지 칸은 양쪽 변경을 모두 유지합니다.\n「저장 안 함」: 저장하지 않고 화면의 수정 내용은 그대로 둡니다.`,
    confirmLabel: '내 값으로 저장', cancelLabel: '저장 안 함', tone: 'warning',
  });
}
