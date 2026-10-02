import {
  fetchRobotPack,
  fetchRobotPackMappingDiff,
  rollbackRobotPack,
  uploadRobotPack,
} from './api.js';
import { escapeHtml } from './format.js';
import { showConfirm } from './ui_dialogs.js';

/** 로봇 팩 · PC 전역 · zip 업로드 → 서버 검사 → 통과해야 교체 · 이전 팩 1개로 되돌리기
 *
 * 화면은 판정하지 않는다 · 검사(필수 파일·경로·크기·형식·모델 로드)는 서버가
 * 하고, 화면은 그 결과(이유 목록)를 그대로 보여 준다.
 */
export function createRobotPackController({ el }) {
  let busy = false;

  function label(entry) {
    if (!entry) return '없음';
    return [entry.name, entry.version].filter(Boolean).join(' ') || '이름 없음';
  }

  function setMessage(text, { error = false } = {}) {
    if (!el.robotPackMessage) return;
    el.robotPackMessage.textContent = text || '';
    el.robotPackMessage.classList.toggle('error', Boolean(error));
  }

  function showList(element, items) {
    if (!element) return;
    element.innerHTML = (items || []).map((item) => `<li>${escapeHtml(item)}</li>`).join('');
    element.classList.toggle('hidden', !(items || []).length);
  }

  function render(status) {
    const current = status?.current || null;
    const previous = status?.previous || null;
    if (el.robotPackCurrent) el.robotPackCurrent.textContent = label(current);
    if (el.robotPackUploadedAt) el.robotPackUploadedAt.textContent = current?.uploaded_at || '-';
    if (el.robotPackPrevious) el.robotPackPrevious.textContent = previous ? label(previous) : '없음';
    if (el.robotPackSummary) {
      el.robotPackSummary.textContent = current ? `${label(current)} 사용 중` : '팩 없음 · zip 을 올리세요';
    }
    if (el.robotPackRollbackButton) el.robotPackRollbackButton.disabled = busy || !previous;
  }

  async function refresh() {
    try {
      render(await fetchRobotPack());
    } catch (error) {
      setMessage(`로봇 팩 상태 확인 실패: ${error.message}`, { error: true });
    }
  }

  async function upload(file) {
    if (!file || busy) return;
    if (!/\.zip$/i.test(file.name)) {
      setMessage(`zip 파일만 올릴 수 있습니다: ${file.name}`, { error: true });
      return;
    }
    busy = true;
    showList(el.robotPackErrors, []);
    setMessage(`검사 중: ${file.name} · 모델 로드 검사까지 수십 초 걸릴 수 있습니다`);
    try {
      const result = await uploadRobotPack(file);
      setMessage(result.message || '', { error: result.success === false });
      showList(el.robotPackErrors, [...(result.errors || []), ...(result.warnings || []).map((w) => `경고 · ${w}`)]);
      if (result.success) render(result);
    } catch (error) {
      setMessage(`업로드 실패: ${error.message}`, { error: true });
    } finally {
      busy = false;
      await refresh();
    }
  }

  async function rollback() {
    if (busy) return;
    const ok = await showConfirm('이전 로봇 팩으로 되돌립니다 · 지금 팩은 이전 팩 자리로 갑니다');
    if (!ok) return;
    busy = true;
    try {
      const result = await rollbackRobotPack();
      setMessage(result.message || '', { error: result.success === false });
      showList(el.robotPackErrors, []);
    } catch (error) {
      setMessage(`되돌리기 실패: ${error.message}`, { error: true });
    } finally {
      busy = false;
      await refresh();
    }
  }

  function pair(pack, mapping) {
    const show = (value) => (Array.isArray(value) ? `[${value.join(', ')}]` : (value ?? '-'));
    return `${escapeHtml(show(pack))} / ${escapeHtml(show(mapping))}`;
  }

  async function showDiff() {
    try {
      const result = await fetchRobotPackMappingDiff();
      if (!result.available || result.success === false) {
        setMessage(result.message || '비교할 수 없습니다', { error: true });
        el.robotPackDiffWrap?.classList.add('hidden');
        return;
      }
      const rows = result.rows || [];
      if (el.robotPackDiffRows) {
        el.robotPackDiffRows.innerHTML = rows.map((row) => `
          <tr class="${row.differences?.length ? 'differs' : ''}">
            <td>${escapeHtml(row.motion_id)}</td>
            <td>${escapeHtml(row.joint || '-')}</td>
            <td>${pair(row.pack_ratio, row.mapping_ratio)}</td>
            <td>${pair(row.pack_range, row.mapping_range)}</td>
            <td>${escapeHtml((row.differences || []).join(' · ') || '같음')}</td>
          </tr>`).join('');
      }
      el.robotPackDiffWrap?.classList.remove('hidden');
      setMessage(result.mapping_file
        ? `비교 대상 모션축 설정: ${result.mapping_file} · 표시만 · 적용하지 않습니다`
        : '등록된 모션축 설정이 없습니다');
    } catch (error) {
      setMessage(`비교 실패: ${error.message}`, { error: true });
    }
  }

  function bindEvents() {
    el.robotPackFileInput?.addEventListener('change', () => {
      const [file] = el.robotPackFileInput.files || [];
      el.robotPackFileInput.value = '';
      upload(file);
    });
    const zone = el.robotPackDropZone;
    zone?.addEventListener('dragover', (event) => {
      event.preventDefault();
      zone.classList.add('dragging');
    });
    zone?.addEventListener('dragleave', () => zone.classList.remove('dragging'));
    zone?.addEventListener('drop', (event) => {
      event.preventDefault();
      zone.classList.remove('dragging');
      upload(event.dataTransfer?.files?.[0]);
    });
    el.robotPackRollbackButton?.addEventListener('click', rollback);
    el.robotPackDiffButton?.addEventListener('click', showDiff);
  }

  return { bindEvents, refresh };
}
