/** UI v2 · 네트워크·시간·그룹 · 메뉴 하나 (설계안 2026-10-09 · 2026-10-12 사용자 결정으로 그룹까지 이름에)
 *
 * Wi-Fi · 바꾸면 60초 안에 「유지」 · 안 누르면(원격이라 끊겨도) 원래 Wi-Fi 로 돌아온다 (수정 목록 81).
 * 시간대 · 이 PC 또는 매장 PC 전부 · 바꾼 PC 는 2초 뒤 프로그램을 다시 띄운다(재생 중이면 거절).
 * 그룹 설정 · 처음 한 번 · 켜고 끄기는 「매장 PC」 · 보이는 칸만 보낸다(§6-283) · 마스터 둘이면 묻는다(§6-70).
 */
import { h, dot } from '../dom.js';
import { api } from '../net.js';
import { confirmBox, toast } from '../dialog.js';
import * as act from '../actions.js';
import { localName } from '../model.js';

const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/;

const ui = {
  networks: null, scanning: false, pick: '', password: '', useStatic: false,
  address: '', gateway: '', dns: '', wifiBusy: false,
  zone: '', zoneBusy: false,
  group: null, groupBusy: false,
};
let pendingTimer = null;

export async function loadNetwork(state, changed) {
  const page = state.networkPage || (state.networkPage = { wifi: null, time: null, version: null, error: '' });
  const [wifi, time, version] = await Promise.allSettled([
    api('GET', '/api/system/wifi'),
    api('GET', '/api/system/time'),
    api('GET', '/api/system/version'),
  ]);
  if (wifi.status === 'fulfilled') page.wifi = wifi.value;
  if (time.status === 'fulfilled') page.time = time.value;
  if (version.status === 'fulfilled') page.version = version.value;
  page.error = wifi.status === 'rejected' ? `Wi-Fi 상태를 읽지 못함 · ${wifi.reason?.message || ''}` : '';
  if (!ui.zone && page.time?.clock?.timezone) ui.zone = page.time.clock.timezone;
  watchPending(state, changed);
  changed();
}

/** 확인 기다리는 동안 1초마다 · 남은 초가 화면에서 줄어든다 */
function watchPending(state, changed) {
  const pending = state.networkPage?.wifi?.pending;
  if (pending && !pendingTimer) {
    pendingTimer = setInterval(async () => {
      if (!location.hash.startsWith('#/network')) { clearInterval(pendingTimer); pendingTimer = null; return; }
      try {
        state.networkPage.wifi = await api('GET', '/api/system/wifi', { timeoutMs: 3000 });
        state.networkPage.wifiLost = false;
      } catch {
        // 연결이 바뀌어 이 화면이 끊겼을 수 있다
        state.networkPage.wifiLost = true;
      }
      if (!state.networkPage.wifi?.pending) { clearInterval(pendingTimer); pendingTimer = null; }
      changed();
    }, 1000);
  }
}

/* ---------- Wi-Fi ---------- */

export function wifiProblem({ ssid, password, security, useStatic, address, gateway }) {
  if (!ssid) return '연결할 Wi-Fi를 선택하세요';
  if (new TextEncoder().encode(ssid).length > 32) return 'Wi-Fi 이름이 너무 깁니다';
  const open = !security || security === '--';
  if (!open && !password) return '비밀번호를 입력하세요';
  if (password && (password.length < 8 || password.length > 63)) return '비밀번호는 8~63자여야 합니다';
  if (/802\.1x|enterprise|eap/i.test(security || '')) return '회사 인증(802.1X) Wi-Fi는 우분투 설정에서 연결하세요';
  if (useStatic) {
    if (!/^\d{1,3}(\.\d{1,3}){3}(\/\d{1,2})?$/.test(address)) return '고정 IP 주소 형식이 올바르지 않습니다 (예: 192.168.0.24 또는 192.168.0.24/24)';
    if (gateway && !/^\d{1,3}(\.\d{1,3}){3}$/.test(gateway)) return '게이트웨이 형식이 올바르지 않습니다 (예: 192.168.0.1)';
  }
  return '';
}

