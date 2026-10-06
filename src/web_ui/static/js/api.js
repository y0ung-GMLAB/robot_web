import {
  inDegView,
  inRadPayload,
  liveOverridePayloadInRad,
  motionRunResponseInDeg,
} from './unit_view.js';

const PROJECT_GENERATION_KEY = '__motionProjectGeneration';

/** 서버가 앞서 갔을 때 알릴 곳 · §6-140
 *
 * 모터 설정을 적용하면 프로젝트 세대가 오른다 · 그 순간 열려 있던 화면은
 * 옛 세대를 들고 있어서, 그다음 요청의 응답이 전부 「이전 프로젝트의 늦은
 * 응답」으로 버려졌다 · 버리는 쪽은 조용히 `return` 만 해서 화면이 빈칸으로
 * 굳었다 · 「재생 등록된 파일 없음」이 그렇게 나왔다. 데이터는 멀쩡했다.
 *
 * 늦은 응답(세대가 **뒤진** 응답)은 버리는 게 맞다 · 그러나 세대가 **앞선**
 * 응답은 버릴 것이 아니라 따라가야 할 신호다.
 */
let projectAheadHandler = null;

export function setProjectAheadHandler(handler) {
  projectAheadHandler = typeof handler === 'function' ? handler : null;
}

export function setProjectGeneration(value) {
  const parsed = Number(value);
  if (Number.isInteger(parsed) && parsed >= 0) {
    window[PROJECT_GENERATION_KEY] = parsed;
  }
}

export function getProjectGeneration() {
  const value = Number(window[PROJECT_GENERATION_KEY]);
  return Number.isInteger(value) && value >= 0 ? value : null;
}

async function projectFetch(input, options = {}) {
  const expectedGeneration = getProjectGeneration();
  const { timeoutMs = 0, ...requestOptions } = options;
  const headers = new Headers(requestOptions.headers || {});
  if (expectedGeneration !== null) {
    headers.set('X-Project-Generation', String(expectedGeneration));
  }
  const timeout = Number(timeoutMs);
  const controller = Number.isFinite(timeout) && timeout > 0 && !requestOptions.signal
    ? new AbortController()
    : null;
  const timer = controller
    ? window.setTimeout(() => controller.abort(), timeout)
    : null;
  try {
    const response = await window.fetch(input, {
      ...requestOptions,
      headers,
      signal: controller?.signal || requestOptions.signal,
    });
    response.projectGenerationExpected = expectedGeneration;
    return response;
  } catch (error) {
    if (controller?.signal.aborted) {
      throw new Error(`상태 응답 시간 초과 · ${Math.round(timeout / 1000)}초`);
    }
    throw error;
  } finally {
    if (timer !== null) window.clearTimeout(timer);
  }
}

/** 응답을 읽는다 · §6-181
 *
 * **프로젝트에 매이지 않는 호출도 있다.** 시스템 시각과 사용법 문서는 어느
 * 프로젝트를 고르든 같은 답이다 · 그런데 응답 헤더에는 프로젝트 세대가 늘
 * 붙어 있어서, 그대로 검사하면 프로젝트를 바꾸는 순간 **아무 상관 없는
 * 호출이 실패**한다.
 *
 * 그래서 `projectScoped: false` 를 주면 세대를 보지 않는다 · 관문은 하나로
 * 두되, 그 관문이 「이 호출이 프로젝트에 매이나」를 안다.
 */
