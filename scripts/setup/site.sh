#!/usr/bin/env bash
# 현장 준비 함수 모음 · 새 PC 를 「전원만 넣으면 뜨는 전시 PC」로 만든다 · 수정 목록 11 (2026-10-04)
#
# `scripts/install.sh --site` 가 source 해서 쓴다 · 손으로 하던 README 2~5단계가 여기 있다.
# 모든 함수는 **다시 실행해도 같은 결과**(멱등) · 이미 돼 있으면 건너뛴다.
#
#   SITE_DRY_RUN=1          실제로 바꾸지 않고 할 일만 찍는다
#   SITE_TIMEZONE=Asia/Seoul  시간대 · 없으면 터미널에서 묻고, 물을 수 없으면 현재 값 유지
#   SITE_ETHERCAT_NIC=enp2s0  EtherCAT 랜카드 지정 · 없으면 자동 감지(IP 없는 유선 포트)
#   SITE_ETHERCAT_NIC=none    EtherCAT 랜카드 안 씀 (직렬 서보만 쓰는 PC · 라즈베리파이) · 이미 묶였으면 풀어 줌
#   SITE_RESET_ETHERCAT=1   이미 적힌 /etc/ethercat.conf 를 다시 쓴다
#   SITE_ETHERLAB_VERSION   EtherLab 태그 (기본 1.6.9 · README 검증 버전)
#   SITE_SCAN=1             자가 점검에서 모터 스캔 1회 (최대 50초)
#
# EtherLab 은 SDO 사전 읽기 끄기 패치(patches/igh-1.6.9-sdo-dict-off.patch)를 넣어 빌드한다 · 수정 목록 139 ·
# 이미 깔린 PC 는 커널 모듈만 다시 빌드(make install 안 함 · PC 마다 깔린 자리가 다름)
#
# 시험용 덮어쓰기 · SITE_GDM_CONF · SITE_ETHERCAT_CONF · SITE_STATE_DIR · SITE_ETHERLAB_PATCH · SITE_SYS_MODULE_DIR
#
# 수작업으로 남는 것 · BIOS 「전원 복구 시 켜기」 1회 · 로봇 팩·모터 설정(웹)

SITE_DRY_RUN="${SITE_DRY_RUN:-0}"
SITE_GDM_CONF="${SITE_GDM_CONF:-/etc/gdm3/custom.conf}"
SITE_WIFI_POWERSAVE_CONF="${SITE_WIFI_POWERSAVE_CONF:-/etc/NetworkManager/conf.d/99-robot-web-wifi-powersave-off.conf}"
SITE_ETHERLAB_VERSION="${SITE_ETHERLAB_VERSION:-1.6.9}"
SITE_ETHERLAB_SRC="${SITE_ETHERLAB_SRC:-/usr/local/src/ethercat}"
SITE_ETHERLAB_REPO="${SITE_ETHERLAB_REPO:-https://gitlab.com/etherlab.org/ethercat.git}"
SITE_STATE_DIR="${SITE_STATE_DIR:-${HOME}/.cache/motion_site}"
SITE_SETUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -z "${SITE_ETHERCAT_CONF:-}" ]]; then
  if [[ -f /usr/local/etc/ethercat.conf && ! -f /etc/ethercat.conf ]]; then
    SITE_ETHERCAT_CONF=/usr/local/etc/ethercat.conf
  else
    SITE_ETHERCAT_CONF=/etc/ethercat.conf
  fi
fi

site_note() { echo "  · $*"; }
site_warn() { echo "  !! $*" >&2; }

# 실행 또는 (dry-run 이면) 출력만
site_run() {
  if [[ "${SITE_DRY_RUN}" == "1" ]]; then
    echo "  [dry-run] $*"
    return 0
  fi
  "$@"
}

# root 소유 파일 쓰기 · 내용은 stdin
site_write_root_file() {
  local path="$1" content
  content="$(cat)"
  if [[ "${SITE_DRY_RUN}" == "1" ]]; then
    echo "  [dry-run] ${path} ←"
    echo "${content}" | sed 's/^/      /'
    return 0
  fi
  printf '%s\n' "${content}" | sudo tee "${path}" >/dev/null
}

site_mark_reboot() {
  if [[ "${SITE_DRY_RUN}" == "1" ]]; then
    echo "  [dry-run] 재부팅 필요 표시 · $1"
    return 0
  fi
  mkdir -p "${SITE_STATE_DIR}"
  echo "$1" >> "${SITE_STATE_DIR}/needs_reboot"
}

site_needs_reboot() { [[ -s "${SITE_STATE_DIR}/needs_reboot" ]]; }
site_clear_reboot() { rm -f "${SITE_STATE_DIR}/needs_reboot"; }

# 터미널이 있으면 묻는다 · curl | bash 라도 /dev/tty 로 묻는다 · 없으면 기본값
site_ask() {
  local prompt="$1" default="$2" answer=""
  if [[ -r /dev/tty && -w /dev/tty ]]; then
    read -r -p "${prompt} [${default}] " answer < /dev/tty || true
  fi
  echo "${answer:-${default}}"
}

# ------------------------------------------------------------------ #
# 2단계 · 저절로 방해되는 것 끄기
# ------------------------------------------------------------------ #