function wifiCard(state, changed) {
  const page = state.networkPage || {};
  const wifi = page.wifi;
  const pending = wifi?.pending;
  if (wifi && wifi.available === false) {
    return h('section', { class: 'card', 'aria-label': 'Wi-Fi' },
      h('div', { class: 'card-head' }, h('h2', { text: 'Wi-Fi' })),
      h('p', { class: 'muted', text: wifi.message || 'Wi-Fi 장치가 없습니다' }));
  }
  const networks = Array.isArray(ui.networks) ? ui.networks : [];
  const picked = networks.find((net) => net.ssid === ui.pick);
  const problem = wifiProblem({ ssid: ui.pick, password: ui.password, security: picked?.security, useStatic: ui.useStatic, address: ui.address, gateway: ui.gateway });
  const scan = async () => {
    ui.scanning = true;
    changed();
    try {
      const result = await api('POST', '/api/system/wifi/scan', { timeoutMs: 40000 });
      ui.networks = Array.isArray(result?.networks) ? result.networks : [];
      if (!ui.networks.some((net) => net.ssid === ui.pick)) ui.pick = '';
    } catch (error) {
      toast(error.message || String(error), 'bad');
    } finally {
      ui.scanning = false;
      changed();
    }
  };
  const connect = async () => {
    const ok = await confirmBox({
      title: 'Wi-Fi 변경',
      body: `「${ui.pick}」 Wi-Fi에 연결합니다.\n연결이 바뀌면 이 화면이 잠시 끊길 수 있습니다. 새 주소로 다시 접속해 60초 안에 「유지」를 누르세요.\n누르지 않으면(연결이 끊겨 누르지 못한 경우 포함) 60초 뒤 원래 Wi-Fi로 돌아갑니다.${ui.useStatic ? '\n\n고정 IP가 필요하면 공유기에서 「DHCP 예약」을 쓰는 것이 더 안전합니다(주소가 겹치지 않습니다).' : ''}`,
      confirmLabel: '전환', tone: 'warning',
    });
    if (!ok) return;
    ui.wifiBusy = true;
    changed();
    try {
      const body = {
        ssid: ui.pick, password: ui.password, security: picked?.security || '',
        static: ui.useStatic ? { address: ui.address.trim(), gateway: ui.gateway.trim(), dns: ui.dns.trim() } : null,
      };
      const result = await api('POST', '/api/system/wifi/connect', { body, timeoutMs: 60000 });
      toast(result?.message || 'Wi-Fi를 변경했습니다. 60초 안에 「유지」를 누르세요.', 'warn');
      ui.password = '';
    } catch (error) {
      toast(error.status === 0
        ? '응답이 없습니다. 연결이 바뀌어 이 화면이 끊겼을 수 있습니다. 60초 안에 새 주소로 접속해 「유지」를 누르세요.'
        : (error.message || String(error)), 'bad');
    } finally {
      ui.wifiBusy = false;
      await loadNetwork(state, changed);
    }
  };
  const decide = async (keep) => {
    ui.wifiBusy = true;
    changed();
    try {
      const result = await api('POST', `/api/system/wifi/${keep ? 'confirm' : 'rollback'}`, { timeoutMs: 60000 });
      toast(result?.message || (keep ? '이 Wi-Fi 연결을 유지합니다' : '원래 Wi-Fi로 되돌렸습니다'), 'ok');
    } catch (error) {
      toast(error.message || String(error), 'bad');
    } finally {
      ui.wifiBusy = false;
      await loadNetwork(state, changed);
    }
  };
  return h('section', { class: 'card', 'aria-label': 'Wi-Fi' },
    h('div', { class: 'card-head' }, h('h2', { text: 'Wi-Fi' }),
      h('button', { class: 'btn btn-mini', type: 'button', disabled: ui.scanning || Boolean(pending), onclick: scan }, ui.scanning ? '검색 중…' : '주변 Wi-Fi 검색')),
    wifi ? h('p', { class: 'mono small' },
      `${wifi.ssid || '연결 안 됨'}${wifi.signal != null ? ` · 신호 ${wifi.signal}` : ''}${wifi.address ? ` · ${wifi.address}` : ''} · `,
      h('span', { text: wifi.method === 'manual' ? '고정 IP' : '자동(DHCP)' }),
      wifi.powersave ? ` · 절전 ${wifi.powersave}` : '') : h('p', { class: 'muted', text: page.error || '불러오는 중…' }),
    pending ? h('div', { class: 'blocker' }, dot('warn'),
      h('span', { class: 'grow', text: page.wifiLost
        ? `응답이 없습니다. 연결이 바뀌어 끊겼을 수 있습니다. 새 주소로 접속해 「유지」를 누르세요. 누르지 않으면 원래 Wi-Fi로 돌아갑니다.`
        : `「${pending.ssid}」에 연결됨 · ${Math.max(0, Math.round(Number(pending.seconds_left ?? 0)))}초 안에 「유지」를 누르세요` }),
      h('button', { class: 'btn btn-primary', type: 'button', disabled: ui.wifiBusy, onclick: () => decide(true) }, '유지'),
      h('button', { class: 'btn', type: 'button', disabled: ui.wifiBusy, onclick: () => decide(false) }, '되돌리기')) : null,
    networks.length ? h('div', { class: 'field' },
      h('span', { class: 'field-label', text: '연결할 Wi-Fi' }),
      h('div', { class: 'choice-list', role: 'radiogroup', 'aria-label': '연결할 Wi-Fi' }, networks.map((net) => h('button', {
        class: 'choice', type: 'button', role: 'radio', 'aria-checked': String(ui.pick === net.ssid), disabled: Boolean(pending),
        onclick: () => { ui.pick = net.ssid; changed(); },
      }, `${net.ssid} · 신호 ${net.signal ?? '-'} · ${net.security && net.security !== '--' ? net.security : '암호 없음'}${net.in_use ? ' · 연결됨' : ''}`)))) : null,
    ui.pick ? [
      h('label', { class: 'field' }, h('span', { class: 'field-label', text: '비밀번호' }),
        h('input', { class: 'input', type: 'password', autocomplete: 'off', value: ui.password, oninput: (e) => { ui.password = e.target.value; }, onchange: () => changed() })),
      h('label', { class: 'inline' }, h('input', { type: 'checkbox', checked: ui.useStatic, onchange: (e) => { ui.useStatic = e.target.checked; changed(); } }), '고정 IP (선택)'),
      ui.useStatic ? h('div', { class: 'row' },
        h('label', { class: 'field grow' }, h('span', { class: 'field-label', text: '주소' }),
          h('input', { class: 'input mono', placeholder: '192.168.0.24/24', value: ui.address, oninput: (e) => { ui.address = e.target.value; }, onchange: () => changed() })),
        h('label', { class: 'field grow' }, h('span', { class: 'field-label', text: '게이트웨이' }),
          h('input', { class: 'input mono', placeholder: '192.168.0.1', value: ui.gateway, oninput: (e) => { ui.gateway = e.target.value; }, onchange: () => changed() })),
        h('label', { class: 'field grow' }, h('span', { class: 'field-label', text: 'DNS (비워 두면 게이트웨이 사용)' }),
          h('input', { class: 'input mono', value: ui.dns, oninput: (e) => { ui.dns = e.target.value; }, onchange: () => changed() }))) : null,
      problem ? h('p', { class: 'tone-text-warn small', text: problem }) : null,
      h('div', { class: 'row' }, h('button', { class: 'btn btn-warn', type: 'button', disabled: Boolean(problem) || ui.wifiBusy || Boolean(pending), onclick: connect }, '이 Wi-Fi에 연결…')),
    ] : null,
    h('p', { class: 'muted small', text: '원격으로 변경하다 연결이 끊겨도 60초 뒤 원래 Wi-Fi로 돌아갑니다. 비밀번호가 틀리면 바로 되돌립니다. 회사 인증(802.1X) Wi-Fi는 우분투 설정에서 연결하세요. 재생 중에는 변경할 수 없습니다.' }));
}

