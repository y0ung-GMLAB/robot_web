# 모터 스캔 계약 (MOTOR_SCAN_CONTRACT)

- 작성 · 2026-10-03 · 수정 목록 10-5 · `AGENTS.md` 「모터 스캔 영구 불변조건」의 코드·테스트 대응표
- 계약 버전 · `MOTOR_SCAN_CONTRACT_VERSION = 3` (`src/motion_state_monitor/motion_state_monitor/monitor_node.py`)
- 적용 범위 · 「전체 모터 검색」 · 「AC Servo 검색」 · 「Dynamixel 검색」 (화면 `05-panel-registration.html` · 버튼 `scanAllButton` · `scanButton` · `scanDynamixelButton`)
- 규칙 · 아래 불변조건은 세션·프로그램·컴퓨터 재시작 후에도 변경하거나 완화하지 않는다 · 스캔 코드를 수정하거나 완료로 보고하기 전에 이 문서와 §4 테스트를 확인한다

## 1. 경로 · 누가 무엇을 한다

| 단계 | 위치 | 역할 |
|---|---|---|
| 화면 | `src/web_ui/static/js/motor_config.js` · `motor_config_actions.js` | 버튼 → `POST /api/motors/scan` · `/scan/ac-servo` · `/scan/dynamixel` · 진행 `GET /api/motors/scan/progress` · 취소 `POST /api/motors/scan/cancel`(버튼 미부착) |
| 조율 | `src/web_bridge/motion_web_bridge/scan_orchestrator.py` · `ScanOrchestrator` | 스캔 요청 락 · 시한(`AC 10s` · `Dynamixel 40s` · 전체 = 합 50s) · 진행 이벤트 수집 · 결과를 프로젝트 축과 대조(서버가 합친다 · `motor_config_rules.py`) · 재시도 1회(`_scan_with_retry`) |
| 전송 | ROS 2 Action `MotorScan` (`src/motion_coordination_interfaces/action/MotorScan.action`) · `transport` = `all` / `ac_servo` / `dynamixel` | 피드백 = 진행 이벤트(`scan_id` 포함) · 취소는 **장치 종류 사이에서만** 확인 |
| 물리 검색 | `src/motion_state_monitor/motion_state_monitor/monitor_node.py` · `_execute_scan_goal` → `_build_scan_result` | `scan_id` 발급(`<ms>-<seq>`) · 장치 종류별 섹션 실행 · `complete` / `partial` / `failed` 판정 · `scan_contract` 블록 기록 |
| AC Servo | `ethercat_scanner.py` · `EthercatScanner` | `ethercat rescan` → Slave 재열거 → Slave 마다 SII EEPROM(`SII_READ_ATTEMPTS = 3`) · Alias 레지스터 · MINAS 드라이브 파라미터 SDO 읽기 |
| Dynamixel | `dynamixel_scanner.py` · `DynamixelScanner` | 직렬 포트 자동 탐색 · `1000000 bps` · Protocol `2.0` Broadcast Ping → ID `0~252` 개별 보조 Ping(`dynamixel_scan_id_fallback`) |

모터 통신 자체는 `motion_system`(Motor Manager)이 단일 통로다 · 스캔은 Motor Manager 를 **멈춘 뒤** 버스를 직접 읽고, 끝나면 다시 띄운다(EtherCAT 소유권 · `test_rescan_after_a_motor_is_gone.py`).

## 2. 불변조건 ↔ 코드