# gsettings 는 사용자 세션 버스가 있어야 한다 · SSH 로 들어왔으면 임시 버스로 쓴다
site_gsettings() {
  if ! command -v gsettings >/dev/null 2>&1; then
    site_warn "gsettings 없음 · 화면 꺼짐·잠금 설정 건너뜀 (데스크톱 없는 PC)"
    return 0
  fi
  if [[ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
    site_run gsettings set "$@"
  elif command -v dbus-run-session >/dev/null 2>&1; then
    site_run dbus-run-session -- gsettings set "$@"
  else
    site_warn "세션 버스 없음 · gsettings set $* 건너뜀"
  fi
}

site_disable_interruptions() {
  echo "자동 업데이트 끄기"
  if systemctl list-unit-files unattended-upgrades.service >/dev/null 2>&1; then
    site_run sudo systemctl mask --now unattended-upgrades || true
  fi
  site_write_root_file /etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Unattended-Upgrade "0";
CONF
  if [[ -f /etc/update-manager/release-upgrades ]]; then
    site_run sudo sed -i 's/^Prompt=.*/Prompt=never/' /etc/update-manager/release-upgrades
  fi
  echo "화면 꺼짐·잠금·절전 끄기"
  site_gsettings org.gnome.desktop.session idle-delay 0
  site_gsettings org.gnome.desktop.screensaver lock-enabled false
  site_gsettings org.gnome.desktop.screensaver idle-activation-enabled false
  site_gsettings org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'
  echo "업데이트 알림 팝업 끄기"
  if [[ "${SITE_DRY_RUN}" == "1" ]]; then
    echo "  [dry-run] ~/.config/autostart/update-notifier.desktop (Hidden=true)"
  else
    mkdir -p "${HOME}/.config/autostart"
    printf '[Desktop Entry]\nType=Application\nName=Update Notifier\nHidden=true\nX-GNOME-Autostart-enabled=false\n' \
      > "${HOME}/.config/autostart/update-notifier.desktop"
  fi
  echo "WiFi 절전 끄기 (기본값 · 지금 있는 무선 연결)"
  # 우분투 기본 /etc/NetworkManager/conf.d/default-wifi-powersave-on.conf = 3(켬) · 그보다 뒤에 읽히는
  # 이름으로 2(끔) · 나중에 손으로 만든 연결도 끈 채로 · 수정 목록 112 차 (2026-10-12 floating4 켜져 있었음)
  if [[ -d /etc/NetworkManager/conf.d ]]; then
    site_write_root_file "${SITE_WIFI_POWERSAVE_CONF}" <<'CONF'
# robot_web · Wi-Fi 절전 끄기 (그룹 동기화 지연 · 수정 목록 112 차)
[connection]
wifi.powersave = 2
CONF
  fi
  site_wifi_powersave_off
}

# 지금 있는 무선 연결마다 절전 끔 · 관리자 권한 없이 됨(웹 Wi-Fi 권한 polkit) · 업데이트(--code-only)도 부른다 ·
# 바뀐 값은 그 연결이 다시 붙을 때(재부팅 · Wi-Fi 재연결) 적용된다 · 이미 2 면 건드리지 않는다
site_wifi_powersave_off() {
  command -v nmcli >/dev/null 2>&1 || return 0
  local line name type current
  while IFS= read -r line; do
    [[ -z "${line}" ]] && continue
    name="${line%:*}"; type="${line##*:}"
    [[ "${type}" == "802-11-wireless" ]] || continue
    current="$(nmcli -g 802-11-wireless.powersave connection show "${name}" 2>/dev/null || true)"
    if [[ "${current}" == "2" || "${current}" == "disable" ]]; then
      continue
    fi
    if site_run nmcli connection modify "${name}" 802-11-wireless.powersave 2; then
      site_note "WiFi 「${name}」 절전 OFF (다음 연결부터)"
    else
      site_warn "WiFi 「${name}」 절전을 끄지 못했습니다 · 웹 관리 권한(allow_web_admin.sh) 확인"
    fi
  done < <(nmcli -t -f NAME,TYPE connection show 2>/dev/null || true)
}

# ------------------------------------------------------------------ #
# 3단계 · 전원만 넣으면 프로그램이 뜨게 · 자동 로그인 + linger
# ------------------------------------------------------------------ #

# gdm3 custom.conf 에 자동 로그인 두 줄을 넣은 결과를 stdout 으로 · 시험 가능 · 멱등
#   $1 기존 파일 경로(없어도 됨) · $2 계정명
site_render_gdm_conf() {
  local path="$1" user="$2"
  local existing=""
  [[ -f "${path}" ]] && existing="$(cat "${path}")"
  # 옛 AutomaticLogin 줄은 지운다 · [daemon] 이 없으면 만든다
  printf '%s\n' "${existing}" | grep -v -E '^\s*AutomaticLogin(Enable)?\s*=' | awk -v user="${user}" '
    BEGIN { done = 0 }
    /^\[daemon\]/ { print; print "AutomaticLoginEnable=true"; print "AutomaticLogin=" user; done = 1; next }
    { print }
    END { if (!done) { if (NR > 0) print ""; print "[daemon]"; print "AutomaticLoginEnable=true"; print "AutomaticLogin=" user } }
  ' | sed -e :a -e '/^\n*$/{$d;N;ba' -e '}'
}

site_autologin() {
  local user="${1:-$(id -un)}"
  echo "로그아웃·화면 잠금에도 서비스 유지 (linger)"
  if loginctl show-user "${user}" 2>/dev/null | grep -q '^Linger=yes'; then
    site_note "이미 켜져 있음"
  else
    site_run sudo loginctl enable-linger "${user}"
  fi
  echo "자동 로그인 (${user})"
  if [[ -f "${SITE_GDM_CONF}" ]] && grep -q "^AutomaticLogin=${user}$" "${SITE_GDM_CONF}" \
     && grep -q '^AutomaticLoginEnable=true' "${SITE_GDM_CONF}"; then
    site_note "이미 켜져 있음 · ${SITE_GDM_CONF}"
    return 0
  fi
  if [[ ! -d "$(dirname "${SITE_GDM_CONF}")" && "${SITE_DRY_RUN}" != "1" ]]; then
    site_warn "gdm3 없음 (${SITE_GDM_CONF}) · 자동 로그인 건너뜀 · 데스크톱이 GNOME 이 아니면 손으로 설정"
    return 0
  fi
  site_render_gdm_conf "${SITE_GDM_CONF}" "${user}" | site_write_root_file "${SITE_GDM_CONF}"
  site_mark_reboot "autologin"
}

# ------------------------------------------------------------------ #
# 원격 · 애니데스크 · 마스터 PC 한 대에만 · 수정 목록 135 (사용자 결정 2026-10-14 · 회사 계정)
#   `scripts/setup/anydesk.sh` 가 부른다 · install.sh 는 부르지 않는다(마스터에서만 손으로)
# ------------------------------------------------------------------ #

SITE_ANYDESK_KEY="${SITE_ANYDESK_KEY:-/etc/apt/keyrings/keys.anydesk.com.asc}"
SITE_ANYDESK_LIST="${SITE_ANYDESK_LIST:-/etc/apt/sources.list.d/anydesk-stable.list}"

# gdm3 custom.conf 에 WaylandEnable=false 를 넣은 결과 · stdout · 멱등 · 시험 가능
#   애니데스크는 Wayland 화면을 조작하지 못한다(보기도 안 되는 경우) · 우분투 22.04 GNOME 기본이 Wayland
site_render_gdm_wayland_off() {
  local path="$1" existing=""
  [[ -f "${path}" ]] && existing="$(cat "${path}")"
  printf '%s\n' "${existing}" | grep -v -E '^\s*#?\s*WaylandEnable\s*=' | awk '
    BEGIN { done = 0 }
    /^\[daemon\]/ { print; print "WaylandEnable=false"; done = 1; next }
    { print }
    END { if (!done) { if (NR > 0) print ""; print "[daemon]"; print "WaylandEnable=false" } }
  ' | sed -e :a -e '/^\n*$/{$d;N;ba' -e '}'
}

site_wayland_off() {
  echo "Wayland 끄기 (애니데스크 원격 조작 · Xorg 로)"
  if [[ -f "${SITE_GDM_CONF}" ]] && grep -q '^WaylandEnable=false' "${SITE_GDM_CONF}"; then
    site_note "이미 꺼짐 · ${SITE_GDM_CONF}"
    return 0
  fi
  if [[ ! -d "$(dirname "${SITE_GDM_CONF}")" && "${SITE_DRY_RUN}" != "1" ]]; then
    site_warn "gdm3 없음 (${SITE_GDM_CONF}) · 데스크톱이 GNOME 이 아니면 손으로 Xorg 로"
    return 0
  fi
  site_render_gdm_wayland_off "${SITE_GDM_CONF}" | site_write_root_file "${SITE_GDM_CONF}"
  site_mark_reboot "wayland_off"
}

site_anydesk_install() {
  echo "애니데스크 설치 (공식 저장소)"
  if command -v anydesk >/dev/null 2>&1; then
    site_note "이미 설치됨 · $(anydesk --version 2>/dev/null || echo 버전 미상)"
  else
    site_run sudo install -m 0755 -d "$(dirname "${SITE_ANYDESK_KEY}")"
    site_run sudo curl -fsSL https://keys.anydesk.com/repos/DEB-GPG-KEY -o "${SITE_ANYDESK_KEY}"
    site_run sudo chmod a+r "${SITE_ANYDESK_KEY}"
    echo "deb [signed-by=${SITE_ANYDESK_KEY}] https://deb.anydesk.com all main" | site_write_root_file "${SITE_ANYDESK_LIST}"
    site_run sudo apt-get update
    site_run sudo apt-get install -y anydesk
  fi
  echo "애니데스크 · 부팅 때 자동 실행"
  if systemctl is-enabled --quiet anydesk 2>/dev/null && systemctl is-active --quiet anydesk 2>/dev/null; then
    site_note "이미 켜짐"
  else
    site_run sudo systemctl enable --now anydesk
  fi
}

# 1 = 설치 · 서비스 켜짐 · Wayland 꺼짐
site_anydesk_ok() {
  if command -v anydesk >/dev/null 2>&1 && systemctl is-active --quiet anydesk 2>/dev/null      && [[ -f "${SITE_GDM_CONF}" ]] && grep -q '^WaylandEnable=false' "${SITE_GDM_CONF}"; then
    echo 1
  else
    echo 0
  fi
}

# 웹에서 하는 관리 · 이 계정만 · 수정 목록 81 (Wi-Fi) · 79 (시간대) · 2026-10-08
#
# 웹 서비스는 systemd 사용자 서비스라 로그인 세션 밖이다 · polkit 이 「비활성」 으로 보고
# NetworkManager 설정 변경·시간대 변경을 막는다 · 이 계정에만 그 두 가지를 허용한다 ·
# 우분투 22.04 polkit 0.105 는 .pkla 를 읽는다
SITE_POLKIT_FILE="${SITE_POLKIT_FILE:-/etc/polkit-1/localauthority/50-local.d/50-robot-web.pkla}"

site_render_polkit() {
  local user="$1"
  cat <<PKLA
[robot_web wifi]
Identity=unix-user:${user}
Action=org.freedesktop.NetworkManager.*
ResultAny=yes
ResultInactive=yes
ResultActive=yes

[robot_web timezone]
Identity=unix-user:${user}
Action=org.freedesktop.timedate1.set-timezone
ResultAny=yes
ResultInactive=yes
ResultActive=yes
PKLA
}

# 우분투 24.04 polkit 124 는 .pkla 를 안 읽는다 · 같은 허용을 JS 규칙(rules.d)으로 · 2026-10-27 (jazzy)
SITE_POLKIT_RULES_FILE="${SITE_POLKIT_RULES_FILE:-/etc/polkit-1/rules.d/50-robot-web.rules}"

# pkla | rules · SITE_POLKIT_MODE 로 정할 수 있음(시험) · pkaction 이 없으면 OS 버전으로
site_polkit_mode() {
  if [[ -n "${SITE_POLKIT_MODE:-}" ]]; then
    echo "${SITE_POLKIT_MODE}"
    return 0
  fi
  local version
  version="$(pkaction --version 2>/dev/null | awk '{print $NF}')"
  if [[ -z "${version}" ]]; then
    version="$( (. /etc/os-release 2>/dev/null && echo "${VERSION_ID:-}") || true)"
    [[ "${version}" == 22.* || -z "${version}" ]] && echo pkla || echo rules
    return 0
  fi
  [[ "${version}" == 0.* ]] && echo pkla || echo rules
}

site_render_polkit_rules() {
  local user="$1"
  cat <<RULES
// robot_web · 웹에서 Wi-Fi · 시간대 바꾸기 · ${user} 만 (scripts/setup/site.sh)
polkit.addRule(function(action, subject) {
  if (subject.user == "${user}" &&
      (action.id.indexOf("org.freedesktop.NetworkManager.") == 0 ||
       action.id == "org.freedesktop.timedate1.set-timezone")) {
    return polkit.Result.YES;
  }
});
RULES
}

site_web_admin_permissions() {
  local user="${1:-$(id -un)}"
  echo "웹에서 Wi-Fi · 시간대 바꾸기 허용 (${user} 만)"
  if [[ "$(site_polkit_mode)" == "rules" ]]; then
    if [[ -f "${SITE_POLKIT_RULES_FILE}" ]] && grep -q "subject.user == \"${user}\"" "${SITE_POLKIT_RULES_FILE}"; then
      site_note "이미 허용됨 · ${SITE_POLKIT_RULES_FILE}"
      return 0
    fi
    site_run sudo mkdir -p "$(dirname "${SITE_POLKIT_RULES_FILE}")"
    site_render_polkit_rules "${user}" | site_write_root_file "${SITE_POLKIT_RULES_FILE}"
    return 0
  fi
  if [[ -f "${SITE_POLKIT_FILE}" ]] && grep -q "unix-user:${user}$" "${SITE_POLKIT_FILE}"; then
    site_note "이미 허용됨 · ${SITE_POLKIT_FILE}"
    return 0
  fi
  site_run sudo mkdir -p "$(dirname "${SITE_POLKIT_FILE}")"
  site_render_polkit "${user}" | site_write_root_file "${SITE_POLKIT_FILE}"
}

# ------------------------------------------------------------------ #
# 4단계 · 시간대
# ------------------------------------------------------------------ #

site_timezone() {
  local current target
  current="$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo UTC)"
  target="${SITE_TIMEZONE:-}"
  if [[ -z "${target}" ]]; then
    target="$(site_ask "시간대 (설치할 매장 현지 · 예 Asia/Seoul · Europe/Paris)" "${current}")"
  fi
  if [[ "${target}" == "${current}" ]]; then
    site_note "시간대 유지 · ${current}"
    return 0
  fi
  site_run sudo timedatectl set-timezone "${target}"
  site_note "시간대 · ${current} → ${target}"
}

# ------------------------------------------------------------------ #
# 방화벽 · 같은 망만 허용 (ufw 가 켜져 있을 때만)
# ------------------------------------------------------------------ #

# `ip -o -4 addr show scope global` 출력에서 네트워크(CIDR) 목록 · 시험 가능
site_local_networks_from() {
  local text="$1"
  printf '%s\n' "${text}" | awk '{ for (i = 1; i <= NF; i++) if ($i == "inet") print $(i + 1) }' | while IFS= read -r cidr; do
    [[ -z "${cidr}" ]] && continue
    python3 - "${cidr}" <<'PY'
import ipaddress, sys
print(ipaddress.ip_interface(sys.argv[1]).network)
PY
  done | sort -u
}

site_firewall() {
  if ! command -v ufw >/dev/null 2>&1; then
    site_note "ufw 없음 · 건너뜀"
    return 0
  fi
  if ! sudo ufw status 2>/dev/null | grep -q '^Status: active'; then
    site_note "ufw 꺼져 있음 · 건너뜀 (켤 때는 같은 망 허용을 함께)"
    return 0
  fi
  local net
  while IFS= read -r net; do
    [[ -z "${net}" ]] && continue
    site_run sudo ufw allow from "${net}" || true
    site_note "같은 망 허용 · ${net}"
  done < <(site_local_networks_from "$(ip -o -4 addr show scope global 2>/dev/null || true)")
}

# ------------------------------------------------------------------ #
# 5단계 · EtherCAT (EtherLab/IgH) · 빌드에 **항상** 필요 · 모터에 쓰는 건 랜카드가 있을 때
# ------------------------------------------------------------------ #

# IgH 1.6.9 패치 · SDO 사전 자동 읽기 끄기(모듈 파라미터 sdo_dict · 기본 0) · 수정 목록 139 (2026-10-14)
#   마스터가 재스캔마다 SDO 사전을 저절로 읽어 우리 `ethercat upload/download` 와 메일박스를 다투다
#   드라이브 메일박스가 멈췄다 · 우리는 사전을 안 쓴다(모든 호출이 `-t`) · 자세히 docs/수정_139_IgH_패치.md
#   재빌드 서비스(/usr/local/sbin 에서 돈다 · 작업공간 경로 모름)는 고정 자리에 둔 사본을 읽는다
SITE_ETHERLAB_PATCH="${SITE_ETHERLAB_PATCH:-${SITE_SETUP_DIR}/patches/igh-1.6.9-sdo-dict-off.patch}"
SITE_ETHERLAB_PATCH_INSTALLED="${SITE_ETHERLAB_PATCH_INSTALLED:-/usr/local/share/robot_web/igh-sdo-dict-off.patch}"
SITE_ETHERLAB_CONFIGURE="--disable-8139too --enable-generic=yes"

# 깔린 IgH CLI 자리 · stdout · 없으면 빈 줄 · 자리는 PC 마다 다르다(install.sh ethercat_search_roots 주석 ·
# 피시1·2 /opt/etherlab · 피시3 /usr/local/etherlab · floating4 /usr/local 손 빌드)
#   있으면 「이미 깔림」 → 모듈만 다시 빌드 · 옛 판정(site_etherlab_ready)은 CLI 가 PATH 에 없거나 헤더가
#   /usr/local/etherlab 같은 자리에 있으면 「없음」 으로 보고 /usr/local 에 한 벌 더 깔 수 있었다 · 139
site_etherlab_cli() {
  local root
  if command -v ethercat >/dev/null 2>&1; then
    command -v ethercat
    return 0
  fi
  for root in /opt/etherlab /usr/local/etherlab /usr/local /usr /opt/ethercat; do
    if [[ -x "${root}/bin/ethercat" ]]; then
      echo "${root}/bin/ethercat"
      return 0
    fi
  done
}

# 깔린(지금 올라간 것이 아니라 modprobe 가 고를) ec_master 에 sdo_dict 파라미터가 있나 · 139
# pipefail 아래 `modinfo | grep -q` 는 grep 이 먼저 끝나면 실패로 보일 수 있어 받아 두고 본다
site_etherlab_patched() {
  local params
  params="$(modinfo -p ec_master 2>/dev/null || true)"
  grep -q '^sdo_dict:' <<<"${params}"
}

# 패치 넣기 · 멱등 · 이미 들어갔으면 그대로 · 안 맞으면(IgH 버전이 바뀜) 멈춘다 · $1 소스 폴더
site_etherlab_apply_patch() {
  local src="$1"
  if [[ "${SITE_DRY_RUN}" == "1" ]]; then
    echo "  [dry-run] sudo git -C ${src} apply ${SITE_ETHERLAB_PATCH} (이미 들어갔으면 건너뜀 · SDO 사전 읽기 끄기 · 수정 목록 139)"
    return 0
  fi
  if sudo git -C "${src}" apply --reverse --check "${SITE_ETHERLAB_PATCH}" 2>/dev/null; then
    site_note "IgH 패치 이미 들어감 · $(basename "${SITE_ETHERLAB_PATCH}")"
    return 0
  fi
  if ! sudo git -C "${src}" apply --check "${SITE_ETHERLAB_PATCH}"; then
    site_warn "IgH 패치가 소스(${src})에 안 맞음 · IgH 버전(${SITE_ETHERLAB_VERSION}) 확인 · 패치는 1.6.9 용 · 수정 목록 139 · 설치를 멈춥니다"
    return 1
  fi
  sudo git -C "${src}" apply "${SITE_ETHERLAB_PATCH}" || return 1
  site_note "IgH 패치 적용 · $(basename "${SITE_ETHERLAB_PATCH}") (SDO 사전 자동 읽기 끔 · sdo_dict=0)"
}

# 돌고 있는(또는 부팅 때 돌) ethercat.service 가 읽는 ethercat.conf · stdout · 못 찾으면 빈 줄
#   ExecStart 의 `ethercatctl -c 설정` → ethercatctl 안의 ETHERCAT_CONFIG= (configure 의 sysconfdir) →
#   ethercatctl 옆 ../etc → 아는 자리들
site_ethercat_active_conf() {
  local exec_line ctl conf
  exec_line="$({ systemctl cat ethercat 2>/dev/null || true; } | sed -n 's/^ExecStart=[-@!+:]*//p' | tail -1)"
  if [[ -n "${exec_line}" ]]; then
    conf="$(printf '%s\n' "${exec_line}" | awk '{ for (i = 1; i < NF; i++) if ($i == "-c") { print $(i + 1); exit } }')"
    if [[ -n "${conf}" && -f "${conf}" ]]; then
      echo "${conf}"
      return 0
    fi
    ctl="${exec_line%% *}"
    if [[ -f "${ctl}" ]]; then
      conf="$(sed -n 's/^[[:space:]]*ETHERCAT_CONFIG="\{0,1\}\([^"$[:space:]]*\)"\{0,1\}[[:space:]]*$/\1/p' "${ctl}" | tail -1)"
      if [[ -n "${conf}" && -f "${conf}" ]]; then
        echo "${conf}"
        return 0
      fi
      conf="$(dirname "$(dirname "${ctl}")")/etc/ethercat.conf"
      if [[ -f "${conf}" ]]; then
        echo "${conf}"
        return 0
      fi
    fi
  fi
  for conf in "${SITE_ETHERCAT_CONF}" /opt/etherlab/etc/ethercat.conf /usr/local/etherlab/etc/ethercat.conf /etc/ethercat.conf; do
    if [[ -f "${conf}" ]]; then
      echo "${conf}"
      return 0
    fi
  done
}

# ethercat.conf 의 DEVICE_MODULES 값 · stdout · 따옴표·뒤 주석 뺌 · 실행(source)하지 않고 읽기만
site_ethercat_device_modules_from() {
  sed -n 's/^[[:space:]]*DEVICE_MODULES=//p' "$1" 2>/dev/null | tail -1 \
    | sed -e 's/[[:space:]]#.*$//' -e 's/^"\(.*\)"[[:space:]]*$/\1/' -e "s/^'\(.*\)'[[:space:]]*\$/\1/" \
    | awk '{ $1 = $1; print }'
}

# generic 말고 다른 랜카드 전용 모듈(r8169 · igb …)이 있으면 1 · 비어 있으면 0
#   모듈만 다시 빌드할 때 우리는 generic 만 만든다 · 옛 전용 모듈은 새 ec_master 와 짝이 안 맞는다
site_ethercat_generic_only() {
  local module
  for module in $1; do
    [[ "${module}" == "generic" ]] || return 1
  done
  return 0
}

# 이미 깔린 PC · 커널 모듈만 다시 빌드 (CLI·라이브러리·ethercatctl·서비스는 그대로) · 139
#   `make install` 을 하면 PC 마다 다른 자리(/opt/etherlab · /usr/local/etherlab)에 깔린 것과 별개로
#   /usr/local 에 CLI·라이브러리·ethercatctl·서비스가 한 벌 더 생긴다 · 그래서 모듈만 바꾼다
#   같은 1.6.9 라 ioctl 버전이 같다 · 버전이 다르면 모듈만 바꿨을 때 CLI·라이브러리와 어긋나므로 멈춘다
site_etherlab_build_modules() {
  local cli version conf modules before after
  cli="$(site_etherlab_cli)"
  version="$("${cli:-ethercat}" version 2>/dev/null | head -1 || true)"
  if ! grep -Eq "master ${SITE_ETHERLAB_VERSION//./\\.}([^0-9.]|$)" <<<"${version}"; then
    site_warn "깔린 EtherLab(${cli:-?} · ${version:-버전 미상})이 ${SITE_ETHERLAB_VERSION} 이 아님 · 모듈만 바꾸면 CLI·라이브러리와 어긋남 · 손으로 · 수정 목록 139 · 설치를 멈춥니다"
    return 1
  fi
  conf="$(site_ethercat_active_conf)"
  if [[ -n "${conf}" ]]; then
    modules="$(site_ethercat_device_modules_from "${conf}")"
    if ! site_ethercat_generic_only "${modules}"; then
      site_warn "EtherCAT 설정(${conf}) DEVICE_MODULES=\"${modules}\" · generic 이 아님 · 모듈만 다시 빌드하면 그 랜카드 전용 모듈이 새 ec_master 와 안 맞음 · 손으로 · 수정 목록 139 · 설치를 멈춥니다"
      return 1
    fi
    site_note "EtherCAT 설정 · ${conf} · DEVICE_MODULES=\"${modules}\""
  else
    site_note "EtherCAT 설정 파일 없음 · 랜카드 설정은 다음 단계에서 (generic)"
  fi
  before="$(modinfo -n ec_master 2>/dev/null || true)"
  site_run sudo apt install -y autoconf automake libtool pkg-config build-essential git gcc-12 g++-12 ethtool "linux-headers-$(uname -r)" || return 1
  if [[ ! -d "${SITE_ETHERLAB_SRC}/.git" ]]; then
    site_run sudo git clone --depth 1 --branch "${SITE_ETHERLAB_VERSION}" "${SITE_ETHERLAB_REPO}" "${SITE_ETHERLAB_SRC}" || return 1
  fi
  site_etherlab_apply_patch "${SITE_ETHERLAB_SRC}" || return 1
  if [[ "${SITE_DRY_RUN}" == "1" ]]; then
    echo "  [dry-run] (cd ${SITE_ETHERLAB_SRC} && ./bootstrap && ./configure ${SITE_ETHERLAB_CONFIGURE} && make modules && sudo make modules_install && sudo depmod) · 모듈만 · make install 안 함"
    return 0
  fi
  # `( set -e … ) || …` 안에서는 set -e 가 꺼진다 · && 로 잇는다
  # shellcheck disable=SC2086
  (
    cd "${SITE_ETHERLAB_SRC}" \
      && sudo ./bootstrap \
      && sudo ./configure ${SITE_ETHERLAB_CONFIGURE} \
      && sudo make -j"$(nproc)" modules \
      && sudo make modules_install \
      && sudo depmod
  ) || { site_warn "EtherLab 모듈 빌드 실패 · ${SITE_ETHERLAB_SRC} · 수정 목록 139"; return 1; }
  site_etherlab_verify_built
  after="$(modinfo -n ec_master 2>/dev/null || true)"
  if [[ -n "${before}" && "${before}" != "${after}" ]]; then
    site_warn "ec_master 자리가 바뀜 · 전 ${before} → 지금 ${after} · 옛 파일은 지우지 않음"
  fi
}

# 새로 깐 모듈(modprobe 가 고를 파일)에 sdo_dict 가 있나 · 없으면 경고만
site_etherlab_verify_built() {
  if [[ "${SITE_DRY_RUN}" == "1" ]]; then
    echo "  [dry-run] modinfo -p ec_master | grep sdo_dict (새 모듈 확인)"
    return 0
  fi
  if site_etherlab_patched; then
    site_note "새 ec_master · $(modinfo -n ec_master 2>/dev/null) · sdo_dict 있음"
  else
    site_warn "새로 깐 ec_master 에 sdo_dict 가 없음 · $(modinfo -n ec_master 2>/dev/null || echo 모듈 없음) · 다른 자리(updates/ 등)의 옛 모듈이 먼저 잡히는지 확인 · 수정 목록 139"
  fi
}

# 깔기만 하면 지금 올라가 있는 모듈은 그대로 · 옛 모듈이 올라가 있으면 사람이 할 일을 찍는다(설치 중에 모터를 멈추지 않는다)
#   처음 설치(아직 안 올라감)면 다음 단계 `systemctl enable --now ethercat` 이 새 모듈을 올린다
site_etherlab_reload_hint() {
  [[ "$(site_sdo_dict_value)" == "없음" ]] || return 0
  site_warn "지금 올라가 있는 EtherCAT 모듈은 아직 옛 것(SDO 사전 읽기 켜짐) · 모터 정지 확인(재생·조그 없음 · 서보 오프) 뒤 순서대로 · 수정 목록 139"
  echo "       systemctl --user stop motion-motor.service"
  echo "       sudo systemctl restart ethercat"
  echo "       systemctl --user start motion-motor.service"
  echo "     확인 · cat /sys/module/ec_master/parameters/sdo_dict → 0"
}

site_ethercat_install() {
  local cli
  cli="$(site_etherlab_cli)"
  if [[ -n "${cli}" ]] && site_etherlab_patched; then
    site_note "EtherLab 이미 설치됨 · $("${cli}" version 2>/dev/null | head -1) · SDO 사전 읽기 끄기 패치 들어감"
  elif [[ -n "${cli}" ]]; then
    echo "EtherLab 이미 설치됨(${cli}) · 커널 모듈만 다시 빌드 (SDO 사전 읽기 끄기 패치 · 수정 목록 139 · 몇 분)"
    site_etherlab_build_modules || return 1
  else
    echo "EtherLab ${SITE_ETHERLAB_VERSION} 설치 (범용 드라이버 · 소스 빌드 · SDO 사전 읽기 끄기 패치 · 몇 분)"
    site_run sudo apt install -y autoconf automake libtool pkg-config build-essential git gcc-12 g++-12 ethtool "linux-headers-$(uname -r)" || return 1
    if [[ ! -d "${SITE_ETHERLAB_SRC}/.git" ]]; then
      site_run sudo git clone --depth 1 --branch "${SITE_ETHERLAB_VERSION}" "${SITE_ETHERLAB_REPO}" "${SITE_ETHERLAB_SRC}" || return 1
    fi
    site_etherlab_apply_patch "${SITE_ETHERLAB_SRC}" || return 1
    if [[ "${SITE_DRY_RUN}" == "1" ]]; then
      echo "  [dry-run] (cd ${SITE_ETHERLAB_SRC} && ./bootstrap && ./configure ${SITE_ETHERLAB_CONFIGURE} && make all modules && sudo make modules_install install && sudo depmod && sudo ldconfig)"
    else
      # shellcheck disable=SC2086
      (
        cd "${SITE_ETHERLAB_SRC}" \
          && sudo ./bootstrap \
          && sudo ./configure ${SITE_ETHERLAB_CONFIGURE} \
          && sudo make -j"$(nproc)" all modules \
          && sudo make modules_install install \
          && sudo depmod \
          && sudo ldconfig
      ) || { site_warn "EtherLab 빌드·설치 실패 · ${SITE_ETHERLAB_SRC}"; return 1; }
    fi
    site_etherlab_verify_built
  fi
  echo "커널 업데이트 뒤 자동 재빌드 (부팅 때 모듈이 없거나 패치가 빠졌으면 다시 만든다)"
  site_run sudo install -D -m 0644 "${SITE_ETHERLAB_PATCH}" "${SITE_ETHERLAB_PATCH_INSTALLED}"
  site_run sudo install -m 0755 "${SITE_SETUP_DIR}/ethercat-rebuild.sh" /usr/local/sbin/ethercat-rebuild
  site_run sudo install -m 0644 "${SITE_SETUP_DIR}/ethercat-rebuild.service" /etc/systemd/system/ethercat-rebuild.service
  site_run sudo systemctl daemon-reload
  site_run sudo systemctl enable ethercat-rebuild.service
  echo "일반 계정이 /dev/EtherCAT0 을 쓰게 (udev)"
  site_write_root_file /etc/udev/rules.d/99-ethercat.rules <<'RULE'
KERNEL=="EtherCAT[0-9]*", MODE="0666"
RULE
  site_run sudo udevadm control --reload-rules || true
}

# 모터용 랜카드 고르기 · 시험 가능 · 출력 "이름 MAC" 또는 빈 줄
#   $1 `ip -br link` 출력 · $2 `ip -o -4 addr show scope global` 출력 · $3 기본 경로 장치 이름
#   규칙 · 유선(en*/eth*)만 · IP 가 있는 포트(사내망)와 기본 경로 포트는 제외 ·
#          남은 것 중 링크 UP 우선 · 하나로 못 좁히면 빈 줄(묻는다)
site_pick_ethercat_nic_from() {
  local links="$1" addrs="$2" default_dev="${3:-}"
  local with_ip
  with_ip="$(printf '%s\n' "${addrs}" | awk '{ print $2 }' | sort -u)"
  printf '%s\n' "${links}" | awk -v withip="${with_ip}" -v defdev="${default_dev}" '
    BEGIN { n = split(withip, arr, "\n"); for (i = 1; i <= n; i++) if (arr[i] != "") used[arr[i]] = 1; if (defdev != "") used[defdev] = 1 }
    {
      name = $1; state = $2; mac = $3
      sub(/@.*/, "", name)
      if (name !~ /^(en|eth)/) next
      if (name in used) next
      # `{2}` `{5}` 반복 표기는 우분투 22.04 기본 mawk 1.3.4-20200120 이 못 읽는다 · 풀어 쓴다 · 수정 목록 63
      if (mac !~ /^[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]:[0-9a-f][0-9a-f]$/) next
      total++
      if (state == "UP") { up++; upname = name; upmac = mac }
      anyname = name; anymac = mac
    }
    END {
      if (up == 1) { print upname, upmac; exit }
      if (total == 1) { print anyname, anymac; exit }
      print ""
    }'
}

# EtherCAT 랜카드 안 씀 · SITE_ETHERCAT_NIC=none · 2026-10-27
#   직렬 서보만 쓰는 PC(라즈베리파이 등)는 하나뿐인 유선 포트를 일반 랜으로 쓴다 · 자동 감지가 그 포트를
#   EtherCAT 에 묶지 않게 · 이미 묶였으면 서비스를 끄고 랜카드 자리를 비운다(EtherLab 자체는 그대로 · 빌드에 필요)
#   「안 씀」 은 설정 파일 표시(SITE_ETHERCAT_NONE_MARK)로 기억 · 나중에 설치를 다시 돌려도 자동 감지로 묶지 않음
SITE_ETHERCAT_NONE_MARK="# robot_web-ethercat: none"
site_ethercat_release() {
  if [[ -f "${SITE_ETHERCAT_CONF}" ]] && grep -q '^MASTER0_DEVICE="[^"]\+"' "${SITE_ETHERCAT_CONF}"; then
    echo "EtherCAT 랜카드 풀기 · $(grep '^MASTER0_DEVICE' "${SITE_ETHERCAT_CONF}")"
  fi
  site_run sudo systemctl disable --now ethercat || true
  site_write_root_file "${SITE_ETHERCAT_CONF}" <<CONF
# robot_web 설치 스크립트가 적음 · $(date +%F) · EtherCAT 랜카드 안 씀 (SITE_ETHERCAT_NIC=none)
${SITE_ETHERCAT_NONE_MARK}
MASTER0_DEVICE=""
DEVICE_MODULES="generic"
CONF
  site_note "EtherCAT 랜카드 안 씀 · 직렬 서보만 · 나중에 쓰려면 bash scripts/ethercat_nic.sh <랜카드 이름>"
}

site_ethercat_configure() {
  if [[ "${SITE_ETHERCAT_NIC:-}" == "none" ]]; then
    site_ethercat_release
    return 0
  fi
  if [[ -z "${SITE_ETHERCAT_NIC:-}" && "${SITE_RESET_ETHERCAT:-0}" != "1" && -f "${SITE_ETHERCAT_CONF}" ]] \
     && grep -qxF "${SITE_ETHERCAT_NONE_MARK}" "${SITE_ETHERCAT_CONF}"; then
    site_note "EtherCAT 랜카드 안 씀 유지 (${SITE_ETHERCAT_CONF}) · 쓰려면 bash scripts/ethercat_nic.sh <랜카드 이름>"
    return 0
  fi
  if [[ -f "${SITE_ETHERCAT_CONF}" ]] && grep -q '^MASTER0_DEVICE="[^"]\+"' "${SITE_ETHERCAT_CONF}" \
     && [[ "${SITE_RESET_ETHERCAT:-0}" != "1" ]]; then
    site_note "EtherCAT 설정 유지 · $(grep '^MASTER0_DEVICE' "${SITE_ETHERCAT_CONF}") (${SITE_ETHERCAT_CONF}) · 다시 쓰려면 SITE_RESET_ETHERCAT=1"
  else
    local nic="${SITE_ETHERCAT_NIC:-}" mac="" picked
    if [[ -z "${nic}" ]]; then
      picked="$(site_pick_ethercat_nic_from "$(ip -br link 2>/dev/null || true)" "$(ip -o -4 addr show scope global 2>/dev/null || true)" "$(ip route show default 2>/dev/null | awk '{ for (i = 1; i <= NF; i++) if ($i == "dev") print $(i + 1); exit }')")"
      nic="${picked%% *}"
    fi
    if [[ -z "${nic}" ]]; then
      local candidates
      candidates="$({ ip -br link 2>/dev/null || true; } | awk '$1 ~ /^(en|eth)/ { sub(/@.*/, "", $1); print $1 }' | tr '\n' ' ')"
      nic="$(site_ask "모터(EtherCAT) 랜카드 이름 (후보: ${candidates:-없음} · 다이나믹셀만 쓰면 Enter)" "")"
    fi
    if [[ -z "${nic}" ]]; then
      site_note "EtherCAT 랜카드 없음 · 설정 건너뜀 (다이나믹셀 전용 · 나중에 SITE_ETHERCAT_NIC=이름 으로 다시 실행)"
      return 0
    fi
    mac="$({ ip -br link show "${nic}" 2>/dev/null || true; } | awk '{ print $3 }')"
    if [[ -z "${mac}" && "${SITE_DRY_RUN}" != "1" ]]; then
      site_warn "랜카드 ${nic} 의 MAC 을 읽지 못함 · 설정 건너뜀"
      return 0
    fi
    echo "EtherCAT 랜카드 · ${nic} (${mac:-MAC 미상}) · 이름이 바뀌어도 MAC 으로 잡는다"
    site_write_root_file "${SITE_ETHERCAT_CONF}" <<CONF
# robot_web 설치 스크립트가 적음 · $(date +%F) · 모터 전용 랜카드 ${nic}
MASTER0_DEVICE="${mac}"
DEVICE_MODULES="generic"
UPDOWN_INTERFACES="${nic}"
CONF
  fi
  site_run sudo systemctl enable --now ethercat || site_warn "ethercat 서비스 시작 실패 · 모터 전원·랜선 확인 후 sudo systemctl restart ethercat"
}

# ------------------------------------------------------------------ #
# 재부팅 뒤 이어가기 · 자동 로그인 → 사용자 systemd 가 install.sh --resume 를 한 번 돌린다
# ------------------------------------------------------------------ #

site_schedule_resume() {
  local workspace="$1" unit_dir="${HOME}/.config/systemd/user"
  if [[ "${SITE_DRY_RUN}" == "1" ]]; then
    echo "  [dry-run] ${unit_dir}/motion-site-resume.service (재부팅 뒤 install.sh --resume 1회)"
    return 0
  fi
  mkdir -p "${unit_dir}" "${workspace}/log/site_setup"
  sed -e "s|@WORKSPACE@|${workspace//&/\\&}|g" "${SITE_SETUP_DIR}/motion-site-resume.service.in" > "${unit_dir}/motion-site-resume.service"
  systemctl --user daemon-reload
  systemctl --user enable motion-site-resume.service
}

site_cancel_resume() {
  systemctl --user disable motion-site-resume.service 2>/dev/null || true
  rm -f "${HOME}/.config/systemd/user/motion-site-resume.service"
  systemctl --user daemon-reload 2>/dev/null || true
}

# ------------------------------------------------------------------ #
# 자가 점검 · 설치 끝에 한눈에
# ------------------------------------------------------------------ #

# Wi-Fi 로 붙어 있으면 절전이 꺼져 있나 · 1 꺼짐(또는 Wi-Fi 아님) · 0 켜짐 · 112 차
site_wifi_powersave_ok() {
  command -v nmcli >/dev/null 2>&1 || { echo 1; return; }
  local name value
  name="$(nmcli -t -f NAME,TYPE connection show --active 2>/dev/null | awk -F: '$2 == "802-11-wireless" { print $1; exit }')"
  [[ -z "${name}" ]] && { echo 1; return; }
  value="$(nmcli -g 802-11-wireless.powersave connection show "${name}" 2>/dev/null || true)"
  if [[ "${value}" == "2" || "${value}" == "disable" ]]; then echo 1; else echo 0; fi
}

# 자동 업데이트가 꺼져 있나 · 1 꺼짐 · 0 켜짐 · 수정 목록 112 사
# masked 면 꺼짐 · disabled 라도 apt 주기 설정(20auto-upgrades)이 "0" 이면 돌지 않으니 꺼짐으로 본다 ·
# floating4 는 disabled 였다(설치 때 mask 대신 끔) · 서비스가 없는 PC 도 꺼짐
auto_upgrades_off() {
  local state
  state="$(systemctl is-enabled unattended-upgrades 2>/dev/null || true)"
  case "${state}" in
    masked|"") echo 1; return ;;
  esac
  if [[ "${state}" != enabled* ]] && grep -qs 'Unattended-Upgrade "0"' /etc/apt/apt.conf.d/20auto-upgrades; then
    echo 1
  else
    echo 0
  fi
}

# 올라가 있는 ec_master 의 sdo_dict · stdout · 0 이면 SDO 사전 자동 읽기 꺼짐 · 수정 목록 139
#   「없음」 = 패치 안 된 옛 모듈 · 「안 올라감」 = 모듈이 아직 안 올라감
site_sdo_dict_value() {
  local sys="${SITE_SYS_MODULE_DIR:-/sys/module}/ec_master"
  if [[ ! -d "${sys}" ]]; then
    echo 안 올라감
  elif [[ -r "${sys}/parameters/sdo_dict" ]]; then
    tr -d '[:space:]' < "${sys}/parameters/sdo_dict"
  else
    echo 없음
  fi
}

site_sdo_dict_detail() {
  case "$1" in
    0) echo "sdo_dict=0" ;;
    없음) echo "패치 안 된 옛 모듈이 올라가 있음 · 모터 서비스 멈춤 → sudo systemctl restart ethercat → 모터 서비스 시작 · 수정 목록 139" ;;
    "안 올라감") echo "ec_master 안 올라감 · sudo systemctl status ethercat" ;;
    *) echo "sdo_dict=$1 · 켜져 있음 · echo 0 | sudo tee /sys/module/ec_master/parameters/sdo_dict · 수정 목록 139" ;;
  esac
}

