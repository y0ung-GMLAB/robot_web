#!/usr/bin/env bash
# EtherCAT(AC 서보) 랜카드 바꾸기 · 이미 설치한 PC 용 (관리자 비밀번호 한 번) · 2026-10-27
#
#   bash ~/ros2_ws/scripts/ethercat_nic.sh none      랜카드 안 씀 · EtherCAT 을 안 쓰는 PC · 묶였으면 풀어 줌
#   bash ~/ros2_ws/scripts/ethercat_nic.sh enp2s0    이 랜카드를 EtherCAT 에 (MAC 기준으로 적음)
#   bash ~/ros2_ws/scripts/ethercat_nic.sh           IP 없는 유선 포트를 자동으로 고름 (설치 때와 같음)
#
# 바꾼 뒤 · 웹 모터 설정에서 「장비에 적용 · 모터 재시작」 또는 모터 서비스 재시작
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/setup/site.sh"
export SITE_ETHERCAT_NIC="${1:-}"
export SITE_RESET_ETHERCAT=1
site_ethercat_configure
# 웹 업데이트용 시스템 설정 도우미가 깔린 PC · 도우미가 읽는 랜카드 기록도 새 것으로 · 수정 목록 211
if [[ -n "$(site_system_helper_installed_version)" ]]; then
  site_system_record_nic || site_warn "도우미 랜카드 기록(${SITE_SYSTEM_CONF})을 바꾸지 못했습니다 · bash ${SITE_SYSTEM_ALLOW_SCRIPT}"
fi
echo "완료 · 지금 설정 · $(grep '^MASTER0_DEVICE' "${SITE_ETHERCAT_CONF}" 2>/dev/null || echo '없음')"
