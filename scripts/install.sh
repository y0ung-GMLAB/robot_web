#!/usr/bin/env bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"

export DEBIAN_FRONTEND=noninteractive
ROS_DAEMON_UPDATED=false
CURRENT_STEP="시작 전"

print_step() {
  CURRENT_STEP="$1"
  echo
  echo "========================================="
  echo "$1"
  echo "========================================="
}

# 멈추면 **어디서 왜 멈췄는지**를 마지막 화면에 남긴다 · §6-102
#
# `set -Eeuo pipefail` 은 오류 한 줄만 뱉고 끝난다 · 화면을 위로 한참 올려야
# 원인이 보이고, 그마저 PC 앞에 있는 사람이 옮겨 적어야 했다. PC 가 늘어날수록
# 그 전달이 병목이 된다 · 마지막 스무 줄만 찍어 보내면 되게 한다.
report_failure() {
  local exit_code=$1 line=$2 command=$3
  echo >&2
  echo "=========================================" >&2
  echo "설치 실패" >&2
  echo "=========================================" >&2
  echo "멈춘 단계 · ${CURRENT_STEP}" >&2
  echo "실행하려던 것 · ${command}" >&2
  echo "스크립트 ${line}행 · 끝난 값 ${exit_code}" >&2
  echo >&2
  case "${CURRENT_STEP}" in
    *"Git"*)
      echo "자주 있는 원인" >&2
      echo "  - 원격에 닿지 못함 · 인터넷·사내망 확인" >&2
      echo "  - 계정 권한 없음 · git 자격증명 확인" >&2
      ;;
    *"필수 프로그램"*|*"ROS 2 저장소"*|*"rosdep"*)
      echo "자주 있는 원인" >&2
      echo "  - apt 잠김 · 다른 설치가 돌고 있는지 확인" >&2
      echo "  - 인터넷 안 됨 · 저장소에 닿는지 확인" >&2
      ;;
    *"빌드"*)
      echo "자주 있는 원인" >&2
      echo "  - 위 로그의 '--- stderr:' 아래 줄이 진짜 원인이다" >&2
      echo "  - 저장 공간 부족 · df -h ~" >&2
      echo "  - EtherCAT 자리 · 7단계가 찍은 경로를 확인" >&2
      ;;
  esac
  echo >&2
  echo "이 화면 그대로(위 20줄 포함) 알려 주시면 됩니다." >&2
  echo "=========================================" >&2
  exit "${exit_code}"
}
trap 'report_failure "$?" "${LINENO}" "${BASH_COMMAND}"' ERR

# 옵션 · 수정 목록 11 (2026-10-04)
#   --site       현장 준비까지 (자동 업데이트·절전 끄기 · 자동 로그인 · linger · 시간대 · 방화벽 ·
#                EtherLab 설치·랜카드 자동 감지) · 끝에 자가 점검 · 재부팅이 필요하면 재부팅 뒤 저절로 이어감
#   --resume     재부팅 뒤 이어가기 (motion-site-resume.service 가 부른다 · 손으로 쳐도 됨)
#   --dry-run    바꾸지 않고 할 일만 찍는다 (빌드·설치는 건너뜀)
#   --no-reboot  재부팅이 필요해도 스스로 재부팅하지 않는다
#   --code-only  관리자 비밀번호 없이 · 코드 받기 → 빌드 → 서비스 재시작만 (웹 「모든 PC 업데이트」 가 쓴다 ·
#                이미 한 번 설치된 PC 전용 · 새 시스템 패키지가 필요하면 멈추고 터미널 설치를 안내)
# 옵션 없이 치면 전과 같다 · 이미 설치된 PC 의 코드 갱신 (현장 준비는 손대지 않는다)
SITE_MODE=false
RESUME_MODE=false
DRY_RUN=false
AUTO_REBOOT=true
CODE_ONLY=false
for arg in "$@"; do
  case "${arg}" in
    --site) SITE_MODE=true ;;
    --resume) RESUME_MODE=true ;;
    --dry-run) DRY_RUN=true; export SITE_DRY_RUN=1 ;;
    --no-reboot) AUTO_REBOOT=false ;;
    --code-only) CODE_ONLY=true ;;
    -h|--help)
      sed -n '/^# 옵션 · 수정 목록 11/,/^# 옵션 없이/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
      exit 0 ;;
    *) echo "알 수 없는 옵션: ${arg} (--site · --resume · --dry-run · --no-reboot · --code-only)" >&2; exit 2 ;;
  esac