/* ---------- 시간대 ---------- */

function timeCard(state, changed) {
  const page = state.networkPage || {};
  const clock = page.time?.clock || state.sched?.clock || {};
  const zones = Array.isArray(page.time?.timezones) ? page.time.timezones : [];
  const browserZone = (() => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone; } catch { return ''; } })();
  const apply = async (all) => {
    const ok = await confirmBox({
      title: all ? '매장 PC 전체 시간대 변경' : `${localName(state)} 시간대 변경`,
      body: `${all ? '매장 PC 전체(스피커 포함)' : localName(state)}의 시간대를 「${ui.zone}」에 맞춥니다.\n스케줄은 바뀐 시각을 기준으로 동작합니다. 시간대를 바꾼 PC는 2초 뒤 프로그램을 다시 시작합니다(재생 중인 PC는 변경하지 않습니다).`,
      confirmLabel: '전환', tone: 'warning',
    });
    if (!ok) return;
    ui.zoneBusy = true;
    changed();
    try {
      const result = await api('POST', all ? '/api/system/timezone-all' : '/api/system/timezone', { body: { zone: ui.zone }, timeoutMs: all ? 90000 : 30000 });
      const failed = (result?.pcs || []).filter((pc) => pc.success === false);
      toast(`${result?.message || '변경했습니다'}${failed.length ? ` · 실패 ${failed.map((pc) => pc.display_name || pc.pc_id).join(', ')}` : ''}`, failed.length ? 'warn' : 'ok');
    } catch (error) {
      toast(error.message || String(error), 'bad');
    } finally {
      ui.zoneBusy = false;
      await loadNetwork(state, changed);
    }
  };
  return h('section', { class: 'card', 'aria-label': '시간대' },
    h('div', { class: 'card-head' }, h('h2', { text: '시간대' })),
    h('p', {}, h('strong', { text: clock.timezone || '-' }), ' · ', h('span', { class: 'mono', text: String(clock.local_time || '').slice(11, 19) || '-' }),
      clock.ntp_synced === true ? ' · 시계 동기화됨' : clock.ntp_synced === false ? h('span', { class: 'tone-text-warn', text: ' · 시계 동기화 안 됨' }) : null),
    browserZone && clock.timezone && browserZone !== clock.timezone
      ? h('p', { class: 'tone-text-warn small', text: `이 브라우저는 ${browserZone}, PC는 ${clock.timezone}입니다. 해외에 설치했다면 PC 시간대를 바꾸세요.` }) : null,
    h('div', { class: 'row' },
      zones.length
        ? h('select', { class: 'select grow', 'aria-label': '시간대', onchange: (e) => { ui.zone = e.target.value; changed(); } },
          zones.map((zone) => h('option', { value: zone, selected: zone === ui.zone }, zone)))
        : h('input', { class: 'input grow mono', value: ui.zone, 'aria-label': '시간대', oninput: (e) => { ui.zone = e.target.value; }, onchange: () => changed() }),
      h('button', { class: 'btn', type: 'button', disabled: ui.zoneBusy || !ui.zone, onclick: () => apply(false) }, `${localName(state)}에만 적용…`),
      h('button', { class: 'btn', type: 'button', disabled: ui.zoneBusy || !ui.zone, onclick: () => apply(true) }, '매장 PC 전체에 적용 (스피커 포함)…')));
}

