"""실행기 밖 구독 · 마지막 한 장만 꺼낸다 · 수정 목록 130 · rclpy 없이 대역으로"""

from motion_common import latest_tap


class _Handle:
    def __init__(self, queue):
        self.queue = list(queue)
        self.entered = 0

    def __enter__(self):
        self.entered += 1
        return self

    def __exit__(self, *_exc):
        return False

    def take_message(self, msg_type, raw):
        assert msg_type == 'MotorStatus'
        assert raw is True
        if not self.queue:
            return None
        return (self.queue.pop(0), {'source_timestamp': 0})


class _Subscription:
    def __init__(self, queue):
        self.handle = _Handle(queue)
        self.msg_type = 'MotorStatus'
        self.raw = True


class _Node:
    created = []

    def __init__(self, name, **kwargs):
        self.name = name
        self.kwargs = kwargs
        self.destroyed = False
        self.subscriptions = []
        _Node.created.append(self)

    def create_subscription(self, msg_type, topic, callback, qos, raw=False):
        subscription = _Subscription(['a', 'b', 'c'])
        self.subscriptions.append((msg_type, topic, qos, raw, subscription))
        return subscription

    def destroy_node(self):
        self.destroyed = True


class _Parent:
    context = 'ctx'

    def get_name(self):
        return 'motion_run_manager'

    def get_namespace(self):
        return '/floating4'


def test_take_latest_drains_and_returns_the_newest():
    tap = latest_tap.LatestMessageTap(_Subscription([b'1', b'2', b'3']))
    assert tap.take_latest() == b'3'
    assert tap.take_latest() is None


def test_open_tap_builds_a_side_node_that_is_never_spun():
    _Node.created.clear()
    tap = latest_tap.open_tap(
        _Parent(), 'MotorStatus', '/floating4/motion_control/motor_status',
        node_class=_Node, qos='depth-1', raw=True, suffix='motor_status_tap',
    )
    node = _Node.created[-1]
    assert node.name == 'motion_run_manager_motor_status_tap'
    assert node.kwargs['namespace'] == '/floating4'
    assert node.kwargs['context'] == 'ctx'
    assert node.kwargs['start_parameter_services'] is False
    assert node.subscriptions[0][:4] == (
        'MotorStatus', '/floating4/motion_control/motor_status', 'depth-1', True,
    )
    assert tap.take_latest() == 'c'
    tap.close()
    assert node.destroyed is True
    assert tap.take_latest() is None
    tap.close()   # 두 번 닫아도 된다


def test_open_tap_returns_none_so_the_caller_falls_back():
    warnings = []

    class _Broken:
        def __init__(self, *_args, **_kwargs):
            raise TypeError('old rclpy')

    logger = type('L', (), {'warning': lambda _self, text: warnings.append(text)})()
    assert latest_tap.open_tap(
        _Parent(), 'MotorStatus', '/t', node_class=_Broken, qos=None, logger=logger,
    ) is None
    assert warnings and '/t' in warnings[0]


def test_a_closing_handle_is_treated_as_empty():
    class _Closing(_Handle):
        def __enter__(self):
            raise RuntimeError('InvalidHandle')

    subscription = _Subscription([])
    subscription.handle = _Closing([b'x'])
    assert latest_tap.LatestMessageTap(subscription).take_latest() is None