done
if [[ "${CODE_ONLY}" == true && ( "${SITE_MODE}" == true || "${RESUME_MODE}" == true ) ]]; then
  echo "--code-only 는 --site · --resume 과 같이 쓸 수 없습니다" >&2
  exit 2
fi
if [[ "${CODE_ONLY}" == true ]]; then
  # 비밀번호를 물을 사람이 없다(웹에서 돈다) · sudo 가 필요해지면 묻지 말고 바로 실패한다
  sudo() { command sudo -n "$@"; }
fi
# shellcheck disable=SC1091
source "${SCRIPT_DIR}/setup/site.sh"
if [[ "${MOTION_SITE_RESUME:-}" == "1" ]]; then RESUME_MODE=true; fi

# 중간에 멈추는 흔한 이유 둘을 **먼저** 걸러낸다
preflight_checks() {
  local avail_gb
  avail_gb="$(df -BG --output=avail "${WORKSPACE_DIR}" | tail -1 | tr -dc '0-9')"
  echo "작업공간 · ${WORKSPACE_DIR}"
  echo "남은 공간 · ${avail_gb}GB"
  if [[ "${avail_gb}" -lt 5 ]]; then
    echo "!! 저장 공간이 5GB 미만입니다 · 전체 빌드가 중간에 멈출 수 있습니다" >&2
  fi
  # Secure Boot 가 켜져 있으면 직접 빌드한 EtherCAT 커널 모듈(서명 없음)이 안 올라간다 · BIOS 에서 끈다
  if command -v mokutil >/dev/null 2>&1 && mokutil --sb-state 2>/dev/null | grep -qi 'enabled'; then
    echo "!! Secure Boot 가 켜져 있습니다 · EtherCAT(AC 서보)이 안 될 수 있습니다 · BIOS 에서 Secure Boot 를 끄세요 (docs/설치_101.md)" >&2
  fi
  # sudo 는 여러 단계에서 쓴다 · 중간에 물어 멈추지 않게 여기서 한 번만 받는다
  if [[ "${CODE_ONLY}" == true ]]; then
    echo "코드만 갱신 · 관리자 비밀번호 없이 (코드 받기 → 빌드 → 서비스 재시작)"
    return 0
  fi
  if [[ "${DRY_RUN}" == true ]]; then
    echo "[dry-run] 바꾸지 않습니다 · 할 일만 찍습니다"
    return 0
  fi
  if ! sudo -n true 2>/dev/null; then
    echo "관리자 권한이 필요합니다 · 비밀번호를 한 번만 입력하세요"
    sudo -v
  fi
}

require_ubuntu_2204() {
  if [[ ! -f /etc/os-release ]]; then
    echo "Ubuntu 버전을 확인할 수 없습니다." >&2
    exit 1
  fi
  # shellcheck disable=SC1091
  source /etc/os-release
  if [[ "${ID:-}" != "ubuntu" || "${VERSION_ID:-}" != "22.04" ]]; then
    echo "지원 대상: Ubuntu 22.04" >&2
    echo "현재 OS: ${PRETTY_NAME:-unknown}" >&2
    if [[ "${DRY_RUN}" == true ]]; then
      echo "[dry-run] 버전이 달라도 계속 찍습니다" >&2
      return 0
    fi
    exit 1
  fi
}

# 현장 준비 · README 2~5단계를 대신한다 · 멱등 · `scripts/setup/site.sh`
prepare_site() {
  echo "-- 자동 업데이트·절전·화면 잠금 끄기"
  site_disable_interruptions
  echo "-- 자동 로그인 · linger"
  site_autologin "$(id -un)"
  echo "-- 시간대"
  site_timezone
  echo "-- 방화벽 (같은 망 허용)"
  site_firewall
  echo "-- 웹 관리 권한 (Wi-Fi · 시간대)"
  site_web_admin_permissions "$(id -un)"
  echo "-- EtherLab (빌드에 필수 · motor_manager 가 libethercat 에 링크)"
  site_ethercat_install
  echo "-- EtherCAT 랜카드"
  site_ethercat_configure
}

