#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE="${MOTION_WORKSPACE:-$(cd "${SCRIPT_DIR}/.." && pwd)}"
BRANCH="${MOTION_WEB_BRANCH:-fix/coordination-safety}"

usage() {
  cat <<'EOF'
Usage: bash scripts/commit_branch.sh "commit message" [--push]

motion_web 브랜치(fix/coordination-safety) 변경만 커밋합니다.
src/motion_system(합친 모터 통신층)은 이 스크립트로 커밋하지 않습니다.
EOF
}

PUSH=false
COMMIT_MESSAGE=""

for arg in "$@"; do
  case "${arg}" in
    --push) PUSH=true ;;
    -h|--help) usage; exit 0 ;;
    *)
      if [[ -z "${COMMIT_MESSAGE}" ]]; then
        COMMIT_MESSAGE="${arg}"
      else
        COMMIT_MESSAGE+=" ${arg}"
      fi
      ;;
  esac
done

if [[ -z "${COMMIT_MESSAGE}" ]]; then
  usage >&2
  exit 1
fi

cd "${WORKSPACE}"

current_branch="$(git branch --show-current)"
if [[ "${current_branch}" != "${BRANCH}" ]]; then
  echo "현재 브랜치가 ${BRANCH}가 아닙니다: ${current_branch}" >&2
  exit 1
fi

if [[ -n "$(git status --porcelain src/motion_system)" ]]; then
  echo "src/motion_system 에 커밋 안 된 변경이 있습니다 · 명시 요청 없이 커밋하지 않습니다. 원복하거나 따로 커밋하세요." >&2
  git status --short src/motion_system >&2
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  git add README.md scripts docs src/motion_coordination src/web_bridge src/web_ui src/motion_schedule config 2>/dev/null || true
  git add -u
  git add scripts/*.sh 2>/dev/null || true
  git commit -m "${COMMIT_MESSAGE}"
else
  echo "커밋할 motion_web 변경이 없습니다."
  exit 0
fi

if [[ "${PUSH}" == true ]]; then
  git push origin "${BRANCH}"
fi

echo "커밋 완료 · ${BRANCH}"
