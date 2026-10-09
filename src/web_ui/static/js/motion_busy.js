/** 애니메이션 화면 · 오래 걸리는 일 표시 · 수정 목록 87 (2026-10-09 사용자)
 *
 * 9분 나레이션(15 MB · 기록 55만 개) 같은 긴 애니는 올리기 · 목록 다시 읽기 · 재생 등록이
 * 몇 초~수십 초 걸린다(서버가 파일을 통째로 읽고 검사한다) · 전에는 그동안 화면에 아무
 * 표시가 없어 멈춘 줄 알았다 · 돌아가는 표시 + 무엇을 하는지 + 지난 초를 띄운다.
 *
 * 일마다 이름(key)을 붙여 겹쳐도 된다 · 마지막에 시작한 일의 글자를 보인다 · 짧게 끝나는
 * 일(목록 새로 고침 등)은 깜빡이지 않게 0.4초 넘게 걸릴 때만 보인다.
 */

export const SHOW_AFTER_MS = 400;

export function busyText(text, elapsedSec) {
  const seconds = Math.max(0, Math.floor(Number(elapsedSec) || 0));
  return seconds >= 1 ? `${text} · ${seconds}초` : text;
}

export function createBusyIndicator({ el, now = () => Date.now(), timers = globalThis }) {
  const jobs = new Map();          // key → {text, startedAt}
  let ticker = null;
  let showTimer = null;
  let shown = false;

  function current() {
    let latest = null;
    let earliest = Infinity;
    for (const job of jobs.values()) {
      if (!latest || job.startedAt >= latest.startedAt) latest = job;
      earliest = Math.min(earliest, job.startedAt);
    }
    return latest ? { text: latest.text, startedAt: earliest } : null;
  }

  function paint() {
    const job = current();
    if (!el.motionBusy) return;
    if (!job || !shown) {
      el.motionBusy.classList.add('hidden');
      return;
    }
    el.motionBusy.classList.remove('hidden');
    if (el.motionBusyText) el.motionBusyText.textContent = busyText(job.text, (now() - job.startedAt) / 1000);
  }

  function stopTimers() {
    if (ticker) timers.clearInterval(ticker);
    if (showTimer) timers.clearTimeout(showTimer);
    ticker = null;
    showTimer = null;
  }

  function begin(key, text) {
    const previous = jobs.get(key);
    jobs.set(key, { text, startedAt: previous ? previous.startedAt : now() });
    if (!shown && !showTimer) {
      showTimer = timers.setTimeout(() => {
        showTimer = null;
        if (!jobs.size) return;
        shown = true;
        paint();
        ticker = timers.setInterval(paint, 1000);
      }, SHOW_AFTER_MS);
    }
    paint();
  }

  function end(key) {
    jobs.delete(key);
    if (!jobs.size) {
      stopTimers();
      shown = false;
    }
    paint();
  }

  /** 일 하나를 감싼다 · 실패해도 표시는 꼭 내린다 */
  async function run(key, text, work) {
    begin(key, text);
    try {
      return await work();
    } finally {
      end(key);
    }
  }

  return { begin, end, run, get active() { return jobs.size > 0; } };
}