ensure_ros_apt_source() {
  if [[ -f /etc/apt/sources.list.d/ros2.list ]]; then
    return 0
  fi
  sudo apt update
  sudo apt install -y curl gnupg lsb-release software-properties-common
  sudo add-apt-repository -y universe
  sudo curl -sSL \
    https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
    -o /usr/share/keyrings/ros-archive-keyring.gpg
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo "$UBUNTU_CODENAME") main" \
    | sudo tee /etc/apt/sources.list.d/ros2.list >/dev/null
}

install_system_packages() {
  sudo apt update
  sudo apt install -y \
    btop \
    build-essential \
    chrony \
    cmake \
    curl \
    ethtool \
    gcc-12 \
    g++-12 \
    git \
    locales \
    python3-colcon-common-extensions \
    python3-fastapi \
    python3-rosdep \
    python3-uvicorn \
    python3-yaml \
    ros-humble-desktop \
    software-properties-common \
    ttyd
}

sync_git_repository() {
  if [[ "${MOTION_WEB_SKIP_GIT_PULL:-}" == "1" ]]; then
    echo "Git 수신 건너뜀 · MOTION_WEB_SKIP_GIT_PULL=1"
    return 0
  fi
  if ! git -C "${WORKSPACE_DIR}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    echo "Git 저장소가 아니므로 수신 건너뜀"
    return 0
  fi
  if ! git -C "${WORKSPACE_DIR}" remote get-url origin >/dev/null 2>&1; then
    echo "Git origin 없음 · 수신 건너뜀"
    return 0
  fi
  if ! git -C "${WORKSPACE_DIR}" fetch --prune origin; then
    echo "!! 원격에 닿지 못했습니다 · 지금 있는 코드로 빌드합니다" >&2
    return 0
  fi

  local upstream
  upstream="$(git -C "${WORKSPACE_DIR}" rev-parse --abbrev-ref \
    --symbolic-full-name '@{u}' 2>/dev/null || echo 'origin/main')"

  # **어떤 PC 든 이 명령 하나로 원격과 같아진다** · §6-102
  #
  # 예전에는 두 자리에서 사람 손을 요구했다.
  #   - 고친 파일이 있으면 수신을 건너뛰고 **옛 코드로 빌드**했다 · 조용한 실패라
  #     설치를 돌려도 코드가 그대로인 줄 몰랐다.
  #   - 이력이 갈라지면 `pull --ff-only` 가 실패하고 `set -e` 로 **스크립트가
  #     통째로 죽었다** · 빌드 근처에도 못 갔다.
  # 그래서 PC 마다 다른 명령을 손으로 치게 됐고, **그 자체가 다음 사고**가 됐다.
  #
  # 여기서는 원격에 맞추되 **아무것도 잃지 않는다** · 이 PC 에서 고친 파일은
  # `backups/` 로 떠 두고, 원격에 없는 커밋에는 표를 붙인다. 둘 다 되돌릴 수 있다.
  #
  # 서브모듈은 보지 않는다 · 빌드 찌꺼기(`__pycache__`)로 늘 "변경됨" 이라
  # 그것까지 세면 모든 PC 가 갱신을 멈춘다 · §6-99
  local stamp dirty backup_dir file
  stamp="$(date +%Y%m%d-%H%M%S)"
  dirty="$(git -C "${WORKSPACE_DIR}" status --porcelain \
    --untracked-files=no --ignore-submodules=all)"
  if [[ -n "${dirty}" ]]; then
    backup_dir="${WORKSPACE_DIR}/backups/pre-update-${stamp}"
    echo "이 PC 에서 고친 파일을 옮겨 둡니다 · ${backup_dir}"
    while read -r _ file; do
      [[ -z "${file}" || ! -f "${WORKSPACE_DIR}/${file}" ]] && continue
      mkdir -p "${backup_dir}/$(dirname "${file}")"
      cp -p "${WORKSPACE_DIR}/${file}" "${backup_dir}/${file}"
      echo "  ${file}"
    done <<< "${dirty}"
  fi

  if [[ -n "$(git -C "${WORKSPACE_DIR}" log --oneline "${upstream}..HEAD" 2>/dev/null)" ]]; then
    echo "이 PC 에만 있는 커밋에 표를 붙입니다 · pre-update-${stamp}"
    git -C "${WORKSPACE_DIR}" log --oneline "${upstream}..HEAD" | sed 's/^/  /'
    git -C "${WORKSPACE_DIR}" tag "pre-update-${stamp}" >/dev/null 2>&1 || true
  fi

  git -C "${WORKSPACE_DIR}" reset --hard "${upstream}"
  git -C "${WORKSPACE_DIR}" submodule update --init --recursive --force
  echo "원격과 같아졌습니다 · $(git -C "${WORKSPACE_DIR}" log --oneline -1)"
  if [[ -n "${dirty}" ]]; then
    echo
    echo "!! 고친 파일은 덮어썼습니다 · 필요하면 아래에서 가져오세요" >&2
    echo "!! ${backup_dir}" >&2
  fi
}

