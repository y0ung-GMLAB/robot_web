#!/usr/bin/env bash
# 커널이 바뀌어 EtherLab 모듈(ec_master)이 없거나 SDO 사전 읽기 끄기 패치(sdo_dict)가 빠졌으면 소스에서 다시 만든다
# 수정 목록 11-1 · 139 · 부팅 때 ethercat-rebuild.service 가 ethercat.service 보다 먼저 한 번 돈다 · 패치된 모듈이 있으면 바로 끝난다
#   --force   모듈이 멀쩡해도 다시 빌드 (사람이 손으로 · docs/수정_139_IgH_패치.md F)
# 커널 모듈만 만든다(make modules · modules_install · depmod) · CLI·라이브러리·ethercatctl·서비스는 건드리지 않는다 ·
# 지금 올라가 있는 모듈도 그대로(다음 `systemctl restart ethercat` 또는 부팅부터 새 모듈)
set -Eeuo pipefail
SRC="${ETHERLAB_SRC:-/usr/local/src/ethercat}"
# 설치(site.sh)가 고정 자리에 복사해 둔다 · 이 스크립트는 /usr/local/sbin 에서 돌아 작업공간 경로를 모른다
PATCH="${ETHERLAB_PATCH:-/usr/local/share/robot_web/igh-sdo-dict-off.patch}"
FORCE=0
for arg in "$@"; do
  case "${arg}" in
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,6p' "$0"; exit 0 ;;
    *) echo "알 수 없는 옵션 · ${arg} (--force 만 있음)" >&2; exit 2 ;;
  esac
done

# pipefail 아래 `modinfo | grep -q` 는 grep 이 먼저 끝나면 실패로 보일 수 있어 받아 두고 본다
module_patched() {
  local params
  params="$(modinfo -p ec_master 2>/dev/null || true)"
  grep -q '^sdo_dict:' <<<"${params}"
}

if [[ "${FORCE}" == 1 ]]; then
  echo "EtherLab 모듈 다시 빌드 (--force · $(uname -r) · ${SRC})"
elif module_patched; then
  exit 0
elif modinfo ec_master >/dev/null 2>&1; then
  echo "EtherLab 모듈에 SDO 사전 읽기 끄기(sdo_dict)가 없다 · 다시 빌드한다 (${SRC} · 수정 목록 139)"
else
  echo "EtherLab 모듈이 이 커널($(uname -r))에 없다 · 다시 빌드한다 (${SRC})"
fi
if [[ ! -f "${SRC}/configure" && ! -f "${SRC}/bootstrap" ]]; then
  echo "EtherLab 소스가 없다 · ${SRC} · bash scripts/install.sh --site 로 다시 설치" >&2
  exit 1
fi
if [[ ! -f "${PATCH}" ]]; then
  echo "IgH 패치 파일이 없다 · ${PATCH} · bash scripts/install.sh --site 로 다시 설치 · 수정 목록 139" >&2
  exit 1
fi
if ! dpkg -s "linux-headers-$(uname -r)" >/dev/null 2>&1; then
  apt-get install -y "linux-headers-$(uname -r)" || true
fi
cd "${SRC}"
# 패치 · 멱등 · 이미 들어갔으면 그대로 · 안 맞으면(IgH 버전이 바뀜) 패치 없는 모듈을 만들지 않고 멈춘다
if git apply --reverse --check "${PATCH}" 2>/dev/null; then
  echo "IgH 패치 이미 들어감 · ${PATCH}"
elif git apply --check "${PATCH}"; then
  git apply "${PATCH}"
  echo "IgH 패치 적용 · ${PATCH} (SDO 사전 자동 읽기 끔 · sdo_dict=0)"
else
  echo "!! IgH 패치가 소스(${SRC})에 안 맞음 · IgH 버전 확인 · 패치는 1.6.9 용 · 수정 목록 139" >&2
  exit 1
fi
[[ -f configure ]] || ./bootstrap
./configure --disable-8139too --enable-generic=yes
make -j"$(nproc)" modules
make modules_install
depmod
if ! module_patched; then
  echo "!! 새로 깐 ec_master 에 sdo_dict 가 없다 · $(modinfo -n ec_master 2>/dev/null || echo 모듈 없음) · 다른 자리(updates/ 등)의 옛 모듈이 먼저 잡히는지 확인 · 수정 목록 139" >&2
  exit 1
fi
echo "EtherLab 모듈 재빌드 완료 · $(modinfo -n ec_master 2>/dev/null) · sdo_dict 있음"
