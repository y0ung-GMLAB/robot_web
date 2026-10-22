# 직렬 버스 서보 설계 (SERIAL_SERVO_DESIGN)

- 작성 · 2026-10-21 · 수정 목록 158 · 사용자 결정 2026-10-21
- 대상 · Dynamixel 여러 모델 · Feetech (STS 계열) · 한 로봇에 AC 서보와 섞어 씀
- 범위 승인 · `src/motion_system` 수정 포함 (사용자 2026-10-21 「2~4 승인」) · 조건 **AC 서보(MINAS · EtherCAT) 동작 변화 없음**
- 제외 · Dynamixel Protocol 1.0(AX · 구형 MX) · Dynamixel XL320 · Y 시리즈 · 옛 PRO(H/M) · RH-P12-RN · Feetech SCS 계열(빅 엔디언 · 후속)
- 어댑터 · ROBOTIS U2D2 (Dynamixel · Feetech 둘 다) · **한 포트 = 한 종류** (Dynamixel 과 Feetech 를 한 버스에 섞지 않음)

## 1. 종류 표 · 한 곳에서 판단

| kind (`motor_type`) | `driver_family` | `transport` | 패킷 | 짧은 이름 | 토크 켜기/끄기 | 재부팅 | 다회전 |
|---|---|---|---|---|---|---|---|
| `ac_servo` | `minas` | `ethercat` | CiA402 PDO | AC | 서보 ON/OFF | 알람 리셋 | 드라이브 |
| `dynamixel` | `dynamixel` | `serial` | Protocol 2.0 (`dxl2`) | DXL | O | O (REBOOT 0x08) | Extended Position(4) |
| `feetech` | `feetech` | `serial` | Feetech SCS/STS (`scs`) | FT | O | **X** | X (한 바퀴 · 0~4095) |

- 판단 함수 · `motion_common/motor_kinds.py` 한 곳 · 문자열 추측 함수(`is_dynamixel_motor` · `_is_dynamixel` · `runtimeIsDynamixel` 등)는 이 표를 부름
- `is_serial_servo(kind)` · `dynamixel` · `feetech` 공통 동작(토크 · 조그 · 절대 이동 · 오류 표시)
- 종류별 동작 · 재부팅 · 모델 이름 · 검색만
- 화면(JS) · 같은 표의 사본 `static/v2/js/motor_kinds.js`
- 새 동작 · `feetech` 로 명시된 모터만 · 그 밖(모르는 종류 · 종류 없음 포함) · **지금과 똑같이** (AC 무영향 조건 · 런타임 줄은 메타데이터 없으면 `motor_type: unknown` 으로 옴 → 지금처럼 AC 화면)

## 2. 레지스트리 · 모터 이름

- 레지스트리 모터 · `motor_type` = kind · `driver_family` · `transport: serial`
- `identity` · `serial_port` · `serial_baudrate` · `bus_id` · `model_number`
- `profile.driver_model` · 정식 모델 이름 (예 `XM430-W350` · `STS3215`)
- `motor_ref` · `dynamixel:port:<포트>:id:<n>` (기존) · `feetech:port:<포트>:id:<n>` (새) · 옛 이름 없음
- 직렬 마스터 · (포트 · 속도) 하나에 하나 · 속도 = 검색 결과 `serial_baudrate` (전 Dynamixel 1 Mbps 고정 · 값 없을 때만 1 Mbps)

## 3. 모터 설정 파일 (motor_manager 입력)

- `masters[].type: serial` · `serial_port` · `serial_baudrate` · `slaves[].bus_id` (기존 그대로)
- `drivers[].type` · `dynamixel` | `feetech` (새)
- `drivers[].param_file` · 저장 때 생성 · `config/serial_params/driver_<id>.yaml` · 절대경로 (MINAS `config/minas_params/` 와 같은 방식)
- 생성 재료 · 패킷 종류 기본 yaml(`config/serial_servo/dynamixel_x.yaml` · `dynamixel_p.yaml` · `feetech_sts.yaml`) + 모델 파일 + 시리즈 값
- 같은 모델 XM540-W150 · W270 · 생성 파일 내용 = 지금 `config/dynamixel_xm540_*.yaml` 과 같음 (회귀 시험)

### 3-1. param yaml 새 키 (없으면 지금 동작 그대로)