# 로봇 팩 검사기(MuJoCo)가 쓰는 uv · 사용자 자리(~/.local/bin)에 깐다 · 2026-10-02
#
# 로봇 팩 업로드는 `uv run --with mujoco ... sim_run.py --check` 로 model.xml 을
# 실제로 열어 본다 · uv 가 없으면 「실행기 로드 검사 불가: uv 없음」으로 팩을
# 받지 않는다 (미니 PC 실측) · 시스템 pip 에는 아무것도 깔지 않는다.
#
# 인터넷이 안 되면 설치 전체를 멈추지 않는다 · 경고만 남긴다 (모터 제어와 무관).
install_uv_and_mujoco() {
  local uv_bin="${HOME}/.local/bin/uv"
  if command -v uv >/dev/null 2>&1; then
    uv_bin="$(command -v uv)"
  elif [[ ! -x "${uv_bin}" ]]; then
    if ! curl -LsSf https://astral.sh/uv/install.sh | sh; then
      echo "!! uv 설치 실패 · 로봇 팩 업로드 검사가 안 됩니다 · 인터넷 확인 후 다시 실행하세요" >&2
      return 0
    fi
  fi
  if [[ ! -x "${uv_bin}" ]]; then
    echo "!! uv 를 찾지 못했습니다 · ${uv_bin}" >&2
    return 0
  fi
  echo "uv · $("${uv_bin}" --version)"
  # 첫 검사 때 mujoco 를 받느라 업로드가 오래 걸리지 않게 미리 받아 둔다
  if "${uv_bin}" run --no-project --with=mujoco --with=numpy --with=pyyaml \
      python -c 'import mujoco; print("mujoco", mujoco.__version__)'; then
    echo "MuJoCo 준비 완료"
  else
    echo "!! MuJoCo 미리 받기 실패 · 첫 로봇 팩 업로드 때 다시 받습니다" >&2
  fi
}

configure_locale_and_groups() {
  sudo locale-gen en_US en_US.UTF-8
  sudo update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
  sudo usermod -aG dialout,audio "$USER"
}

initialize_rosdep() {
  if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]]; then
    sudo rosdep init
  fi
  rosdep update
}

#: 죽은 노드가 남긴 공유메모리 조각을 치운다 · §6-298
#:
#: 노드가 비정상으로 죽으면 `/dev/shm` 에 Fast DDS 조각이 남는다 · 다음에 뜬
#: 노드가 같은 번호를 잡으면 **그 죽은 조각에 붙는다** · 그러면 보내는 쪽은
#: 초당 수천 건을 내보내는데 받는 쪽은 **한 건도 못 받는다** · 아무 오류도
#: 안 난다.
#:
#: 실측 · 모터 노드가 여덟 번 죽은 날 조각이 29개 쌓였고, 그중 하나를 밟아
#: 모터 피드백이 끊겼다 · 화면에는 「로컬 Web Bridge 응답 없음」으로 떠서
#: 원인을 찾는 데 한 시간이 걸렸다.
#:
#: **세 서비스가 전부 꺼졌을 때만 지운다** · 살아 있는 노드가 쓰는 조각을
#: 지우면 그 순간 통신이 끊긴다 · 여기는 갱신 절차가 셋을 모두 내린 직후라
#: 남은 것은 전부 쓰레기다.
clean_dead_dds_segments() {
  local unit
  for unit in motion-control motion-motor motion-coordination; do
    if systemctl --user is-active --quiet "${unit}.service"; then
      echo "[건너뜀] ${unit} 가 아직 돌고 있어 공유메모리를 건드리지 않습니다"
      return 0
    fi
  done
  local count
  # `ls … | wc -l` 은 조각이 하나도 없으면 ls 가 실패하고 pipefail 로 설치가 멈췄다(8단계 · 실물 2026-10-08) ·
  # find 는 없어도 성공한다
  count=$( { find /dev/shm -maxdepth 1 -name 'fastrtps_*' 2>/dev/null || true; } | wc -l)
  if [[ "${count}" -gt 0 ]]; then
    rm -f /dev/shm/fastrtps_* 2>/dev/null || true
    echo "죽은 공유메모리 조각 ${count}개 정리"
  fi
}

