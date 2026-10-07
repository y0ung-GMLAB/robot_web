# 스피커 트리거 앱

ROS 2 Humble 모션 제어 시스템(robot_web)의 DDS 트리거를 **구독만** 하여
모션 시작 시점에 음성 파일을 재생하는 웹 앱이다.

2026-10-07 부터 robot_web 저장소 안(`robot_web/speaker_app`)에 있다 · 출처 [ORIGIN.md](ORIGIN.md) ·
로봇 PC 와 **같은 robot_web 커밋**으로 맞춰야 한다(그룹 메시지 정의가 같아야 받는다).

로봇 PC 의 연동에 관여하지 않는다. 모션 토픽에는 쓰지 않고, 발행은 「같은 망 PC 알림」
(`/motion_group/presence` · 2초마다 이 PC 이름 · IP · 웹 주소) 하나뿐이다 · 로봇 PC 화면 「같은 망 PC」 표에
스피커가 보이게 하는 용도다(수정 목록 75). 이 PC가 꺼져 있거나 고장 나도 로봇의 모션 실행은 영향을 받지 않는다.

설계 근거와 대상 시스템 분석 결과는 [DESIGN.md](DESIGN.md)에 정리되어 있다.

## 기능

- **연동 모드** — `/motion_group/command` 를 구독해 `start_at` 명령에 반응. 사이클마다 재생
  - 그룹 재생(마스터가 보냄)과 **PC 1대 재생**(그 로봇 PC 가 회차마다 보냄) 모두 · 같은 그룹 ID 면 받는다
  - **애니메이션마다 다른 음원** — 웹 「애니메이션별 음원」 표에서 고른다 · 정하지 않은 애니메이션은 기본 음원
  - 로봇 PC 가 실어 보내는 「시작까지 남은 초」(`start_delay_sec`)를 오프셋에 더해 같은 순간에 튼다
  - 모션 정지·오류(그룹 사건 `stopped`/`error`, PC 1대 재생의 `solo_stopped`) → 재생 정지
- **단독 모드** — DDS 없이 반복 횟수·간격을 지정해 재생
- 재생 시점 오프셋 조절 (-10.0 ~ +10.0초, 음수면 모션보다 먼저 재생)
- 웹 UI (동일 네트워크의 다른 PC·폰에서 접속 가능), 볼륨·일시정지·음원 업로드
- 모노 wav 자동 스테레오 변환 (양쪽 출력)

## 요구 환경

- Ubuntu 22.04 / Python 3.10
- ROS 2 Humble (연동 모드에만 필요 — 없어도 단독 모드와 웹 UI는 동작)
- robot_web 에서 `motion_coordination_interfaces` 빌드 완료(아래 1)
- ALSA (`aplay`)

## 설치 — 새 PC 기준 순서대로

### 1. robot_web 받기 + 메시지 빌드 (연동 모드 필수)

```bash
git clone https://github.com/y0ung-GMLAB/robot_web ~/robot_web
cd ~/robot_web
source /opt/ros/humble/setup.bash
colcon build --packages-up-to motion_coordination_interfaces
```

메시지 패키지와 그것이 쓰는 `midi_msgs` 만 빌드한다(모터 쪽은 빌드하지 않는다 · `--packages-select` 로 하나만
고르면 `midi_msgs` 가 없어 실패한다). `run.sh` 는 `~/robot_web/install` 을 먼저 쓰고,
없을 때만 옛 `~/ros2_ws` 를 쓴다. 로봇 PC 를 새 커밋으로 올리면 **스피커 PC 도 `git pull` 뒤 다시 빌드**한다.
ROS 2 Humble 자체가 없으면 먼저 설치한다.

### 2. 파이썬 패키지

```bash
cd ~/robot_web/speaker_app
pip3 install -r requirements.txt
```

예전 `~/speaker_app` 에서 옮겨 오는 PC 는 `systemctl --user disable --now speaker-app` 으로 옛 것을 멈추고
`cp ~/speaker_app/sounds/*.wav ~/robot_web/speaker_app/sounds/` 로 음원을 옮긴 뒤 아래 5 를 다시 한다.

### 3. 사운드 장치 독점 (**빼먹으면 소리가 전혀 안 난다**)

```bash
./deploy/setup-audio.sh
```

이 앱은 `aplay`로 ALSA 장치를 직접 연다. PulseAudio가 같은 장치를 붙잡고 있으면
`Device or resource busy`로 실패해 **소리가 한 번도 나지 않는다.**
스크립트가 PulseAudio와 speech-dispatcher를 봉인해 장치를 앱 전용으로 만든다.
(데스크톱 소리는 나지 않게 된다 — 의도한 동작이다)

