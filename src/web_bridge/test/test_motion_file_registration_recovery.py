"""재생 등록은 조인트 매핑과 남남이다 · §6-160

**모션 데이터만 건드렸는데 조인트 매핑 창이 떴다.**

    조인트 매핑 저장 충돌
    저장된 조인트 매핑과 이 화면이 기준으로 삼은 설정이 다릅니다.
    현재 편집 내용은 저장되지 않았습니다.

모션 실행 화면에서 `재생 등록` 을 눌렀을 뿐인데 이런 창이 떴다 · 편집한 적도
없는 설정을 되돌릴지 물으니 무슨 말인지 알 수가 없다.

조인트 매칭 파일 하나에 **주인이 셋**이기 때문이었다.

    mappings        조인트 매핑 화면
    midi_banks      MIDI 입력 설정 화면
    motion_file_id  모션 실행 화면 (재생 등록)

MIDI 는 오래전에 제 길을 얻었는데(`save_midi_banks`) 재생 등록만
「설정 전체 저장」 길로 다녔다 · 그 길에는 두 가지가 딸려 있다 ·
편집 중인 설정까지 같이 저장되고, 설정 개정 검사에 걸린다.

곁가지로 버튼까지 죽었다 · 저장 전에 「편집 중」 표시를 세워 놓고 저장에
실패하면 그 표시가 남았는데, 두 버튼의 비활성 조건에 그 표시가 들어 있었다 ·
프로그램이 제 손으로 세운 표시가 제 발을 묶어 되돌아갈 길이 사라졌다.

여기서 지키는 것 : **셋은 서로 상관하지 않는다.**
"""

from pathlib import Path

WORKSPACE = Path(__file__).resolve().parents[3]
MANAGER = (
    WORKSPACE
    / 'src/motion_runtime/motion_runtime'
    / 'motion_mapping_manager.py'
)
ROUTES = (
    WORKSPACE
    / 'src/web_bridge/motion_web_bridge/routes/motion_run_routes.py'
)
BRIDGE = WORKSPACE / 'src/web_bridge/motion_web_bridge/bridge_node.py'


def _function(source: str, name: str) -> str:
    """`name` 함수의 몸통 · 들여쓰기가 돌아올 때까지."""
    start = source.index(f'function {name}(')
    line_start = source.rindex('\n', 0, start) + 1
    indent = len(source[line_start:start]) - len(source[line_start:start].lstrip())
    lines = source[line_start:].splitlines()
    body = [lines[0]]
    for line in lines[1:]:
        body.append(line)
        if line.strip() and line.startswith(' ' * indent + '}'):
            break
    return '\n'.join(body)


# --------------------------------------------------------------------------- #
# 버튼 · 조인트 매핑을 편집 중이어도 눌린다
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 저장 경로 · 설정 전체를 보내지 않는다
# --------------------------------------------------------------------------- #


# --------------------------------------------------------------------------- #
# 개정 번호 · 제 주인의 것만 센다
# --------------------------------------------------------------------------- #

def test_the_revision_ignores_the_registration():
    """재생 등록이 바뀌었다고 조인트 매핑이 바뀐 것으로 세면 안 된다.

    **글자가 아니라 값을 잰다** · §6-242

    전에는 이 시험이 소스에서 `key != 'motion_file_id'` 라는 **글자**를
    찾았다 · 그래서 빼는 칸을 하나 더 늘려 고쳤더니, 동작은 더 맞아졌는데
    시험이 깨졌다 · 재는 것이 틀렸던 것이다 · 이제 함수를 직접 불러 본다.
    """
    import sys
    sys.path.insert(0, str(MANAGER.parent.parent))
    from motion_runtime.motion_mapping_manager import MotionMappingManager

    base = {
        'file_id': 'show.yaml',
        'name': 'show',
        'motion_file_id': '',
        'mappings': [{'motion_id': '1-1', 'enabled': True, 'motor_axis': 0}],
    }

    assert MotionMappingManager._mapping_revision(dict(base)) == (
        MotionMappingManager._mapping_revision({**base, 'motion_file_id': 'show.json'})
    ), '개정 번호가 아직 재생 등록을 센다 · 모션 파일만 바꿔도 창이 뜬다'

    assert MotionMappingManager._mapping_revision(dict(base)) == (
        MotionMappingManager._mapping_revision({**base, 'midi_banks': {'version': 1}})
    ), '개정 번호가 아직 MIDI 뱅크를 센다 · 저장 한 번 뒤 다음 저장이 막힌다'

    assert MotionMappingManager._mapping_revision(dict(base)) != (
        MotionMappingManager._mapping_revision({
            **base, 'mappings': [{'motion_id': '1-1', 'enabled': True, 'motor_axis': 1}],
        })
    ), '조인트 매핑을 고쳤는데 개정 번호가 그대로다'


def test_running_motion_still_blocks_the_swap():
    """도는 중에 재생 파일이 바뀌면 다음 회차가 무엇을 돌지 알 수 없다.

    풀어야 할 것은 「조인트 매핑 편집 중」 이지 「모션이 도는 중」 이 아니다.
    """
    source = BRIDGE.read_text(encoding='utf-8')
    start = source.index('def save_registered_motion_file(')
    body = source[start:source.index('def save_motion_mapping(', start)]

    assert 'change_blocker()' in body, (
        '모션이 도는 중에도 재생 파일을 갈아 끼울 수 있습니다'
    )