async function readJson(response, { projectScoped = true } = {}) {
  let payload = null;
  try {
    payload = await response.json();
  } catch (error) {
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    throw error;
  }
  if (!projectScoped) {
    if (!response.ok) {
      const detail = payload?.message || payload?.detail || `HTTP ${response.status}`;
      throw new Error(detail);
    }
    return payload;
  }
  const expected = response.projectGenerationExpected;
  const headerGeneration = Number(response.headers.get('X-Project-Generation'));
  const payloadGeneration = Number(payload?.project_generation);
  const responseGeneration = Number.isInteger(payloadGeneration)
    ? payloadGeneration
    : (Number.isInteger(headerGeneration) ? headerGeneration : null);
  const previousGeneration = Number(payload?.previous_project_generation);
  const transition = Number.isInteger(expected)
    && Number.isInteger(previousGeneration)
    && previousGeneration === expected
    && Number.isInteger(payloadGeneration)
    && payloadGeneration > expected;
  const externalBoundary = response.status === 409
    && payload?.stale_project_generation === true
    && Number.isInteger(expected)
    && Number.isInteger(responseGeneration)
    && responseGeneration > expected;
  if (externalBoundary) {
    setProjectGeneration(responseGeneration);
    const error = new Error(payload?.message || '프로젝트가 다른 브라우저에서 변경되었습니다');
    error.projectBoundaryGeneration = responseGeneration;
    throw error;
  }
  if (
    !transition
    && Number.isInteger(expected)
    && Number.isInteger(responseGeneration)
    && responseGeneration > expected
  ) {
    // 서버가 앞서 갔다 · 버릴 것이 아니라 따라가야 한다 · §6-140
    setProjectGeneration(responseGeneration);
    if (projectAheadHandler) projectAheadHandler(responseGeneration);
    const error = new Error('프로젝트 설정이 바뀌어 다시 읽습니다');
    error.staleProjectResponse = true;
    error.projectMovedAhead = responseGeneration;
    throw error;
  }
  if (
    !transition
    && Number.isInteger(expected)
    && (
      (Number.isInteger(getProjectGeneration()) && expected !== getProjectGeneration())
      || (Number.isInteger(responseGeneration) && responseGeneration !== expected)
    )
  ) {
    const error = new Error('이전 프로젝트의 늦은 응답을 폐기했습니다');
    error.staleProjectResponse = true;
    throw error;
  }
  if (transition || getProjectGeneration() === null) {
    setProjectGeneration(responseGeneration);
  }
  if (!response.ok) {
    const detail = payload?.message || payload?.detail || `HTTP ${response.status}`;
    throw new Error(detail);
  }
  return payload;
}


export const fetchStatusSnapshot = (timeoutMs = 5000) =>
  request('GET', '/api/status', { timeoutMs });

export const fetchSystemVersion = () => request('GET', '/api/system/version');

// --------------------------------------------------------------------------- //
// 스케줄 · 프로젝트에 매인다 (`active_project_id` 를 갖는다) · §6-181
// --------------------------------------------------------------------------- //

export const fetchScheduleStatus = () => request('GET', '/api/schedule/status');

export const fetchScheduleList = () => request('GET', '/api/schedule/list');

export const saveScheduleRunMode = (mode) =>
  request('PUT', '/api/schedule/mode', { body: { run_mode: mode } });

export const saveSchedule = (payload) =>
  request('POST', '/api/schedule/save', { body: payload });

//: 주소를 조건식으로 이어 붙이지 않는다 · §6-181 · 글자로 남아 있어야
//: 「이 길을 누가 쓰나」를 찾을 수 있다 · 조립하면 죽은 길 검사가 못 본다
const enableSchedule = (scheduleId) =>
  request('POST', `/api/schedule/${encodeURIComponent(scheduleId)}/enable`);

const disableSchedule = (scheduleId) =>
  request('POST', `/api/schedule/${encodeURIComponent(scheduleId)}/disable`);

export const setScheduleEnabled = (scheduleId, enabled) =>
  (enabled ? enableSchedule : disableSchedule)(scheduleId);

export const deleteSchedule = (scheduleId) =>
  request('DELETE', `/api/schedule/${encodeURIComponent(scheduleId)}`);

// --------------------------------------------------------------------------- //
// 프로젝트와 무관한 것 · 어느 프로젝트를 골라도 답이 같다 · §6-181
// --------------------------------------------------------------------------- //

export const fetchSystemTime = () => request('GET', '/api/system/time', { projectScoped: false });

export const fetchDocumentList = () => request('GET', '/api/docs', { projectScoped: false });

export const fetchDocument = (documentId) =>
  request('GET', `/api/docs/${encodeURIComponent(documentId)}`, { projectScoped: false });

export const fetchCoordinationStatus = () => request('GET', '/api/coordination');

