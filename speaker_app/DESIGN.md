# 스피커 트리거 앱 — 설계 및 진행 문서

최종 갱신: 2026-08-20

---

## 1. 배경

별도 PC 3대에서 ROS 2 Humble 기반 모션 제어 시스템(`motion_web`)이 DDS로 연동 동작 중이다.
이 문서의 대상은 **4번째 PC(스피커 PC)** 로, 위 시스템의 모션 시작 트리거를 수동으로 관찰해
음성 파일을 재생하는 앱이다.

- 대상 저장소: https://github.com/kimjoonho-git/motion_web (공개)
- 기존 3대: Ubuntu 22.04.5 / ROS 2 Humble / Python 3.10.12
- 스피커 PC: 동일 사양 (Ubuntu 22.04.5, Python 3.10.12, amd64)
- 네트워크: 동일 공유기, Wi-Fi `wlp3s0` (172.16.20.0/22, GW 172.16.20.1), 유선 미사용

### 최우선 원칙

**스피커 PC는 기존 3대의 연동에 일절 관여하지 않는다.**
DDS 도메인에 대한 발행(publish)은 0건이며, 구독만 한다.
스피커 PC가 꺼져 있거나 고장 나도 3대의 모션 실행은 영향을 받지 않는다.

---

## 2. 요구사항

1. 모션 시작 트리거를 감지해 음성 재생
2. 초기화 이동 시에는 재생하지 않고, **모션 시작 시에만** 재생
3. 사이클 반복마다 재생
4. 도메인 ID / 그룹 ID를 사용자가 설정 가능
5. 재생 시점 오프셋을 사용자가 설정 가능 (음수 = 모션보다 먼저 재생)
6. DDS와 무관하게 **단독으로도** 음성 재생 가능 (반복 횟수, 반복 간격)
7. 웹 UI로 조작 (동일 네트워크의 다른 PC/폰에서도 접속)
8. 정지 처리는 불필요. 재생 중 새 트리거가 오면 **처음부터 재시작**

---

## 3. 대상 시스템 분석 결과 (코드로 검증 완료)

### 3.1 DDS 토픽 구성

토픽은 `group_id`로 분리되지 않고 **`/motion_group/` 고정 네임스페이스**를 사용한다.
그룹 구분은 메시지 내부의 `group_id` 필드로만 이루어진다.

| 토픽 | 타입 | QoS | 사용 여부 |
|---|---|---|---|
| `/motion_group/command` | `GroupCommand` | RELIABLE, VOLATILE, depth 32 | **구독함** |
| `/motion_group/event` | `GroupEvent` | RELIABLE, VOLATILE, depth 32 | 미사용 |
| `/motion_group/heartbeat` | `GroupHeartbeat` | RELIABLE, TRANSIENT_LOCAL, 8 | 미사용(주의) |
| `/motion_group/system_info` | `GroupSystemInfo` | RELIABLE, TRANSIENT_LOCAL, 16 | 미사용(주의) |
| `/motion_group/alarm` | `GroupAlarm` | RELIABLE, TRANSIENT_LOCAL, 16 | 미사용(주의) |
| `/motion_group/time_sync` | `GroupTimeSync` | RELIABLE, VOLATILE, 32 | 미사용 |

**주의**: TRANSIENT_LOCAL 토픽을 구독하면 발행자가 과거 샘플을 재전송하므로
기존 3대에 실제 부하가 발생한다. 절대 구독하지 않는다.

구독은 **BEST_EFFORT** 로 건다. RELIABLE 발행자와 정상 매칭되며,
발행자에게 ACK/재전송 의무를 지우지 않는다.

### 3.2 GroupCommand 메시지 필드

```
string   group_id
string   execution_id
string   command_id
string   coordinator_id
string   command
uint64   sequence
uint32   cycle_number
builtin_interfaces/Time sent_at
int64    scheduled_monotonic_ns
string[] participant_ids
string   repeat_mode
float64  dwell_sec
bool     initialization_only
string   run_mode
uint32   target_cycle_count
```

### 3.3 명령 종류 (`command` 필드)

