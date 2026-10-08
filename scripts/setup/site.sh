#!/usr/bin/env bash
# 현장 준비 함수 모음 · 새 PC 를 「전원만 넣으면 뜨는 전시 PC」로 만든다 · 수정 목록 11 (2026-10-04)
#
# `scripts/install.sh --site` 가 source 해서 쓴다 · 손으로 하던 README 2~5단계가 여기 있다.
# 모든 함수는 **다시 실행해도 같은 결과**(멱등) · 이미 돼 있으면 건너뛴다.
#
#   SITE_DRY_RUN=1          실제로 바꾸지 않고 할 일만 찍는다
#   SITE_TIMEZONE=Asia/Seoul  시간대 · 없으면 터미널에서 묻고, 물을 수 없으면 현재 값 유지
#   SITE_ETHERCAT_NIC=enp2s0  EtherCAT 랜카드 지정 · 없으면 자동 감지(IP 없는 유선 포트)
#   SITE_RESET_ETHERCAT=1   이미 적힌 /etc/ethercat.conf 를 다시 쓴다
#   SITE_ETHERLAB_VERSION   EtherLab 태그 (기본 1.6.9 · README 검증 버전)
#   SITE_SCAN=1             자가 점검에서 모터 스캔 1회 (최대 50초)
#
# 시험용 덮어쓰기 · SITE_GDM_CONF · SITE_ETHERCAT_CONF · SITE_STATE_DIR
#
# 수작업으로 남는 것 · BIOS 「전원 복구 시 켜기」 1회 · 로봇 팩·모터 설정(웹)

SITE_DRY_RUN="${SITE_DRY_RUN:-0}"
SITE_GDM_CONF="${SITE_GDM_CONF:-/etc/gdm3/custom.conf}"
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
  echo "WiFi 절전 끄기 (무선 연결이 있을 때만)"
  if command -v nmcli >/dev/null 2>&1; then
    local line name type
    while IFS= read -r line; do
      [[ -z "${line}" ]] && continue
      name="${line%%:*}"; type="${line##*:}"
      if [[ "${type}" == "802-11-wireless" ]]; then
        site_run nmcli connection modify "${name}" 802-11-wireless.powersave 2 || true
        site_note "WiFi 「${name}」 절전 OFF"
      fi
    done < <(nmcli -t -f NAME,TYPE connection show 2>/dev/null || true)
  fi
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

site_web_admin_permissions() {
  local user="${1:-$(id -un)}"
  echo "웹에서 Wi-Fi · 시간대 바꾸기 허용 (${user} 만)"
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

site_etherlab_ready() {
  command -v ethercat >/dev/null 2>&1 && modinfo ec_master >/dev/null 2>&1 \
    && { [[ -f /usr/local/include/ecrt.h ]] || [[ -f /usr/include/ecrt.h ]] || [[ -s /opt/etherlab/include/ecrt.h ]]; }
}

site_ethercat_install() {
  if site_etherlab_ready; then
    site_note "EtherLab 이미 설치됨 · $(ethercat version 2>/dev/null | head -1)"
  else
    echo "EtherLab ${SITE_ETHERLAB_VERSION} 설치 (범용 드라이버 · 소스 빌드 · 몇 분)"
    site_run sudo apt install -y autoconf automake libtool pkg-config build-essential git gcc-12 g++-12 ethtool "linux-headers-$(uname -r)"
    if [[ ! -d "${SITE_ETHERLAB_SRC}/.git" ]]; then
      site_run sudo git clone --depth 1 --branch "${SITE_ETHERLAB_VERSION}" "${SITE_ETHERLAB_REPO}" "${SITE_ETHERLAB_SRC}"
    fi
    if [[ "${SITE_DRY_RUN}" == "1" ]]; then
      echo "  [dry-run] (cd ${SITE_ETHERLAB_SRC} && ./bootstrap && ./configure --disable-8139too --enable-generic=yes && make all modules && sudo make modules_install install && sudo depmod && sudo ldconfig)"
    else
      (
        cd "${SITE_ETHERLAB_SRC}"
        sudo ./bootstrap
        sudo ./configure --disable-8139too --enable-generic=yes
        sudo make -j"$(nproc)" all modules
        sudo make modules_install install
        sudo depmod
        sudo ldconfig
      )
    fi
  fi
  echo "커널 업데이트 뒤 자동 재빌드 (부팅 때 모듈 없으면 다시 만든다)"
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

site_ethercat_configure() {
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
  site_check_row "$(systemctl is-enabled unattended-upgrades 2>/dev/null | grep -q masked && echo 1 || echo 0)" "자동 업데이트" "$(systemctl is-enabled unattended-upgrades 2>/dev/null || echo 없음)"
  for unit in motion-control motion-motor motion-coordination; do
    site_check_row "$(systemctl --user is-active --quiet "${unit}.service" && echo 1 || echo 0)" "${unit}.service" "$(systemctl --user is-active "${unit}.service" 2>/dev/null || echo unknown)"
  done
  if [[ -f "${SITE_ETHERCAT_CONF}" ]] && grep -q '^MASTER0_DEVICE="[^"]\+"' "${SITE_ETHERCAT_CONF}"; then
    local phase
    phase="$({ ethercat master 2>/dev/null || true; } | awk -F: '/Phase/ { gsub(/^ +/, "", $2); print $2; exit }')"
    site_check_row "$([[ -n "${phase}" ]] && echo 1 || echo 0)" "EtherCAT master" "${phase:-응답 없음 · 모터 전원·랜선·sudo systemctl status ethercat}"
    site_check_row 1 "EtherCAT slaves" "$({ ethercat slaves 2>/dev/null || true; } | wc -l)대"
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
