/** 드래그&드롭 · 폴더째 놓은 것을 파일 목록으로 · 로봇 팩과 애니메이션이 같이 쓴다 · 2026-10-02 */

/** 드롭된 폴더 항목 → [{path, file}] · readEntries 는 나눠서 주므로 빌 때까지 */
export async function walkEntry(entry, prefix = '') {
  const path = prefix ? `${prefix}/${entry.name}` : entry.name;
  if (entry.isFile) {
    const file = await new Promise((resolve, reject) => entry.file(resolve, reject));
    return [{ path, file }];
  }
  const reader = entry.createReader();
  const children = [];
  for (;;) {
    const batch = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
    if (!batch.length) break;
    children.push(...batch);
  }
  const nested = await Promise.all(children.map((child) => walkEntry(child, path)));
  return nested.flat();
}

/** 드롭 이벤트의 항목(entry) · drop 처리 안에서 **바로** 꺼내야 한다 (await 뒤엔 비어 있다) */
export function droppedEntries(dataTransfer) {
  return [...(dataTransfer?.items || [])]
    .map((item) => item.webkitGetAsEntry?.())
    .filter(Boolean);
}

/** 파일이 끌려 오는 중인가 · 글자·링크 끌기는 건드리지 않는다 */
export function draggingFiles(event) {
  return [...(event?.dataTransfer?.types || [])].includes('Files');
}

/** 받는 칸 밖에 떨어뜨리면 브라우저가 그 파일을 열어 화면을 떠난다 · 문서 전체에서 막는다
 *
 * 받는 칸(애니메이션 목록 · 로봇 팩)은 제 처리기가 먼저 받는다 · 여기는 남은 것만.
 */
export function guardDocumentDrops(target = window) {
  target.addEventListener('dragover', (event) => {
    if (draggingFiles(event)) event.preventDefault();
  });
  target.addEventListener('drop', (event) => {
    if (draggingFiles(event)) event.preventDefault();
  });
}