/* ---------- 이 PC ---------- */

function pcCard(state) {
  const page = state.networkPage || {};
  const snap = state.snap || {};
  const version = page.version || {};
  const service = snap.service_management || {};
  const runtime = service.runtime || {};
  const access = snap.web_access || {};
  const rows = [
    ['이름', snap.system_info?.hostname || snap.coordination?.config?.pc_id || '-'],
    ['버전', version.hash ? `${version.branch || '-'} · ${version.hash}${version.message ? ` · ${version.message}` : ''}` : '-'],
    ['접속 주소', access.url || `${location.protocol}//${location.host}`],
    ['모터 프로그램', runtime.phase ? `${runtime.phase === 'ready' ? '정상' : runtime.phase}${runtime.message ? ` · ${runtime.message}` : ''}` : '-'],
  ];
  return h('section', { class: 'card', 'aria-label': 'PC 정보' },
    h('div', { class: 'card-head' }, h('h2', { text: 'PC 정보' })),
    h('dl', { class: 'facts' }, rows.map(([label, value]) => [h('dt', { text: label }), h('dd', { class: label === '이름' ? '' : 'mono', text: value })])),
    runtime.motor_manager_start_block_reason ? h('p', { class: 'tone-text-bad small', text: runtime.motor_manager_start_block_reason }) : null,
    h('div', { class: 'row' },
      h('button', { class: 'btn', type: 'button', onclick: act.restartProgram }, '프로그램 다시 시작…'),
      h('a', { class: 'btn', href: '#/tools' }, '터미널 ›')));
}

/* ---------- 그룹 설정 ---------- */

export function groupProblem(form) {
  if (!form) return '';
  if (form.group_id && !ID_PATTERN.test(form.group_id)) return '그룹 ID는 영문 또는 숫자로 시작해야 하며, 영문·숫자·_ . : - 만 쓸 수 있습니다';
  const domain = Number(form.dds_domain_id);
  if (!Number.isInteger(domain) || domain < 0 || domain > 101) return 'DDS Domain은 0~101 사이여야 합니다';
  if (form.display_name && form.display_name.length > 128) return '표시 이름은 128자까지 입력할 수 있습니다';
  if (form.is_master && !form.group_id) return '마스터는 그룹 ID가 있어야 합니다';
  return '';
}

