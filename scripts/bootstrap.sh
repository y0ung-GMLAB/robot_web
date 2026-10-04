#!/usr/bin/env bash
# 한 줄 설치 · 우분투 22.04 설치 직후 터미널에서 · 수정 목록 11 (2026-10-04)
#
#   curl -fsSL https://raw.githubusercontent.com/y0ung-GMLAB/robot_web/main/scripts/bootstrap.sh | bash
#
#   · sudo 비밀번호 1회 · 시간대 질문 1회(Enter = 현재) · 나머지 자동 · 재부팅 1회 뒤 저절로 이어서 끝남
#   · 코드는 ~/ros2_ws 에 받는다 (MOTION_WORKSPACE 로 변경) · 이미 있으면 갱신만 한다
#   · 다른 용도로 쓰던 PC 도 됨 · 있는 프로그램은 지우지 않고 **더하기만** 한다 ·
#     단 자동 로그인·자동 업데이트 끄기·절전 끄기는 전시 PC 전제라 그대로 적용된다
#   · 수작업으로 남는 것 · BIOS 「전원 복구 시 켜기」 · 로봇 팩·모터 설정(웹)
set -Eeuo pipefail

REPO="${MOTION_REPO:-https://github.com/y0ung-GMLAB/robot_web.git}"
BRANCH="${MOTION_BRANCH:-main}"
WORKSPACE="${MOTION_WORKSPACE:-${HOME}/ros2_ws}"

echo "========================================="
echo "robot_web 한 줄 설치"
echo "========================================="
echo "저장소   · ${REPO} (${BRANCH})"
echo "작업공간 · ${WORKSPACE}"
echo "계정     · $(id -un) (이 계정이 자동 로그인 계정이 됩니다)"

if [[ -f /etc/os-release ]]; then
  # shellcheck disable=SC1091
  source /etc/os-release
  if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "22.04" ]]; then
    echo "지원 대상: Ubuntu 22.04 · 현재: ${PRETTY_NAME:-unknown}" >&2
    exit 1
  fi
fi
if [[ "$(id -u)" == "0" ]]; then
  echo "root 가 아니라 늘 쓸 일반 계정으로 실행하세요 (sudo 는 스크립트가 필요할 때 묻습니다)" >&2
  exit 1
fi

echo "관리자 권한이 필요합니다 · 비밀번호를 한 번만 입력하세요"
sudo -v

if ! command -v git >/dev/null 2>&1 || ! command -v curl >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y git curl
fi

if [[ -d "${WORKSPACE}/.git" ]]; then
  origin="$(git -C "${WORKSPACE}" remote get-url origin 2>/dev/null || echo '')"
  if [[ "${origin}" != *robot_web* ]]; then
    echo "${WORKSPACE} 는 다른 저장소입니다 (${origin}) · MOTION_WORKSPACE 로 다른 폴더를 지정하세요" >&2
    exit 1
  fi
  if [[ -n "$(git -C "${WORKSPACE}" status --porcelain --untracked-files=no)" ]]; then
    echo "${WORKSPACE} 에 커밋되지 않은 변경이 있습니다 · 정리한 뒤 다시 실행하세요 (git -C ${WORKSPACE} status)" >&2
    exit 1
  fi
  echo "기존 작업공간 갱신 · git pull (${BRANCH})"
  git -C "${WORKSPACE}" fetch origin "${BRANCH}"
  git -C "${WORKSPACE}" checkout -q "${BRANCH}"
  git -C "${WORKSPACE}" pull --ff-only origin "${BRANCH}"
elif [[ -e "${WORKSPACE}" ]]; then
  echo "${WORKSPACE} 가 이미 있는데 git 저장소가 아닙니다 · 옮기거나 MOTION_WORKSPACE 로 다른 폴더를 지정하세요" >&2
  exit 1
else
  echo "코드 받기 · git clone"
  git clone -b "${BRANCH}" "${REPO}" "${WORKSPACE}"
fi

cd "${WORKSPACE}"
exec bash scripts/install.sh --site "$@"
