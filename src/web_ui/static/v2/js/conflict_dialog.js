/** UI v2 · 저장 충돌 확인 창 · 같은 칸을 다른 곳에서도 다르게 바꿨을 때만 (2026-10-12) */
import { confirmBox } from './dialog.js';

function show(value) {
  if (value === undefined || value === null || value === '') return '-';
  return typeof value === 'object' ? JSON.stringify(value) : String(value);
}

/** conflicts · threeWayMerge 결과 · labelOf(key) · 사람이 읽는 이름 · 「내 값으로 저장」 이면 true */
export function confirmConflicts(conflicts, labelOf) {
  const lines = conflicts.slice(0, 6).map((c) => `· ${labelOf(c.key)} · ${c.path.join('.')} · 다른 곳 ${show(c.theirs)} / 이 화면 ${show(c.mine)}`);
  const more = conflicts.length > 6 ? `\n· 외 ${conflicts.length - 6}개` : '';
  return confirmBox({
    title: '다른 곳에서도 같은 칸을 바꿨습니다',
    body: `최신 파일을 다시 받아 이 화면에서 고친 칸만 얹었습니다. 아래 칸은 양쪽이 다르게 바꿔서 하나를 골라야 합니다.\n\n${lines.join('\n')}${more}\n\n「내 값으로 저장」 · 위 칸은 이 화면 값으로 저장합니다(나머지는 양쪽 변경이 모두 남습니다).\n「저장 안 함」 · 아무것도 저장하지 않습니다. 고친 내용은 화면에 남아 있습니다.`,
    confirmLabel: '내 값으로 저장', cancelLabel: '저장 안 함', tone: 'warning',
  });
}
