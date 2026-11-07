"""그룹 설정에서 실행 환경을 뽑는다 · §6-96

"이 PC 는 누구인가"와 "어느 DDS 망에 있는가"는 그룹 설정이 주인이다 ·
`config/motion_coordination.yaml` 의 `pc_id` 와 `dds_domain_id`.

호스트 이름을 따로 읽으면 주인이 둘이 된다 · 설정에서 `pc_id` 를 바꿨는데
토픽 이름은 호스트 이름을 따라가면, 같은 PC 가 두 이름으로 불린다.

실행 스크립트가 ROS 를 켜기 **전에** 부르므로 표준 라이브러리만 쓴다.

    eval "$(python3 .../group_env.py)"          # 연동 노드 · 그룹 도메인 · 네트워크
    eval "$(python3 .../group_env.py --local)"  # 그 밖의 노드 · 이 PC 안(루프백) · 수정 목록 176
"""

from __future__ import annotations

import os
import re
import socket
import sys
from pathlib import Path

# 이름을 토픽에 쓸 수 있는 모양으로 바꾸는 규칙은 `topics.py` 가 주인이다 ·
# 여기서 따로 적으면 둘이 갈린다 · 실제로 `pc_id` 에 하이픈이 있으면
# (`pc-a`, `floating3-Ecolite-Series`) 파이썬 노드는 `pc_a` 를 열고 모터
# 노드는 `/pc-a` 를 받아 **아예 뜨지도 못한다**.
#
# ROS 를 켜기 전이라 경로를 직접 넣는다 · `topics.py` 는 표준 라이브러리만 쓴다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from motion_common.topics import sanitize_namespace  # noqa: E402

#: 설정을 못 읽어도 시스템은 떠야 한다 · 그룹 기본값과 같은 값
FALLBACK_DOMAIN_ID = 21

#: ROS 2 도메인 번호 범위 · 기본 포트 계산에서 PC 한 대에 참가자가 넉넉히 들어가는 곳까지
MAX_DOMAIN_ID = 101

# PC 안쪽 노드의 DDS · 수정 목록 176 (실물 NY 2026-11-07)
#
# 전에는 모터 · 모니터 · 실행 · 웹 노드까지 모두 그룹 도메인에서 Wi-Fi 로 열려 있었다(§6-96) ·
# 그러자 Wi-Fi 가 막히거나 끊길 때 **같은 PC 안의** 모터 상태까지 늦거나 끊겼다 · Wi-Fi 가
# 7분 끊겼다 돌아온 floating2 는 재부팅 전까지 「연결되지 않은 모터 0~4」 에서 못 돌아왔다
# (Fast DDS 는 참가자를 만든 순간의 랜카드만 본다 · net_ready.py) · 4대가 같은 몇 초 동안
# 재생 루프가 밀린 것도 같은 때다.
#
# PC 끼리 만나는 일은 연동 노드 하나가 맡는다(그룹 토픽만 · 로컬과는 HTTP) · 그 밖의 노드는
# 다른 PC 토픽을 쓰지 않는다 · 그래서 이 PC 안(루프백)에만, 그룹과 **다른 도메인**에 둔다 ·
# 같은 도메인에 두면 그룹 쪽 디스커버리가 이 노드들 소켓에도 쏟아진다.
#
# 되돌리기 · `MOTION_LOCAL_DDS=0` (옛 방식 · 그룹 도메인 · `MOTION_GROUP_NETWORK` 를 따름).
LOCAL_DDS_ENV = 'MOTION_LOCAL_DDS'
#: 로컬 도메인을 손으로 정할 때 · `ROS_DOMAIN_ID` 는 그룹 값이 상속돼 있을 수 있어 따로 둔다
LOCAL_DOMAIN_ENV = 'MOTION_LOCAL_DOMAIN_ID'


def local_domain_id(group_domain_id: int, configured: object = None) -> int:
    """PC 안쪽 노드의 도메인 · 그룹 도메인과 **반드시 다르다**.

    설정(`local_dds_domain_id`)이 올바르고 그룹과 다르면 그것 · 아니면 그룹 바로 다음 번호
    (끝 번호면 바로 앞) · 루프백에만 열리므로 다른 PC · 다른 그룹과 겹쳐도 상관없다.
    """
    try:
        value = int(str(configured).strip())
    except (TypeError, ValueError):
        value = -1
    if 0 <= value <= MAX_DOMAIN_ID and value != group_domain_id:
        return value
    return group_domain_id + 1 if group_domain_id < MAX_DOMAIN_ID else group_domain_id - 1