| 키 | 값 | 기본 | 뜻 |
|---|---|---|---|
| `protocol.packet` | `dxl2` · `scs` | `dxl2` | 패킷 형식 |
| `protocol.sync_read` · `sync_write` | 바이트 | 0 | `scs` 묶음 읽기·쓰기 (0x82 · 0x83) · 0 = 개별 READ |
| `protocol.reboot` | 바이트 | 8 | 0 = 재부팅 없음 (Feetech) |
| `byte_order` | `little` · `big` | `little` | 여러 바이트 값 순서 |
| `interfaces[].sign_bit` | 비트 번호 | 없음 | 부호-크기 표현 (Feetech 위치·속도 bit 15) |
| `acceleration_unit` | deg/s² per raw | 21.4577 | Profile Acceleration 단위 (X 214.577 rev/min² · P 1 rev/min² = 0.1) |
| `position_raw_min` · `position_raw_max` | raw | ±`extended_position_raw_limit` | 목표 위치 자르기 범위 |

### 3-2. 시리즈 값

| 시리즈 | 모델 파일 | 운전 모드 | 가속 단위 | 전류 단위(`unit_effort`) | 위치 범위 |
|---|---|---|---|---|---|
| Dynamixel X (XL430 · XC430 · XM · XH · XD · XW · 2XL · 2XC) | `control_table/<모델>.model` | 4 Extended | 21.4577 | XM · XH · XD · XW 0.00269 · XL430 · XC430 없음(부하 %) | ±1,048,575 |
| Dynamixel XL330 · XC330 | 〃 | 4 | 21.4577 | 0.001 | ±1,048,575 |
| Dynamixel MX (2.0) | 〃 | 4 | 21.4577 | MX-64 · 106 0.00336 · MX-28 없음 | ±1,048,575 |
| Dynamixel P (PH · PM) | 〃 | 4 | 0.1 | 0.001 | ±2,147,483,647 |
| Feetech STS | `hardware/feetech/control_table/sts.model` | 0 위치 | 8.7890625 (100 step/s²) | 0.0065 | 0 ~ 4095 |

- P · MX · XL330 · Feetech 값 · e-manual · 공개 SDK 기준 · **실물 미검증**

## 4. motor_manager (C++) 변경

- `SerialMaster` · 패킷 형식 둘 (`dxl2` 지금 그대로 · `scs` 새)
- 읽기 · 노드마다 읽을 항목을 연속 구간(span)으로 묶음 · **매 주기 전 구간 읽기** (전 주기마다 한 항목만 · 위치 갱신이 항목 수만큼 늦음)
- `dxl2` · Bulk Read 0x92 · 구간 번호마다 한 패킷 · `scs` · Sync Read 0x82 (같은 구간끼리) · 없으면 개별 READ
- 쓰기 · `dxl2` Bulk Write 0x93 (지금 그대로) · `scs` Sync Write 0x83
- 통신 끊김 · 주기 단위 셈 (전 패킷 단위) · 20 주기 무응답 → `errorcode` 0xFFFF (기존 값)
- 장애 격리 (수정 목록 27-1 · 27-2) · 직렬 스레드 예외 → 그 포트만 「통신 불가」 · 1 s 마다 다시 열기 · **EtherCAT 루프 계속** · 시작 때 포트 없음도 같은 처리 (전 motor_manager 시작 실패)
- 다시 연결 · 부팅 항목 다시 확인·쓰기 · 토크는 자동으로 켜지 않음
- 설정 항목 못 씀 → 그 축 `errorcode` 0xFFFE (설정 대기) · 토크 켜기·명령 막음
- Torque Enable · 0/1 만 씀 (Feetech STS 128 = 현재 위치를 중앙으로 보정 · 금지)
- 알람 리셋(controlword bit 7) · Dynamixel REBOOT · Feetech 토크 OFF 쓰기 (재부팅 없음 · Feetech 0x06 = 공장 초기화 · 금지)
- `DriverType::Feetech` · 클래스 `feetech::FeetechDriver` (Dynamixel 드라이버와 같은 yaml·모델 파일 방식)
- 빌드 · `MOTOR_MANAGER_WITH_ETHERCAT` (기본 ON · ON 이면 지금처럼 ecrt.h 필수) · OFF = 직렬 전용 PC · 개발 PC 시험용
- EtherCAT · MINAS · 공용 프레임 · `MotorStatus` 메시지 · **변경 없음**