실행이 끝나면 그 PC의 사운드 카드 목록이 출력된다. **카드 번호는 PC마다 다르다.**

```
card 1: Generic_1 [HD-Audio Generic], device 0: CX20632 Analog
        ^                                       ^
        plughw:1,0
```

번호가 다르면 `config/speaker.yaml` 의 `audio.device` 를 고친다. 웹 UI 설정에서 바꿔도 된다.

### 4. 음원 파일 넣기

**wav 파일은 저장소에 없다.** 용량 때문에 제외되어 있어 `git clone` 으로 딸려오지 않는다.
USB나 `scp` 로 `sounds/` 에 직접 넣거나, 앱을 띄운 뒤 **웹 UI에서 추가**한다.
여러 개를 둘 수 있다 · 처음 올린 것이 기본 음원 · 「애니메이션별 음원」 표에서 애니메이션마다 고른다
(로봇이 한 번 재생하면 그 애니메이션 이름이 표에 저절로 생긴다 · 이름을 직접 넣어도 된다).

### 5. 자동 시작 등록 (**빼먹으면 재부팅해도 안 뜬다**)

```bash
mkdir -p ~/.config/systemd/user
cp deploy/speaker-app.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now speaker-app
sudo loginctl enable-linger $USER
```

마지막 `enable-linger` 가 핵심이다. 이것이 없으면 **로그인해야만** 앱이 뜬다.
등록해 두면 전원만 켜도 자동으로 올라온다.

### 6. 확인

```bash
systemctl --user status speaker-app
```

브라우저에서 `http://<이 PC의 IP>:8100` 접속 → DDS 상태가 **connected** 면 정상.

### 빼먹으면 생기는 일

| 단계 | 빼먹으면 |
|---|---|
| 1 ROS 메시지 빌드 | 연동 안 됨 (단독 모드·웹 UI는 동작) |
| 1 로봇 PC 와 같은 커밋 | 메시지 형식이 달라 트리거를 못 받음 |
| 3 `setup-audio.sh` | **소리 안 남** |
| 3 카드 번호 확인 | **소리 안 남** |
| 4 wav 파일 | 재생할 음원이 없음 |
| 5 `enable` + `enable-linger` | **재부팅해도 안 뜸** |

설정(`config/speaker.yaml`)은 저장소에 포함되어 도메인·그룹 값이 그대로 따라온다.
새 PC에서 손댈 것은 **카드 번호(3)와 음원 파일(4)** 둘뿐이다.

## 수동 실행

```bash
./run.sh
```

## 소리가 안 날 때

```bash
aplay -D plughw:1,0 -d 1 <아무 wav>
```

`audio open error: Device or resource busy` 가 나오면 다른 프로그램이 장치를 잡고 있다.
범인은 거의 항상 PulseAudio다. 누가 잡고 있는지는 이렇게 본다.

```bash
fuser -v /dev/snd/*
cat /proc/asound/card1/pcm0p/sub0/status    # state: RUNNING 이면 점유 중
```

`./deploy/setup-audio.sh` 를 실행하면 해결된다.
앱 로그(웹 UI 하단)에는 `재생 종료(코드 1) audio open error: Device or resource busy` 로 남는다.

## 구조

```
backend/
  main.py           진입점 — 설정 로드 → 앱 조립 → uvicorn 기동
  api.py            REST 엔드포인트
  state.py          앱 상태 단일 소스 + 락
  config.py         speaker.yaml 로드/저장
  player.py         재생 엔진 (aplay 서브프로세스)
  standalone.py     단독 모드 반복 스케줄러
  dds_listener.py   rclpy 를 import 하는 유일한 파일
  audio_prep.py     모노 → 스테레오 변환
  volume.py         ALSA 믹서 제어
  sysinfo.py        시스템 정보
  logbuf.py         최근 100건 링버퍼
frontend/           순수 HTML/JS, 빌드 도구 없음
config/speaker.yaml 설정 영속
deploy/
  speaker-app.service  systemd 유닛
  setup-audio.sh       사운드 장치 독점 설정 (새 PC 1회)
```

`dds_listener.py` 만 `rclpy` 를 import 한다. 나머지는 ROS를 전혀 모르므로,
ROS가 없거나 DDS가 붙지 않아도 재생과 웹 UI는 정상 동작한다.
