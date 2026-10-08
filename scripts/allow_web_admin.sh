#!/usr/bin/env bash
# 웹에서 Wi-Fi · 시간대를 바꿀 수 있게 이 계정에 권한 하나 · 이미 설치한 PC 용 (한 번)
# 새로 설치하는 PC 는 `install.sh --site` 가 같은 일을 한다 · 수정 목록 81 · 79 (2026-10-08)
#
#   bash ~/ros2_ws/scripts/allow_web_admin.sh      (관리자 비밀번호 한 번)
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/setup/site.sh"
site_web_admin_permissions "$(id -un)"
echo "완료 · 웹 「시스템 정보 → Wi-Fi」 에서 바꿀 수 있습니다"