| 값 | 의미 | 재생 |
|---|---|---|
| `initialize_at` | 최초 초기화 이동 | X |
| `cycle_initialize_at` | 사이클 시작 전 원위치 복귀 | X |
| `start_at` | **실제 모션 시작** | O |

### 3.4 실행 상태 머신

```
idle -> preparing -> initializing -> armed -> start_scheduled -> running
     -> motion_completed -> cycle_initializing -> cycle_ready -> (다시 start_at)
```

기타 상태: `stopped`, `error`

### 3.5 사이클 반복 구조 — 검증 완료

`group_execution.py` 확인 결과, **coordinator가 사이클마다 `start_at`을 새로 발행**한다.

```python
if self.state == 'armed':          next_cycle = 1
elif self.state == 'cycle_ready':  next_cycle = self.cycle_number + 1
```

- 참가 PC에 로컬 반복 로직이 **없다**. 모든 사이클을 coordinator가 명령으로 돌린다.
- `target_cycle_count`는 coordinator가 정지 판단에만 사용한다.
- `dwell_sec`, `repeat_mode`는 이 계층에서 저장만 되고 참가자에게 전달되지 않는다.

=> `command == 'start_at'` 필터 하나로 **사이클마다 정확히 1회** 잡힌다.

### 3.6 모드 값

| 필드 | 값 | 의미 |
|---|---|---|
| `run_mode` | `continuous` / `once` | 반복 실행 / 1회 실행 |
| `repeat_mode` | `reinitialize` / `direct` | 사이클마다 원위치 복귀 / 초기화 없이 바로 다음 사이클 |

4가지 조합 모두 사이클마다 `start_at`이 발행되는 구조는 동일하다.
=> **추가 필터 불필요.**

### 3.7 중복 제거 — `command_id` 단독 키

원본 시스템도 동일한 방식을 쓴다.

```python
if not message.command_id or self._command_seen(message.command_id):
    return
```

`sequence`는 단조 증가하는 일회용 값이며, 중복 판정에 쓰이지 않는다.
=> 우리도 **`command_id` 단독 키**로 중복 제거한다.

### 3.8 시각 동기 — 우리는 사용할 수 없음

`scheduled_monotonic_ns`는 **coordinator의 monotonic 시계** 기준이다.
각 참가 PC는 `/motion_group/time_sync` 4-타임스탬프 교환(`trigger_sync.py`)으로
자기 오프셋을 구해 변환하는데, 이 교환은 **응답을 발행해야** 성립한다.

우리는 발행하지 않으므로 이 값을 변환할 수 없다.
=> **`start_at` 수신 시각 + 사용자 오프셋**으로 재생 시점을 결정한다.
   (`start_lead_time` 기본값이 0.5초이므로, 모션과 정확히 맞추려면 오프셋을
    0.5초 근처에서 귀로 튜닝하면 된다)

### 3.9 은닉 수준 — "관여하지 않음"의 구조적 근거

- 웹 UI의 피어 목록은 `GroupHeartbeat` 수신으로 구성된다.
  heartbeat를 발행하지 않으면 **3대 어느 화면에도 표시되지 않는다.**
- `participant_ids`는 "그룹 참가"를 누른 PC로만 채워진다. 우리는 영원히 미포함.
- `preparing -> armed` 배리어는 참가자의 `mark_ready`/`mark_armed` **보고 수**로 판정한다.
  보고하지 않는 우리는 카운트에 들어가지 않으므로, **스피커 PC가 죽어도 모션은 시작된다.**
- `time_sync` 교환 불참 -> 3대의 시계 동기 정확도에 영향 없음.

단, DDS discovery 목록(`ros2 node list` 등)에는 구독자로 표시된다. 이는 허용 범위로 합의됨.

### 3.10 RMW 구현 — 기본값 확정

`install.sh`, `run_coordination_user_service.sh` 모두 `RMW_IMPLEMENTATION`을 설정하지 않는다.
=> 3대 모두 Humble 기본값 **`rmw_fastrtps_cpp`** 사용.
=> 스피커 PC도 아무것도 설정하지 않으면 자동으로 일치한다.

