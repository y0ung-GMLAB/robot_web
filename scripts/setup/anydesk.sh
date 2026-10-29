#!/usr/bin/env bash
# 원격 · 애니데스크 · 필요한 PC 마다 손으로 · 수정 목록 135 (사용자 결정 2026-10-14 · 회사 계정 · 대수 제한 없앰 2026-10-29)
#
#   bash ~/ros2_ws/scripts/setup/anydesk.sh            설치 · Wayland 끄기 · 부팅 때 자동 실행
#   SITE_DRY_RUN=1 bash ~/ros2_ws/scripts/setup/anydesk.sh   바꾸지 않고 할 일만
#
# 그다음 사람이 · 재부팅(Wayland 끄기 적용) → 애니데스크 창에서 회사 계정 로그인 · 무인 접속 비밀번호 ·
# 다른 곳에서 이 PC 의 애니데스크 ID 로 들어가 그 PC 브라우저로 http://localhost:8000/v2 ·
# 다른 PC 는 웹 「같은 망 PC」 새 탭 · **ID · 비밀번호는 저장소 · 문서에 적지 않는다**
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=site.sh
source "${SCRIPT_DIR}/site.sh"

if [[ "$(id -u)" == "0" ]]; then
  echo "root 가 아니라 자동 로그인 계정으로 실행하세요 (sudo 는 스크립트가 묻습니다)" >&2
  exit 1
fi
if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
  if [[ "${ID:-}" != "ubuntu" ]]; then
    echo "지원 대상: Ubuntu · 현재: ${PRETTY_NAME:-unknown}" >&2
    exit 1
  fi
fi

echo "========================================="
echo "애니데스크 · 원격 · $(hostname)"
echo "========================================="
[[ "${SITE_DRY_RUN}" == "1" ]] || sudo -v
site_anydesk_install
site_wayland_off

echo
if [[ "${SITE_DRY_RUN}" != "1" ]]; then
  id_text="$(anydesk --get-id 2>/dev/null || true)"
  echo "애니데스크 ID · ${id_text:-아직 없음(재부팅 · 애니데스크 창을 한 번 연 뒤 다시)} (이 ID 는 저장소에 적지 마세요)"
fi
if site_needs_reboot; then
  echo "다음 · 재부팅해야 Wayland 끄기가 적용됩니다 · sudo reboot"
fi
echo "그다음(사람) · 애니데스크 창 → 회사 계정 로그인 · 설정 → 보안 → 무인 접속 켜고 비밀번호"
echo "확인 · bash ${SCRIPT_DIR}/../check.sh 의 「애니데스크」 줄"
