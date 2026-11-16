#!/bin/bash
# robot_web 시스템 설정 고정 도우미 · 수정 목록 211 (2026-11-16 · 사용자 결정)
#
# 웹 「모든 PC 업데이트」(install.sh --code-only · install_speaker.sh --code-only · 관리자 비밀번호 없음)가
#   `sudo -n /usr/local/sbin/robot-web-system-apply` 로 **인자 없이** 부른다 ·
#   허용은 /etc/sudoers.d/robot-web-system-apply 한 줄(설치한 계정 · 이 명령 하나 · 인자 없이 · 비밀번호 없이)
# 설치(scripts/setup/site.sh 의 site_system_helper_install)가 이 파일을 /usr/local/sbin/robot-web-system-apply 로
#   **복사**한다(root:root 0755) · 저장소를 고쳐도 다시 깔기 전에는 깔린 것 그대로
#
# 보안 · root 로 돈다
#   - 사용자가 고칠 수 있는 곳(저장소 · 작업공간 · 홈)의 파일은 읽지도 실행하지도 않는다 · site.sh 도 안 읽는다
#   - root 일 때는 밖에서 준 환경 변수를 하나도 안 받는다(PATH 도 고정) · 인자도 안 받는다
#   - 읽는 설정 파일(/etc/robot-web/system-apply.conf)과 부르는 재빌드 스크립트·IgH 소스는 root 것이고
#     다른 사람이 못 고칠 때만 믿는다
#   - 하는 일은 아래 넷으로 고정
#       1 Wi-Fi 칩(rtw88) 절전 끄기 · /etc/modprobe.d/rtw88-robot.conf · 재부팅 뒤 적용 · 수정 목록 173
#       2 EtherCAT 랜카드를 NetworkManager 에서 빼기 · 놓으며 내린 링크 다시 켜기 · 177 · 180
#         랜카드는 설치 때 적어 둔 /etc/robot-web/system-apply.conf 의 MAC
#       3 fwupd 끄기 · fwupd.service · fwupd-refresh.timer mask · 210
#       4 깔린 ec_master 에 sdo_dict 가 없을 때만 /usr/local/sbin/ethercat-rebuild (커널 모듈만 빌드·설치) · 139
#         지금 올라간 모듈 · ethercat 서비스 · 모터는 건드리지 않는다 → 다음 재부팅 · EtherCAT 재시작 때 적용
#         랜카드 기록이 none(직렬 서보 전용 · 스피커)이면 해당 없음
#
# 줄마다 [이미 됨] · [바꿈] · [재부팅 필요] · [해당 없음] · [실패] · [실패] 가 하나라도 있으면 끝난 값 1
# 판정은 site.sh 의 같은 단계(site_rtw88_conf_ok · site_ethercat_nm_unmanage · site_fwupd_off ·
#   site_etherlab_patched)와 맞춘다 · 고치면 HELPER_VERSION 을 올리고 site.sh SITE_SYSTEM_HELPER_VERSION 도 같게
#   (웹 업데이트가 깔린 것이 옛 버전이면 다시 까는 명령 bash scripts/allow_system_apply.sh 를 찍는다)
# 지우기 · sudo rm /usr/local/sbin/robot-web-system-apply /etc/sudoers.d/robot-web-system-apply
set -uo pipefail
HELPER_VERSION=1

case "$#:${1:-}" in
  0:) ;;
  1:--version) echo "${HELPER_VERSION}"; exit 0 ;;
  1:-h|1:--help) sed -n '2,28p' "$0"; exit 0 ;;
  *) echo "인자 없이 실행합니다 · 받은 인자 · $*" >&2; exit 2 ;;
esac

if [[ "${EUID}" -eq 0 ]]; then
  TEST=0
  export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
elif [[ "${RWSA_TEST:-}" == "1" ]]; then
  # 시험 · root 아님 · 아래 자리를 RWSA_* 로 바꿀 수 있다
  TEST=1
else
  echo "관리자 권한 필요 · sudo /usr/local/sbin/robot-web-system-apply" >&2
  exit 2
fi
export LC_ALL=C
umask 022

