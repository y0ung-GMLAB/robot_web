"""Opt-in real DDS process test; enable with MOTION_RUN_DDS_INTEGRATION=1.

여러 PC 를 한 기계에서 · 실제 연동 노드 프로세스 여럿 + 이 시험 프로세스의 가짜 PC · 수정 목록 209

- 그룹 도메인(설정 `dds_domain_id`) · 연동 노드끼리 · 네트워크
- 로컬 도메인(`MOTION_LOCAL_DOMAIN_ID` · 루프백) · PC 마다 이름표(`MOTION_PC_NAMESPACE`)로 가른다 · 연동 노드의
  로컬 연결(`local_link.py`) ↔ 가짜 재생 관리자 · 감독(이 프로세스의 두 번째 rclpy 컨텍스트)
- 가짜 웹(HTTP) · 준비 검사 · 웹 쪽 칸 · 웹만 아는 일(운영 로그 · 복귀 준비 · 주차) · 로컬 연결이 없을 때 되돌리기 길

빌드(WSL · 시험 끝나면 지운다) ·
`colcon build --symlink-install --base-paths src/motion_common src/motion_coordination --packages-select motion_common
motion_coordination` · 실행 파일 경로를 `MOTION_COORDINATION_EXECUTABLE` 로 · 여러 PC 모의의 바탕(나중에 시뮬레이션).
"""

import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from motion_common.group_config import GroupConfig, save_group_config


pytestmark = pytest.mark.skipif(
    os.environ.get('MOTION_RUN_DDS_INTEGRATION') != '1',
    reason='real DDS process integration is opt-in',
)

#: 가짜 재생 관리자의 실행 설정 · 준비 검사가 돌려주는 값과 같다
FAKE_CONTEXT = {'project_id': 'project-dds', 'project_generation': 1, 'context_id': 'ctx-dds', 'ready': True}
#: 재생 관리자 명령 → 연동 로컬 명령 이름(웹 길과 같은 이름으로 센다)
_RUNTIME_ALIASES = {'stop': 'stop_now'}


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(('127.0.0.1', 0))
        return int(sock.getsockname()[1])


def _get(port, path='/status'):
    with urllib.request.urlopen(
        f'http://127.0.0.1:{port}{path}', timeout=1.0,
    ) as response:
        return json.loads(response.read().decode('utf-8'))


