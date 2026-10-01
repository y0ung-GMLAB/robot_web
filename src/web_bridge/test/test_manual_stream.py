"""수동 스트림(페이더) 중계 · 발사 후 망각 + 축별 마지막 결과.

20Hz 로 흘리는 경로라 조그처럼 요청마다 응답을 기다리지 않는다 ·
supervisor 의 축별 임대(0.15s)가 안전을 쥐고, 여기는 **그대로 싣고 ·
마지막 거부 사유만 돌려준다**.
"""

import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

# Windows 시험 환경에는 ROS 메시지가 없다 · 모양만 같은 대역을 세운다
if 'std_msgs.msg' not in sys.modules:
    std_msgs = types.ModuleType('std_msgs')
    msg_module = types.ModuleType('std_msgs.msg')

    class _String:
        def __init__(self, data=''):
            self.data = data

    msg_module.String = _String
    std_msgs.msg = msg_module
    sys.modules.setdefault('std_msgs', std_msgs)
    sys.modules['std_msgs.msg'] = msg_module

from motion_web_bridge.manual_stream import ManualStreamService  # noqa: E402

BRIDGE_DIR = Path(__file__).resolve().parents[1] / 'motion_web_bridge'


class _Publisher:
    def __init__(self):
        self.sent = []

    def publish(self, msg):
        self.sent.append(json.loads(msg.data))


def _service(generation=7):
    publisher = _Publisher()
    bridge = SimpleNamespace(current_project_generation=lambda: generation)
    return ManualStreamService(bridge, publisher=publisher), publisher


def _result_msg(payload):
    return SimpleNamespace(data=json.dumps(payload, ensure_ascii=False))


def test_send_target_publishes_one_generation_tagged_request():
    service, publisher = _service(generation=7)
    result = service.send_target(2, 36.5, motion_id='Neck_Yaw', motion_deg=0.365)
    assert result['success'] is True
    [request] = publisher.sent
    assert request['axis'] == 2
    assert request['target_deg'] == 36.5
    assert request['motion_id'] == 'Neck_Yaw'
    assert request['motion_deg'] == 0.365
    assert '-g7-' in request['request_id']
    assert request['project_generation'] == 7


def test_bad_inputs_are_refused_without_publishing():
    service, publisher = _service()
    assert service.send_target(None, 10.0)['success'] is False
    assert service.send_target(-1, 10.0)['success'] is False
    assert service.send_target(0, 'nan')['success'] is False
    assert service.send_target(0, None)['success'] is False
    assert publisher.sent == []


def test_release_becomes_a_hold_request_with_deduped_axes():
    service, publisher = _service()
    result = service.hold([3, '3', 0, None, 'x'])
    assert result['success'] is True
    [request] = publisher.sent
    assert request['hold_axes'] == [3, 0]
    assert service.hold([])['success'] is False
    assert len(publisher.sent) == 1


def test_results_keep_only_the_last_entry_per_axis():
    service, _ = _service(generation=7)
    service.result_callback(_result_msg({
        'request_id': 'stream-g7-1', 'axis': 0, 'success': False, 'message': '먼저',
    }))
    service.result_callback(_result_msg({
        'request_id': 'stream-g7-2', 'axis': 0, 'success': True, 'message': '나중',
    }))
    stored = service.pop_result(0)
    assert stored['message'] == '나중'
    assert service.pop_result(0) is None


def test_batch_results_fan_out_per_axis():
    service, _ = _service(generation=7)
    service.result_callback(_result_msg({
        'request_id': 'stream-g7-3',
        'results': [
            {'axis': 1, 'success': True, 'message': 'a'},
            {'axis': 2, 'success': False, 'message': 'b'},
        ],
    }))
    assert service.pop_result(1)['message'] == 'a'
    assert service.pop_result(2)['message'] == 'b'


def test_stale_generation_results_are_dropped():
    service, _ = _service(generation=7)
    service.result_callback(_result_msg({
        'request_id': 'stream-g6-9', 'axis': 0, 'success': True, 'message': '옛 세대',
    }))
    assert service.pop_result(0) is None


def test_project_change_clears_held_results():
    service, _ = _service(generation=7)
    service.result_callback(_result_msg({
        'request_id': 'stream-g7-1', 'axis': 0, 'success': True, 'message': 'x',
    }))
    service.clear_pending()
    assert service.pop_result(0) is None


# --------------------------------------------------------------------------- #
# 배선 · 끊기면 잡은 곳에 세우고, 오프 모드 문이 달려 있다
# --------------------------------------------------------------------------- #

def test_bridge_wires_publisher_subscription_and_project_clear():
    source = (BRIDGE_DIR / 'bridge_node.py').read_text(encoding='utf-8')
    assert 'self.manual_stream = ManualStreamService(' in source
    assert 'self.manual_stream_request_topic' in source
    assert 'lambda msg: self.manual_stream.result_callback(msg)' in source
    assert 'self.manual_stream.clear_pending()' in source
    assert 'register_stream_routes(app, bridge)' in source


def test_websocket_route_gates_off_mode_and_holds_on_disconnect():
    route = (BRIDGE_DIR / 'routes' / 'stream_routes.py').read_text(encoding='utf-8')
    assert "@app.websocket('/ws/manual-stream')" in route
    # 길목은 받아서 넘기기만 한다 · 업무는 세션 모듈에 있다
    assert 'run_manual_stream_socket(bridge, websocket)' in route
    source = (BRIDGE_DIR / 'manual_stream_socket.py').read_text(encoding='utf-8')
    assert 'motion_command_block_reason' in source
    # 흐르는 중에도 다시 확인한다 · 상단에서 오프로 바꾸면 끊긴다
    assert 'BLOCK_RECHECK_SEC' in source
    # 낡은 변환표 거절 · 매핑이 바뀐 화면은 그대로 흘릴 수 없다
    assert 'base_mapping_revision' in source
    assert 'load_motion_mapping' in source
    # 끊기면 만졌던 축을 현재 위치에 세운다 (finally · 어떤 길로 나가도)
    assert 'finally:' in source
    assert 'await asyncio.to_thread(service.hold, list(touched_axes))' in source
