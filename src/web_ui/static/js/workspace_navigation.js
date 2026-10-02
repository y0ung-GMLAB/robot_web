export const WORKSPACE_GROUPS = Object.freeze({
  operations: Object.freeze([
    'monitoring', 'motion-trace', 'servo-errors', 'log', 'docs',
  ]),
  setup: Object.freeze(['config', 'project', 'system']),
  execution: Object.freeze(['motion-run', 'manual', 'coordination']),
});

const WORKSPACE_DEFAULTS = Object.freeze({
  operations: 'monitoring',
  setup: 'config',
  execution: 'motion-run',
});

const MOTION_WORKSPACE_TABS = Object.freeze({
  'motion-run': 'run',
});

// 모션축 설정은 모터 관리 화면으로 합쳐졌다 · 옛 경로·북마크는 그리로 보낸다
const LEGACY_ROUTE_ALIASES = Object.freeze({ 'motion-mapping': 'config' });

export const MOTION_WORKSPACE_DETAILS = Object.freeze({
  'motion-run': Object.freeze([
    '애니메이션 재생',
    '애니메이션을 고르고 재생 등록한 뒤 초기 위치 이동과 재생을 제어합니다',
  ]),
});

const WORKSPACE_ROUTES = new Set(Object.values(WORKSPACE_GROUPS).flat());
const PROJECT_SELECTION_WORKSPACE = 'system';

export function normalizeWorkspaceRoute(route) {
  const value = String(route || '').trim();
  const target = LEGACY_ROUTE_ALIASES[value] || value;
  return WORKSPACE_ROUTES.has(target) ? target : WORKSPACE_DEFAULTS.operations;
}

export function canChangeProjectInWorkspace(route) {
  return normalizeWorkspaceRoute(route) === PROJECT_SELECTION_WORKSPACE;
}

export function workspaceGroupFor(route) {
  const target = normalizeWorkspaceRoute(route);
  return Object.entries(WORKSPACE_GROUPS)
    .find(([, routes]) => routes.includes(target))?.[0] || 'operations';
}

export function workspacePanelFor(route) {
  const target = normalizeWorkspaceRoute(route);
  return MOTION_WORKSPACE_TABS[target] ? 'motion' : target;
}

export function motionTabForWorkspace(route) {
  return MOTION_WORKSPACE_TABS[normalizeWorkspaceRoute(route)] || '';
}

export function defaultWorkspaceForGroup(group) {
  return WORKSPACE_DEFAULTS[String(group || '')] || WORKSPACE_DEFAULTS.operations;
}

export function workspaceForLegacyNavigation(workspace, motionTab = '') {
  // `'project'`는 여기 없어야 한다 · 지금은 `WORKSPACE_GROUPS.setup`에 실재하는
  // **프로젝트 관리 탭**의 이름이다. 옛 이름으로 알아들으면 그 탭을 누를 때마다
  // `motion-run`으로 튕겨 나가고, `onManageFile`의 편집기 스크롤도 빗나간다.
  if (!['motion'].includes(workspace)) return normalizeWorkspaceRoute(workspace);
  // 파일 관리는 애니메이션 재생 화면으로 합쳐졌다 · 옛 'files' 요청도 그리로 보낸다
  const tab = String(motionTab || 'run') === 'files' ? 'run' : String(motionTab || 'run');
  // 모션축 설정은 모터 관리 화면에 산다 · 옛 ('motion', 'mapping') 요청 대비
  if (tab === 'mapping') return 'config';
  return Object.entries(MOTION_WORKSPACE_TABS)
    .find(([, value]) => value === tab)?.[0] || 'motion-run';
}

export function workspaceForProjectCategory(
  category,
  fallbackWorkspace = 'monitoring',
  motionTab = '',
) {
  const routes = {
    motor_axes: 'config',
    motion_axis_matching: 'config',
    motions: 'motion-run',
    logs: 'log',
  };
  return routes[String(category || '')]
    || workspaceForLegacyNavigation(fallbackWorkspace, motionTab);
}

export function createWorkspaceRouteState(initialRoute = WORKSPACE_DEFAULTS.operations) {
  let activeRoute = normalizeWorkspaceRoute(initialRoute);
  const lastByGroup = { ...WORKSPACE_DEFAULTS };
  lastByGroup[workspaceGroupFor(activeRoute)] = activeRoute;
  return {
    current: () => activeRoute,
    select: (route) => {
      activeRoute = normalizeWorkspaceRoute(route);
      lastByGroup[workspaceGroupFor(activeRoute)] = activeRoute;
      return activeRoute;
    },
    forGroup: (group) => (
      lastByGroup[String(group || '')] || defaultWorkspaceForGroup(group)
    ),
  };
}