build_workspace() {
  systemctl --user stop motion-control.service motion-motor.service motion-coordination.service 2>/dev/null || true
  systemctl --user reset-failed 2>/dev/null || true
  clean_dead_dds_segments
  # 옛 작업공간이 환경에 남아 있으면 그쪽 경로를 먼저 본다 · 깨끗한 ROS 만 켠다
  unset AMENT_PREFIX_PATH CMAKE_PREFIX_PATH COLCON_PREFIX_PATH || true
  unset ROS_PACKAGE_PATH LD_LIBRARY_PATH PYTHONPATH || true
  # `CMAKE_INCLUDE_PATH`·`CMAKE_LIBRARY_PATH` 는 7단계가 정해 준 EtherCAT
  # 자리다 · 여기서 지우면 다시 못 찾는다
  set +u
  source /opt/ros/humble/setup.bash
  set -u
  if [[ "${CODE_ONLY}" == true ]]; then
    # 새 시스템 패키지를 깔려면 관리자 권한이 필요하다 · 빠진 것이 있으면 여기서 알리고 멈춘다
    if ! rosdep check --from-paths "${WORKSPACE_DIR}/src" --ignore-src; then
      echo "!! 이번 코드에 새 시스템 패키지가 필요합니다 · 이 PC 터미널에서 bash scripts/install.sh 로 설치하세요" >&2
      return 1
    fi
  else
    rosdep install --from-paths "${WORKSPACE_DIR}/src" --ignore-src -r -y
  fi
  # 지우고 처음부터 빌드한다 · §6-99
  #
  # `colcon` 은 **지워진 파일을 정리하지 않는다** · 꾸러미에서 파일이 빠지면
  # `install/` 에 옛 흔적(끊어진 링크 등)이 남아 다음 빌드가 거기서 깨진다 ·
  # 다른 PC 가 실제로 그렇게 멈췄다.
  #
  # 이 스크립트는 설치·업데이트 때만 돈다 · 1~2분 더 걸리는 대신 **늘 같은
  # 결과**가 나온다 · 빌드 상태를 사람이 추측할 일이 없어진다.
  rm -rf "${WORKSPACE_DIR}/build" "${WORKSPACE_DIR}/install"

  # `robot_manager` 는 심볼릭 링크로 깔지 않는다 · §6-102
  #
  # 이 꾸러미는 `ament_python` 인데 **소스 뿌리가 둘**이다.
  #     find_packages(where='robots/src') + find_packages(where='robot_manager/src')
  #     package_dir = {'robots': 'robots/src/robots', ...}
  # `--symlink-install` 은 `setup.py develop` 로 도는데, develop 은 뿌리 하나를
  # 전제해서 경로가 어긋난다 · `No such file or directory: .../robots/src/robots`
  # 가 그것이다. 예전에는 "한 번 더 빌드" 로 우연히 넘겼는데, 실패가 남는 PC 가
  # 있었다.
  #
  # 이 꾸러미는 합친 외부 코드(`src/motion_system`) 것이라 고치지 않는다 · 대신
  # **이것만** 평범하게 복사해 깐다. 우리가 손대는 꾸러미들은 그대로 심볼릭
  # 링크라 파이썬을 고치면 즉시 반영된다.
  echo "1/2 · robot_manager (심볼릭 링크 없이)"
  colcon build --base-paths "${WORKSPACE_DIR}/src" --packages-up-to robot_manager
  # 2단계는 **따로 도는 colcon** 이다 · 1단계가 깐 것을 환경으로 받아야
  # 거기 기대는 꾸러미가 파이썬 경로를 제대로 잡는다.
  #
  # 이 줄을 빠뜨렸더니 `motion_control_robot`(robot_manager 에 기댄다)과
  # `motion_state_monitor` 가 이렇게 죽었다:
  #     Fatal Python error: init_import_site: Failed to import the site module
  # 한 번에 빌드하던 때는 colcon 이 제 안에서 이어 줘서 필요 없던 줄이다 ·
  # 둘로 가르면서 그 이음매가 생겼다.
  set +u
  source "${WORKSPACE_DIR}/install/setup.bash"
  set -u
  echo "2/2 · 나머지 전부"
  colcon build --symlink-install --base-paths "${WORKSPACE_DIR}/src" \
    --packages-skip-up-to robot_manager
  if command -v ros2 >/dev/null 2>&1; then
    ros2 daemon stop || true
    ros2 daemon start || true
    ROS_DAEMON_UPDATED=true
  fi
}

