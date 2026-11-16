#!/usr/bin/env bash
# 웹 「모든 PC 업데이트」 가 시스템 설정을 비밀번호 없이 하게 · 고정 도우미 깔기 · 새 버전으로 바꾸기 · 수정 목록 211
# 이미 설치한 PC 용 (한 번 · 관리자 비밀번호 한 번) · 새로 설치하는 PC 는 install.sh(--site 포함) · install_speaker.sh 가 같은 일을 한다
#
#   bash ~/ros2_ws/scripts/allow_system_apply.sh       로봇 PC
#   bash ~/robot_web/scripts/allow_system_apply.sh     스피커 PC
#
# 깔리는 것 (scripts/setup/site.sh 「웹 업데이트용 시스템 설정 고정 도우미」)
#   /usr/local/sbin/robot-web-system-apply  · 저장소 scripts/setup/robot-web-system-apply.sh 의 복사본 · root:root 0755
#   /etc/robot-web/system-apply.conf        · EtherCAT 랜카드 MAC (도우미는 저장소를 안 읽는다)
#   /etc/sudoers.d/robot-web-system-apply   · 이 계정이 그 명령 하나만 · 인자 없이 · 비밀번호 없이
# 깐 뒤 도우미를 한 번 돌린다 · Wi-Fi 칩 절전 · EtherCAT 랜카드 NM 제외 · fwupd 끄기 · IgH 모듈 (재생 없을 때)
# 지우기 · sudo rm /usr/local/sbin/robot-web-system-apply /etc/sudoers.d/robot-web-system-apply
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/setup/site.sh"
if [[ "$(id -u)" == "0" ]]; then
  echo "root(sudo)가 아니라 늘 쓰는 계정으로 실행하세요 · bash ${SCRIPT_DIR}/allow_system_apply.sh" >&2
  exit 1
fi
if ! sudo -n true 2>/dev/null; then
  echo "관리자 권한이 필요합니다 · 비밀번호를 한 번만 입력하세요"
  sudo -v
fi
site_system_helper_install "$(id -un)"
echo
# 저장해 둔 비밀번호(sudo 시간)를 지우고 · 허용 줄만으로 비밀번호 없이 되는지 본다(웹 업데이트와 같은 조건)
sudo -k
if ! site_system_helper_allowed; then
  site_warn "깔았는데 비밀번호 없이 돌릴 수 없습니다 · ${SITE_SYSTEM_SUDOERS} · sudo -l 로 확인 · 수정 목록 211"
  exit 1
fi
if sudo -n "${SITE_SYSTEM_HELPER}"; then
  echo "완료 · 다음 웹 「모든 PC 업데이트」 부터 위 설정을 비밀번호 없이 합니다"
else
  echo "도우미는 깔렸습니다 · [실패] 줄은 그 안내대로 · 다음 웹 「모든 PC 업데이트」 때 다시 봅니다" >&2
  exit 1
fi
