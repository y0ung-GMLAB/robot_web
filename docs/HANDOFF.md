# 인수인계

- 최초 작성 · 2026-08-22 · 최종 갱신 · 2026-10-03 (수정 목록 10-6 · `robot_web` · `main` 기준 현행화)
- 저장소 · `https://github.com/y0ung-GMLAB/robot_web` · 기본 브랜치 `main`
- 전신 · `motion_web` (`kimjoonho-git/motion_web` · 브랜치 `refactor/motion-common-extract`) · MIDI 녹화·모션 스튜디오(`midi_control` · `motion_studio`)는 삭제됐다 · 애니메이션 저작은 Blender(저장소 밖)
- `src/motion_system` · **서브모듈 아님** · 2026-10-02 이 저장소 안으로 합침 (`src/motion_system/VENDORED.md`) · 보호 대상 · 사용자가 범위를 명시한 경우에만 수정 (`AGENTS.md`)
- 실물 구성 · 문서의 옛 구성(AC 1축 · Dynamixel 2대 · MIDI)은 더 이상 기준이 아니다 · 현재 매장 로봇은 MINAS 5축(매장마다 다름) · 현행화는 수정 목록 17 과 함께

---

## 1. 패키지 · 무엇이 어디에 있나

| 패키지 (`src/`) | 역할 | 비고 |
|---|---|---|
| `motion_common` | 공용 순수 모듈 · 토픽 상수 · 주기 · 모션 테이블 · 로봇 팩 · 저장소 락 | `rclpy` 의존 없음 (`test_package_boundaries.py`) |
| `motion_coordination` · `motion_coordination_interfaces` | PC 간 그룹 연동 · `MotorScan` Action 정의 | DDS · `docs/DDS_MULTI_PC_VALIDATION.md` |
| `motion_runtime` | 매핑 관리 · 실행 계획(`plan_builder`) · 재생(`motion_player`) · 자동 반복 | 초기 위치 기본값 `reference` (13-3) |
| `motion_supervisor` | 재생·조그·페이더 명령 중계 · 모터 명령 발행 | 수신 정지 결함(수정 목록 14) 미해결 |
| `motion_state_monitor` | 모터 상태 · 물리 검색(EtherCAT · Dynamixel) | 계약 `docs/MOTOR_SCAN_CONTRACT.md` |
| `motion_schedule` | 스케줄 발화 | - |
| `web_bridge` (`motion_web_bridge`) | FastAPI · 프로젝트 저장소 · 서비스 계층 · MuJoCo 미리보기 | 라우트 `routes/` |
| `web_ui` (`motion_web_ui`) | 정적 화면 · `static/js` · 패널 `static/panels` · `node --test` 테스트 | 소스에서 서빙 · 빌드 불필요 |
| `motion_system` | Motor Manager(C++) · EtherCAT · Dynamixel 드라이버 · 모터 통신 단일 통로 | 보호 대상 · 자동 테스트 0건 |

문서 · `README.md`(구성 · 설치) · `docs/사용법.md` · `docs/ARCHITECTURE_REVIEW.md`(§5 계획 · §6 이력 · §8 검증 표) · `docs/MOTOR_SETUP_ARCHITECTURE.md` · `docs/SYSTEM_OPERATION_FLOW.md` · `docs/SCHEDULE_MOTION_DESIGN.md` · `docs/구조_점검.md` · **`docs/수정_목록.md`(현재 할 일 · 상태 · 검증 기준)**

---

## 2. 검증 환경 · 세 가지

| 환경 | 되는 것 | 안 되는 것 |
|---|---|---|
| 실기 (Ubuntu · ROS 2 Humble · 모터) | `pytest` 전체 · `colcon build` · 노드 실행 · 실물 검증 | - |
| ROS 없는 Linux (클라우드 컨테이너 · 2026-10-03 확인) | `ruff` · `node --test` · `pytest` 중 `rclpy` 안 쓰는 파일 (약 1,600건) | `rclpy` 수집 오류 파일(46) · 노드 생성 테스트 · 실물 |
| Windows | 코드 편집 · `pytest src/motion_common` · `ruff` | 그 외 전부 |

### ROS 없는 PC 에서 돌리는 법

```bash
pip install pytest pyyaml numpy fastapi httpx uvicorn ruff
export PYTHONPATH=$(ls -d $PWD/src/*/ | grep -v motion_system | tr '\n' ':')
pytest -q --continue-on-collection-errors -m "not hardware"
ruff check .                                   # 2026-10-03 · 48건 (기준선 55 이하)
cd src/web_ui && node --test test/*.test.mjs   # 411건 · Node 18~22
```

`rclpy` 수집 오류는 환경 한계다 · 그 파일의 조건은 실기에서만 `확인됨` 으로 보고한다.
`std_msgs`·`rclpy` 대역(stub)을 넣으면 더 돌지만 메시지 기본값이 달라 거짓 실패가 섞인다 · 결과를 실기 결과로 쓰지 않는다.