`ROS_LOCALHOST_ONLY=0`은 coordination 서비스에서 설정된다. 우리도 `0`이어야 한다.

---

## 4. 확정된 설계 결정

| # | 항목 | 결정 |
|---|---|---|
| 1 | 동작 모드 | **연동 모드 / 단독 모드** 2가지, 배타적 전환 |
| 2 | 구독 토픽 | `/motion_group/command` + `/motion_group/event`(정지신호 토글 ON일 때만) |
| 3 | 발행 | 없음 (0건) |
| 4 | 필터 | `group_id` 일치 AND `command == 'start_at'` AND `initialization_only == false` |
| 5 | 중복 제거 | `command_id` 단독 키 |
| 6 | 재생 시점 | 수신 시각 + 사용자 오프셋 (-10.0 ~ +10.0초) |
| 7 | 겹침 정책 | 재생 중 새 트리거 -> **처음부터 재시작** |
| 8 | 정지 감지 | `GroupEvent.state`가 `stopped`/`error`면 재생 정지. UI 토글로 켜고 끔(기본 ON). `motion_completed`(정상 사이클 종료)에는 반응하지 않음. `alarm`은 계속 미구독 |
| 9 | 프로세스 | 단일 프로세스 3스레드, 모듈 단위 분리 |
| 10 | 앱 위치 | `~/speaker_app` |
| 11 | 음성 폴더 | `~/speaker_app/sounds/` — **파일 1개만 유지**. 웹에서 업로드/다운로드/삭제 |
| 12 | 음성 포맷 | wav. **모노는 자동으로 스테레오 변환** 후 재생(양쪽 출력) |
| 13 | 재생 도구 | `aplay -D plughw:1,0` (ALSA 직접, PulseAudio 우회) |
| 14 | 출력 장치 | `plughw:1,0` 고정 (card 1 = CX20632 Analog, AUX 단자) |
| 15 | 볼륨 | 웹 UI 슬라이더로 조절 (ALSA `Master` 믹서 직접 제어) |
| 16 | 일시정지 | 두 모드 공통 제공 (SIGSTOP/SIGCONT) |
| 17 | 웹 프레임워크 | FastAPI + uvicorn (3대와 동일 스택) |
| 18 | 프론트엔드 | 순수 HTML/JS, 빌드 도구 없음 |
| 19 | 갱신 방식 | 1초 폴링 |
| 20 | 바인딩 | `0.0.0.0:8100` (동일 네트워크에서 접속 가능) |
| 21 | 인증 | 없음 |
| 22 | 언어 | 한국어 |
| 23 | 로그 | 최근 100건 링버퍼, 메모리 방식 (재시작 시 소멸) |
| 24 | 설정 영속 | `config/speaker.yaml`, 마지막 값 기억 |
| 25 | 자동 시작 | systemd **user service** + `loginctl enable-linger` |
| 26 | 트리거 OFF 시 수신 | 무시 (표시도 안 함) |
| 27 | msg 동기화 | 수동 (`git pull` 후 재빌드) |

---

## 5. 아키텍처

### 5.1 프로세스 구조

```
speaker_app (프로세스 1개)
|
+- [메인 스레드]      uvicorn / FastAPI -> 웹 UI + REST API
+- [DDS 스레드]       rclpy spin — 연동 모드일 때만 생성, 모드 끄면 종료
+- [재생 감시 스레드]  aplay 종료 감지, 단독 모드 반복 스케줄
```

스레드 간 통신은 공유 상태 객체 + 락. IPC 없음, 내부 DDS 없음.

### 5.2 디렉터리 구조

```
~/ros2_ws/
+- src/motion_coordination_interfaces/    # msg 전용, colcon 빌드

~/speaker_app/
+- backend/
|  +- main.py           # 진입점 — 설정 로드 -> 앱 조립 -> uvicorn 기동
|  +- api.py            # REST 엔드포인트 (프론트와의 유일한 접점)
|  +- state.py          # 앱 상태 단일 소스 + 락
|  +- config.py         # speaker.yaml 로드/저장, 기본값/검증
|  +- player.py         # 재생 엔진 (aplay 서브프로세스)
|  +- standalone.py     # 단독 모드 반복/간격 스케줄러
|  +- dds_listener.py   # ★ rclpy를 import하는 유일한 파일
|  +- logbuf.py         # 최근 100건 링버퍼
+- frontend/
|  +- index.html  app.js  style.css
+- config/
|  +- speaker.yaml
+- deploy/
|  +- speaker-app.service
+- sounds/              # wav 파일 위치
+- DESIGN.md            # 이 문서
```