install_user_services() {
  set +u
  source "${WORKSPACE_DIR}/install/setup.bash"
  set -u
  bash "${WORKSPACE_DIR}/src/web_bridge/deploy/install_user_service.sh"
}

restart_user_services() {
  systemctl --user daemon-reload
  systemctl --user restart motion-control.service || true
  systemctl --user restart motion-coordination.service || true
}

# IgH EtherCAT 이 **어디에 깔렸든** 찾아서 빌드·실행에 넘긴다 · §6-102
#
# 왜 PC 마다 결과가 달랐나.
#   피시1·2 : `--prefix=/opt/etherlab` 로 깔았고 `/usr/lib` 에도 복사돼 있었다.
#   피시3   : `--prefix=/usr/local/etherlab` 로 깔았다.
# `motor_manager/CMakeLists.txt` 가 뒤지는 자리는 고정돼 있다 ·
#   헤더 `/usr/local/include /usr/include /opt/etherlab/include`
#   라이브러리 `/usr/local/lib /usr/lib/x86_64-linux-gnu /usr/lib /opt/etherlab/lib`
# `/usr/local/etherlab/**` 은 **둘 다 없다.** 그래서 같은 코드가 한 PC 에서만
# 깨졌다. 깔린 자리 하나 차이였다.
#
# 게다가 옛 검사는 진짜 헤더를 못 찾으면 **빈 가짜 헤더**를 만들었다 · CMake 의
# `find_path` 는 통과하고 `find_library` 만 실패해서, "라이브러리가 없다" 는
# 엉뚱한 곳을 가리켰다. 있는 것을 없다고 판정하고 그 위에 가짜를 덮은 셈이다.
#
# 여기서는 자리를 **실제로 뒤져** 찾고, 찾으면 CMake 변수로 직접 넘긴다
# (`motor_manager` 가 덮어쓰라고 열어 둔 변수다) · 서브모듈은 건드리지 않는다.
ethercat_search_roots() {
  printf '%s\n' \
    /opt/etherlab \
    /usr/local/etherlab \
    /usr/local \
    /usr \
    /opt/ethercat \
    /usr/local/src/ethercat
}

find_ethercat_include_dir() {
  local root
  while read -r root; do
    # 크기가 0 인 것은 예전 설치가 만든 가짜다 · 진짜만 인정한다
    if [[ -s "${root}/include/ecrt.h" ]]; then
      echo "${root}/include"
      return 0
    fi
  done < <(ethercat_search_roots)
  local found
  found="$(find /opt /usr/local /usr/include -maxdepth 4 -name ecrt.h -size +0 \
    -print -quit 2>/dev/null || true)"
  [[ -n "${found}" ]] && dirname "${found}"
}

find_ethercat_library() {
  local root candidate
  while read -r root; do
    for candidate in "${root}/lib/libethercat.so" "${root}/lib/x86_64-linux-gnu/libethercat.so"; do
      if [[ -e "${candidate}" ]]; then
        echo "${candidate}"
        return 0
      fi
    done
  done < <(ethercat_search_roots)
  find /opt /usr/local /usr/lib -maxdepth 4 -name 'libethercat.so' -print -quit 2>/dev/null || true
}