site_check_row() {
  local ok="$1" what="$2" detail="$3"
  if [[ "${ok}" == "1" ]]; then printf '  [OK]   %-28s %s\n' "${what}" "${detail}"; else printf '  [확인] %-28s %s\n' "${what}" "${detail}"; SITE_CHECK_FAILED=1; fi
}

site_selfcheck() {
  local workspace="$1" rt unit tz
  SITE_CHECK_FAILED=0
  echo "자가 점검"
  rt="$(ulimit -r 2>/dev/null || echo 0)"
  site_check_row "$([[ "${rt}" -ge 99 ]] && echo 1 || echo 0)" "실시간 권한 (ulimit -r)" "${rt} (99 필요 · 재부팅 뒤 적용)"
  site_check_row "$(loginctl show-user "$(id -un)" 2>/dev/null | grep -q '^Linger=yes' && echo 1 || echo 0)" "linger" "$(loginctl show-user "$(id -un)" 2>/dev/null | grep '^Linger=' || echo 미상)"
  site_check_row "$([[ -f "${SITE_GDM_CONF}" ]] && grep -q '^AutomaticLoginEnable=true' "${SITE_GDM_CONF}" && echo 1 || echo 0)" "자동 로그인" "${SITE_GDM_CONF}"
  tz="$(timedatectl show -p Timezone --value 2>/dev/null || echo 미상)"
  site_check_row 1 "시간대" "${tz}"
  if command -v mokutil >/dev/null 2>&1; then
    local sb
    sb="$(mokutil --sb-state 2>/dev/null | head -1 || true)"
    site_check_row "$(printf '%s' "${sb}" | grep -qi enabled && echo 0 || echo 1)" "Secure Boot 꺼짐 (EtherCAT 모듈)" "${sb:-미상}"
  fi
  site_check_row "$(auto_upgrades_off)" "자동 업데이트" "$(systemctl is-enabled unattended-upgrades 2>/dev/null || echo 없음)"
  site_check_row "$(site_wifi_powersave_ok)" "Wi-Fi 절전 꺼짐" "$(iwconfig 2>/dev/null | grep -o 'Power Management:[a-z]*' | head -1 || echo 무선 없음) · 재연결 뒤 적용"
  for unit in motion-control motion-motor motion-coordination; do
    site_check_row "$(systemctl --user is-active --quiet "${unit}.service" && echo 1 || echo 0)" "${unit}.service" "$(systemctl --user is-active "${unit}.service" 2>/dev/null || echo unknown)"
  done
  if [[ -f "${SITE_ETHERCAT_CONF}" ]] && grep -q '^MASTER0_DEVICE="[^"]\+"' "${SITE_ETHERCAT_CONF}"; then
    local phase
    phase="$({ ethercat master 2>/dev/null || true; } | awk -F: '/Phase/ { gsub(/^ +/, "", $2); print $2; exit }')"
    site_check_row "$([[ -n "${phase}" ]] && echo 1 || echo 0)" "EtherCAT master" "${phase:-응답 없음 · 모터 전원·랜선·sudo systemctl status ethercat}"
    site_check_row 1 "EtherCAT slaves" "$({ ethercat slaves 2>/dev/null || true; } | wc -l)대"
    local sdo_dict
    sdo_dict="$(site_sdo_dict_value)"
    site_check_row "$([[ "${sdo_dict}" == "0" ]] && echo 1 || echo 0)" "EtherCAT SDO 사전 읽기 꺼짐" "$(site_sdo_dict_detail "${sdo_dict}")"
  else
    site_check_row 1 "EtherCAT" "설정 없음 (다이나믹셀 전용)"
  fi
  local http
  http="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:8000/api/status 2>/dev/null || echo 000)"
  site_check_row "$([[ "${http}" == "200" ]] && echo 1 || echo 0)" "웹 http://localhost:8000" "HTTP ${http}"
  if [[ "${SITE_SCAN:-0}" == "1" && "${http}" == "200" ]]; then
    echo "  모터 스캔 1회 (최대 50초) …"
    local scan
    scan="$(curl -s --max-time 70 -X POST http://localhost:8000/api/motors/scan 2>/dev/null || echo '{}')"
    site_check_row "$(printf '%s' "${scan}" | grep -q '"success": *true' && echo 1 || echo 0)" "전체 모터 검색" "$(printf '%s' "${scan}" | head -c 160)"
  fi
  if [[ "${SITE_CHECK_FAILED}" == "1" ]]; then
    echo "  [확인] 표시 항목은 위 안내대로 보고 다시 실행하면 됩니다 · bash ${workspace}/scripts/install.sh --site"
  fi
  echo
  echo "정전 복구 리허설 · 전원 케이블을 뽑았다 꽂는다 → 사람 손 없이 http://<이 PC IP>:8000 이 뜨고 스케줄이 이어지면 통과"
}