## 5. 검색

- `MotorScan.action` `transport` · `all` · `ac_servo` · `dynamixel` · `feetech` (문자열 · 메시지 구조 변경 없음)
- `전체 모터 검색` · AC · Dynamixel · Feetech 각각 새로 물리 검색 · 하나라도 실패 → `부분 완료`
- Dynamixel · 지금 규칙 그대로 (Protocol 2.0 Broadcast Ping + ID 0~252 보조 Ping) · 속도 목록 · 1 Mbps 먼저 · 그 뒤 57600 (X 공장값) · 4 Mbps
- Feetech · 포트마다 · 속도 1 Mbps 먼저 · 그 뒤 500000 · 115200 · ID 0~253 개별 Ping(0x01) · 응답 ID 의 모델 번호(주소 3 · 2 바이트) 읽기
- 모델 번호 · STS3215 777 · STS3250 2825 · 그 외 → `Feetech (버전 <n>)` (같은 제어표로 동작 · 확인 필요 표시 · 주소 3~4 = 서보 버전 번호 · HLS 도 우리가 쓰는 주소 33 · 40~46 · 56~69 가 STS 와 같음 · 2026-10-22)
- 한 포트에서 두 종류 모두 응답 → 검색 결과 경고 (한 포트 = 한 종류)

## 6. 화면

- 모터 목록 짧은 이름 · AC · DXL · FT
- 검색 버튼 · 「AC 서보 검색」 · 「다이나믹셀 검색」 · 「Feetech 검색」 · 「전체 모터 검색」
- 직렬 서보 공통 · 토크 켜기/끄기 · 조그 · 절대 이동 · 감속·기어비 편집
- 재부팅 · Dynamixel 만
- AC 전용 · 드라이브 게인 · EEPROM 저장 · 앱솔루트 · 다회전 클리어 · 과부하율 · 브레이크 지연 · 지금 그대로 AC 만

## 7. 설치

- udev · `/etc/udev/rules.d/99-robot-serial.rules` · FTDI(U2D2 = FT232H · 0403:6014) `latency_timer` = 1 ms (기본 16 ms · 왕복마다 16 ms 대기)
- 포트 이름 · `/dev/serial/by-id/...` 사용 (USB 순서가 바뀌어도 같음 · 검색이 이미 이 경로 우선)
- `dialout` 그룹 · 기존 그대로

## 8. AC 무영향 검증

- C++ · EtherCAT · MINAS 파일 diff 없음 · `motor_manager.cpp` EtherCAT 경로 변경 없음 (`#if` 감싸기만)
- Python · 전체 pytest (WSL ROS) · AC 시험 모두 통과
- JS · 전체 `node --test`
- 회귀 · AC 전용 레지스트리 → 생성 모터 설정 파일 = 변경 전과 같음 (바이트 비교)
- 회귀 · XM540 레지스트리 → param 파일 내용 = 변경 전 정적 파일과 같음
- 직렬 · 가짜 서보(pty) 로 motor_manager_node 실행 · Dynamixel · Feetech 각각 읽기·쓰기·끊김·다시 연결
- 결과 (2026-10-21 · WSL · IgH 사용자 라이브러리로 EtherCAT 켠 빌드) · `libethercat.a` · `libminas.a` · `libzeroerr.a` · `libcanopen.a` · `libsocketcan.a` · `libcubemars.a` · HEAD 와 바이트 같음 · 가짜 서보 시험 25/25 · 4회 반복 같음

## 9. 실물 확인 목록

- F-1 · U2D2 + STS3215 · 검색 · 모델 번호 777 · ID
- F-2 · 토크 켜기/끄기 · 조그 · 위치 단위 (4096 step = 360°)
- F-3 · 가속 단위 (100 step/s²) · 속도 단위 (step/s)
- F-4 · 과부하 보호 뒤 알람 리셋(토크 OFF) 으로 풀리는가
- F-5 · Status(주소 65) 비트 뜻
- D-1 · Dynamixel X 외 모델(XL330 · P) · 전류 · 가속 단위
- D-2 · 포트 하나에 여러 모델 · 매 주기 전 항목 읽기 · 주기 시간
- C-1 · 섞어 쓰기 · AC + Dynamixel + Feetech · USB 뽑기 → AC 계속 동작 · 다시 꽂기 → 복귀