export const saveCoordinationSettings = (payload) => request('PUT', '/api/coordination/settings', { body: payload });

export const sendCoordinationControl = (payload) =>
  request('POST', '/api/coordination/control', { body: payload, timeoutMs: 7000 });

export const fetchServoAlarmPolicy = () => request('GET', '/api/servo-alarm-policy');

export const saveServoAlarmPolicy = (overrides) => request('PUT', '/api/servo-alarm-policy', { body: { overrides } });

export const restartManagedProgram = () => request('POST', '/api/system/program/restart');

export const createDesktopShortcut = () => request('POST', '/api/system/desktop-shortcut');


export const clearMotorRuntimeApplication = () => request('POST', '/api/system/motor-runtime/clear');

/** 경로와 메서드만 다른 요청을 한 곳으로 모은다.
 *
 * 74개 함수가 거의 같은 여섯 줄을 반복하고 있었다 · 봉투가 같으니 표로 쓰면
 * 어떤 화면이 어느 엔드포인트를 쓰는지 한눈에 보인다. 이 파일 안에 이미
 * 요청은 전부 이 한 함수를 지난다.
 */
async function request(method, path, { body, rawBody, contentType, timeoutMs, projectScoped = true } = {}) {
  const options = { method };
  if (rawBody !== undefined) {
    // 파일 그대로 (zip 등) · multipart 를 쓰지 않는다
    options.headers = { 'Content-Type': contentType || 'application/octet-stream' };
    options.body = rawBody;
  } else if (body !== undefined) {
    options.headers = { 'Content-Type': 'application/json' };
    options.body = JSON.stringify(body);
  }
  if (timeoutMs !== undefined) options.timeoutMs = timeoutMs;
  return readJson(await projectFetch(path, options), { projectScoped });
}


export async function fetchMotorEvents(category = 'all', limit = 300, fileName = 'all') {
  const query = new URLSearchParams({
    category: String(category || 'all'),
    limit: String(limit),
    file_name: String(fileName || 'all'),
  });
  const response = await projectFetch(`/api/motor-events?${query.toString()}`);
  return readJson(response);
}

export const clearMotorEvents = () => request('DELETE', '/api/motor-events');

export const deleteMotorEventLogFile = (fileName) =>
  request('DELETE', `/api/motor-events/files/${encodeURIComponent(fileName)}`);

// 회차별 재생 기록 · motion_runtime 이 회차마다 남긴 목표·실제 CSV
export const fetchMotionTraceDays = () => request('GET', '/api/motion-trace/days');

export const fetchMotionTraceRuns = (date) =>
  request('GET', `/api/motion-trace/runs?${new URLSearchParams({ date: String(date || '') })}`);

export const fetchMotionTrace = (date, file) =>
  request('GET', `/api/motion-trace/trace?${new URLSearchParams({ date: String(date), file: String(file) })}`);

export const deleteMotionTraceDay = (date) =>
  request('DELETE', `/api/motion-trace/days/${encodeURIComponent(date)}`);

/** 내려받기는 링크로 · 브라우저가 파일로 받는다 */
export const motionTraceDownloadUrl = (date, file) =>
  `/api/motion-trace/download?${new URLSearchParams({ date: String(date), file: String(file) })}`;

export const setMonitoringEnabled = (enabled) => request('POST', '/api/monitoring/enabled', { body: { enabled } });

export const requestMotorScan = () => request('POST', '/api/motors/scan');

export const requestAcServoScan = () => request('POST', '/api/motors/scan/ac-servo');

export const requestDynamixelScan = () => request('POST', '/api/motors/scan/dynamixel');

export const fetchMotorScanProgress = () => request('GET', '/api/motors/scan/progress');

export const writeEthercatAlias = (payload) => request('POST', '/api/motors/ethercat-alias', { body: payload });

export const fetchMotorConfig = () => request('GET', '/api/motor-config');

export const saveMotorConfig = (payload) => request('PUT', '/api/motor-config', { body: payload });


export const applyMotorConfig = () => request('POST', '/api/motor-config/apply');

export const fetchProjects = () => request('GET', '/api/projects');