# 자리 · root 면 늘 기본값 · 시험(RWSA_TEST=1 · root 아님)에서만 바꿀 수 있다
setting() {
  local name="$1" default="$2"
  if [[ "${TEST}" == "1" && -n "${!name:-}" ]]; then printf '%s' "${!name}"; else printf '%s' "${default}"; fi
}
SYSTEM_CONF="$(setting RWSA_SYSTEM_CONF /etc/robot-web/system-apply.conf)"
RTW88_CONF="$(setting RWSA_RTW88_CONF /etc/modprobe.d/rtw88-robot.conf)"
NM_CONF="$(setting RWSA_NM_CONF /etc/NetworkManager/conf.d/99-robot-web-ethercat-unmanaged.conf)"
SYS_MODULE="$(setting RWSA_SYS_MODULE /sys/module)"
FWUPD_UNITS="$(setting RWSA_FWUPD_UNITS 'fwupd.service fwupd-refresh.timer')"
REBUILD="$(setting RWSA_REBUILD /usr/local/sbin/ethercat-rebuild)"
ETHERLAB_SRC="$(setting RWSA_ETHERLAB_SRC /usr/local/src/ethercat)"
ETHERLAB_PATCH="$(setting RWSA_ETHERLAB_PATCH /usr/local/share/robot_web/igh-sdo-dict-off.patch)"
ROOT_UID="$(setting RWSA_ROOT_UID 0)"
LOCK="$(setting RWSA_LOCK /run/robot-web-system-apply.lock)"
RELINK_WAIT_SEC="$(setting RWSA_RELINK_WAIT_SEC 10)"
REBUILD_HOME="$(setting RWSA_HOME /root)"

FAILED=0
REBOOT=0

# 한 줄 · $1 상태 · $2 항목 · $3 자세히
report() {
  printf '  [%s] %s · %s\n' "$1" "$2" "$3"
  case "$1" in
    실패) FAILED=1 ;;
    *재부팅*) REBOOT=1 ;;
  esac
}