| # | 불변조건 (`AGENTS.md`) | 코드 | 결과 필드 |
|---|---|---|---|
| I-1 | 실행마다 AC Servo · Dynamixel 을 각각 새로 물리 검색 | `monitor_node._build_scan_result` · `SCAN_TRANSPORTS` | `scan_contract.physical_only = True` |
| I-2 | AC Servo · `ethercat rescan` → 재열거 → SII EEPROM · Alias 레지스터 | `ethercat_scanner.py` · `subprocess.run(['ethercat', 'rescan'])` · Slave 가 `OP` 이거나 마스터가 점유 중이면 `rescan_blocked = True` 로 **실패** 처리(옛 열거 재사용 금지) | `ethercat_scan.rescan_performed` · `rescan_blocked` · `slaves[].sii` · `rotary_alias` |
| I-3 | Dynamixel · 실제 직렬 포트 · Protocol 2.0 Broadcast Ping + ID 0~252 보조 Ping | `dynamixel_scanner.py` · `DYNAMIXEL_SCAN_MAX_ID = 252` · `DYNAMIXEL_SCAN_PROTOCOL = '2.0'` · `_broadcast_ping_dynamixel` · `_ping_dynamixel_id` | `dynamixel_scan.scan_rule` · `devices[].source = broadcast_ping / id_ping` |
| I-4 | 프로젝트 파일 · 이전 스캔 · 브라우저 메모리 · 런타임 캐시로 대체·보충 금지 | `monitor_node` 스캔 섹션은 버스·포트 응답만 담는다 · 런타임 축 목록은 **대조용** 으로만(`scan_orchestrator._expected_runtime_axes`) · 화면은 서버 결과를 그대로 그린다(`the_screen_draws_what_the_server_paired`) | `scan_contract.physical_only` |
| I-5 | 물리 응답 없으면 이전 값 대신 `실패` 또는 `검증 불가` | `_physical_section_success` · 섹션 `error` · 화면 「검색 실패」 · 첫 스캔(설정 파일 없음)은 실패가 아님(`test_the_first_scan_is_not_a_failure.py`) | `ethercat_scan.error` · `dynamixel_scan.error` |
| I-6 | 한 장치 종류만 성공 → 전체 `부분 완료` | `monitor_node` · `outcome = complete / partial / failed` · `scan_orchestrator` · `result['partial']` · `motor_config_rules` 「모터 검색 부분 완료」 | `scan_outcome` · `scan_complete` · `scan_contract.full_success_requires_all_requested_transports = True` |
| I-7 | 실행마다 고유 `scan_id` · 단계 · 장치별 응답 · 오류 · 재시도 · 총 소요시간 기록 | `_active_scan_id` · `_publish_scan_progress`(단계 이벤트) · `SII_READ_ATTEMPTS` · `scan_duration_ms` · 조율층 재시도 1회 | `scan_id` · `scan_duration_ms` · 진행 이벤트 `phase` |
| I-8 | 실물 응답 없이 `실물 검증 완료` 보고 금지 | 작업 규칙 · 코드 검증·실행 검증·실물 검증 구분 (`AGENTS.md`) | - |

## 3. 결과 모양 (요약)

```
scan_id               '<epoch_ms>-<seq>'
scan_duration_ms      총 소요시간
scan_outcome          complete | partial | failed
scan_complete         요청한 장치 종류가 모두 성공했는가
scan_contract         { version: 3, physical_only: true, ethercat_requires_rescan: true,
                        dynamixel_protocol: '2.0', dynamixel_baudrate: 1000000,
                        dynamixel_id_min: 0, dynamixel_id_max: 252,
                        full_success_requires_all_requested_transports: true }
ethercat_scan         { rescan_performed, rescan_blocked, slaves[], slaves_count, error }
dynamixel_scan        { scan_rule, port, devices[], devices_count, error }
cancelled             장치 종류 사이에서 취소됐는가
```

## 4. 관련 자동 테스트 · 수정 전후 반드시 실행