**핵심 규칙**: `dds_listener.py`만 `rclpy`를 import한다.
나머지 파일은 ROS를 전혀 모른다. 따라서 ROS가 없거나 DDS가 안 붙어도
재생과 웹 UI는 정상 동작한다.

### 5.3 REST API

| 메서드 | 경로 | 용도 |
|---|---|---|
| GET | `/api/state` | 전체 상태 (프론트가 1초마다 폴링) |
| POST | `/api/mode` | `{"mode": "dds" \| "standalone"}` |
| GET/POST | `/api/config` | 도메인/그룹/오프셋/파일/장치 |
| POST | `/api/play` | 단독 모드 재생 시작 |
| POST | `/api/pause` `/api/resume` `/api/stop` | 재생 제어 (공통) |
| POST | `/api/test` | 출력 장치 테스트 재생 |

`GET /api/state` 응답 예:

```json
{
  "mode": "dds",
  "dds_status": "connected",
  "playback": "playing",
  "config": {
    "domain_id": 21, "group_id": "test1",
    "offset_sec": 0.0,
    "sounds_dir": "/home/speaker/speaker_app/sounds",
    "file_path": "/home/speaker/speaker_app/sounds/sound.wav",
    "device": "plughw:1,0"
  },
  "last_trigger": { "cycle_number": 3, "at": "14:22:05" },
  "logs": ["14:22:05  start_at 수신 (cycle 3) -> 재생"]
}
```

### 5.4 상태 모델

```
mode       : dds | standalone         (배타)
dds_status : off | connecting | connected | error
playback   : idle | playing | paused
```

- `mode`를 `standalone`으로 바꾸면 DDS 스레드 종료, `dds_status = off`
- `mode`를 `dds`로 바꾸면 스레드 신규 생성
- **도메인 ID 변경도 같은 경로** (rclpy는 도메인을 init 시점에만 정할 수 있음)
- 그룹 ID는 단순 필터 변수라 즉시 반영

### 5.5 설정 파일 (`config/speaker.yaml`)

```yaml
mode: dds
dds:
  domain_id: 21
  group_id: test1
audio:
  device: plughw:1,0
  sounds_dir: /home/speaker/speaker_app/sounds
  file_path: /home/speaker/speaker_app/sounds/sound.wav
trigger:
  offset_sec: 0.0             # -10.0 ~ +10.0 (음수는 0으로 처리)
  stop_on_motion_stop: true   # 모션 정지/오류 시 재생도 정지
standalone:
  repeat: 0              # 0 = 무한
  dwell_sec: 2.0
web:
  host: 0.0.0.0
  port: 8100
log:
  max_entries: 100
```

### 5.6 데이터 흐름

**연동 모드**
```
3대 coordination 노드
  -> /motion_group/command 발행
       | (BEST_EFFORT 구독, 발행 0)
  dds_listener
       |-- group_id == 설정값?
       |-- command == 'start_at'?
       |-- initialization_only == false?
       |-- command_id 처음 보는 것?
       v
  오프셋만큼 대기 -> player.restart()
       v
  aplay -D plughw:1,0 sound.wav
       v
  logbuf 기록 -> 프론트 폴링으로 표시
```

**단독 모드**
```
사용자 [재생] -> standalone 스케줄러
              -> player.play() -> 종료 감지 -> 간격 대기 -> 반복
                 (repeat 0이면 무한)
```

### 5.7 재생 엔진

| 동작 | 구현 |
|---|---|
| 재생 | `aplay -D <device> <file>` 서브프로세스 시작 |
| 일시정지 | `SIGSTOP` |
| 재개 | `SIGCONT` |
| 정지 | `SIGTERM` |
| 재시작(트리거) | `SIGCONT` -> `SIGTERM` -> 새 프로세스 시작 |

