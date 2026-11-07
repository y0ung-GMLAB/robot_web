"""그룹 설정에서 실행 환경을 뽑는다 · §6-96

"이 PC 는 누구인가"와 "어느 DDS 망에 있는가"는 그룹 설정이 주인이다 ·
호스트 이름을 따로 읽으면 주인이 둘이 되고, 설정에서 `pc_id` 를 바꿨는데
토픽 이름은 호스트 이름을 따라가는 일이 생긴다.

ROS 를 켜기 전에 도는 코드라 표준 라이브러리만 쓴다.
"""

import re
import socket

from motion_common import topics
from motion_common.group_env import FALLBACK_DOMAIN_ID, exports, resolve

SAMPLE = """version: 2
pc_id: joonhoTest
display_name: joonhoTest
group_id: test1
dds_domain_id: 21
heartbeat_sec: 1.0
"""


def _config(tmp_path, text):
    path = tmp_path / 'motion_coordination.yaml'
    path.write_text(text, encoding='utf-8')
    return path


def test_it_takes_both_values_from_the_group_config(tmp_path):
    resolved = resolve(_config(tmp_path, SAMPLE))
    assert resolved['namespace'] == 'joonhoTest'
    assert resolved['domain_id'] == 21


def test_the_pc_id_wins_over_the_hostname(tmp_path):
    """설정에서 이름을 바꾸면 토픽 이름도 따라가야 한다 · 주인은 하나다."""
    resolved = resolve(_config(tmp_path, SAMPLE.replace('joonhoTest', 'stage_left')))
    assert resolved['namespace'] == 'stage_left'
    assert resolved['namespace'] != socket.gethostname()


# --------------------------------------------------------------------- #
# 설정이 없거나 깨져도 시스템은 떠야 한다
# --------------------------------------------------------------------- #

def test_a_missing_config_falls_back_to_the_hostname(tmp_path):
    resolved = resolve(tmp_path / 'nowhere.yaml')
    assert resolved['namespace'] == socket.gethostname()
    assert resolved['domain_id'] == FALLBACK_DOMAIN_ID


def test_an_empty_config_still_works(tmp_path):
    resolved = resolve(_config(tmp_path, ''))
    assert resolved['namespace'] == socket.gethostname()
    assert resolved['domain_id'] == FALLBACK_DOMAIN_ID


def test_a_missing_domain_uses_the_group_default(tmp_path):
    text = '\n'.join(
        line for line in SAMPLE.splitlines() if not line.startswith('dds_domain_id')
    )
    assert resolve(_config(tmp_path, text))['domain_id'] == FALLBACK_DOMAIN_ID


def test_a_broken_domain_does_not_crash_the_boot(tmp_path):
    for broken in ('abc', '', '-1', '999', '21.5'):
        text = SAMPLE.replace('dds_domain_id: 21', f'dds_domain_id: {broken}')
        resolved = resolve(_config(tmp_path, text))
        assert resolved['domain_id'] == FALLBACK_DOMAIN_ID, broken


def test_a_domain_at_the_edges_is_kept(tmp_path):
    for good in (0, 21, 101):
        text = SAMPLE.replace('dds_domain_id: 21', f'dds_domain_id: {good}')
        assert resolve(_config(tmp_path, text))['domain_id'] == good


def test_quoted_values_are_read(tmp_path):
    text = SAMPLE.replace('pc_id: joonhoTest', 'pc_id: "stage_left"')
    assert resolve(_config(tmp_path, text))['namespace'] == 'stage_left'


def test_a_similar_key_is_not_mistaken_for_the_real_one(tmp_path):
    """`display_name` 이나 주석이 `pc_id` 로 읽히면 안 된다."""
    text = '# pc_id: wrong\ndisplay_name: wrong\npc_id: right\ndds_domain_id: 21\n'
    assert resolve(_config(tmp_path, text))['namespace'] == 'right'


