#!/usr/bin/env bash
# 스피커 PC 한 번에 설치 · 우분투 22.04 · 수정 목록 38 · 75 (2026-10-07)
#
#   새 PC   · curl -fsSL https://raw.githubusercontent.com/y0ung-GMLAB/robot_web/main/scripts/bootstrap.sh | bash -s -- --speaker
#   갱신    · bash ~/robot_web/scripts/install_speaker.sh      (같은 명령 · 몇 번 쳐도 같은 결과)
#
# 하는 일 · ROS 2(기본만) · 그룹 메시지 빌드(모터 쪽 빌드 안 함) · 사운드 장치 독점 · 사운드 카드 자동 선택 ·
#           speaker-app 서비스 등록(전원만 켜면 뜸) · 자동 업데이트·절전 끄기 · 방화벽 같은 망 허용 ·
#           옛 ~/speaker_app 에서 음원·설정 옮기기
# 로봇 PC 서비스(모터·웹 :8000·연동)는 깔지 않는다 · 이 PC 는 스피커만 한다
#
#   --dry-run   바꾸지 않고 할 일만 찍는다
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
APP_DIR="${WORKSPACE_DIR}/speaker_app"
OLD_APP_DIR="${HOME}/speaker_app"
UNIT_DIR="${HOME}/.config/systemd/user"
UNIT="speaker-app.service"
DRY_RUN=false
CODE_ONLY=false

for arg in "$@"; do
  case "${arg}" in
    --dry-run) DRY_RUN=true; export SITE_DRY_RUN=1 ;;
    # 관리자 비밀번호 없이 · 코드 받기 → 그룹 메시지 빌드 → 앱 재시작 (웹 「모든 PC 업데이트」 · 2026-10-08)
    --code-only) CODE_ONLY=true ;;
    -h|--help) sed -n '2,13p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "알 수 없는 옵션: ${arg} (--dry-run · --code-only)" >&2; exit 2 ;;
  esac
done
if [[ "${CODE_ONLY}" == true ]]; then
  # 물을 사람이 없다 · sudo 가 필요해지면 묻지 말고 바로 실패
  sudo() { command sudo -n "$@"; }
fi

step() { echo; echo "== $*"; }
run() {
  if [[ "${DRY_RUN}" == true ]]; then echo "  [dry-run] $*"; else "$@"; fi
}
trap 'echo; echo "!! ${LINENO}번째 줄에서 멈췄습니다 · ${BASH_COMMAND}" >&2; echo "!! 이 화면 마지막 스무 줄을 보내 주세요" >&2' ERR

# shellcheck disable=SC1091
source "${SCRIPT_DIR}/setup/site.sh"

step "0. 사전 확인"
if [[ "$(id -u)" == "0" ]]; then
  echo "root 가 아니라 늘 쓸 일반 계정으로 실행하세요" >&2
  exit 1
fi
# shellcheck disable=SC1091
source /etc/os-release
if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "22.04" ]]; then
  echo "지원 대상: Ubuntu 22.04 · 현재: ${PRETTY_NAME:-unknown}" >&2
  [[ "${DRY_RUN}" == true ]] || exit 1
fi
echo "작업공간 · ${WORKSPACE_DIR}"
echo "스피커 앱 · ${APP_DIR}"
if [[ "${DRY_RUN}" != true && "${CODE_ONLY}" != true ]] && ! sudo -n true 2>/dev/null; then
  echo "관리자 권한이 필요합니다 · 비밀번호를 한 번만 입력하세요"
  sudo -v
fi

if [[ "${CODE_ONLY}" == true ]]; then
  step "1. 건너뜀 · 코드만 갱신 (현장 준비는 첫 설치 때 끝남)"
else
step "1. 자동 업데이트·절전 끄기 · 로그아웃해도 유지 · 방화벽 같은 망 허용"
site_disable_interruptions
if loginctl show-user "$(id -un)" 2>/dev/null | grep -q '^Linger=yes'; then
  site_note "linger 이미 켜짐"
else
  site_run sudo loginctl enable-linger "$(id -un)"
fi
site_firewall
fi

step "2. 코드 갱신"
if git -C "${WORKSPACE_DIR}" remote get-url origin >/dev/null 2>&1; then
  if [[ -n "$(git -C "${WORKSPACE_DIR}" status --porcelain --untracked-files=no)" ]]; then
    echo "!! 고친 파일이 있어 갱신을 건너뜁니다 · 지금 코드로 설치합니다 (git -C ${WORKSPACE_DIR} status)" >&2
  elif ! run git -C "${WORKSPACE_DIR}" pull --ff-only; then
    echo "!! 갱신 실패(인터넷 · 이력 갈라짐) · 지금 코드로 설치합니다" >&2
  fi
