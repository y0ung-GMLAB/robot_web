#!/usr/bin/env bash
# 커널이 바뀌어 EtherLab 모듈(ec_master)이 없으면 소스에서 다시 만든다 · 수정 목록 11-1
# 부팅 때 ethercat-rebuild.service 가 ethercat.service 보다 먼저 한 번 돈다 · 모듈이 있으면 바로 끝난다
set -Eeuo pipefail
SRC="${ETHERLAB_SRC:-/usr/local/src/ethercat}"
if modinfo ec_master >/dev/null 2>&1; then
  exit 0
fi
echo "EtherLab 모듈이 이 커널($(uname -r))에 없다 · 다시 빌드한다 (${SRC})"
if [[ ! -f "${SRC}/configure" && ! -f "${SRC}/bootstrap" ]]; then
  echo "EtherLab 소스가 없다 · ${SRC} · bash scripts/install.sh --site 로 다시 설치" >&2
  exit 1
fi
if ! dpkg -s "linux-headers-$(uname -r)" >/dev/null 2>&1; then
  apt-get install -y "linux-headers-$(uname -r)" || true
fi
cd "${SRC}"
[[ -f configure ]] || ./bootstrap
./configure --disable-8139too --enable-generic=yes
make -j"$(nproc)" modules
make modules_install
depmod
echo "EtherLab 모듈 재빌드 완료"