register_ethercat_runtime_path() {
  # 빌드에서 찾아도 **실행할 때** 못 찾으면 소용없다 · ldconfig 에 등록한다
  local lib_dir="$1"
  if ldconfig -p 2>/dev/null | grep -q 'libethercat\.so'; then
    return 0
  fi
  echo "${lib_dir}" | sudo tee /etc/ld.so.conf.d/motion-etherlab.conf >/dev/null
  sudo ldconfig
  echo "EtherCAT 실행 경로 등록 · ${lib_dir}"
}

resolve_ethercat_paths() {
  local include_dir lib_file
  include_dir="$(find_ethercat_include_dir)"
  lib_file="$(find_ethercat_library)"

  if [[ -n "${include_dir}" && -n "${lib_file}" ]]; then
    echo "EtherCAT 헤더 · ${include_dir}/ecrt.h"
    echo "EtherCAT 라이브러리 · ${lib_file}"
    # `-D` 로 넘기면 그 변수를 안 쓰는 꾸러미마다 CMake 가 "쓰이지 않은
    # 변수" 경고를 낸다 · 경고가 쌓이면 진짜 오류가 묻힌다. CMake 가 표준으로
    # 읽는 탐색 경로를 쓴다 · `find_path`·`find_library` 가 HINTS 보다 **먼저**
    # 본다.
    export CMAKE_INCLUDE_PATH="${include_dir}${CMAKE_INCLUDE_PATH:+:${CMAKE_INCLUDE_PATH}}"
    export CMAKE_LIBRARY_PATH="$(dirname "${lib_file}")${CMAKE_LIBRARY_PATH:+:${CMAKE_LIBRARY_PATH}}"
    register_ethercat_runtime_path "$(dirname "${lib_file}")"
    # 예전 설치가 만든 빈 가짜 헤더는 치운다 · 두면 다음 사람이 또 속는다
    if [[ -f /opt/etherlab/include/ecrt.h && ! -s /opt/etherlab/include/ecrt.h \
          && "${include_dir}" != /opt/etherlab/include ]]; then
      sudo rm -f /opt/etherlab/include/ecrt.h
      echo "예전에 만들어 둔 빈 ecrt.h 를 지웠습니다"
    fi
    return 0
  fi

  echo
  echo "========================================="
  echo "EtherCAT 서보 모터 미설치 경고 (빌드는 진행됨)"
  echo "========================================="
  [[ -z "${include_dir}" ]] && echo "- ecrt.h 를 찾지 못했습니다"
  [[ -z "${lib_file}" ]] && echo "- libethercat.so 를 찾지 못했습니다"
  echo "찾아본 자리:"
  ethercat_search_roots | sed 's/^/  /'
  echo
  echo "EtherLab(IgH EtherCAT Master) 은 **모터에 안 써도 빌드에 필요**합니다 ·"
  echo "motor_manager 가 libethercat 에 링크합니다 (motor_manager/CMakeLists.txt) ·"
  echo "다이나믹셀만 써도 마찬가지입니다 · bash scripts/install.sh --site 가 설치합니다."
  echo "========================================="

  if [[ -z "${include_dir}" ]]; then
    # 빌드만 통과시키는 자리표시 헤더 · **진짜로 아무 데도 없을 때만** 만든다
    sudo mkdir -p /opt/etherlab/include
    sudo touch /opt/etherlab/include/ecrt.h
    echo "!! 빈 ecrt.h 를 만들었습니다 · AC 서보는 동작하지 않습니다" >&2
  fi
}

print_step "0. 사전 확인"
preflight_checks

print_step "1. Ubuntu 버전 확인"
require_ubuntu_2204

if [[ "${SITE_MODE}" == true ]]; then
  print_step "1-1. 현장 준비 (자동 업데이트·절전 끄기 · 자동 로그인 · 시간대 · 방화벽 · EtherLab)"
  prepare_site
fi

if [[ "${DRY_RUN}" == true ]]; then
  print_step "dry-run 끝"
  echo "실제 실행 때는 이어서 · 2 Git 수신 · 3 ROS 2 저장소 · 4 필수 프로그램 · 4-1 uv·MuJoCo · 5 권한·언어 · 6 rosdep · 7 EtherCAT 경로 · 8 전체 빌드 · 9 서비스 등록 · 10 적용 · 자가 점검"
  exit 0
fi