# root 것이고 다른 사람이 못 고치나 · 파일 · 폴더 하나 (그룹·남 쓰기 없음)
root_only() {
  local uid mode
  read -r uid mode < <(stat -c '%u %a' "$1" 2>/dev/null) || return 1
  [[ "${uid}" == "${ROOT_UID}" ]] || return 1
  (( (8#${mode} & 8#022) == 0 ))
}

# 폴더 아래 전부 · root 것이 아니거나 그룹·남이 쓸 수 있는 것이 하나라도 있으면 실패 (링크는 주인만)
tree_root_only() {
  local found
  [[ -d "$1" ]] || return 1
  found="$(find "$1" -xdev \( \( -type l ! -uid "${ROOT_UID}" \) -o \( ! -type l \( ! -uid "${ROOT_UID}" -o -perm /022 \) \) \) -print -quit 2>/dev/null)" || return 1
  [[ -z "${found}" ]]
}

# 파일 쓰기 · 같은 폴더 임시 이름(.conf 로 안 끝남 → modprobe · NetworkManager 가 안 읽음) → 바꿔 넣기
write_file() {
  local path="$1" content="$2" tmp
  tmp="${path}.robot-web-tmp"
  mkdir -p "$(dirname "${path}")" || return 1
  if printf '%s\n' "${content}" > "${tmp}" && chmod 0644 "${tmp}" && mv -f "${tmp}" "${path}"; then
    return 0
  fi
  rm -f "${tmp}"
  return 1
}

# ------------------------------------------------------------------ #
# 1 · Wi-Fi 칩(rtw88) 절전 끄기 · 173
# ------------------------------------------------------------------ #
rtw88_conf_ok() {
  [[ -f "${RTW88_CONF}" ]] \
    && grep -qxE '[[:space:]]*options[[:space:]]+rtw88_pci[[:space:]]+disable_aspm=(1|Y|y)[[:space:]]*' "${RTW88_CONF}" \
    && grep -qxE '[[:space:]]*options[[:space:]]+rtw88_core[[:space:]]+disable_lps_deep=(1|Y|y)[[:space:]]*' "${RTW88_CONF}"
}

module_param() {
  local file="${SYS_MODULE}/$1/parameters/$2"
  if [[ -r "${file}" ]]; then tr -d '[:space:]' < "${file}"; else echo 미상; fi
}

item_rtw88() {
  local what="Wi-Fi 칩 절전 끄기 (rtw88 · 수정 목록 173)" now
  if [[ ! -d "${SYS_MODULE}/rtw88_pci" ]]; then
    report "해당 없음" "${what}" "rtw88 칩 아님"
    return
  fi
  now="disable_aspm=$(module_param rtw88_pci disable_aspm) · disable_lps_deep=$(module_param rtw88_core disable_lps_deep)"
  if rtw88_conf_ok; then
    if [[ "${now}" == "disable_aspm=Y · disable_lps_deep=Y" ]]; then
      report "이미 됨" "${what}" "${now}"
    else
      report "재부팅 필요" "${what}" "${RTW88_CONF} 있음 · 지금 ${now} · 재부팅 뒤 적용"
    fi
    return
  fi
  if write_file "${RTW88_CONF}" "# robot_web · Wi-Fi 칩 절전 끄기 (rtw88 · EtherCAT 프레임 끊김 · 수정 목록 173) · 재부팅 뒤 적용
options rtw88_pci disable_aspm=1
options rtw88_core disable_lps_deep=1"; then
    report "바꿈 · 재부팅 필요" "${what}" "${RTW88_CONF} 적음 · 재부팅 뒤 적용"
  else
    report 실패 "${what}" "${RTW88_CONF} 를 쓰지 못함"
  fi
}

# ------------------------------------------------------------------ #
# 2 · EtherCAT 랜카드 NetworkManager 에서 빼기 · 링크 다시 켜기 · 177 · 180
# ------------------------------------------------------------------ #

# 설치 때 적은 MAC · stdout 소문자 MAC · none · 빈 값(기록 없음) · 끝난 값 1 = 파일을 믿을 수 없음
recorded_mac() {
  local value
  [[ -e "${SYSTEM_CONF}" ]] || return 0
  root_only "${SYSTEM_CONF}" && root_only "$(dirname "${SYSTEM_CONF}")" || return 1
  value="$(sed -n 's/^ETHERCAT_MAC=//p' "${SYSTEM_CONF}" | tail -1 | tr -d '[:space:]' | tr '[:upper:]' '[:lower:]')"
  if [[ "${value}" == "none" || "${value}" =~ ^([0-9a-f]{2}:){5}[0-9a-f]{2}$ ]]; then
    echo "${value}"
    return 0
  fi
  return 1
}

nic_dev() {
  { ip -br link 2>/dev/null || true; } | awk -v mac="$1" 'tolower($3) == mac { sub(/@.*/, "", $1); print $1; exit }'
}

link_is_up() {
  { ip -br link 2>/dev/null || true; } \
    | awk -v dev="$1" '$1 == dev && $4 ~ /[<,]UP[,>]/ { found = 1 } END { exit found ? 0 : 1 }'
}

ethercat_cli() {
  local cli
  for cli in "$(command -v ethercat 2>/dev/null || true)" /opt/etherlab/bin/ethercat /usr/local/etherlab/bin/ethercat /usr/local/bin/ethercat; do
    if [[ -n "${cli}" && -x "${cli}" ]]; then
      echo "${cli}"
      return 0
    fi
  done
  return 0
}

# 꺼진 링크 켜기 · IgH(ec_generic)는 링크가 UP 이어야 슬레이브를 찾는다 · stdout 자세히 · 끝난 값 1 = 못 켬
relink() {
  local dev="$1" cli i
  ip link set dev "${dev}" up || return 1
  cli="$(ethercat_cli)"
  if [[ -z "${cli}" ]]; then
    echo "링크 ${dev} 다시 켬"
    return 0
  fi
  for ((i = 0; i < RELINK_WAIT_SEC; i++)); do
    if [[ -n "$("${cli}" slaves 2>/dev/null || true)" ]]; then
      echo "링크 ${dev} 다시 켬 · 슬레이브 다시 보임"
      return 0
    fi
    sleep 1
  done
  echo "링크 ${dev} 다시 켬 · 슬레이브가 아직 안 보임 · sudo systemctl restart ethercat 또는 재부팅 · 웹에서 알람 해제 → 서보 ON"
}

item_nm() {
  local what="EtherCAT 랜카드 NetworkManager 에서 빼기 (수정 목록 177 · 180)" mac dev detail
  if ! mac="$(recorded_mac)"; then
    report 실패 "${what}" "${SYSTEM_CONF} 를 믿을 수 없음(root 것이 아니거나 값이 이상함) · 이 PC 터미널에서 bash scripts/allow_system_apply.sh"
    return
  fi
  if [[ -z "${mac}" ]]; then
    report "해당 없음" "${what}" "랜카드 기록 없음 (${SYSTEM_CONF})"
    return
  fi
  if [[ "${mac}" == "none" ]]; then
    report "해당 없음" "${what}" "EtherCAT 랜카드 안 씀"
    return
  fi
  if ! command -v nmcli >/dev/null 2>&1; then
    report "해당 없음" "${what}" "NetworkManager 없음"
    return
  fi
  dev="$(nic_dev "${mac}")"
  if [[ -f "${NM_CONF}" ]] && grep -qiE "^[[:space:]]*unmanaged-devices[[:space:]]*=.*mac:${mac}" "${NM_CONF}"; then
    if [[ -z "${dev}" ]] || link_is_up "${dev}"; then
      report "이미 됨" "${what}" "mac:${mac}${dev:+ · ${dev} 켜짐}"
    elif detail="$(relink "${dev}")"; then
      report 바꿈 "${what}" "이미 빠져 있었음 · 꺼져 있던 ${detail}"
    else
      report 실패 "${what}" "링크 ${dev} 를 켜지 못함 · 모터 끊김 · sudo ip link set dev ${dev} up · 수정 목록 180"
    fi
    return
  fi
  if ! write_file "${NM_CONF}" "# robot_web · EtherCAT(모터) 랜카드는 NetworkManager 가 관리하지 않음 · 수정 목록 177
[keyfile]
unmanaged-devices=mac:${mac}"; then
    report 실패 "${what}" "${NM_CONF} 를 쓰지 못함"
    return
  fi
  # 설정을 다시 읽는다 · Wi-Fi 는 그대로 · EtherCAT 랜카드는 NM 이 놓으며 링크를 내린다 → 바로 다시 켠다(180)
  nmcli general reload conf >/dev/null 2>&1 || true
  detail="NetworkManager 설정 다시 읽음"
  if [[ -n "${dev}" ]] && ! link_is_up "${dev}"; then
    if ! detail+=" · $(relink "${dev}")"; then
      report 실패 "${what}" "${NM_CONF} 적음 · 링크 ${dev} 를 켜지 못함 · 모터 끊김 · sudo ip link set dev ${dev} up · 수정 목록 180"
      return
    fi
  fi
  report 바꿈 "${what}" "${NM_CONF} (mac:${mac}) · ${detail}"
}

# ------------------------------------------------------------------ #
# 3 · fwupd 끄기 · 210
# ------------------------------------------------------------------ #

# masked · enabled · static … · 없으면 빈 값 (새 systemd 는 not-found)
unit_state() {
  local state
  state="$(systemctl is-enabled "$1" 2>/dev/null || true)"
  state="${state%%$'\n'*}"
  [[ "${state}" == "not-found" ]] && state=""
  printf '%s' "${state}"
}

item_fwupd() {
  local what="fwupd 끄기 (펌웨어 업데이트 · 수정 목록 210)" unit state present=0 out
  local -a todo=()
  # shellcheck disable=SC2086
  for unit in ${FWUPD_UNITS}; do
    state="$(unit_state "${unit}")"
    [[ -z "${state}" ]] && continue
    present=1
    [[ "${state}" == "masked" ]] || todo+=("${unit}")
  done
  if [[ "${present}" == "0" ]]; then
    report "해당 없음" "${what}" "fwupd 없음"
    return
  fi
  if (( ${#todo[@]} == 0 )); then
    report "이미 됨" "${what}" "${FWUPD_UNITS} masked"
    return
  fi
  if out="$(systemctl mask --now "${todo[@]}" 2>&1)"; then
    report 바꿈 "${what}" "${todo[*]} masked · 다시 켜려면 sudo systemctl unmask ${todo[*]}"
  else
    report 실패 "${what}" "systemctl mask --now ${todo[*]} · ${out//$'\n'/ · }"
  fi
}

# ------------------------------------------------------------------ #
# 4 · IgH SDO 사전 읽기 끄기 모듈 · 139
# ------------------------------------------------------------------ #

# 깔린(modprobe 가 고를) ec_master 에 sdo_dict 가 있나
installed_patched() {
  local params
  params="$(modinfo -p ec_master 2>/dev/null || true)"
  grep -q '^sdo_dict:' <<<"${params}"
}

item_igh() {
  local what="EtherCAT SDO 사전 읽기 끄기 모듈 (IgH 패치 · 수정 목록 139)" loaded="${SYS_MODULE}/ec_master" bad="" mac
  # 직렬 서보 전용 PC(SITE_ETHERCAT_NIC=none · 라즈베리파이 · jazzy) · EtherLab 은 빌드용으로 깔려 있어도 EtherCAT 을
  #   안 쓴다 · 커널을 바꾼 뒤 웹 업데이트마다 모듈을 몇 분씩 다시 빌드하지 않게(실패하면 [실패] 로 남음) · 기록을
  #   믿을 수 없으면(위 2 가 [실패]) 전처럼 본다
  if mac="$(recorded_mac)" && [[ "${mac}" == "none" ]]; then
    report "해당 없음" "${what}" "EtherCAT 랜카드 안 씀"
    return
  fi
  if installed_patched; then
    if [[ -d "${loaded}" && ! -e "${loaded}/parameters/sdo_dict" ]]; then
      report "재부팅 필요" "${what}" "새 모듈은 깔림 · 올라간 모듈은 옛 것 · 다음 재부팅 · EtherCAT 재시작 때 적용"
    else
      report "이미 됨" "${what}" "sdo_dict 있음"
    fi
    return
  fi
  if [[ ! -e "${REBUILD}" ]] && ! modinfo ec_master >/dev/null 2>&1; then
    report "해당 없음" "${what}" "EtherLab 없음"
    return
  fi
  if [[ ! -x "${REBUILD}" ]]; then
    report 실패 "${what}" "${REBUILD} 없음 · 이 PC 터미널에서 bash scripts/install.sh --site · docs/수정_139_IgH_패치.md"
    return
  fi
  # root 로 빌드한다 · 재빌드 스크립트 · 패치 · 소스가 root 것이고 다른 사람이 못 고칠 때만
  root_only "${REBUILD}" && root_only "$(dirname "${REBUILD}")" || bad="${REBUILD}"
  if [[ -z "${bad}" && -e "${ETHERLAB_PATCH}" ]] && ! root_only "${ETHERLAB_PATCH}"; then bad="${ETHERLAB_PATCH}"; fi
  if [[ -z "${bad}" && -e "${ETHERLAB_SRC}" ]] && ! tree_root_only "${ETHERLAB_SRC}"; then bad="${ETHERLAB_SRC}"; fi
  if [[ -n "${bad}" ]]; then
    report 실패 "${what}" "${bad} 가 root 것이 아니거나 다른 계정이 고칠 수 있음 · root 로 빌드하지 않음 · 손으로 · docs/수정_139_IgH_패치.md"
    return
  fi
  echo "    · 커널 모듈만 다시 빌드 (몇 분 · 지금 올라간 모듈 · ethercat 서비스 · 모터는 그대로)"
  if env -i PATH="${PATH}" HOME="${REBUILD_HOME}" LC_ALL=C "${REBUILD}" 2>&1 | sed 's/^/      /'; then
    report "바꿈 · 재부팅 필요" "${what}" "새 ec_master 깔림 · 다음 재부팅 · EtherCAT 재시작 때 적용 (지금 도는 모터는 그대로)"
  else
    report 실패 "${what}" "ethercat-rebuild 실패 · 위 줄 · docs/수정_139_IgH_패치.md F"
  fi
}

# ------------------------------------------------------------------ #

# 두 번 겹쳐 돌지 않게 (재빌드가 몇 분 걸린다)
exec 9>"${LOCK}" || { echo "잠금 파일을 열지 못함 · ${LOCK}" >&2; exit 1; }
if ! flock -n 9; then
  echo "시스템 설정 도우미가 이미 도는 중 · 끝난 뒤 다시" >&2
  exit 1
fi

echo "시스템 설정 도우미 v${HELPER_VERSION} (robot-web-system-apply · 수정 목록 211)"
item_rtw88
item_nm
item_fwupd
item_igh
if [[ "${FAILED}" == "1" ]]; then
  echo "  !! [실패] 줄이 있습니다 · 그 줄의 안내대로 · 수정 목록 211"
fi
if [[ "${REBOOT}" == "1" ]]; then
  echo "  · 재부팅 뒤 적용되는 것이 있습니다 · 재생 없을 때 sudo reboot"
fi
exit "${FAILED}"