# --------------------------------------------------------------------- #
# 이름은 토픽에 쓸 수 있는 모양이어야 한다
# --------------------------------------------------------------------- #

#: 실제로 이 그룹에 있는 이름들이다 · 셋 다 하이픈이나 점이 들어간다
AWKWARD = ('pc-a', 'floating3-Ecolite-Series', 'stage.left', '3rd-pc')


def _resolve_pc_id(tmp_path, pc_id):
    text = SAMPLE.replace('pc_id: joonhoTest', f'pc_id: {pc_id}')
    return resolve(_config(tmp_path, text))


def test_the_name_can_be_used_as_a_ros_namespace(tmp_path):
    """`pc_id` 에는 하이픈이 들어간다(`pc-a`) · 그대로 넘기면 모터 노드가
    `__ns:=/pc-a` 를 거부해 **아예 뜨지 않는다** · 화면에 모터가 0대로 나온다.
    """
    for pc_id in AWKWARD:
        namespace = _resolve_pc_id(tmp_path, pc_id)['namespace']
        assert re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', namespace), (
            f'{pc_id} → {namespace} · ROS 이름으로 쓸 수 없다'
        )


def test_the_script_and_the_nodes_end_up_with_the_same_name(
    tmp_path, monkeypatch
):
    """실행 스크립트가 넘기는 값과 노드가 여는 토픽 이름이 갈리면 아무 말 없이
    통신이 끊긴다 · 규칙의 주인은 `topics.py` 하나이고, 여기서 그것을 지난다 ·
    갈리는 순간 이 검사가 잡는다.
    """
    for pc_id in AWKWARD + ('joonhoTest',):
        namespace = _resolve_pc_id(tmp_path, pc_id)['namespace']
        monkeypatch.setenv('MOTION_PC_NAMESPACE', namespace)
        assert topics.pc_namespace() == namespace, f'{pc_id} 에서 둘이 갈렸다'


# --------------------------------------------------------------------- #
# 바깥에서 덮어쓰기 · 되돌릴 수 있어야 한다
# --------------------------------------------------------------------- #

RESOLVED = {'namespace': 'joonhoTest', 'domain_id': 21}


def test_nothing_given_uses_the_config():
    assert exports(RESOLVED, {}) == [
        'export MOTION_PC_NAMESPACE="joonhoTest"',
        'export ROS_DOMAIN_ID="21"',
    ]


def test_what_is_given_from_outside_wins():
    lines = exports(RESOLVED, {'MOTION_PC_NAMESPACE': 'stage_left',
                               'ROS_DOMAIN_ID': '42'})
    assert lines == [
        'export MOTION_PC_NAMESPACE="stage_left"',
        'export ROS_DOMAIN_ID="42"',
    ]


def test_an_empty_name_is_a_choice_not_a_missing_value():
    """`MOTION_PC_NAMESPACE=` 는 이름표 끄기다 · 예전 이름으로 돌아간다 ·
    설정 값으로 덮어 버리면 되돌릴 길이 없어진다."""
    lines = exports(RESOLVED, {'MOTION_PC_NAMESPACE': ''})
    assert 'export MOTION_PC_NAMESPACE=""' in lines


def test_even_a_hand_written_name_goes_through_the_same_rule():
    """손으로 `pc-a` 를 넣어도 모터 노드가 받는 이름과 노드가 여는 토픽이
    갈리지 않아야 한다."""
    lines = exports(RESOLVED, {'MOTION_PC_NAMESPACE': 'pc-a'})
    assert 'export MOTION_PC_NAMESPACE="pc_a"' in lines


# --------------------------------------------------------------------- #
# PC 안쪽 노드 · 로컬 도메인 + 루프백 · 수정 목록 176
# --------------------------------------------------------------------- #

from motion_common.group_env import local_domain_id, local_exports  # noqa: E402


def _value(lines, name):
    prefix = f'export {name}="'
    found = [line[len(prefix):-1] for line in lines if line.startswith(prefix)]
    return found[-1] if found else None