print_step "2. Git 코드 수신"
sync_git_repository

if [[ "${CODE_ONLY}" == true ]]; then
  print_step "3~6. 건너뜀 · 코드만 갱신 (시스템 패키지 · 권한 · rosdep 은 첫 설치 때 끝남)"
else
  print_step "3. ROS 2 저장소 확인"
  ensure_ros_apt_source

  print_step "4. 필수 프로그램 설치"
  install_system_packages

  print_step "4-1. 로봇 팩 검사기 (uv · MuJoCo)"
  install_uv_and_mujoco

  print_step "5. 사용자 권한·언어 설정"
  configure_locale_and_groups

  print_step "6. rosdep 초기화"
  initialize_rosdep
fi

print_step "7. EtherCAT 경로 확인"
resolve_ethercat_paths

print_step "8. 전체 빌드"
cd "${WORKSPACE_DIR}"
build_workspace

print_step "9. 자동실행 서비스 등록"
# 첫 설치에서는 실시간 권한 파일을 쓰고 78 로 끝난다(재부팅 필요) · 현장 준비 모드면 여기서
# 멈추지 않고 재부팅 뒤 이어가게 예약한다 · 옵션 없이 치면 전처럼 안내만 하고 끝난다
REBOOT_REQUIRED=false
if ! install_user_services; then
  rc=$?
  if [[ "${rc}" == "78" ]]; then
    REBOOT_REQUIRED=true
    site_mark_reboot "rtprio"
  else
    exit "${rc}"
  fi
fi

if [[ "${REBOOT_REQUIRED}" == true && "${SITE_MODE}" == true ]]; then
  print_step "재부팅 필요 · 재부팅 뒤 저절로 이어서 끝냅니다"
  site_schedule_resume "${WORKSPACE_DIR}"
  echo "재부팅 뒤 자동 로그인 → 설치가 이어서 돌고(몇 분) → 웹이 뜹니다 · 기록 · ${WORKSPACE_DIR}/log/site_setup/"
  if [[ "${AUTO_REBOOT}" == true ]]; then
    for i in 15 10 5; do echo "  ${i}초 뒤 재부팅 (Ctrl+C 로 취소 · 나중에 sudo reboot)"; sleep 5; done
    sudo reboot
  else
    echo "  지금 재부팅하세요 · sudo reboot"
  fi
  exit 0
fi
if [[ "${REBOOT_REQUIRED}" == true ]]; then
  echo "재부팅 뒤 같은 명령을 다시 실행하세요 · sudo reboot → bash scripts/install.sh" >&2
  exit 78
fi

print_step "10. 서비스 적용"
restart_user_services

print_step "설치 완료"
# 끝났는지 **눈으로 한 번에** 보이게 · 단계 제목만 지나가면 끝난 줄 알기 어렵다
echo "작업공간 · ${WORKSPACE_DIR}"
echo "코드     · $(git -C "${WORKSPACE_DIR}" log --oneline -1 2>/dev/null || echo '(git 아님)')"
echo "빌드     · $(find "${WORKSPACE_DIR}/install" -maxdepth 1 -mindepth 1 -type d 2>/dev/null | wc -l)개 꾸러미"
echo -n "서비스   · "
for unit in motion-control motion-motor motion-coordination; do
  echo -n "${unit}=$(systemctl --user is-active "${unit}.service" 2>/dev/null || echo unknown) "
done
echo
echo "웹 주소: http://localhost:8000"
echo "상태 확인: systemctl --user status --no-pager motion-control.service motion-coordination.service"
echo "설치 확인: bash ${WORKSPACE_DIR}/scripts/check.sh"
if [[ "${ROS_DAEMON_UPDATED}" == true ]]; then
  echo "ROS 2 daemon 초기화 완료"
fi
if [[ "${SITE_MODE}" == true || "${RESUME_MODE}" == true ]]; then
  print_step "11. 자가 점검"
  site_selfcheck "${WORKSPACE_DIR}"
  if [[ "${RESUME_MODE}" == true ]]; then
    site_cancel_resume
  fi
  site_clear_reboot
  echo
  echo "남은 수작업 · BIOS 「전원 복구 시 켜기」(1회) · 웹에서 로봇 팩 업로드 · 모터 관리 → 전체 모터 검색 → 설정 적용"
fi