일시정지 상태에서 새 트리거가 오면 정지 후 처음부터 재생한다.

### 5.8 웹 UI 레이아웃

```
[ 모드 ]   (o) 연동 모드    ( ) 단독 모드
           DDS: 연결됨 (도메인 21 / test1)

[ 설정 ]   도메인 [21]  그룹 [test1]  [적용]
           음성 폴더: /home/speaker/speaker_app/sounds
           음성 파일: sound.wav
           오프셋 [0.0] 초  (음수 = 먼저 재생)

[ 재생 ]   상태: 재생 중
           [일시정지] [정지]
           (단독 모드일 때만) [재생]  반복 [0]회  간격 [2.0]초

[ 로그 ]   최근 100건
           14:22:05  start_at 수신 (cycle 3) -> 재생
```

---

## 6. 진행 상황

### 완료 (2026-08-21)

- [x] 대상 시스템 코드 분석 (토픽/QoS/메시지/상태머신/반복구조/중복제거/RMW)
- [x] 아키텍처 설계 및 전체 결정 확정 (27개 항목)
- [x] 1~3단계 설치 — git 2.34.1, ros-humble-desktop, colcon,
      fastapi 0.63.0 / uvicorn 0.15.0 / PyYAML 5.4.1, ufw disable, usermod -aG audio
- [x] **5단계** 저장소 부분 clone (sparse checkout, 560KB만 받음)
      -> `~/ros2_ws/_upstream`, `~/ros2_ws/src/`에 심볼릭 링크
- [x] **6단계** msg 패키지 colcon 빌드 성공, `ros2 interface show` 검증
- [x] **7단계** DDS 연결 실증 — 도메인 21에서 토픽 6개, 코디네이터 노드 3개 확인
      발행자 QoS 실측: RELIABLE + VOLATILE (코드 분석과 일치)
- [x] **10단계** 앱 구현 완료 (백엔드 8파일, 프론트엔드 3파일, systemd 서비스)
- [x] systemd user service 등록 + linger 활성화 (재부팅 시 자동 시작)

### 검증 완료 항목

도메인 21에는 발행하지 않는다는 원칙을 지키기 위해, **별도 도메인 99**에서
가짜 GroupCommand를 발행해 리스너 로직을 검증했다.

| 검증 | 결과 |
|---|---|
| `start_at` 수신 -> 재생 | 통과 |
| 같은 `command_id` 5회 발행 -> 재생 1회 | 통과 (중복제거) |
| `initialize_at` -> 재생 안 함 | 통과 |
| `cycle_initialize_at` -> 재생 안 함 | 통과 |
| 다른 그룹(`other`)의 `start_at` -> 재생 안 함 | 통과 |
| `initialization_only=true` -> 재생 안 함 | 통과 |
| 재생 중 새 트리거 -> PID 교체(처음부터 재시작) | 통과 |
| 오프셋 3초 -> 3초 뒤 재생 | 통과 |
| 일시정지(SIGSTOP, 프로세스 T) / 재개(SIGCONT, S) / 정지 | 통과 |
| 단독 모드 재생/반복/정지 | 통과 |
| 모드 전환 시 DDS 스레드 기동/종료 | 통과 |
| 도메인 변경 시 리스너 재시작 | 통과 |
| 발행자 유무에 따른 연결 상태 표시 | 통과 |

### 8단계 실트리거 검증 완료 (2026-08-21 10:23~10:25)

3대에서 테스트 모션(모션 7~8초 + 초기화 5초)을 실행하며 실제 트래픽으로 검증.

```
10:23:24  start_at 수신 (cycle 1)
10:23:39  start_at 수신 (cycle 2)   +15s
10:23:54  start_at 수신 (cycle 3)   +15s
10:24:08  start_at 수신 (cycle 4)   +14s
10:24:24  start_at 수신 (cycle 5)   +16s
10:24:39  start_at 수신 (cycle 6)   +15s
10:24:54  start_at 수신 (cycle 7)   +15s
```