def test_local_nodes_never_share_the_group_domain():
    """같은 도메인이면 그룹 쪽 디스커버리가 모터 · 웹 노드 소켓에도 쏟아진다 · 실물 NY 11-07."""
    for group in (0, 21, 42, 100, 101):
        assert local_domain_id(group) != group
        assert 0 <= local_domain_id(group) <= 101


def test_local_domain_is_the_next_number_by_default():
    assert local_domain_id(21) == 22
    assert local_domain_id(101) == 100, '끝 번호면 바로 앞'


def test_a_configured_local_domain_is_used_unless_it_collides():
    assert local_domain_id(21, 60) == 60
    assert local_domain_id(21, '60') == 60
    assert local_domain_id(21, 21) == 22, '그룹과 같으면 버린다'
    for broken in ('abc', '', '-1', '999', None):
        assert local_domain_id(21, broken) == 22, broken


def test_the_config_can_name_the_local_domain(tmp_path):
    resolved = resolve(_config(tmp_path, SAMPLE + 'local_dds_domain_id: 60\n'))
    assert resolved['local_domain_id'] == 60
    assert resolve(_config(tmp_path, SAMPLE))['local_domain_id'] == 22


def test_local_exports_lock_the_nodes_into_this_pc():
    lines = local_exports(RESOLVED, {})
    assert _value(lines, 'MOTION_PC_NAMESPACE') == 'joonhoTest', '이름표는 연동 노드와 같아야 한다'
    assert _value(lines, 'ROS_DOMAIN_ID') == '22'
    assert _value(lines, 'ROS_LOCALHOST_ONLY') == '1'
    assert _value(lines, 'MOTION_LOCAL_DDS') == '1', '손으로 띄우는 스크립트가 상속을 알아본다'


def test_an_inherited_group_domain_does_not_pull_local_nodes_back():
    """서비스 환경에 그룹 도메인이 남아 있어도 로컬 노드는 로컬 도메인 · 조용히 그룹에 다시 붙으면 안 된다."""
    lines = local_exports(RESOLVED, {'ROS_DOMAIN_ID': '21'})
    assert _value(lines, 'ROS_DOMAIN_ID') == '22'


def test_the_local_domain_can_be_set_by_hand():
    lines = local_exports(RESOLVED, {'MOTION_LOCAL_DOMAIN_ID': '60'})
    assert _value(lines, 'ROS_DOMAIN_ID') == '60'
    lines = local_exports(RESOLVED, {'MOTION_LOCAL_DOMAIN_ID': '21'})
    assert _value(lines, 'ROS_DOMAIN_ID') == '22', '손으로 넣어도 그룹과 같으면 버린다'


def test_local_dds_can_be_turned_back_off():
    """되돌리기 · `MOTION_LOCAL_DDS=0` → 옛 줄 그대로(그룹 도메인) · 루프백은 스크립트 가지가 정한다."""
    lines = local_exports(RESOLVED, {'MOTION_LOCAL_DDS': '0'})
    assert lines[:2] == exports(RESOLVED, {'MOTION_LOCAL_DDS': '0'})
    assert _value(lines, 'ROS_DOMAIN_ID') == '21'
    assert _value(lines, 'ROS_LOCALHOST_ONLY') is None
    assert _value(lines, 'MOTION_LOCAL_DDS') == '0'


def test_both_scopes_agree_on_the_name(tmp_path):
    """연동 노드(그룹)와 로컬 노드가 같은 PC 이름표를 써야 화면 · 기록이 갈리지 않는다."""
    resolved = resolve(_config(tmp_path, SAMPLE.replace('joonhoTest', 'pc-a')))
    assert _value(exports(resolved, {}), 'MOTION_PC_NAMESPACE') == \
        _value(local_exports(resolved, {}), 'MOTION_PC_NAMESPACE') == 'pc_a'