fi
echo "코드 · $(git -C "${WORKSPACE_DIR}" log --oneline -1 2>/dev/null || echo '(git 아님)')"

if [[ "${CODE_ONLY}" == true ]]; then
  step "3. 건너뜀 · 코드만 갱신 (프로그램은 첫 설치 때 깔림)"
else
step "3. 프로그램 설치 (ROS 2 기본 · 빌드 도구 · 파이썬 · ALSA)"
if [[ ! -f /etc/apt/sources.list.d/ros2.list ]]; then
  run sudo apt-get update
  run sudo apt-get install -y curl gnupg lsb-release software-properties-common
  run sudo add-apt-repository -y universe
  run sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
    -o /usr/share/keyrings/ros-archive-keyring.gpg
  if [[ "${DRY_RUN}" != true ]]; then
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu ${UBUNTU_CODENAME} main" \
      | sudo tee /etc/apt/sources.list.d/ros2.list >/dev/null
  fi
fi
run sudo apt-get update
run sudo apt-get install -y \
  alsa-utils git build-essential cmake \
  python3-colcon-common-extensions python3-fastapi python3-uvicorn python3-yaml \
  ros-humble-ros-base
if ! id -nG "$(id -un)" | tr ' ' '\n' | grep -qx audio; then
  run sudo usermod -aG audio "$(id -un)"
  site_mark_reboot "audio 그룹"
fi
fi

step "4. 그룹 메시지 빌드 (모터 쪽은 빌드하지 않음)"
if [[ "${DRY_RUN}" == true ]]; then
  echo "  [dry-run] colcon build --packages-up-to motion_coordination_interfaces"
else
  (
    cd "${WORKSPACE_DIR}"
    unset AMENT_PREFIX_PATH CMAKE_PREFIX_PATH COLCON_PREFIX_PATH PYTHONPATH || true
    set +u
    source /opt/ros/humble/setup.bash
    set -u
    rm -rf build install
    # midi_msgs 가 딸려 온다 · 그룹 메시지가 쓴다 · --packages-select 로 하나만 고르면 실패
    colcon build --base-paths src --packages-up-to motion_coordination_interfaces
  )
fi