| 테스트 | 지키는 조건 | 실행 조건 |
|---|---|---|
| `src/motion_state_monitor/test/test_connection_state.py` · `test_ethercat_scan_rescans_bus_before_reading_sii` · `test_ethercat_scan_blocks_rescan_while_slave_is_operational` · `test_ethercat_scan_blocks_rescan_while_master_is_claimed_during_startup` | I-2 | ROS 2 (`rclpy`) |
| 〃 · `test_dynamixel_targets_cover_all_valid_ids` · `test_dynamixel_scan_never_injects_runtime_devices` | I-3 · I-4 | 〃 |
| 〃 · `test_physical_scan_success_requires_complete_direct_result` · `test_failed_physical_scan_never_turns_runtime_feedback_into_physical_online` · `test_bus_discovery_does_not_override_runtime_offline` | I-4 · I-5 | 〃 |
| 〃 · `test_full_scan_is_not_success_when_only_one_transport_completes` | I-6 | 〃 |
| 〃 · `test_scan_contract_is_persisted_in_every_scan_result` · `test_scan_progress_publishes_real_backend_event` | I-7 · 계약 블록 | 〃 |
| 〃 · `test_cancel_between_transports_skips_the_remaining_one` · `test_without_cancel_both_transports_run` · `test_transport_map_covers_every_scan_kind` | 취소 위치 · 종류 표 | 〃 |
| 〃 · `test_sii_header_is_the_physical_alias_and_identity_source` · `test_physical_alias_matching_is_scoped_to_master` | SII 가 신원의 출처 | 〃 |
| `src/motion_state_monitor/test/test_eeprom_read_is_retried.py` | SII 재시도 3회 · 1회 실패로 전체 실패 금지 | 없음 |
| `src/motion_state_monitor/test/test_ping_reply_is_really_a_ping_reply.py` | Ping 응답 검증(CRC · 포트 공유 시 오염 거부) | 없음 |
| `src/web_bridge/test/test_scan_timeouts.py` | 시한 · 전체 = AC + Dynamixel | ROS 2 |
| `src/web_bridge/test/test_scan_progress.py` | 진행 이벤트 수집 · `scan_id` | ROS 2 |
| `src/web_bridge/test/test_a_failed_scan_tries_again.py` | 조율층 재시도 1회 | ROS 2 |
| `src/web_bridge/test/test_rescan_after_a_motor_is_gone.py` | 재검색 시 Motor Manager 정지·재기동 · EtherCAT 소유권 | ROS 2 |
| `src/web_bridge/test/test_the_first_scan_is_not_a_failure.py` | 첫 스캔 · 설정 없음 ≠ 실패 | ROS 2 |
| `src/web_bridge/test/test_the_server_pairs_the_scan.py` | 서버가 스캔 결과·프로젝트 축을 합친다 · 부분 완료 판정 | 없음 |
| `src/web_bridge/test/test_alias_addressing.py` · `test_ethercat_alias_manager.py` | Alias 주소 · `alias` 있으면 `position = 0` | 없음 / ROS 2 |
| `src/web_bridge/test/test_mapping_motor_presence.py` | 매핑 줄의 모터가 이 PC 에 있는가 (스캔 결과 기준) | ROS 2 |
| `src/web_ui/test/a_fresh_scan_shows_now_not_before.test.mjs` · `the_screen_draws_what_the_server_paired.test.mjs` · `operation_progress.test.mjs` · `motor_config_buttons.test.mjs` | 화면은 지금 결과만 · 서버 판정 그대로 · 진행 표시 | `node --test` |

실행 · 실기(ROS 2) · `pytest src/motion_state_monitor src/web_bridge` · `cd src/web_ui && node --test test/*.test.mjs`
ROS 없는 PC · `rclpy` 를 쓰는 파일은 수집 오류로 빠진다 · 그 결과로 I-2 · I-6 을 `확인됨` 으로 보고하지 않는다.

## 5. 실물 검증 항목 (코드·실행 검증으로 대체 불가)

- 「전체 모터 검색」 2회 연속 → `scan_id` 다름 · `scanned_at` 갱신 · 값 동일
- 모터 1대 전원 차단 후 검색 → 해당 장치 `실패`/빠짐 · 이전 값 미표시
- AC Servo 만 연결 · Dynamixel 포트 분리 → 결과 `부분 완료`
- 검색 중 `ethercat slaves` 로 `OP` 상태 Slave 확인 → `rescan_blocked` 사유 표시