def _read_scalar(text: str, key: str) -> str:
    """아주 단순한 YAML 한 줄 읽기 · ROS 를 켜기 전이라 pyyaml 이 없다."""
    match = re.search(rf'^{re.escape(key)}\s*:\s*(.+?)\s*$', text, re.M)
    if not match:
        return ''
    return match.group(1).strip().strip('"').strip("'")


def resolve(config_path: Path) -> dict:
    """이름공간과 도메인 · 설정이 없거나 깨져도 쓸 수 있는 값을 돌려준다.

    이름은 토픽에 쓸 수 있는 모양으로 돌려준다 · 여기서 정리해 두어야 모터
    노드에 넘기는 `__ns` 와 파이썬 노드가 여는 토픽이 **같은 이름**이 된다.
    """
    pc_id = ''
    domain = ''
    local = ''
    try:
        text = config_path.read_text(encoding='utf-8')
    except OSError:
        text = ''
    if text:
        pc_id = _read_scalar(text, 'pc_id')
        domain = _read_scalar(text, 'dds_domain_id')
        local = _read_scalar(text, 'local_dds_domain_id')

    namespace = sanitize_namespace(pc_id or socket.gethostname())
    try:
        domain_id = int(domain)
    except (TypeError, ValueError):
        domain_id = FALLBACK_DOMAIN_ID
    if not 0 <= domain_id <= MAX_DOMAIN_ID:
        domain_id = FALLBACK_DOMAIN_ID
    return {
        'namespace': namespace,
        'domain_id': domain_id,
        'local_domain_id': local_domain_id(domain_id, local),
    }


def exports(resolved: dict, environ) -> list:
    """셸이 그대로 삼킬 두 줄.

    **바깥에서 이미 정했으면 그것을 존중한다** · 되돌릴 수 있어야 한다 ·
    빈 값으로 둔 것도 뜻이 있다(`MOTION_PC_NAMESPACE=` · 이름표 끄기) ·
    그래서 "안 정했다"와 "비워 뒀다"를 가른다.

    덮어쓴 값도 **같은 규칙을 지난다** · 손으로 `pc-a` 를 넣어도 모터 노드가
    받는 이름과 노드가 여는 토픽이 갈리지 않아야 한다.
    """
    given = environ.get('MOTION_PC_NAMESPACE')
    namespace = (
        resolved['namespace'] if given is None else sanitize_namespace(given)
    )
    domain = (environ.get('ROS_DOMAIN_ID') or '').strip()
    return [
        f'export MOTION_PC_NAMESPACE="{namespace}"',
        f'export ROS_DOMAIN_ID="{domain or resolved["domain_id"]}"',
    ]


def local_exports(resolved: dict, environ) -> list:
    """PC 안쪽 노드(모터 · 모니터 · 실행 · 웹)의 줄 · 수정 목록 176

    이름표는 연동 노드와 같다 · 도메인은 그룹과 다른 로컬 도메인 · 루프백에만 연다 ·
    `ROS_DOMAIN_ID` 는 보지 않는다 · 그룹 값이 상속돼 있으면 조용히 그룹에 다시 붙는다 ·
    손으로 정할 때는 `MOTION_LOCAL_DOMAIN_ID`.

    `MOTION_LOCAL_DDS=0` 이면 옛 줄 그대로(그룹 도메인 · 루프백 여부는 실행 스크립트의
    `MOTION_GROUP_NETWORK` 가지가 정한다).
    """
    if str(environ.get(LOCAL_DDS_ENV, '1')).strip() == '0':
        return exports(resolved, environ) + [f'export {LOCAL_DDS_ENV}="0"']
    namespace_line = exports(resolved, environ)[0]
    group_domain = int(resolved['domain_id'])
    local = local_domain_id(
        group_domain,
        environ.get(LOCAL_DOMAIN_ENV) or resolved.get('local_domain_id'),
    )
    return [
        namespace_line,
        f'export ROS_DOMAIN_ID="{local}"',
        'export ROS_LOCALHOST_ONLY="1"',
        f'export {LOCAL_DDS_ENV}="1"',
    ]


def main() -> int:
    workspace = Path(
        os.environ.get('MOTION_WORKSPACE') or Path.cwd()
    ).resolve()
    config_path = Path(
        os.environ.get('MOTION_COORDINATION_CONFIG')
        or workspace / 'config/motion_coordination.yaml'
    ).expanduser()
    build = local_exports if '--local' in sys.argv[1:] else exports
    for line in build(resolve(config_path), os.environ):
        print(line)
    return 0


if __name__ == '__main__':
    sys.exit(main())