export const createProject = (payload) => request('POST', '/api/projects', { body: payload });

export const deleteProject = (projectId) => request('DELETE', `/api/projects/${encodeURIComponent(projectId)}`);
// 백업·복원·휴지통 · 수정 목록 33
export const projectExportUrl = (projectId) => `/api/projects/${encodeURIComponent(projectId)}/export`;
export const importProjectZip = (file, overwrite = false) =>
  request('POST', `/api/project-import${overwrite ? '?overwrite=true' : ''}`, {
    rawBody: file, contentType: 'application/zip', timeoutMs: 120000,
  });
export const fetchProjectTrash = () => request('GET', '/api/project-trash');
export const restoreProjectTrash = (entry) =>
  request('POST', `/api/project-trash/${encodeURIComponent(entry)}/restore`);


export const fetchProject = (projectId) => request('GET', `/api/projects/${encodeURIComponent(projectId)}`);

export const selectProject = (projectId) => request('POST', `/api/projects/${encodeURIComponent(projectId)}/select`);

export const saveProjectMemo = (projectId, memo) =>
  request('PATCH', `/api/projects/${encodeURIComponent(projectId)}`, { body: { memo } });

function projectFileUrl(projectId, category, fileName) {
  return `/api/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(category)}/${encodeURIComponent(fileName)}`;
}

export const importProjectFile = (projectId, payload) =>
  request('POST', `/api/projects/${encodeURIComponent(projectId)}/files`, { body: payload });

export const fetchProjectFile = (projectId, category, fileName) =>
  request('GET', projectFileUrl(projectId, category, fileName));

export async function fetchReadOnlyProjectFile(projectId, relativePath) {
  const query = new URLSearchParams({ relative_path: relativePath });
  const response = await projectFetch(
    `/api/projects/${encodeURIComponent(projectId)}/tree-file?${query.toString()}`,
  );
  return readJson(response);
}

export const renameProjectFile = (projectId, category, fileName, newName) =>
  request('POST', `${projectFileUrl(projectId, category, fileName)}/rename`, { body: { new_name: newName } });

export const activateProjectFile = (projectId, category, fileName) =>
  request('POST', `${projectFileUrl(projectId, category, fileName)}/active`);

export const openProjectFileEditor = (projectId, category, fileName) =>
  request('POST', `${projectFileUrl(projectId, category, fileName)}/open-editor`);

export const deleteProjectFile = (projectId, category, fileName) =>
  request('DELETE', projectFileUrl(projectId, category, fileName));

export function projectFileDownloadUrl(projectId, category, fileName) {
  return `${projectFileUrl(projectId, category, fileName)}/download`;
}

export const fetchMotionFiles = () => request('GET', '/api/motion-files');

export const fetchMotionFile = (fileId) => request('GET', `/api/motion-files/${encodeURIComponent(fileId)}`);

export const deleteMotionFile = (fileId) => request('DELETE', `/api/motion-files/${encodeURIComponent(fileId)}`);

// 조인트 매핑·재생 상태는 서버가 rad · 화면은 deg · 바꾸는 곳은 `unit_view.js` 하나 (수정 목록 6)
export const fetchMotionMappings = () => request('GET', '/api/motion-mappings').then(inDegView);

export const fetchMotionMapping = (fileId) =>
  request('GET', `/api/motion-mappings/${encodeURIComponent(fileId)}`).then(inDegView);

export const saveMotionMapping = (payload) =>
  request('POST', '/api/motion-mappings', { body: inRadPayload(payload) }).then(inDegView);

export const validateMotionMapping = (payload) =>
  request('POST', '/api/motion-mappings/validate', { body: inRadPayload(payload) }).then(inDegView);

/** 재생 등록만 바꾼다 · 조인트 매핑은 안 건드린다 · §6-160 */
export const saveRegisteredMotionFile = (payload) =>
  request('POST', '/api/motion-mappings/motion-file', { body: inRadPayload(payload) }).then(inDegView);


export const fetchMotionRunStatus = () => request('GET', '/api/motion-run/status').then(motionRunResponseInDeg);

