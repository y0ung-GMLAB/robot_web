#!/usr/bin/env bash
# 시간표 재생 · PC 시계 맞추기(chrony) 역할 · 수정 목록 186 (2026-11-09)
#
# 사용자 결정(설계 `docs/설계_시계기준_재생.md` Q4) · 인터넷 NTP + 마스터 PC 를 함께 소스로 ·
# 마스터는 인터넷이 끊겨도 같은 망의 기준 시계(local stratum) · 그 밖 PC(스피커 포함)는 인터넷 + 마스터.
#
# 사용
#   sudo bash scripts/chrony_role.sh master              # 마스터 PC
#   sudo bash scripts/chrony_role.sh follow floating1.local   # 그 밖 PC · 마스터 주소(이름.local 또는 IP)
#   bash scripts/chrony_role.sh status                   # 지금 맞춤 상태(sudo 불필요)
#   sudo bash scripts/chrony_role.sh remove              # 이 설정 지우기(Ubuntu 기본으로)
#
# 웹 업데이트로는 /etc 를 못 쓴다 · PC 마다 한 번 손으로 · 바꾼 뒤 chrony 를 다시 시작한다.
set -euo pipefail

CONF_DIR="${ROBOT_CHRONY_CONF_DIR:-/etc/chrony/conf.d}"
CONF_FILE="${CONF_DIR}/robot-web.conf"
DRY_RUN="${ROBOT_CHRONY_DRY_RUN:-0}"

usage() {
  sed -n '7,12p' "$0" | sed 's/^# \{0,1\}//'
  exit 2
}

write_conf() {
  local text="$1"
  if [[ "${DRY_RUN}" == "1" ]]; then
    printf '%s\n' "${text}"
    return
  fi
  if ! command -v chronyd >/dev/null 2>&1; then
    echo "chrony 가 없습니다 · sudo apt install chrony" >&2
    exit 1
  fi
  mkdir -p "${CONF_DIR}"
  printf '%s\n' "${text}" > "${CONF_FILE}"
  systemctl restart chrony 2>/dev/null || systemctl restart chronyd
  echo "저장 · ${CONF_FILE} · chrony 다시 시작"
}

case "${1:-}" in
  master)
    write_conf "# robot_web 시간표 재생 · 마스터 · 수정 목록 186
# 인터넷 NTP(기본 pool)는 /etc/chrony/chrony.conf 그대로 · 인터넷이 끊겨도 같은 망 PC 의 기준
local stratum 10
allow 192.168.0.0/16
allow 10.0.0.0/8
allow 172.16.0.0/12
# 부팅 직후만 크게 맞춤 · 그 뒤는 천천히(재생 중 시계가 튀지 않게)
makestep 1 3
rtcsync"
    ;;
  follow)
    master="${2:-}"
    [[ -n "${master}" ]] || usage
    if [[ ! "${master}" =~ ^[A-Za-z0-9._:-]+$ ]]; then
      echo "마스터 주소 형식이 올바르지 않습니다 · ${master}" >&2
      exit 2
    fi
    write_conf "# robot_web 시간표 재생 · 그 밖 PC · 수정 목록 186
# 인터넷 NTP(기본 pool) + 마스터 · 인터넷이 끊겨도 마스터에 맞춘다
server ${master} iburst prefer
makestep 1 3
rtcsync"
    ;;
  status)
    if command -v chronyc >/dev/null 2>&1; then
      chronyc tracking || true
      echo
      chronyc sources -v || true
    else
      echo "chrony 없음"
    fi
    [[ -f "${CONF_FILE}" ]] && { echo; echo "== ${CONF_FILE}"; cat "${CONF_FILE}"; } || echo "robot_web chrony 설정 없음"
    ;;
  remove)
    if [[ "${DRY_RUN}" == "1" ]]; then
      echo "rm ${CONF_FILE}"
      exit 0
    fi
    rm -f "${CONF_FILE}"
    systemctl restart chrony 2>/dev/null || systemctl restart chronyd || true
    echo "지움 · ${CONF_FILE}"
    ;;
  *)
    usage
    ;;
esac
