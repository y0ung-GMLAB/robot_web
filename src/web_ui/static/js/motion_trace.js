/** 회차별 재생 기록 화면 · 목표 위치와 실제 위치를 두 색 그래프로
 *
 * motion_runtime 이 회차마다 `<프로젝트>/logs/motion_trace/<날짜>/` 에 CSV 와
 * 요약(index.jsonl)을 남긴다 · 이 화면은 그것을 읽어 보여 주기만 한다.
 *
 * 탭을 눌러 이 화면이 보일 때 읽는다 · 패널의 `hidden` 이 곧 신호다 (사용법
 * 화면과 같은 방식) · 첫 화면 뜨는 속도에 얹지 않는다.
 */

import {
  deleteMotionTraceDay,
  fetchMotionTrace,
  fetchMotionTraceDays,
  fetchMotionTraceRuns,
  motionTraceDownloadUrl,
} from './api.js';
import {
  formatTraceBytes,
  tracePolylines,
  traceResultLabel,
  traceValueRange,
  traceWorstError,
} from './motion_trace_chart.js';
import { showConfirm } from './ui_dialogs.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
const CHART_WIDTH = 1000;
const CHART_HEIGHT = 140;

const panel = document.querySelector('[data-workspace-panel="motion-trace"]');

if (panel) {
  const summary = document.getElementById('motionTraceSummary');
  const daySelect = document.getElementById('motionTraceDaySelect');
  const refreshButton = document.getElementById('motionTraceRefreshButton');
  const deleteDayButton = document.getElementById('motionTraceDeleteDayButton');
  const storage = document.getElementById('motionTraceStorage');
  const runRows = document.getElementById('motionTraceRunRows');
  const detailTitle = document.getElementById('motionTraceDetailTitle');
  const downloadLink = document.getElementById('motionTraceDownloadLink');
  const charts = document.getElementById('motionTraceCharts');

  const state = {
    days: [],
    date: '',
    runs: [],
    file: '',
    loading: false,
  };

  function cell(row, text, className = '') {
    const td = document.createElement('td');
    if (className) td.className = className;
    td.textContent = String(text ?? '-');
    row.appendChild(td);
  }

  function emptyRow(text) {
    runRows.replaceChildren();
    const row = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 6;
    td.className = 'empty';
    td.textContent = text;
    row.appendChild(td);
    runRows.appendChild(row);
  }

  function clearDetail(title = '회차를 고르세요') {
    state.file = '';
    detailTitle.textContent = title;
    downloadLink.classList.add('hidden');
    charts.replaceChildren();
  }

  function renderDays(payload) {
    state.days = Array.isArray(payload?.days) ? payload.days : [];
    if (!state.days.some((day) => day.date === state.date)) {
      state.date = state.days[0]?.date || '';
    }
    daySelect.replaceChildren(...state.days.map((day) => {
      const option = document.createElement('option');
      option.value = day.date;
      option.textContent = `${day.date} · ${day.cycle_count}회차 · ${formatTraceBytes(day.bytes)}`;
      option.selected = day.date === state.date;
      return option;
    }));
    daySelect.disabled = !state.days.length;
    deleteDayButton.disabled = !state.date;
    storage.textContent = payload?.directory
      ? `${payload.directory} · 전체 ${formatTraceBytes(payload.total_bytes)}`
      : '';
    if (!payload?.project_id) {
      summary.textContent = payload?.message || '프로젝트를 먼저 선택하세요';
    } else if (!state.days.length) {
      summary.textContent = '아직 기록된 회차가 없습니다 · 애니메이션을 실행하면 회차마다 남습니다';
    }
  }

  function renderRuns() {
    if (!state.runs.length) {
      emptyRow(state.date ? '이 날짜에 기록된 회차가 없습니다' : '기록된 회차가 없습니다');
      return;
    }
    runRows.replaceChildren(...state.runs.map((run) => {
      const row = document.createElement('tr');
      row.dataset.file = String(run.file || '');
      row.classList.toggle('selected', run.file === state.file);
      const worst = traceWorstError(run);
      cell(row, String(run.started_text || '').slice(11, 19) || '-');
      cell(row, run.cycle);
      cell(row, run.motion_file_id || '-');
      cell(row, traceResultLabel(run.result), `result-${run.result}`);
      cell(row, `${Number(run.duration_sec || 0).toFixed(1)}s`);
      cell(row, worst ? `${worst.value.toFixed(2)}° (${worst.motionId})` : '-');
      if (!run.file_exists) {
        row.title = 'CSV 파일이 보존 기간·용량 정리로 지워졌습니다 · 요약만 남아 있습니다';
        row.classList.add('muted');
      }
      return row;
    }));
    summary.textContent = `${state.date} · ${state.runs.length}회차`;
  }

  function chartFor(axis, times, timeRange) {
    const box = document.createElement('div');
    box.className = 'motion-trace-chart';
    const range = traceValueRange([axis.target, axis.actual]);
    const errors = (axis.error || []).filter((v) => v !== null && Number.isFinite(v));
    const maxError = errors.length ? Math.max(...errors.map(Math.abs)) : null;

    const head = document.createElement('div');
    head.className = 'motion-trace-chart-head';
    const name = document.createElement('strong');
    name.textContent = axis.motion_id;
    const info = document.createElement('small');
    info.textContent = `${range[0].toFixed(2)}° ~ ${range[1].toFixed(2)}°`
      + (maxError === null ? ' · 실제값 없음' : ` · 최대 오차 ${maxError.toFixed(3)}°`);
    head.append(name, info);

    const svg = document.createElementNS(SVG_NS, 'svg');
    svg.setAttribute('viewBox', `0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`);
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', `${axis.motion_id} 목표·실제`);
    const geometry = { width: CHART_WIDTH, height: CHART_HEIGHT, timeRange, valueRange: range };

    if (range[0] < 0 && range[1] > 0) {
      const zero = document.createElementNS(SVG_NS, 'line');
      const y = CHART_HEIGHT - ((0 - range[0]) / (range[1] - range[0])) * CHART_HEIGHT;
      zero.setAttribute('x1', '0');
      zero.setAttribute('x2', String(CHART_WIDTH));
      zero.setAttribute('y1', y.toFixed(1));
      zero.setAttribute('y2', y.toFixed(1));
      zero.setAttribute('class', 'grid-line');
      zero.setAttribute('vector-effect', 'non-scaling-stroke');
      svg.appendChild(zero);
    }
    for (const [values, className] of [[axis.target, 'line-target'], [axis.actual, 'line-actual']]) {
      for (const points of tracePolylines(times, values, geometry)) {
        const line = document.createElementNS(SVG_NS, 'polyline');
        line.setAttribute('points', points);
        line.setAttribute('class', className);
        line.setAttribute('vector-effect', 'non-scaling-stroke');
        svg.appendChild(line);
      }
    }
    box.append(head, svg);
    return box;
  }

  async function openRun(file) {
    state.file = file;
    renderRuns();
    detailTitle.textContent = '불러오는 중';
    charts.replaceChildren();
    try {
      const trace = await fetchMotionTrace(state.date, file);
      if (state.file !== file) return;   // 그사이 다른 회차를 골랐다
      const times = trace.time || [];
      const timeRange = [times[0] ?? 0, times[times.length - 1] ?? 1];
      const record = trace.record || {};
      detailTitle.textContent = `${record.motion_file_id || file} · ${record.cycle ?? '-'}회차 · `
        + `${traceResultLabel(record.result)} · ${(timeRange[1] - timeRange[0]).toFixed(2)}s`
        + (trace.decimation > 1 ? ` · 그래프는 ${trace.decimation}개 중 1개 표시` : '');
      charts.replaceChildren(...(trace.axes || []).map((axis) => chartFor(axis, times, timeRange)));
      downloadLink.href = motionTraceDownloadUrl(state.date, file);
      downloadLink.setAttribute('download', file);
      downloadLink.classList.remove('hidden');
    } catch (error) {
      if (state.file === file) clearDetail(`불러오지 못했습니다: ${error.message}`);
    }
  }

  async function loadRuns() {
    if (!state.date) {
      state.runs = [];
      renderRuns();
      clearDetail();
      return;
    }
    const payload = await fetchMotionTraceRuns(state.date);
    state.runs = Array.isArray(payload?.runs) ? payload.runs : [];
    if (!state.runs.some((run) => run.file === state.file)) clearDetail();
    renderRuns();
  }

  async function load() {
    if (state.loading) return;
    state.loading = true;
    refreshButton.disabled = true;
    try {
      renderDays(await fetchMotionTraceDays());
      await loadRuns();
    } catch (error) {
      summary.textContent = `기록을 불러오지 못했습니다: ${error.message}`;
    } finally {
      state.loading = false;
      refreshButton.disabled = false;
    }
  }

  daySelect.addEventListener('change', () => {
    state.date = daySelect.value;
    deleteDayButton.disabled = !state.date;
    clearDetail();
    loadRuns().catch((error) => { summary.textContent = `기록을 불러오지 못했습니다: ${error.message}`; });
  });

  runRows.addEventListener('click', (event) => {
    const row = event.target.closest('tr[data-file]');
    if (!row || !row.dataset.file) return;
    const run = state.runs.find((item) => item.file === row.dataset.file);
    if (run && !run.file_exists) return;
    openRun(row.dataset.file);
  });

  refreshButton.addEventListener('click', () => load());

  deleteDayButton.addEventListener('click', async () => {
    if (!state.date) return;
    const confirmed = await showConfirm(
      `${state.date} 의 재생 기록(CSV ${state.runs.length}회차)을 모두 삭제합니다.\n삭제한 기록은 복구할 수 없습니다.`,
      { title: '재생 기록 삭제', confirmLabel: '삭제', tone: 'danger' },
    );
    if (!confirmed) return;
    deleteDayButton.disabled = true;
    try {
      renderDays(await deleteMotionTraceDay(state.date));
      clearDetail();
      await loadRuns();
    } catch (error) {
      summary.textContent = `삭제하지 못했습니다: ${error.message}`;
      deleteDayButton.disabled = !state.date;
    }
  });

  new MutationObserver(() => {
    if (!panel.classList.contains('hidden')) load();
  }).observe(panel, { attributes: true, attributeFilter: ['class'] });

  if (!panel.classList.contains('hidden')) load();
}