export const checkMotionRun = (payload) =>
  request('POST', '/api/motion-run/check', { body: payload }).then(motionRunResponseInDeg);

export const initializeMotionRun = (payload) =>
  request('POST', '/api/motion-run/initialize', { body: payload }).then(motionRunResponseInDeg);

export const startMotionRun = (payload) =>
  request('POST', '/api/motion-run/start', { body: payload }).then(motionRunResponseInDeg);

export const configureMotionAutomation = (payload) =>
  request('PUT', '/api/motion-run/automation', { body: payload }).then(motionRunResponseInDeg);


export const stopMotionRun = () => request('POST', '/api/motion-run/stop').then(motionRunResponseInDeg);

/** 웹 3D 표시 · 7-a · 장면(팩 1회) · 프레임(.sim.npz) */
export const fetchPreviewScene = () => request('GET', '/api/preview/scene');
export const exportPreviewScene = () => request('POST', '/api/preview/scene/export');
export const fetchPreviewSceneData = () => request('GET', '/api/preview/scene/data');
export const fetchPreviewFrames = (fileId) =>
  request('GET', `/api/motion-files/${encodeURIComponent(fileId)}/preview-frames`);

/** MuJoCo 계산 시작 · 무거운 물리 시뮬 · 업로드 직후 자동으로도 부른다 · P7 */
export const precomputeMotionFile = (fileId) =>
  request('POST', `/api/motion-files/${encodeURIComponent(fileId)}/preview-precompute`);

/** 재생 라이브 오버라이드 · 조인트 뮤트·좁힌 리밋 · 재생 중에도 듣는다 · P7 */
export const setMotionRunLiveOverride = (payload) =>
  request('POST', '/api/motion-run/live-override', { body: liveOverridePayloadInRad(payload) })
    .then(motionRunResponseInDeg);

export const stopMotionRunAfterCycle = () =>
  request('POST', '/api/motion-run/stop-after-cycle').then(motionRunResponseInDeg);

// 로봇 팩 · PC 전역 (PC 1대 = 로봇 1대) · 축·모터·환경·MuJoCo 모델 묶음
export const fetchRobotPack = () => request('GET', '/api/robot-pack');

/** zip 파일 그대로 올린다 · 검사를 하나라도 못 넘으면 서버가 교체하지 않는다 */
export const uploadRobotPack = (file) =>
  request('PUT', '/api/robot-pack', { rawBody: file, contentType: 'application/zip', timeoutMs: 240000 });

export const rollbackRobotPack = () => request('POST', '/api/robot-pack/rollback');

/** 팩 ↔ 등록된 조인트 매핑 차이 · 표시만 */
export const fetchRobotPackMappingDiff = () => request('GET', '/api/robot-pack/mapping-diff');

export const requestMotionSafetyStop = () => request('POST', '/api/safety/motion-stop');

export const requestEmergencySafetyStop = () => request('POST', '/api/safety/emergency-stop');

// 조그·절대 이동 · 화면은 `relative_deg`·`target_deg`(모터 deg) 로 부르고 서버에는 rad 로 (수정 목록 6-4)
export const requestAcServoJog = (payload) =>
  request('POST', '/api/motion-test/ac-servo/jog', { body: inRadPayload(payload) }).then(inDegView);

export const requestDynamixelJog = (payload) =>
  request('POST', '/api/motion-test/dynamixel/jog', { body: inRadPayload(payload) }).then(inDegView);

export const requestAcServoAction = (payload) =>
  request('POST', '/api/motion-test/ac-servo/action', { body: inRadPayload(payload) }).then(inDegView);

export const requestDynamixelAction = (payload) =>
  request('POST', '/api/motion-test/dynamixel/action', { body: inRadPayload(payload) }).then(inDegView);

/** MINAS 정비 · EEPROM 저장 · 앱솔루트 방식 · 다회전 클리어 · 수정 목록 15 + 34-3 */
export const requestDriveMaintenance = (payload) =>
  request('POST', '/api/motor-config/drive-maintenance', { body: payload });

export const requestAcServoControl = (payload) =>
  request('POST', '/api/motion-test/ac-servo/control', { body: payload });