def _post(port, command):
    request = urllib.request.Request(
        f'http://127.0.0.1:{port}/control',
        data=json.dumps({'command': command}).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    with urllib.request.urlopen(request, timeout=1.0) as response:
        return json.loads(response.read().decode('utf-8'))


def _wait(predicate, timeout=8.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
            if last:
                return last
        except OSError:
            pass
        time.sleep(0.1)
    raise AssertionError(f'DDS integration timeout: {last!r}')


def _one_peer_snapshot(port):
    value = _get(port)
    return value if len(value.get('peers') or []) == 1 else None


def _executable():
    path = Path(
        os.environ.get('MOTION_COORDINATION_EXECUTABLE')
        or Path.cwd()
        / 'install/motion_coordination/lib/motion_coordination/'
        'motion_coordination_node'
    )
    if not path.is_file():
        pytest.skip('motion_coordination_node is not built')
    return path


class _LocalDomain:
    """이 시험 프로세스의 로컬 도메인 컨텍스트 하나 · 가짜 PC 노드들을 돌린다 · 루프백만"""

    def __init__(self, domain_id):
        import rclpy
        from rclpy.context import Context
        from rclpy.executors import MultiThreadedExecutor
        from rclpy.signals import SignalHandlerOptions

        self.domain_id = int(domain_id)
        self.context = Context()
        previous = os.environ.get('ROS_LOCALHOST_ONLY')
        os.environ['ROS_LOCALHOST_ONLY'] = '1'
        try:
            rclpy.init(
                context=self.context, domain_id=self.domain_id,
                signal_handler_options=SignalHandlerOptions.NO,
            )
        finally:
            if previous is None:
                os.environ.pop('ROS_LOCALHOST_ONLY', None)
            else:
                os.environ['ROS_LOCALHOST_ONLY'] = previous
        self.executor = MultiThreadedExecutor(num_threads=4, context=self.context)
        self.nodes = []
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def _spin(self):
        from rclpy.executors import ExternalShutdownException
        try:
            self.executor.spin()
        except ExternalShutdownException:
            pass

    def add(self, node):
        self.nodes.append(node)
        self.executor.add_node(node)

    def close(self):
        self.executor.shutdown(timeout_sec=2.0)
        self._thread.join(timeout=3.0)
        for node in self.nodes:
            node.destroy_node()
        self.context.try_shutdown()


class _FakeLocalPC:
    """가짜 PC 하나 · 웹(HTTP) + 재생 관리자 · 감독(로컬 DDS) · 받은 명령을 `via`(dds · http)와 함께 센다"""

    def __init__(self, domain, namespace, *, cycle_duration_sec, start_trigger_delays=None):
        from rclpy.node import Node
        from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
        from std_msgs.msg import String

        self._lock = threading.RLock()
        self._timers = []
        self.namespace = namespace
        self.cycle_duration_sec = float(cycle_duration_sec)
        self.control_calls = []
        self.cycle_ready_at = {}
        self.cycle_initialized_at = {}
        self.motion_started_at = {}
        self.start_trigger_delays = list(start_trigger_delays or [])
        self.safety_stops = 0
        self.alive_count = 0
        self.web_alive = True
        self._motion_status = {}
        self._String = String
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                if not owner.web_alive:
                    self.close_connection = True
                    return
                # `?link=down` · 연동 노드가 로컬 연결 없이 웹 길로 되돌린 동안(209 되돌리기 길의 「살아 있음」)
                if self.path.split('?', 1)[0] != '/api/coordination/local-status':
                    self._send(404, {'success': False})
                    return
                with owner._lock:
                    status = dict(owner._motion_status)
                self._send(200, {
                    'bridge_state': 'ok',
                    'ready': True,
                    'bridge_instance_id': f'web-{owner.namespace}',
                    'operation_mode': '',
                    'motion_run_status': status,
                    'safety_status': {'servo_alarm_grade': 0, 'servo_alarm_active': []},
                })

            def do_POST(self):  # noqa: N802
                if not owner.web_alive:
                    self.close_connection = True
                    return
                length = int(self.headers.get('Content-Length') or 0)
                payload = json.loads(self.rfile.read(length).decode('utf-8'))
                if self.path == '/api/coordination/local-readiness':
                    self._send(200, {
                        'success': True, 'message': 'ready',
                        'run_request': {
                            'motion_file_id': 'show.jsonl', 'mapping_file_id': 'map.yaml',
                            **{key: FAKE_CONTEXT[key] for key in ('project_id', 'project_generation', 'context_id')},
                        },
                    })
                    return
                if self.path != '/api/coordination/local-control':
                    self._send(404, {'success': False})
                    return
                self._send(200, owner._control(str(payload.get('command') or ''), payload, via='http'))

            def log_message(self, _format, *_args):
                return

            def _send(self, status, payload):
                body = json.dumps(payload).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self._server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.port = int(self._server.server_address[1])
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

        prefix = f'/{namespace}'
        node = Node(f'fake_runtime_{namespace}', context=domain.context)
        self._status_pub = node.create_publisher(String, f'{prefix}/motion_run/status', 10)
        self._response_pub = node.create_publisher(String, f'{prefix}/motion_run/response', 10)
        safety_qos = QoSProfile(
            depth=1, reliability=ReliabilityPolicy.RELIABLE, durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self._safety_pub = node.create_publisher(String, f'{prefix}/safety/status', safety_qos)
        node.create_subscription(String, f'{prefix}/motion_run/request', self._on_request, 10)
        node.create_subscription(String, f'{prefix}/safety/request', self._on_safety_request, 10)
        node.create_subscription(String, f'{prefix}/motion_coordination/alive', self._on_alive, 10)
        node.create_timer(0.2, self._publish_status)
        self._node = node
        domain.add(node)
        self._safety_pub.publish(String(data=json.dumps({'servo_alarm_grade': 0, 'servo_alarm_active': []})))

    # 로컬 DDS · 재생 관리자 · 감독 ------------------------------------------------------- #

    def _on_request(self, message):
        request = json.loads(message.data)
        command = _RUNTIME_ALIASES.get(str(request.get('command') or ''), str(request.get('command') or ''))
        result = self._control(command, dict(request.get('payload') or {}), via='dds')
        self._response_pub.publish(self._String(data=json.dumps({
            **result,
            'request_id': request.get('request_id'),
            'project_generation': request.get('project_generation'),
        })))
        self._publish_status()

    def _on_safety_request(self, _message):
        with self._lock:
            self.safety_stops += 1

    def _on_alive(self, _message):
        with self._lock:
            self.alive_count += 1

    def _publish_status(self):
        with self._lock:
            status = {**self._motion_status, 'execution_context': dict(FAKE_CONTEXT)}
        try:
            self._status_pub.publish(self._String(data=json.dumps(status)))
        except Exception:  # noqa: BLE001, S110 · 시험 정리 중
            pass

    # 명령 · 두 길이 같은 곳으로 --------------------------------------------------------- #

    def _control(self, command, payload, *, via):
        now = time.monotonic()
        with self._lock:
            self.control_calls.append({**dict(payload), 'command': command, 'via': via, 'received_at': now})
        if command == 'group_prepare':
            execution_id = str(payload['execution_id'])
            initialize_at = float(payload['initialize_monotonic'])
            self._later(max(initialize_at - now, 0.0) + 0.05, self._arm, execution_id)
        elif command == 'group_start_at':
            execution_id = str(payload['execution_id'])
            cycle = int(payload['cycle_number'])
            start_at = float(payload['start_monotonic'])
            start_index = len(self.calls('group_start_at')) - 1
            extra_delay = (
                float(self.start_trigger_delays[start_index])
                if start_index < len(self.start_trigger_delays) else 0.0
            )
            delay = max(start_at - now, 0.0) + max(extra_delay, 0.0)
            self._later(delay, self._start_motion, {
                'group_execution': True, 'execution_id': execution_id,
                'state': 'running', 'phase': 'running',
                'group_cycle_number': cycle, 'current_cycle': cycle, 'lifecycle': {},
            })
            self._later(delay + self.cycle_duration_sec, self._motion_completed, execution_id, cycle, start_at)
        elif command == 'group_initialize_at':
            execution_id = str(payload['execution_id'])
            cycle = int(payload['cycle_number'])
            initialize_at = float(payload['initialize_monotonic'])
            self._later(max(initialize_at - now, 0.0) + 0.05, self._cycle_initialized, execution_id, cycle)
        elif command in {'stop_now', 'group_cancel'}:
            self._set_status({
                'group_execution': True,
                'execution_id': str(payload.get('execution_id') or ''),
                'state': 'stopped', 'phase': 'stopped',
            })
        return {'success': True, 'message': command}

    def _motion_completed(self, execution_id, cycle, start_at):
        with self._lock:
            if self._motion_status.get('state') == 'stopped':
                return
            self.cycle_ready_at[int(cycle)] = time.monotonic()
        self._set_status({
            'group_execution': True, 'execution_id': execution_id,
            'state': 'motion_completed', 'phase': 'group_motion_completed',
            'group_cycle_number': int(cycle), 'current_cycle': int(cycle),
            'lifecycle': {'motion_started_monotonic': float(self.motion_started_at.get(int(cycle), start_at))},
        })

    def _cycle_initialized(self, execution_id, cycle):
        with self._lock:
            if self._motion_status.get('state') == 'stopped':
                return
            self.cycle_initialized_at[int(cycle)] = time.monotonic()
        self._set_status({
            'group_execution': True, 'execution_id': execution_id,
            'state': 'cycle_ready', 'phase': 'group_cycle_initialized',
            'group_cycle_number': int(cycle), 'current_cycle': int(cycle),
        })

    def _arm(self, execution_id):
        with self._lock:
            if self._motion_status.get('state') == 'stopped' and self._motion_status.get('execution_id') == execution_id:
                return
        self._set_status({
            'group_execution': True, 'execution_id': execution_id,
            'state': 'armed', 'phase': 'group_armed',
            'group_cycle_number': 0, 'current_cycle': 0,
            'initialize_triggered_monotonic': time.monotonic(),
        })

    def _start_motion(self, value):
        with self._lock:
            if self._motion_status.get('state') == 'stopped':
                return
        actual = time.monotonic()
        cycle = int(value.get('group_cycle_number') or 0)
        with self._lock:
            self.motion_started_at[cycle] = actual
        value = dict(value)
        value['lifecycle'] = {'motion_started_monotonic': actual}
        self._set_status(value)

    def _set_status(self, value):
        with self._lock:
            self._motion_status = dict(value)
        self._publish_status()

    def _later(self, delay, callback, *args):
        timer = threading.Timer(max(float(delay), 0.0), callback, args=args)
        timer.daemon = True
        with self._lock:
            self._timers.append(timer)
        timer.start()

    # 시험이 보는 것 ------------------------------------------------------------------- #

    def start_cycles(self):
        return [int(row['cycle_number']) for row in self.calls('group_start_at')]

    def start_call(self, cycle):
        return next(row for row in self.calls('group_start_at') if int(row.get('cycle_number') or 0) == int(cycle))

    def calls(self, command):
        with self._lock:
            return [dict(row) for row in self.control_calls if row.get('command') == command]

    def close(self):
        with self._lock:
            timers = list(self._timers)
        for timer in timers:
            timer.cancel()
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2.0)


class _Group:
    """가짜 PC 들 + 연동 노드 프로세스 · 첫 PC 가 마스터"""

    def __init__(self, tmp_path, name, group_domain, local_domain, pcs, **config):
        self.tmp_path = tmp_path
        self.domain = _LocalDomain(local_domain)
        self.pcs = []
        self.ports = []
        self.processes = []
        self.pc_ids = []
        self.logs = []
        executable = _executable()
        for index, spec in enumerate(pcs):
            pc_id = spec.get('pc_id') or f'{name}-{chr(ord("a") + index)}'
            namespace = spec.get('namespace') or pc_id.replace('-', '_')
            pc = _FakeLocalPC(
                self.domain, namespace,
                cycle_duration_sec=spec.get('cycle', 0.2),
                start_trigger_delays=spec.get('start_trigger_delays'),
            )
            if spec.get('status'):
                pc._set_status(spec['status'])
            path = tmp_path / f'{namespace}.yaml'
            options = {
                'heartbeat_sec': 0.1, 'warning_timeout_sec': 0.8, 'peer_timeout_sec': 1.6,
                'start_lead_sec': 0.5, 'schedule_ack_margin_sec': 0.1,
                'max_trigger_sync_uncertainty_ms': 20.0, 'trigger_sync_samples': 5,
                'prepare_timeout_sec': 3.0, 'trigger_report_timeout_sec': 1.0,
                **config,
            }
            save_group_config(path, GroupConfig(
                pc_id, spec.get('display_name') or pc_id, True, f'{name}-group', group_domain,
                is_master=spec.get('is_master', index == 0), **options,
            ))
            port = _free_port()
            workspace = tmp_path / f'ws-{namespace}'
            (workspace / 'config').mkdir(parents=True, exist_ok=True)
            environment = dict(os.environ)
            environment.update({
                'MOTION_WORKSPACE': str(workspace),
                'MOTION_COORDINATION_CONFIG': str(path),
                'MOTION_COORDINATION_LOCAL_PORT': str(port),
                'MOTION_WEB_BRIDGE_PORT': str(pc.port),
                'MOTION_PC_NAMESPACE': namespace,
                'MOTION_LOCAL_DOMAIN_ID': str(local_domain),
                'MOTION_COORDINATION_WATCHDOG_SEC': '0',
                'ROS_LOCALHOST_ONLY': '0',
            })
            log = open(tmp_path / f'{namespace}.log', 'w', encoding='utf-8')
            self.logs.append(log)
            self.processes.append(subprocess.Popen(
                [str(executable)], env=environment,
                stdout=log, stderr=subprocess.STDOUT,
            ))
            self.pcs.append(pc)
            self.ports.append(port)
            self.pc_ids.append(pc_id)

    def join_all(self):
        for port in self.ports:
            _wait(lambda port=port: _get(port).get('node_connected'))
            assert _post(port, 'join')['success'] is True
        for port in self.ports:
            _wait(lambda port=port: len(_get(port).get('peers') or []) == len(self.ports) - 1)
        # 로컬 연결 · 연동 노드가 가짜 재생 관리자 상태를 받고, 가짜가 연동 노드 「살아 있음」 을 받을 때까지
        for port, pc in zip(self.ports, self.pcs):
            _wait(lambda port=port: (_get(port).get('local_runtime') or {}).get('runtime_link', {}).get('runtime_age_ms')
                  is not None)
            _wait(lambda pc=pc: pc.alive_count > 0)

    def close(self):
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
        for process in self.processes:
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        for pc in self.pcs:
            pc.close()
        self.domain.close()
        for log in self.logs:
            log.close()
            if os.environ.get('DDS_TEST_DUMP') == '1':
                # 실패 원인 보기 · 연동 노드 로그 끝부분
                print(f'===== {log.name}')
                print(''.join(Path(log.name).read_text(encoding='utf-8', errors='replace').splitlines(True)[-60:]))


def test_two_processes_discover_joined_peer_over_typed_dds(tmp_path):
    executable = _executable()
    ports = [_free_port(), _free_port()]
    configs = []
    for pc_id in ('dds-test-a', 'dds-test-b'):
        path = tmp_path / f'{pc_id}.yaml'
        save_group_config(path, GroupConfig(
            pc_id, pc_id, True, 'dds-process-test', 77,
            heartbeat_sec=0.1, warning_timeout_sec=0.6,
            peer_timeout_sec=1.2, start_lead_sec=0.5,
            schedule_ack_margin_sec=0.1,
            max_trigger_sync_uncertainty_ms=20.0,
            trigger_sync_samples=5,
            prepare_timeout_sec=2.0,
        ))
        configs.append(path)
    processes = []
    try:
        for path, port in zip(configs, ports):
            environment = dict(os.environ)
            environment.update({
                'MOTION_COORDINATION_CONFIG': str(path),
                'MOTION_COORDINATION_LOCAL_PORT': str(port),
                'MOTION_WORKSPACE': str(tmp_path),
                'MOTION_PC_NAMESPACE': path.stem.replace('-', '_'),
                'MOTION_COORDINATION_WATCHDOG_SEC': '0',
                'ROS_LOCALHOST_ONLY': '0',
            })
            processes.append(subprocess.Popen(
                [str(executable)], env=environment,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            ))
        for port in ports:
            _wait(lambda port=port: _get(port).get('node_connected'))
            assert _post(port, 'join')['success'] is True
        for port in ports:
            snapshot = _wait(lambda port=port: _one_peer_snapshot(port))
            assert snapshot['transport'] == 'ros2_dds'
            assert snapshot['peers'][0]['state'] == 'online'
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)


def test_two_processes_complete_two_barrier_cycles_over_typed_dds(tmp_path):
    group = _Group(tmp_path, 'dds-flow', 78, 92, [{'cycle': 0.22}, {'cycle': 0.38}], heartbeat_sec=0.2)
    pcs = group.pcs
    try:
        group.join_all()
        started = _post(group.ports[0], 'start_group')
        assert started['success'] is True, started
        _wait(lambda: all(pc.start_cycles() == [1] for pc in pcs), timeout=8.0)
        _wait(lambda: all(1 in pc.cycle_ready_at for pc in pcs), timeout=8.0)
        _wait(lambda: all(1 in pc.cycle_initialized_at for pc in pcs), timeout=8.0)
        _wait(lambda: all(pc.start_cycles()[:2] == [1, 2] for pc in pcs), timeout=8.0)

        latest_ready = max(pc.cycle_ready_at[1] for pc in pcs)
        latest_initialized = max(pc.cycle_initialized_at[1] for pc in pcs)
        for pc in pcs:
            assert pc.start_call(2)['received_at'] >= latest_ready
            assert pc.start_call(2)['received_at'] >= latest_initialized
            assert pc.start_cycles().count(1) == 1
            assert pc.start_cycles().count(2) == 1
        _wait(lambda: _get(group.ports[0]).get('execution', {}).get('start_spread_ms') is not None)
        synchronized = _get(group.ports[0])
        assert synchronized['execution']['start_within_tolerance'] is True
        assert synchronized['trigger_sync']['trigger_sync_source'] == 'dds_relative_monotonic'

        # 슬레이브만 내려간다 · 제 재생을 세우고(로컬 연결이 내려가 웹 길) · 마스터는 혼자 계속 돈다(178 · 183 ·
        # 하트비트만 끊김 = 「연락 끊김」) · 2회차부터 회차 눈금(10 s 올림)이라 다음 시작까지 10 s 남짓
        group.processes[1].terminate()
        group.processes[1].wait(timeout=5.0)
        _wait(lambda: pcs[1].calls('stop_now'), timeout=3.0)
        before = len(pcs[0].start_cycles())
        _wait(lambda: len(pcs[0].start_cycles()) > before, timeout=30.0)
        assert pcs[0].calls('stop_now') == []
    finally:
        group.close()


def test_group_reservations_go_straight_to_each_runtime_master_included(tmp_path):
    """수정 목록 207 · 209 · 그룹 예약(초기 위치 · 시작 · 회차 초기화)은 모든 PC 가 로컬 DDS 로 재생 관리자에 바로 ·
    마스터 자신도(DDS 로 제게 돌아온 명령 · HTTP · 웹 없이) · 웹(HTTP)으로는 웹만 아는 일만 간다"""
    group = _Group(tmp_path, 'dds-direct', 84, 93, [{'cycle': 0.2}, {'cycle': 0.25}])
    pcs = group.pcs
    try:
        group.join_all()
        assert _post(group.ports[0], 'start_group')['success'] is True
        # 2회차부터 회차 눈금(10 s 올림 · 178)
        _wait(lambda: all(pc.start_cycles()[:2] == [1, 2] for pc in pcs), timeout=20.0)
        for pc in pcs:
            for command in ('group_prepare', 'group_start_at', 'group_initialize_at'):
                rows = pc.calls(command)
                assert rows, (pc.namespace, command)
                assert {row['via'] for row in rows} == {'dds'}, (pc.namespace, command, rows)
            # 같은 예약을 두 번(제 것 · DDS 로 돌아온 것) 받지 않는다
            assert len(pc.calls('group_prepare')) == 1
        snapshot = _get(group.ports[0])
        assert snapshot['local_runtime']['runtime_link']['up'] is True
        assert pcs[0].alive_count > 0, '웹 역감시가 듣는 「살아 있음」'
    finally:
        group.close()


def test_a_dead_web_does_not_drop_a_playing_pc(tmp_path):
    """수정 목록 209 · 웹(HTTP)이 죽어도 재생 · 그룹은 그대로 · 전에는 1.5 s 넘게 웹 상태를 못 받으면 빠졌다(172)"""
    group = _Group(tmp_path, 'dds-webless', 85, 94, [{'cycle': 0.2}, {'cycle': 0.2}])
    pcs = group.pcs
    try:
        group.join_all()
        assert _post(group.ports[0], 'start_group')['success'] is True
        _wait(lambda: all(len(pc.start_cycles()) >= 1 for pc in pcs), timeout=10.0)
        for pc in pcs:
            pc.web_alive = False
        counts = [len(pc.start_cycles()) for pc in pcs]
        # 회차 눈금 10 s · 웹 없이 두 회차 더(전에는 1.5 s 안에 빠졌다)
        _wait(lambda: all(len(pc.start_cycles()) >= count + 2 for pc, count in zip(pcs, counts)), timeout=35.0)
        execution = _get(group.ports[0])['execution']
        assert sorted(execution['participants']) == sorted(group.pc_ids)
        assert execution['excluded'] == {}
        assert all(pc.calls('stop_now') == [] for pc in pcs)
    finally:
        group.close()


def test_trigger_spread_is_recorded_without_stopping(tmp_path):
    group = _Group(tmp_path, 'dds-spread', 79, 95, [
        {'cycle': 0.15}, {'cycle': 0.15, 'start_trigger_delays': [0.04]},
    ])
    pcs = group.pcs
    try:
        group.join_all()
        assert _post(group.ports[0], 'start_group')['success'] is True
        # 끊김 시험 F · 40 ms 어긋남은 기록만 · 그룹을 세우거나 잠그지 않는다
        _wait(lambda: pcs[1].calls('group_start_at'), timeout=10.0)
        time.sleep(1.0)
        assert pcs[0].calls('stop_now') == [] and pcs[1].calls('stop_now') == []
        assert not _get(group.ports[0]).get('coordination_error', {}).get('active')
    finally:
        group.close()


def test_duplicate_pc_id_is_detected_by_both_dds_processes(tmp_path):
    group = _Group(tmp_path, 'dds-duplicate', 81, 96, [
        {'pc_id': 'duplicate-pc', 'namespace': 'duplicate_a', 'display_name': 'Duplicate 0'},
        {'pc_id': 'duplicate-pc', 'namespace': 'duplicate_b', 'display_name': 'Duplicate 1', 'is_master': True},
    ], trigger_report_timeout_sec=0.5)
    ports = group.ports
    try:
        for port in ports:
            _wait(lambda port=port: _get(port).get('node_connected'))
        join_results = [None, None]
        threads = [
            threading.Thread(
                target=lambda index=index, port=port: join_results.__setitem__(index, _post(port, 'join'))
            )
            for index, port in enumerate(ports)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2.0)
        assert all(result and result['success'] for result in join_results)
        for port in ports:
            failed = _wait(lambda port=port: (
                _get(port)
                if _get(port).get('coordination_error', {}).get('code') == 'DUPLICATE_PC_ID' else None
            ))
            assert failed['coordination_error']['active'] is True
            assert _post(port, 'start_group')['success'] is False
    finally:
        group.close()


def test_a_missing_start_report_keeps_the_group_playing_over_dds(tmp_path):
    """시작 보고가 늦은 PC · 회차 맞춤 연속 재생이면 빼되 그 PC 는 재생 계속(연락 끊김 · 경계에서 다시 합침) ·
    그룹 정지 · 잠금 없음 · 끊김 시험 J(178 · 183) · 전에는 GROUP_MOTION_START_REPORT_TIMEOUT 으로 모두 세우고 잠갔다"""
    group = _Group(tmp_path, 'dds-report', 82, 97, [
        {'cycle': 0.1}, {'cycle': 0.1, 'start_trigger_delays': [2.0]},
    ], trigger_report_timeout_sec=0.5)
    pcs = group.pcs
    try:
        group.join_all()
        assert _post(group.ports[0], 'start_group')['success'] is True
        lost = _wait(lambda: (_get(group.ports[0]).get('execution') or {}).get('lost'), timeout=10.0)
        assert group.pc_ids[1] in lost
        assert not _get(group.ports[0]).get('coordination_error', {}).get('active')
        assert pcs[0].calls('stop_now') == []
        assert pcs[1].calls('stop_now') == [], '늦은 PC 도 세우지 않는다 · 재생 계속'
    finally:
        group.close()