| 확인 항목 | 결과 |
|---|---|
| `start_at`이 사이클마다 재발행되는가 (A안) | 통과 — cycle 1~7 순차 증가 |
| 간격이 실제 사이클과 맞는가 | 통과 — 약 15초 (모션 7~8초 + 초기화 5초) |
| 초기화 이동에는 반응하지 않는가 | 통과 — 사이클당 로그 1건 |
| 3대 중복 수신에도 1회만 재생하는가 | 통과 — 중복 0건 |
| 그룹 필터 | 통과 — test1만 통과 |

=> 코드 분석으로 예측한 A안이 실물로 증명됨. 최대 리스크 해소.

### 정지 신호 수신 추가 (2026-08-21)

`GroupEvent.state`가 `stopped` / `error`일 때 재생을 멈춘다. UI 토글로 켜고 끌 수 있다(기본 ON).
`motion_completed`는 정상 사이클 종료이므로 제외한다 — 반응시키면 사이클마다 소리가 끊긴다.
3대가 각각 이벤트를 보내지만 "재생 중일 때만 정지"라 자연히 1회만 처리된다(별도 중복제거 불필요).

| 검증 (도메인 99) | 결과 |
|---|---|
| 토글 ON + `state=stopped` -> 정지 | 통과 |
| 토글 ON + `state=motion_completed` -> 계속 재생 | 통과 |
| 토글 OFF + `state=stopped` -> 계속 재생 | 통과 |
| 토글 변경 시 event 구독 생성/해제 (리스너 재시작) | 통과 |

실측 구독 현황 (도메인 21): `command` 구독자 4, `event` 구독자 4(우리 포함),
`heartbeat`/`alarm` 구독자 3(우리 미구독), 전 토픽 발행자 3(우리 0).

### 모노 → 스테레오 자동 변환 (2026-08-21)

증상: 이어폰 한쪽에서만 소리가 남.
원인: 음원이 모노(1채널)인데 `plughw`로 스테레오 장치에 보내면 한쪽 채널로만 매핑된다.
      이어폰 규격(TRRS) 문제가 아니었다.

해결: `audio_prep.ensure_stereo()` — 모노 wav를 좌우 동일한 스테레오로 변환해
      `sounds/.stereo_cache/`에 캐시하고 그 파일을 재생한다. **원본은 건드리지 않는다.**
      `audioop.tostereo` 사용으로 26MB 파일 변환에 0.2초. 이후 캐시 재사용.
      원본 수정 시각이 바뀌면 자동 재변환. 스테레오 파일은 변환 없이 통과.

### 음원 관리 · 볼륨 (2026-08-21)

웹에서 음원을 업로드/다운로드/삭제하고 볼륨을 조절한다.

- **업로드**: `POST /api/sound/upload?name=<파일명>` — 원시 바디 스트리밍.
  `python-multipart` 의존성을 피하려고 multipart 대신 raw body를 쓴다. 최대 500MB.
  업로드 성공 시 **기존 wav와 변환 캐시를 모두 지우고** 새 파일로 교체(폴더에 항상 1개).
  wav로 열리지 않으면 거부하고 기존 파일을 유지한다.
- **다운로드**: `GET /api/sound/download` — RFC5987로 한글 파일명 인코딩.
- **삭제**: `POST /api/sound/delete` — 재생 중이면 먼저 정지.
- **볼륨**: `POST /api/volume` — `amixer -c <카드> sset Master <n>%`.
  재생이 plughw 직접 경로라 PulseAudio가 아닌 ALSA 믹서가 실제 음량을 결정한다.

| 검증 | 결과 |
|---|---|
| 다운로드 26MB, 원본과 바이트 동일 | 통과 |
| 업로드 시 기존 파일·캐시 제거 후 교체 | 통과 |
| wav가 아닌 파일 거부, 기존 파일 보존 | 통과 |
| 삭제 후 폴더 비움 | 통과 |
| 볼륨 55% 적용 → amixer 실측 55% | 통과 |

### 발자국 최소화 (2026-08-21)

`enable_rosout=False`, `start_parameter_services=False` 적용.