### 실기 명령 모음

```bash
pytest                                              # 전체
cd src/web_ui && node --test test/*.test.mjs
ruff check .
colcon build --symlink-install --packages-select motion_web_bridge
systemctl --user restart motion-control.service      # 웹·노드
systemctl --user restart motion-motor.service        # Motor Manager
./scripts/build_and_restart.sh                       # 전체 빌드 + 재시작
bash scripts/restart_motion_monitor.sh               # 실행 권한 없음 · bash 로
```

웹 UI 는 소스에서 서빙된다 (`system_routes.py`) · JS 수정은 브라우저 `Ctrl+F5` 만으로 반영.

---

## 3. 현재 상태 · 2026-10-03

- 로드맵 (`ARCHITECTURE_REVIEW.md` §5) 0~7단계 완료 · 8단계(하드웨어 스캐너 `motion_system` 이관) 접음
- 저장소 정리(수정 목록 10) · 깨진 테스트 재작성 · `motion_studio`/`midi_control` 잔여 참조 정리 · ruff 85 → 48 · 루트 임시 파일 삭제 · `MOTOR_SCAN_CONTRACT.md` 신설
- 열린 결함 · `motion_supervisor` 수신 정지(14 · 2026-09-08 1회 · 원인 미특정) · 재생 프레임 폐기 무감지(12) · 알람 리셋 폐기(1 · `motion_system`)
- 단위 전환(6 · 내부 rad · 화면 deg) · 웹 3D(7) · 시뮬·실물 동기(8) · 무인 복귀 설치(11) · 전부 `대기`

할 일의 유일한 기준은 **`docs/수정_목록.md`** 다 · 항목별 대상 · 범위 · 검증 방법 · 상태(`대기`/`진행`/`완료`/`보류`) 가 거기 있다.

---

## 4. 알아둘 것

- **`src/motion_system` 보호** · 일반 수정 요청을 여기까지 넓히지 않는다 · 모터 통신은 이 경로만 쓴다
- **프로젝트 격리** · 설정·작업 데이터는 활성 프로젝트 기준 · 다른 프로젝트 값을 기본값으로 쓰지 않는다 · 관련 수정은 프로젝트 2개로 검증
- **모터 스캔 불변조건** · `AGENTS.md` · `docs/MOTOR_SCAN_CONTRACT.md` · 매번 물리 검색 · 캐시 대체 금지 · 부분 완료 구분
- **`ROS_LOCALHOST_ONLY`** · 서비스·재시작 스크립트 모두 `MOTION_GROUP_NETWORK=1` → `=0` (그룹 연동 · 19 정정 완료) · 셸에서 `ros2` 명령이 노드를 못 보면 이 값을 맞춘다
- **ROS 노드 로그** · systemd 저널이 아니라 `log/ros/<실행>/` (`ROS_LOG_DIR` · 서비스 스크립트가 지정 · 14일 지나면 시작 시 삭제 · 21-1) · 재시작 로그 `log/web_apply_restart/` 14일 · 설정 변경 이력 `<프로젝트>/runtime/history/<분류>/` 50개 (21)
- **MuJoCo 미리보기** · `config/animation_preview.yaml` 또는 로봇 팩 `preview.yaml` · 계산 결과 `.sim.npz` · 계산 출력 기록 `log/animation_preview/` · 네이티브 뷰어 창 없음(7) · **웹 3D 표시**(7-a · 「MuJoCo 같이 보기」 = 웹 3D 따라가기) · `scripts/sim/export_scene.py` → `runtime/preview/scene-*.json` · 브라우저 three.js(`static/vendor/three/`) + `sim3d_math.js`(MuJoCo 와 같은 순방향 운동학 · `sim3d_fk.test.mjs`)
- **설치** · `scripts/install.sh` · 수동 단계 잔존(EtherLab · linger · 절전) · 수정 목록 11
- **Claude Code** · `.claude/settings.json` · 모터 관련 명령은 확인을 받도록 설정 · 작업 규칙은 `AGENTS.md`

### 되돌리기

```bash
git log --oneline -20
git revert <해시>                 # 커밋 단위
./scripts/build_and_restart.sh
```

---

## 5. 지표 · 도구

- `scripts/code_metrics.py --baseline docs/metrics/baseline-20260822.json` · 줄 수·테스트·ruff 추이
- `scripts/bridge_state_map.py --bundles` · 브리지 상태·락 의존 지도 (`docs/metrics/bridge-state-map-20260908.json`)
- `scripts/check_locks.sh` · 락 파일 점검 · `scripts/check_dds_shm.sh` · DDS 공유메모리 점검
- `scripts/sim/` · MuJoCo 계산(`sim_run.py`) · 재생(`replay_run.py`) · 보기(`view_run.py`) · `scripts/sim/README.md`
