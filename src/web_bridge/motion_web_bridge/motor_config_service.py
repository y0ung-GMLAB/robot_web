"""모터축 설정 · 저장 · 적용 · 재시작 · 실행 해제.

`MotionWebBridge`에서 떼어냈다 · §5 분해 목표안의 `MotorConfigService` · §6-19

**가변 상태 두 개의 소유자를 여기로 옮겼다.** §6-13이 "계약을 어디로 옮길지
먼저 정해야 한다"고 남겨둔 항목이다.

- `selected` (옛 `motor_config_file`) · 지금 고른 모터축 설정 파일
- `applied` (옛 `applied_motor_config_file`) · Motor Manager가 실제로 물고 있는 파일

프로젝트를 바꿀 때 `selected`를 비우는 것이 프로젝트 격리 보장이고,
`test_project_repository`가 그 성질을 검사한다. 이제 그 계약이 이 객체 안에 있다.

`lifecycle_lock`은 노드가 소유하고 넘겨준다 · `ScanOrchestrator`와 **같은 락**이다.
"지금 모터 관련 작업이 하나 돌고 있다"를 뜻하므로 나눠 가질 수 없다 · §6-18
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

from motion_common.paths import NO_PROJECT_SELECTED

import yaml

from motion_common import run_state, store
from motion_common.values import optional_int

from motion_web_bridge.motor_runtime_store import MOTOR_BUSY_MESSAGE
from motion_web_bridge import (
    boot_params,
    mapping_motor_limits,
    minas_params,
    motion_file_analysis,
    motor_config_build,
    motor_config_rules,
    serial_params,
)


class MotorConfigService:
    def __init__(
        self,
        bridge: Any,
        *,
        project: Any,
        runtime: Any,
        lifecycle_lock: threading.Lock,
        repository: Any,
        workspace_root: Path,
        selected: Path,
        applied: Path,
        restart_script: Path,
    ) -> None:
        self.bridge = bridge
        #: 프로젝트 서비스 협력자 (§6-23)
        self.project = project
        #: 모터 런타임 수명주기 협력자 (§6-22)
        self.runtime = runtime
        #: `ScanOrchestrator`와 공유 · 노드가 소유 (§6-18)
        self.lifecycle_lock = lifecycle_lock
        self.repository = repository
        self.workspace_root = workspace_root
        #: 지금 고른 모터축 설정 파일 · 프로젝트 전환 시 비운다
        self.selected = selected
        #: Motor Manager가 실제로 물고 있는 파일
        self.applied = applied
        self.restart_script = restart_script

    def clear_selection(self) -> None:
        """프로젝트가 바뀌면 이전 프로젝트의 설정 파일을 가리키지 않는다."""
        self.selected = Path()

    def load(self) -> Dict[str, Any]:
        try:
            self.selected = motor_config_rules.selected_motor_config_path(self.repository)
        except ValueError as exc:
            if '모터 설정 파일이 없습니다' in str(exc):
                return {
                    'success': True,
                    'saved': False,
                    'message': '아직 저장된 모터 설정 파일이 없습니다',
                    'config_file': '',
                    'config_revision': '',
                    'content': '',
                    'registry': motor_config_rules.empty_motor_registry(),
                }
            return {
                'success': False,
                'message': str(exc),
                'config_file': '',
                'config_revision': '',
                'content': '',
                'registry': motor_config_rules.empty_motor_registry(),
            }
        return self._payload_from_path(self.selected)

    def select_file(self, path: Any = None) -> None:
        """어느 모터 축 파일을 쓸 것인가 · §6-183

        **고르는 것과 적용하는 것은 다르다** · `selected` 는 「화면에서 고른
        것」이고 `applied` 는 「모터에 들어간 것」이다 · 빈 값이면 고른 것이
        없다는 뜻이다.

        전에는 `project_service` 가 `bridge._motor_config.selected = Path()`
        처럼 남의 칸에 직접 적었다 · 일곱 자리다 · 그중 다섯은 「비운다」는
        같은 뜻인데 `Path()` 라는 **표현**을 일곱 곳이 똑같이 알아야 했다.
        """
        self.selected = Path(path) if path else Path()

    def selected_file(self) -> Path:
        return self.selected

    def applied_file(self) -> Path:
        return self.applied

    def _payload_from_path(
        self,
        config_file: Path,
        *,
        message: str = 'motor config YAML loaded',
    ) -> Dict[str, Any]:
        """Build the UI/API payload from one concrete motor_axes YAML path."""
        path = Path(config_file)
        if not path.is_file():
            return {
                'success': False,
                'message': 'motor config YAML not found',
                'config_file': str(path),
                'config_revision': '',
                'content': '',
                'registry': motor_config_rules.empty_motor_registry(),
            }
        try:
            raw = path.read_bytes()
            content = raw.decode('utf-8')
            config = yaml.safe_load(content) or {}
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            return {
                'success': False,
                'message': f'failed to load motor config YAML: {exc}',
                'config_file': str(path),
                'config_revision': '',
                'content': '',
                'registry': motor_config_rules.empty_motor_registry(),
            }
        if not isinstance(config, dict):
            return {
                'success': False,
                'message': 'motor config YAML root must be an object',
                'config_file': str(path),
                'config_revision': '',
                'content': '',
                'registry': motor_config_rules.empty_motor_registry(),
            }
        axis_config = motor_config_rules.expand_shared_driver_profiles(config)
        if axis_config != config:
            content = yaml.safe_dump(axis_config, sort_keys=False, allow_unicode=True)
        self.selected = path
        return {
            'success': True,
            'message': message,
            'config_file': str(path),
            'config_revision': hashlib.sha256(raw).hexdigest(),
            'content': content,
            'registry': motor_config_rules.registry_from_motor_config(axis_config),
        }

    def _file_from_payload(self, payload: Dict[str, Any]) -> Path:
        project_id = self.repository.require_selected_project_id()
        detail = self.repository.get_project(project_id)
        project = detail.get('project') or {}
        active = project.get('active_files') or {}
        active_name = str(active.get('motor_axes') or '').strip()
        config_dir = (Path(str(project.get('path') or '')) / 'motor_axes').resolve()
        active_path = config_dir / active_name if active_name else config_dir / 'motor_axes.yaml'
        self.selected = active_path
        requested = str(payload.get('file_name') or '').strip()
        if not requested:
            return active_path

        name = Path(requested).name.strip()
        if not name or name in ('.', '..'):
            raise ValueError('motor config file name is empty')
        if not name.lower().endswith(('.yaml', '.yml')):
            name = f'{name}.yaml'

        target = (config_dir / name).resolve()
        try:
            target.relative_to(config_dir)
        except ValueError as exc:
            raise ValueError('motor config file must stay under config directory') from exc
        return target

    def _read_current(self) -> Dict[str, Any]:
        try:
            self.selected = motor_config_rules.selected_motor_config_path(self.repository)
        except ValueError:
            return motor_config_build.default_motor_config(self.workspace_root)
        if not self.selected.is_file():
            return motor_config_build.default_motor_config(self.workspace_root)
        content = self.selected.read_text(encoding='utf-8')
        config = yaml.safe_load(content) or {}
        if isinstance(config, dict):
            return config
        return motor_config_build.default_motor_config(self.workspace_root)

    def _write(self, content: str, target_file: Optional[Path] = None) -> None:
        target = target_file or self.selected
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file():
            timestamp = time.strftime('%Y%m%d-%H%M%S')
            history_dir = target.parent.parent / 'runtime' / 'history' / 'motor_axes'
            history_dir.mkdir(parents=True, exist_ok=True)
            backup = history_dir / f'{timestamp}-{target.name}'
            counter = 2
            while backup.exists():
                backup = history_dir / f'{timestamp}-{counter}-{target.name}'
                counter += 1
            store.atomic_write_text(backup, target.read_text(encoding='utf-8'))
            store.prune_history(history_dir)   # 분류별 50개 상한 · 21-3
        # 원자적 교체 · 기록 도중 죽어도 모터 설정이 반쪽으로 남지 않는다 · §6-24
        store.atomic_write_text(target, content.rstrip() + '\n')
        self.selected = target
        motor_config_rules.write_motor_config_selection(self.repository, target)

    def save(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            self.bridge.ensure_project_mutation_allowed(
                self.repository.selected_project_id()
            )
            target_file = self._file_from_payload(payload)
            expected_revision = str(payload.get('base_revision') or '').strip()
            if target_file.is_file():
                actual_revision = hashlib.sha256(target_file.read_bytes()).hexdigest()
                if not expected_revision:
                    raise ValueError(
                        '설정 파일 버전 정보가 없습니다. 화면을 새로고침해 설정을 다시 불러온 뒤 저장하세요'
                    )
                if expected_revision != actual_revision:
                    raise ValueError(
                        '설정 파일이 화면을 불러온 뒤 변경됐습니다. '
                        '현재 파일을 보호하려고 저장하지 않았습니다. 화면을 새로고침해 설정을 다시 불러오세요'
                    )
            elif expected_revision:
                raise ValueError(
                    '화면에서 불러온 설정 파일이 없어졌습니다. '
                    '화면을 새로고침해 설정을 다시 불러오세요'
                )
            if 'content' in payload:
                content = str(payload.get('content') or '')
                config = yaml.safe_load(content) or {}
                config = motor_config_rules.expand_shared_driver_profiles(config)
            else:
                registry = payload.get('registry', payload)
                if not isinstance(registry, dict):
                    raise ValueError('registry must be an object')
                normalized = motor_config_rules.normalize_motor_registry(registry)
                # 최대 ≥ 프로파일 · 어기면 저장 거부 · 수정 목록 37
                for motor in normalized.get('motors') or []:
                    speed_error = motor_config_build.axis_speed_limit_error(motor)
                    if speed_error:
                        raise ValueError(speed_error)
                normalized['updated_at'] = time.time()
                current = self._read_current()
                config = motor_config_build.motor_config_from_registry(
                    self.workspace_root, normalized, current
                )

            if not isinstance(config, dict):
                raise ValueError('motor config YAML root must be an object')
            # 운전 한계(lower/upper)는 조인트 매핑에서 온다 · 어느 저장 경로든 마지막에 덮는다
            config, _ = mapping_motor_limits.apply_mapping_limits(
                config, mapping_motor_limits.active_mapping(self.repository),
            )
            # Feetech 한 바퀴 범위 · 한 포트 한 종류 · 어기면 저장 거부 · 수정 목록 158 (AC 만 있으면 해당 없음)
            # 한 포트 한 속도 · 수정 목록 161
            serial_errors = [
                *mapping_motor_limits.single_turn_errors(config),
                *serial_params.port_kind_conflicts(config.get('masters') or [], config.get('drivers') or []),
                *serial_params.port_baudrate_conflicts(config.get('masters') or []),
            ]
            if serial_errors:
                raise ValueError(serial_errors[0])
            content = yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
            configured_axes = len(
                motor_config_rules.registry_from_motor_config(
                    motor_config_rules.expand_shared_driver_profiles(config)
                ).get('motors') or []
            )
            if configured_axes == 0:
                raise ValueError(
                    '모터가 하나도 없는 설정은 저장할 수 없습니다. '
                    '설정 파일을 삭제하려면 프로젝트 파일 메뉴의 「휴지통으로 이동」을 누르세요'
                )

            self._write(content, target_file)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            return {
                'success': False,
                'message': f'failed to save motor config YAML: {exc}',
                'config_file': str(self.selected),
                'content': payload.get('content', ''),
                'registry': motor_config_rules.empty_motor_registry(),
            }

        # Persist project ownership of the written file, then return that same
        # file as the save response. Do not rebuild the response through the
        # active-file selector alone: a new project has an empty
        # active_files.motor_axes until sync finishes, and an empty registry
        # response would wipe the UI axis list (names/aliases) and leave
        # "장비에 적용 · 모터 재시작" disabled until a manual reload.
        synced = self.project.sync_file({}, 'motor_axes', target_file)
        result = self._payload_from_path(
            target_file,
            message=(
                'motor config YAML saved; restart motor_manager_node to apply'
            ),
        )
        if not result.get('success'):
            return result
        saved_motors = (result.get('registry') or {}).get('motors') or []
        if len(saved_motors) == 0:
            return {
                'success': False,
                'message': (
                    '모터 설정 파일은 저장됐지만 저장 응답에 모터 목록이 없습니다. '
                    '화면을 새로고침해 파일을 다시 확인하세요'
                ),
                'config_file': str(target_file),
                'config_revision': '',
                'content': '',
                'registry': motor_config_rules.empty_motor_registry(),
            }
        if 'project_sync' in synced:
            result['project_sync'] = synced['project_sync']
        if 'project_sync_warning' in synced:
            result['project_sync_warning'] = synced['project_sync_warning']
        return result

    # -- MINAS 공통 값 · 수정 목록 114 (사용자 2026-10-13 · 계속 맞춰 보는 값은 화면에서 · 잠금) -- #

    def minas_base(self) -> Dict[str, Any]:
        """모든 MINAS 축에 부팅 때 쓰는 공통 값 · 기본값(저장소) · 이 PC 값 · 쓰일 값"""
        return minas_params.site_base_view(self.workspace_root)

    def save_minas_base(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """이 PC 값 저장 → 모터 설정의 param 파일을 다시 만든다 · 드라이브에는 「장비에 적용」 때 들어간다"""
        try:
            self.bridge.ensure_project_mutation_allowed(self.repository.selected_project_id())
            values = payload.get('values') if isinstance(payload, dict) else None
            if not isinstance(values, dict):
                raise ValueError('values 가 필요합니다')
            view = minas_params.save_site_local(self.workspace_root, values)
        except ValueError as exc:
            return {**minas_params.site_base_view(self.workspace_root), 'success': False, 'message': str(exc)}
        # param 파일은 모터 설정을 저장할 때 만들어진다 · 지금 설정을 같은 내용으로 다시 저장해 새 공통 값을 싣는다
        loaded = self.load()
        motors = ((loaded.get('registry') or {}).get('motors') or []) if loaded.get('success') else []
        if motors:
            result = self.save({
                'registry': loaded['registry'],
                'base_revision': str(loaded.get('config_revision') or ''),
            })
            if not result.get('success'):
                return {
                    **view, 'success': False,
                    'message': f'공통 값은 저장했지만 모터 설정에 싣지 못했습니다 · {result.get("message") or ""}',
                }
        return {
            **view, 'success': True, 'needs_apply': bool(motors),
            'message': '저장했습니다. 「장비에 적용」 을 해야 드라이브에 들어갑니다.' if motors
            else '저장했습니다. 모터 설정을 저장하면 같이 들어갑니다.',
        }

    def sync_limits_from_mapping(self) -> Dict[str, Any]:
        """조인트 매핑 저장 뒤 · 지금 모터 설정 파일의 lower/upper 를 매핑 환산값으로.

        모터 설정 파일이 없으면 할 일이 없다 · 바뀐 것이 없으면 파일을 안 쓴다
        (쓰면 sha 가 바뀌어 「장비에 적용 필요」가 괜히 뜬다).
        """
        try:
            path = motor_config_rules.selected_motor_config_path(self.repository)
        except ValueError:
            return {'success': True, 'changed': [], 'config_file': ''}
        if not path.is_file():
            return {'success': True, 'changed': [], 'config_file': ''}
        try:
            config = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
            if not isinstance(config, dict):
                raise ValueError('motor config YAML root must be an object')
            updated, changed = mapping_motor_limits.apply_mapping_limits(
                config, mapping_motor_limits.active_mapping(self.repository),
            )
            # Feetech 한 바퀴 밖이면 모터 설정에 안 쓴다 · 수정 목록 158
            single_turn = mapping_motor_limits.single_turn_errors(updated) if changed else []
            if single_turn:
                raise ValueError(single_turn[0])
            if changed:
                self._write(
                    yaml.safe_dump(updated, sort_keys=False, allow_unicode=True), path,
                )
                self.project.sync_file({}, 'motor_axes', path)
        except (OSError, ValueError, yaml.YAMLError) as exc:
            return {
                'success': False,
                'changed': [],
                'config_file': str(path),
                'message': f'모터 운전 한계 갱신 실패: {exc}',
            }
        return {'success': True, 'changed': changed, 'config_file': str(path)}

    def delete(self) -> Dict[str, Any]:
        project_id = self.repository.selected_project_id()
        if not project_id:
            return {
                'success': False,
                'message': NO_PROJECT_SELECTED,
                'config_file': '',
                'content': '',
                'registry': motor_config_rules.empty_motor_registry(),
            }
        try:
            current_path = motor_config_rules.selected_motor_config_path(self.repository)
            deleted = self.project.delete_file(
                project_id, 'motor_axes', current_path.name
            )
        except (OSError, ValueError) as exc:
            return {
                'success': False,
                'message': f'모터 설정 파일 삭제 실패: {exc}',
                'config_file': '',
                'content': '',
                'registry': motor_config_rules.empty_motor_registry(),
            }

        loaded = self.load()
        replacement = str(deleted.get('replacement_active_file') or '')
        loaded.update({
            'success': True,
            'deleted_file': str(deleted.get('deleted_file') or current_path.name),
            'replacement_active_file': replacement,
            'trash_path': str(deleted.get('trash_path') or ''),
            'message': (
                f'모터 설정 파일을 프로젝트 휴지통으로 이동하고 {replacement} 파일을 선택했습니다'
                if replacement
                else '모터 설정 파일을 프로젝트 휴지통으로 이동했습니다'
            ),
        })
        return loaded

    def apply(self) -> Dict[str, Any]:
        if not self.restart_script.is_file():
            return {
                'success': False,
                'message': f'restart script not found: {self.restart_script}',
                'restart_script': str(self.restart_script),
                **self.bridge.snapshot(),
            }

        try:
            self.project.ensure_change_allowed()
        except ValueError as exc:
            return {
                'success': False,
                'message': str(exc),
                **self.bridge.snapshot(),
            }
        lifecycle_lock = getattr(self, 'lifecycle_lock', None)
        if lifecycle_lock is None:
            lifecycle_lock = threading.Lock()
            self.lifecycle_lock = lifecycle_lock
        if not lifecycle_lock.acquire(blocking=False):
            return {
                'success': False,
                'message': MOTOR_BUSY_MESSAGE,
                **self.bridge.snapshot(),
            }
        project_id = self.repository.selected_project_id()
        if not project_id:
            lifecycle_lock.release()
            return {
                'success': False,
                'message': '적용할 프로젝트를 먼저 선택하세요',
                **self.bridge.snapshot(),
            }
        operation: Dict[str, Any] = {}
        previous_runtime = self.repository.runtime.motor_runtime_target_snapshot()
        try:
            operation = self.repository.runtime.begin_motor_operation(
                'motor_apply',
                'preparing',
                timeout_sec=45.0,
                details={
                    'project_id': project_id,
                    'previous_runtime': previous_runtime,
                },
            )
            # 부팅 목록(param 파일)이 지금 공통 설정 · 모터 칸과 다르면 먼저 다시 만든다 · 수정 목록 116
            boot_refresh = self._refresh_boot_param_files()
            prepared = self.repository.prepare_runtime_motor_config(project_id)
            runtime_file = self.repository.runtime.mark_runtime_motor_config_applied(
                project_id
            )
            expected_axes = motion_file_analysis.configured_axes_from_runtime_file(
                runtime_file
            )
            if not expected_axes:
                raise ValueError('적용할 모터 실행 설정에서 대상 모터를 확인할 수 없습니다')
            self.repository.runtime.update_motor_operation(
                str(operation['operation_id']),
                'prepared',
                details={
                    'runtime_file': str(runtime_file),
                    'expected_axes': expected_axes,
                },
            )
            managed_service = str(
                os.environ.get('MOTION_CONTROL_SERVICE_UNIT') or ''
            ).strip()
            motor_service = str(
                os.environ.get('MOTION_MOTOR_SERVICE_UNIT') or ''
            ).strip()
            if managed_service and managed_service != 'motion-control.service':
                raise ValueError('허용되지 않은 자동실행 서비스 이름입니다')
            if managed_service:
                if motor_service != 'motion-motor.service':
                    raise ValueError(
                        'Motor Manager 분리 서비스가 설치되지 않았습니다. '
                        '최초 설치를 다시 실행하세요'
                    )
                motor_config_rules.schedule_managed_service_restart(
                    motor_service,
                    managed_service,
                )
                restart_mode = 'split_managed_services'
            else:
                environment = dict(os.environ)
                environment['MOTOR_CONFIG_FILE'] = str(runtime_file)
                environment['MOTION_WORKSPACE'] = str(self.workspace_root)
                environment['START_MOTOR_MANAGER'] = 'true'
                subprocess.Popen(
                    ['/bin/bash', str(self.restart_script)],
                    cwd=str(self.restart_script.parent.parent),
                    env=environment,
                    start_new_session=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                restart_mode = 'legacy_script'
            self.repository.runtime.update_motor_operation(
                str(operation['operation_id']),
                'restart_requested',
                message='새 모터 설정으로 서비스 재시작 요청 완료',
                details={'runtime_file': str(runtime_file)},
            )
        except (OSError, ValueError, yaml.YAMLError) as exc:
            operation_id = str(operation.get('operation_id') or '')
            if operation_id:
                try:
                    self.repository.runtime.finish_motor_operation(
                        operation_id,
                        'failure',
                        phase='failed',
                        error=str(exc),
                    )
                except ValueError:
                    pass
            self.repository.runtime.restore_motor_runtime_target(previous_runtime)
            return {
                'success': False,
                'message': f'프로젝트 설정을 적용할 수 없습니다: {exc}',
                'restart_script': str(self.restart_script),
                **self.bridge.snapshot(),
            }
        finally:
            lifecycle_lock.release()

        return {
            'success': True,
            'message': (
                '프로젝트 설정 적용을 시작했습니다. 잠시 후 화면이 다시 연결됩니다'
                + (f' · 부팅 값을 새 설정으로 다시 만들었습니다({boot_refresh})' if boot_refresh else '')
            ),
            'restart_script': str(self.restart_script),
            'restart_mode': restart_mode,
            'runtime_config': {
                **prepared,
                'session_file': str(runtime_file),
                'session_id': self.repository.runtime.motor_runtime_state().get(
                    'session_id', ''
                ),
            },
            'motor_operation': self.repository.runtime.motor_operation_status(),
            **self.bridge.snapshot(),
        }

    def _refresh_boot_param_files(self) -> str:
        """저장된 모터 설정이 가리키는 부팅 목록(param 파일)이 지금 설정과 다르면 **param 파일과 그 경로만** 다시 쓴다 · 수정 목록 116 · 129

        업데이트로 공통 설정(`config/minas_base.yaml`)이 바뀌었거나, 옛 모터 설정이 아직 플랫폼
        `param/minas.yaml` 을 가리키면(floating4 2026-10-13) 「적용」 만으로는 새 값이 안 들어갔다 ·
        처음엔 registry 로 설정 전체를 다시 저장했는데 · ① 「적용」 이 연 모터 작업 안이라 저장 검사에 막히고
        ② 전체 저장은 파일을 더 엄격한 꼴로 다시 만들어(식별 정보 등) 적용 준비가 거절됐다(129 · 시험) ·
        그래서 다른 칸은 손대지 않고 MINAS 드라이버의 `param_file` 만 저장 때와 같은 규칙
        (`minas_params.write_param_file` · 모터 칸 오버라이드)으로 바꾼다 ·
        같으면 아무것도 안 쓴다(설정 sha 가 괜히 바뀌지 않게) · 바꾼 것 한 줄을 돌려준다 · 실패는 ValueError
        """
        loaded = self.load()
        motors = ((loaded.get('registry') or {}).get('motors') or []) if loaded.get('success') else []
        config_file = Path(str(loaded.get('config_file') or ''))
        if not motors or not config_file.is_file():
            return ''
        expected = boot_params.expected_for(self.workspace_root, motors)
        rows = boot_params.config_differences(config_file, expected)
        if not rows:
            return ''
        try:
            config = yaml.safe_load(config_file.read_text(encoding='utf-8')) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError(f'부팅 값을 새 설정으로 다시 만들지 못했습니다 · 모터 설정을 못 읽음 · {exc}') from exc
        by_axis = {
            optional_int(motor.get('axis')): motor
            for motor in motors
            if isinstance(motor, dict) and optional_int(motor.get('axis')) is not None
        }
        axis_of_driver: Dict[Any, Any] = {}
        for master in config.get('masters') or []:
            for slave in (master.get('slaves') or []) if isinstance(master, dict) else []:
                if isinstance(slave, dict):
                    axis_of_driver.setdefault(optional_int(slave.get('driver_id')), optional_int(slave.get('controller_index')))
        for driver in config.get('drivers') or []:
            if not isinstance(driver, dict) or str(driver.get('type') or '') != 'minas':
                continue
            driver_id = optional_int(driver.get('id'))
            motor = by_axis.get(axis_of_driver.get(driver_id)) or {}
            driver['param_file'] = minas_params.write_param_file(
                self.workspace_root, driver_id, minas_params.param_overrides(motor),
            )
        self._write(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), config_file)
        left = boot_params.config_differences(config_file, expected)
        if left:
            raise ValueError(f'부팅 값을 새 설정으로 다시 만들지 못했습니다 · {boot_params.describe(left)}')
        return boot_params.describe(rows)

    #: 실행 적용을 해제했을 때 「정지 중」에 붙는 마무리 문구 · 한 곳에서 쓴다
    RELEASE_SETTLED_MESSAGE = '실행 적용을 해제해 정지를 마무리했습니다'

    def clear_stopping_release_state(self) -> None:
        """실행 적용을 해제했다 · 「정지 중」을 매듭짓는다 · §6-186

        **무엇을 어떻게 적을지는 가진 쪽이 안다** · 전에는 여기서 브리지
        속으로 손을 넣어 직접 적었고, 자물쇠가 없을 때를 위한 같은 블록이
        한 벌 더 있었다.
        """
        self.bridge.settle_stopping_run_state(self.RELEASE_SETTLED_MESSAGE)

    #: 재생 중 「프로그램 다시 시작」 · 정지가 듣기를 기다리는 최대 시간 · 수정 목록 144
    RESTART_STOP_WAIT_SEC = 5.0
    RESTART_NEEDS_STOP_MESSAGE = '재생 중입니다 · 정지하고 다시 시작하려면 확인하세요'
    RESTART_MOTOR_JOB_MESSAGE = (
        '모터 설정·검색·재시작 작업이 진행 중입니다 · 끝난 뒤 다시 시작하세요'
    )

    def restart_managed_program(
        self, payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Restart only upper-level nodes while Motor Manager keeps running.

        **재생 중이면 먼저 묻는다** · 수정 목록 144 (실물 V-28 ③ · 2026-10-14 11:35)

        전에는 프로젝트 변경 잠금(`ensure_change_allowed`)을 지나 재생 중이면 「애니메이션이 동작
        중(waiting)이라 프로젝트를 변경할 수 없습니다」 로 거절했다 · 프로젝트를 바꾸는 일이 아니고,
        사람은 무엇을 해야 하는지 몰랐다.

        - 재생(단독 · 그룹 · 초기 이동 · 대기) 중 · `stop_first` 없음 → 거절 · `needs_stop: true` ·
          화면이 두 번째 확인을 받고 `stop_first: true` 로 다시 보낸다
        - `stop_first` · 연동 노드에 「이 PC 빠짐」 을 먼저 알리고(그룹이면 이 PC 만 빠지고 나머지는
          계속 · 수정 목록 145 ①) → 「정지」 버튼과 같은 정지(그 자리 · 서보 유지) → 멈출 때까지
          최대 `RESTART_STOP_WAIT_SEC` 기다림 → 다시 시작
        - 모터 설정·검색·재시작 작업 중이면 거절(그 작업을 끊지 않게)
        - 이 PC 가 다른 PC 들의 그룹을 진행 중이면 연동 서비스는 다시 시작하지 않는다(진행이 끊기지 않게)
        """
        request = payload if isinstance(payload, dict) else {}
        stop_first = request.get('stop_first') is True
        self.clear_stopping_release_state()
        managed_service = str(
            os.environ.get('MOTION_CONTROL_SERVICE_UNIT') or ''
        ).strip()
        if managed_service != 'motion-control.service':
            self.clear_stopping_release_state()
            return {
                'success': False,
                'message': '자동실행 서비스가 설치되지 않았습니다. 최초 설치를 먼저 완료하세요',
                **self.bridge.snapshot(),
            }
        if os.environ.get('MOTION_MOTOR_SERVICE_UNIT') != 'motion-motor.service':
            self.clear_stopping_release_state()
            return {
                'success': False,
                'message': (
                    'Motor Manager 분리 서비스가 설치되지 않았습니다. '
                    '최초 설치를 다시 실행하세요'
                ),
                **self.bridge.snapshot(),
            }
        if self.project.motor_job_running():
            return {
                **self.bridge.snapshot(),
                'success': False,
                'message': self.RESTART_MOTOR_JOB_MESSAGE,
            }
        playing = self.playback_in_progress()
        if playing and not stop_first:
            return {
                **self.bridge.snapshot(),
                'success': False,
                'needs_stop': True,
                'run_state': playing,
                'message': self.RESTART_NEEDS_STOP_MESSAGE,
            }
        restart_services = [managed_service]
        coordination_service = str(
            os.environ.get('MOTION_COORDINATION_SERVICE_UNIT') or ''
        ).strip()
        # 사람이 누른 재시작이다 · 연동 노드에 「이 PC 빠짐」 을 **정지보다 먼저** 알린다 · 그래야 이 PC 의
        # 정지가 「참가 PC 먼저 정지 · 전체 풀기」 로 읽히지 않고 이 PC 만 빠진다 · 실패해도 재시작은 간다 ·
        # 수정 목록 123 (실물 S-11 다시) · 145 ①
        coordination = getattr(self.bridge, 'coordination', None)
        notify = getattr(coordination, 'notify_planned_restart', None)
        notice = notify() if callable(notify) else {}
        still_coordinating = bool(
            isinstance(notice, dict) and notice.get('still_coordinating')
        )
        if coordination_service == 'motion-coordination.service' and not still_coordinating:
            restart_services.append(coordination_service)
        notes = []
        # 이 PC 로컬 재생이 돌 때만 세운다 · 진행만 하던 마스터(로컬은 쉼)는 세울 것이 없다
        stopped_playback = bool(playing and self._local_run_state())
        if stopped_playback:
            notes.append(self._stop_playback_before_restart())
        if still_coordinating:
            notes.append('연동 서비스는 다른 PC 그룹을 진행 중이라 다시 시작하지 않음')
        try:
            motor_config_rules.schedule_managed_service_restart(*restart_services)
        except OSError as exc:
            self.clear_stopping_release_state()
            return {
                'success': False,
                'message': f'프로그램 재시작 요청에 실패했습니다: {exc}',
                **self.bridge.snapshot(),
            }
        return {
            'success': True,
            'message': ' · '.join([
                '상위 프로그램 재시작을 시작했습니다. '
                'Motor Manager와 현재 서보 상태는 유지됩니다',
                *[note for note in notes if note],
            ]),
            'restart_mode': 'upper_service',
            'stopped_playback': stopped_playback,
            'restart_services': list(restart_services),
            **self.bridge.snapshot(),
        }

    def _run_status(self) -> Dict[str, Any]:
        status = self.bridge.cached_run_status()
        return dict(status) if isinstance(status, dict) else {}

    def _local_run_state(self) -> str:
        """이 PC 의 재생(단독 · 그룹 몫)이 돌면 그 상태 이름 · 아니면 빈 값"""
        state = str(self._run_status().get('state') or '').strip().lower()
        return state if state and run_state.is_running(state) else ''

    def playback_in_progress(self) -> str:
        """재생이 도는가 · 돌면 상태 이름 · 수정 목록 144

        단독 재생 · 초기 이동 · 회차 대기 · 그룹 초기 위치 뒤 시작 대기 · 그룹 준비 단계(이 PC 로컬
        재생은 아직 서 있다 · `run_state.group_is_active`)까지 「재생 중」 으로 본다.
        """
        local = self._local_run_state()
        if local:
            return local
        status = self._run_status()
        if str(status.get('state') or '') == 'initialized' and status.get('group_execution'):
            return 'initialized'
        coordination = getattr(self.bridge, 'coordination', None)
        group_blocker = getattr(coordination, 'local_execution_blocker', None)
        if callable(group_blocker):
            try:
                if group_blocker():
                    return 'group'
            except Exception:  # noqa: BLE001 · 연동 노드를 못 읽으면 로컬 상태만으로 판단
                return ''
        return ''

    def _stop_playback_before_restart(self) -> str:
        """「정지」 버튼과 같은 정지 · 최종 출력 정지 → 재생 정지 · 그 자리 · 서보 유지 · 수정 목록 144

        멈출 때까지 최대 `RESTART_STOP_WAIT_SEC` 기다린다 · 넘기면 그대로 다시 시작한다(재생 노드가
        재시작으로 내려가고 Motor Manager 는 마지막 목표에 선다) · 돌려주는 값은 응답에 붙일 한 줄.
        """
        failures = []
        for label, call in (
            ('최종 출력 정지', lambda: self.bridge.request_safety_stop(False)),
            ('재생 정지', self.bridge.motion_run_stop),
        ):
            try:
                result = call()
            except Exception as exc:  # noqa: BLE001 · 정지 실패도 다시 시작은 간다
                result = {'success': False, 'message': str(exc)}
            if isinstance(result, dict) and result.get('success') is False:
                failures.append(f'{label} 확인 실패: {result.get("message") or "응답 없음"}')
        deadline = time.monotonic() + float(self.RESTART_STOP_WAIT_SEC)
        while self._local_run_state() and time.monotonic() < deadline:
            time.sleep(0.1)
        remaining = self._local_run_state()
        if remaining:
            failures.append(
                f'{self.RESTART_STOP_WAIT_SEC:g} s 안에 정지 확인 못 함({remaining}) · 그대로 다시 시작'
            )
        return ' · '.join(['재생을 정지했습니다', *failures])

    def restart_motor_control(self) -> Dict[str, Any]:
        """Restart the persistent Motor Manager only after explicit confirmation."""
        self.clear_stopping_release_state()
        motor_service = str(
            os.environ.get('MOTION_MOTOR_SERVICE_UNIT') or ''
        ).strip()
        if motor_service != 'motion-motor.service':
            self.clear_stopping_release_state()
            return {
                'success': False,
                'message': (
                    'Motor Manager 분리 서비스가 설치되지 않았습니다. '
                    '최초 설치를 다시 실행하세요'
                ),
                **self.bridge.snapshot(),
            }
        runtime_config = self.repository.runtime.selected_runtime_motor_config()
        if runtime_config is None:
            self.clear_stopping_release_state()
            return {
                'success': False,
                'message': (
                    '현재 프로젝트의 모터 설정이 장비에 적용되지 않았습니다. '
                    '모터 설정에서 「장비에 적용 · 모터 재시작」을 먼저 누르세요'
                ),
                **self.bridge.snapshot(),
            }
        expected_axes = motion_file_analysis.configured_axes_from_runtime_file(runtime_config)
        if not expected_axes:
            self.clear_stopping_release_state()
            return {
                'success': False,
                'message': '현재 모터 실행 설정에서 대상 모터를 확인할 수 없습니다',
                **self.bridge.snapshot(),
            }
        self.project.ensure_change_allowed()
        lifecycle_lock = getattr(self, 'lifecycle_lock', None)
        if lifecycle_lock is None:
            lifecycle_lock = threading.Lock()
            self.lifecycle_lock = lifecycle_lock
        if not lifecycle_lock.acquire(blocking=False):
            self.clear_stopping_release_state()
            return {
                'success': False,
                'message': MOTOR_BUSY_MESSAGE,
                **self.bridge.snapshot(),
            }
        try:
            operation = self.runtime.restart_lifecycle().begin(
                project_id=self.repository.selected_project_id(),
                runtime_file=runtime_config,
                expected_axes=expected_axes,
            )
        except (OSError, RuntimeError, ValueError) as exc:
            operation_id = str(
                locals().get('operation', {}).get('operation_id') or ''
            )
            if operation_id:
                try:
                    self.repository.runtime.finish_motor_operation(
                        operation_id,
                        'failure',
                        phase='failed',
                        error=str(exc),
                    )
                except ValueError:
                    pass
            return {
                'success': False,
                'message': f'모터 제어 시스템 재시작 요청에 실패했습니다: {exc}',
                **self.bridge.snapshot(),
            }
        finally:
            lifecycle_lock.release()
        return {
            'success': True,
            'message': (
                '모터 제어 시스템 재시작을 시작했습니다. '
                'AC 서보가 꺼졌다가 자동으로 다시 켜질 수 있습니다'
            ),
            'restart_mode': 'motor_service',
            'motor_operation': self.repository.runtime.motor_operation_status(),
            **self.bridge.snapshot(),
        }

    def clear_runtime_application(self) -> Dict[str, Any]:
        """Stop Motor Manager and clear runtime ownership for project deletion."""
        motor_service = str(
            os.environ.get('MOTION_MOTOR_SERVICE_UNIT') or ''
        ).strip()
        if motor_service != 'motion-motor.service':
            return {
                'success': False,
                'message': (
                    'Motor Manager 분리 서비스가 설치되지 않았습니다. '
                    '최초 설치를 다시 실행하세요'
                ),
                **self.bridge.snapshot(),
            }
        runtime_state = self.repository.runtime.motor_runtime_state()
        runtime_project_id = str(runtime_state.get('target_project_id') or '').strip()
        if not runtime_project_id:
            return {
                'success': True,
                'cleared': False,
                'message': '해제할 모터 실행 적용이 없습니다',
                'runtime_project_id': '',
                **self.bridge.snapshot(),
            }
        project_blocker = self.project.change_blocker(
            allow_run_stopping=True,
        )
        if project_blocker:
            return {
                'success': False,
                'message': project_blocker,
                **self.bridge.snapshot(),
            }
        execution_blocker = self.bridge.coordination_execution_blocker()
        if execution_blocker:
            return {
                'success': False,
                'message': f'실행 적용을 해제하지 못했습니다: {execution_blocker}',
                **self.bridge.snapshot(),
            }
        moving_blocker = self.runtime.ethercat_scan_safety_blocker(
            require_fresh_motor_state=self.runtime.managed_service_active(motor_service),
            allow_run_stopping=True,
        )
        if moving_blocker:
            return {
                'success': False,
                'message': (
                    f'실행 적용을 해제하지 못했습니다: {moving_blocker}. '
                    '먼저 「전체 동작 정지」를 누르세요'
                ),
                **self.bridge.snapshot(),
            }
        lifecycle_lock = getattr(self, 'lifecycle_lock', None)
        if lifecycle_lock is None:
            lifecycle_lock = threading.Lock()
            self.lifecycle_lock = lifecycle_lock
        if not lifecycle_lock.acquire(blocking=False):
            return {
                'success': False,
                'message': MOTOR_BUSY_MESSAGE,
                **self.bridge.snapshot(),
            }
        operation: Dict[str, Any] = {}
        cleared: Dict[str, Any] = {}
        try:
            operation = self.repository.runtime.begin_motor_operation(
                'motor_runtime_clear',
                'preparing',
                timeout_sec=30.0,
                details={'previous_project_id': runtime_project_id},
            )
            try:
                self.bridge.motion_run_stop()
            except Exception:
                pass
            try:
                self.bridge.publish_safety_stop(False)
            except Exception:
                pass
            if self.runtime.managed_service_active(motor_service):
                self.repository.runtime.update_motor_operation(
                    str(operation['operation_id']),
                    'stopping_runtime',
                    message='Motor Manager 정지 및 EtherCAT 소유권 해제 중',
                )
                self.runtime.run_managed_service('stop', motor_service)
                try:
                    motor_config_rules.wait_for_ethercat_release(8.0)
                except Exception:
                    pass
            cleared = self.repository.runtime.clear_motor_runtime_target()
            motor_config_rules.clear_motor_config_selection(self.repository)
            self.clear_stopping_release_state()
            # Drop launch-time ownership so delete / runtime_project_id update
            # without waiting for a Bridge restart.
            self.applied = Path()
            self.repository.runtime.finish_motor_operation(
                str(operation['operation_id']),
                'success',
                phase='completed',
                message=str(cleared.get('message') or '모터 실행 적용 해제 완료'),
                details={
                    'previous_project_id': cleared.get('previous_project_id') or '',
                    'motor_service_stopped': True,
                },
            )
        except (OSError, RuntimeError, ValueError) as exc:
            operation_id = str(operation.get('operation_id') or '')
            if operation_id:
                try:
                    self.repository.runtime.finish_motor_operation(
                        operation_id,
                        'failure',
                        phase='failed',
                        error=str(exc),
                    )
                except ValueError:
                    pass
            return {
                'success': False,
                'message': f'실행 적용 해제 실패: {exc}',
                **self.bridge.snapshot(),
            }
        finally:
            lifecycle_lock.release()
        return {
            'success': True,
            'cleared': bool(cleared.get('cleared')),
            'previous_project_id': cleared.get('previous_project_id') or '',
            'message': (
                f"{cleared.get('message') or '모터 실행 적용을 해제했습니다'}. "
                'Motor Manager는 정지 상태입니다. '
                '다시 사용하려면 모터 설정에서 「장비에 적용 · 모터 재시작」을 누르세요'
            ),
            'runtime_project_id': '',
            'motor_operation': self.repository.runtime.motor_operation_status(),
            **self.project.list_projects(),
            **self.bridge.snapshot(),
        }