step "5. 옛 스피커 앱에서 옮기기 (${OLD_APP_DIR})"
mkdir -p "${APP_DIR}/sounds"
if [[ -d "${OLD_APP_DIR}" && "${OLD_APP_DIR}" != "${APP_DIR}" ]]; then
  shopt -s nullglob
  for wav in "${OLD_APP_DIR}"/sounds/*.wav; do
    if [[ -e "${APP_DIR}/sounds/$(basename "${wav}")" ]]; then
      site_note "있음 · $(basename "${wav}")"
    else
      run cp -p "${wav}" "${APP_DIR}/sounds/"
      site_note "음원 옮김 · $(basename "${wav}")"
    fi
  done
  shopt -u nullglob
  if [[ -f "${OLD_APP_DIR}/config/speaker.yaml" && ! -f "${APP_DIR}/config/speaker.local.yaml" && "${DRY_RUN}" != true ]]; then
    # 도메인·그룹·출력 장치·오프셋 등만 가져온다 · 옛 절대 경로는 버리고 파일 이름만
    python3 - "${OLD_APP_DIR}/config/speaker.yaml" "${APP_DIR}/config/speaker.local.yaml" <<'PY'
import os, sys, yaml
old = yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}
audio = dict(old.get("audio") or {})
audio.pop("sounds_dir", None)
if audio.get("file_path"):
    audio["file_path"] = os.path.basename(audio["file_path"])
new = {k: old[k] for k in ("mode", "dds", "trigger", "standalone", "web", "log") if k in old}
new["audio"] = audio
with open(sys.argv[2], "w", encoding="utf-8") as f:
    yaml.safe_dump(new, f, allow_unicode=True, sort_keys=False)
PY
    site_note "설정 옮김 · 도메인 · 그룹 · 출력 장치 · 오프셋"
  fi
  if systemctl --user cat "${UNIT}" 2>/dev/null | grep -q "${OLD_APP_DIR}/run.sh"; then
    site_note "옛 서비스는 아래 6 에서 새 위치로 바꿉니다"
  fi
else
  site_note "옛 스피커 앱 없음 · 건너뜀"
fi

step "6. 사운드 장치 독점 · 카드 자동 선택"
if [[ "${CODE_ONLY}" != true ]]; then
  run bash "${APP_DIR}/deploy/setup-audio.sh" || echo "!! 사운드 장치 독점 실패 · 소리가 안 나면 다시 실행" >&2
fi
if [[ "${DRY_RUN}" != true ]]; then
  # 지금 설정된 카드가 없으면 HDMI 가 아닌 첫 카드로 · 이미 있으면 손대지 않는다
  APP_DIR="${APP_DIR}" python3 - <<'PY' || true
import os, re, subprocess, sys
sys.path.insert(0, os.path.join(os.environ["APP_DIR"], "backend"))
import config
try:
    listing = subprocess.run(["aplay", "-l"], capture_output=True, text=True, timeout=5).stdout
except Exception:
    listing = ""
cards = re.findall(r"^card (\d+): [^\n]*?device (\d+): ([^\n]*)", listing, re.M)
cfg = config.load()
current = re.match(r"plughw:(\d+),(\d+)", cfg["audio"]["device"])
present = {(c, d) for c, d, _ in cards}
if current and (current.group(1), current.group(2)) in present:
    print("  · 출력 장치 그대로 · %s" % cfg["audio"]["device"])
else:
    pick = next(((c, d) for c, d, name in cards if "HDMI" not in name.upper()), None) or (cards[0][:2] if cards else None)
    if pick is None:
        print("  !! 사운드 카드를 찾지 못했습니다 · 스피커 연결 뒤 웹에서 출력 장치를 정하세요")
    else:
        cfg["audio"]["device"] = "plughw:%s,%s" % pick
        config.save(cfg)
        print("  · 출력 장치 자동 선택 · %s" % cfg["audio"]["device"])
PY
fi

if [[ "${DRY_RUN}" != true ]]; then
  # 「같은 망 PC」 표에 보이는 이름 · bootstrap --name 이 있으면 그것 · 없으면 컴퓨터 이름(이미 정해 둔 이름은 그대로)
  APP_DIR="${APP_DIR}" python3 - "${SPEAKER_PC_NAME:-}" "$(hostname)" <<'PY'
import os, sys, yaml
sys.path.insert(0, os.path.join(os.environ["APP_DIR"], "backend"))
import config
given, host = sys.argv[1], sys.argv[2]
local = {}
if os.path.isfile(config.CONFIG_PATH):
    local = yaml.safe_load(open(config.CONFIG_PATH, encoding="utf-8")) or {}
already = str(((local.get("dds") or {}).get("pc_name")) or "")
name = given or already or host
cfg = config.load()
if cfg["dds"]["pc_name"] != name or not already:
    cfg["dds"]["pc_name"] = name
    config.save(cfg)
print("  · PC 이름 · %s" % name)
PY
fi

step "7. 자동 시작 등록 (${UNIT})"
if [[ "${DRY_RUN}" == true ]]; then
  echo "  [dry-run] ${UNIT_DIR}/${UNIT} · ExecStart=${APP_DIR}/run.sh"
else
  mkdir -p "${UNIT_DIR}"
  chmod +x "${APP_DIR}/run.sh"
  sed "s#^ExecStart=.*#ExecStart=${APP_DIR}/run.sh#" "${APP_DIR}/deploy/${UNIT}" > "${UNIT_DIR}/${UNIT}"
  systemctl --user daemon-reload
  systemctl --user enable "${UNIT}" >/dev/null
  systemctl --user restart "${UNIT}"
fi

step "설치 완료"
ip_addr="$(ip -o -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i == "src") print $(i + 1)}' || true)"
port="$(APP_DIR="${APP_DIR}" python3 -c 'import os,sys; sys.path.insert(0, os.environ["APP_DIR"] + "/backend"); import config; print(config.load()["web"]["port"])' 2>/dev/null || echo 8100)"
echo "코드     · $(git -C "${WORKSPACE_DIR}" log --oneline -1 2>/dev/null || echo '-')"
echo "서비스   · ${UNIT}=$(systemctl --user is-active "${UNIT}" 2>/dev/null; true)"
echo "스피커 화면 · http://${ip_addr:-<이 PC IP>}:${port}"
echo "음원     · $(find "${APP_DIR}/sounds" -maxdepth 1 -iname '*.wav' 2>/dev/null | wc -l)개 · 없으면 스피커 화면에서 추가"
echo "설치 확인 · bash ${WORKSPACE_DIR}/scripts/check.sh"
echo "맞출 것  · 로봇 PC 와 같은 robot_web 커밋 · 같은 DDS Domain ID · 같은 그룹 ID(스피커 화면 「연동 설정」)"
if site_needs_reboot; then
  echo
  echo "재부팅 1회 필요 · $(cat "${SITE_STATE_DIR}/needs_reboot" | tr '\n' ' ')· sudo reboot"
  site_clear_reboot
fi