function groupCard(state, changed) {
  const coord = state.snap?.coordination || {};
  const config = coord.config || {};
  // 상태가 오기 전에 초안을 만들면 빈 값이 굳는다 · 설정이 보일 때까지 기다린다
  if (!config.pc_id) {
    return h('section', { class: 'card', 'aria-label': '그룹 설정' },
      h('div', { class: 'card-head' }, h('h2', { text: '그룹 설정 (처음 한 번만)' })),
      h('p', { class: 'muted', text: coord.config_error || '연동 설정을 불러오는 중…' }));
  }
  if (!ui.group) {
    ui.group = { is_master: config.is_master === true, group_id: config.group_id || '', dds_domain_id: config.dds_domain_id ?? 21, display_name: config.display_name || '' };
  }
  const form = ui.group;
  const dirty = form.is_master !== (config.is_master === true) || form.group_id !== (config.group_id || '')
    || Number(form.dds_domain_id) !== Number(config.dds_domain_id ?? 21) || form.display_name !== (config.display_name || '');
  const problem = groupProblem(form);
  const save = async () => {
    const otherMaster = (coord.runtime?.peers || []).find((peer) => peer.is_master);
    if (form.is_master && config.is_master !== true && otherMaster) {
      const name = otherMaster.display_name || otherMaster.pc_id;
      const go = await confirmBox({
        title: '마스터가 이미 있습니다',
        body: `그룹에 이미 마스터가 있습니다: ${name}\n마스터가 둘이면 그룹 오류로 실행이 멈춥니다.\n계속하려면 먼저 ${name}의 마스터 설정을 해제하세요.`,
        confirmLabel: '그래도 저장', tone: 'danger',
      });
      if (!go) return;
    } else {
      const go = await confirmBox({ title: '그룹 설정 저장', body: '저장하면 연동 서비스가 한 번 다시 시작됩니다(몇 초). 그룹 재생 중에는 저장할 수 없습니다.', confirmLabel: '저장' });
      if (!go) return;
    }
    ui.groupBusy = true;
    changed();
    try {
      // 보이는 칸만 · 켜기(enabled)·참여(joined) 는 「매장 PC」 스위치가 정한다 (수정 목록 83)
      const body = { is_master: form.is_master, group_id: form.group_id.trim(), dds_domain_id: Number(form.dds_domain_id), display_name: form.display_name.trim() };
      const result = await api('PUT', '/api/coordination/settings', { body, timeoutMs: 20000 });
      toast(result?.message || '저장했습니다. 연동 서비스를 다시 시작합니다.', 'ok');
      ui.group = null;
    } catch (error) {
      toast(error.message || String(error), 'bad');
    } finally {
      ui.groupBusy = false;
      changed();
    }
  };
  const field = (key, label, attrs = {}) => h('label', { class: 'field' }, h('span', { class: 'field-label', text: label }),
    h('input', { class: 'input mono', value: String(form[key] ?? ''), ...attrs, oninput: (e) => { form[key] = e.target.value; }, onchange: () => changed() }));
  return h('section', { class: 'card', 'aria-label': '그룹 설정' },
    h('div', { class: 'card-head' }, h('h2', { text: '그룹 설정 (처음 한 번만)' })),
    h('p', { class: 'muted small', text: '그룹 ID와 Domain이 같은 PC끼리 묶입니다. 그룹 참여를 켜고 끄는 것은 「매장 PC」 화면에서 합니다.' }),
    h('div', { class: 'field' }, h('span', { class: 'field-label', text: '역할' }),
      h('div', { class: 'segmented', role: 'group', 'aria-label': '역할' },
        [[true, '마스터'], [false, '슬레이브']].map(([value, label]) => h('button', {
          class: 'seg', type: 'button', 'aria-pressed': String(form.is_master === value), onclick: () => { form.is_master = value; changed(); },
        }, label)))),
    h('div', { class: 'row form-row' },
      field('group_id', '그룹 ID', { placeholder: 'stage-a' }),
      field('dds_domain_id', 'DDS Domain', { type: 'number', min: '0', max: '101' }),
      field('display_name', '표시 이름 (비워 두면 PC ID 사용)'),
      h('label', { class: 'field' }, h('span', { class: 'field-label', text: 'PC ID (바꿀 수 없음)' }),
        h('input', { class: 'input mono', value: config.pc_id || '-', disabled: true }))),
    problem ? h('p', { class: 'tone-text-warn small', text: problem }) : null,
    h('div', { class: 'row end' },
      dirty ? h('button', { class: 'btn', type: 'button', onclick: () => { ui.group = null; changed(); } }, '되돌리기') : null,
      h('button', { class: 'btn btn-primary', type: 'button', disabled: Boolean(problem) || ui.groupBusy, onclick: save }, '저장 후 연동 재시작…')));
}

export function renderNetwork(state, { changed }) {
  return [
    h('div', { class: 'page-head' }, h('h1', { text: '네트워크·시간·그룹' })),
    h('div', { class: 'grid-2' }, wifiCard(state, changed), h('div', { class: 'stack' }, timeCard(state, changed), pcCard(state))),
    groupCard(state, changed),
  ];
}