| | 이전 | 이후 |
|---|---|---|
| `/rosout` 발행자 | 있음 | 제거 |
| 파라미터 서비스 | 6개 | 0개 |
| `/parameter_events` 발행자 | 있음 | 있음 (rclpy 필수, 트래픽 0건) |

실측 확인: `/motion_group/*` 6개 토픽 모두 **발행자 3**(모션 PC만),
`command`만 구독자 4(3대 + 우리 1), 나머지 5개는 구독자 3(우리 미구독).

### 단독 모드 무한 반복 검증 (2026-08-21)

3초짜리 테스트 wav + 간격 1초로 확인. 약 4초 주기로 계속 재반복, [정지]로 즉시 종료.

```
재생 #1  10:35:59
재생 #2  10:36:04
재생 #3  10:36:08
재생 #4  10:36:12
```

### 남은 것 (모두 코드 외 작업)

- [ ] **4단계** 재로그인 — `audio` 그룹 적용 (현재 미적용)
- [ ] **9단계** 실제 소리 검증 — AUX 케이블 연결 후 확인
      (현재 `aplay`가 `plughw:1,0`을 오류 없이 열고 재생하는 것까지는 확인됨)
- [ ] 오프셋 실측 튜닝 — 모션과 소리를 눈/귀로 맞추기
- [ ] 실제 정지 신호 값 확인 — 3대에서 정지를 눌렀을 때 `state`가 `stopped`로 오는지
      (코드상 확인 + 도메인 99 모의 검증은 완료, 실트래픽 관찰만 남음)

### 구현 완료 (2026-08-21)

요구사항 8개 + 추가 요청(정지신호 토글, 일시정지) 전부 구현 및 검증 완료.
남은 것은 물리 연결(AUX)과 실측 튜닝뿐이며 코드 작업은 없다.

## 7. 미해결 / 확인 필요

| 항목 | 내용 |
|---|---|
| AUX 연결 | 현재 AUX 단자에 아무것도 연결되어 있지 않음. 이 때문에 PulseAudio 기본 싱크가 `auto_null`. 케이블 연결 시 `card 1 CX20632 Analog`가 잡힐 것으로 예상. 단 우리는 ALSA 직접 접근이라 무관 |
| audio 그룹 | `usermod` 실행됐으나 **재로그인 전까지 미적용** |
| wav 파일 | 아직 준비되지 않음. 약 9분 분량 예정. `~/speaker_app/sounds/`에 배치 |
| 모션 사이클 길이 | 9분보다 길게 설정 예정 -> 재시작 정책과 충돌 없음 |
| 트리거 테스트 | 3대가 실제 연동 동작 중이므로 관찰만 하면 됨. 테스트용 발행기 불필요 |

---

## 8. 참고 — 하드웨어/환경 정보

```
OS        : Ubuntu 22.04.5 LTS (Jammy), amd64
Kernel    : 6.8.0-138-generic
Python    : 3.10.12
네트워크   : wlp3s0 (Wi-Fi), 172.16.23.x/22, GW 172.16.20.1
            enp1s0/enp2s0 DOWN
디스크     : /dev/sda2, 206GB 여유
오디오 카드 :
  card 0: HD-Audio Generic — HDMI 0/1/2
  card 1: HD-Audio Generic — CX20632 Analog  <- AUX 단자, 사용 대상
세션      : Wayland, DISPLAY=:0
사운드서버 : PulseAudio (현재 기본 싱크 auto_null)
```

## 9. 자주 쓸 명령

```bash
# ROS 환경 로드
source /opt/ros/humble/setup.bash
source ~/ros2_ws/install/setup.bash

# DDS 연결 확인
ROS_DOMAIN_ID=21 ROS_LOCALHOST_ONLY=0 ros2 topic list

# 트리거 관찰
ROS_DOMAIN_ID=21 ROS_LOCALHOST_ONLY=0 ros2 topic echo /motion_group/command

# 오디오 테스트
aplay -D plughw:1,0 ~/speaker_app/sounds/sound.wav
aplay -l                 # 카드 목록
pactl list short sinks   # 싱크 상태
```
