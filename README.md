# Robot Web

ROS 2 기반 로봇 모션 제어 프로그램입니다 (로봇 무관 · 로봇별 값은 로봇 팩). 웹 모니터링·설정, 애니메이션 재생과
저수준 모터 제어 계층을 하나의 작업공간에서 빌드합니다.

애니메이션 저작은 이 저장소 밖(Blender)에서 합니다 · Blender 가 내보낸
`.json` 을 웹 화면에 끌어다 놓으면 재생됩니다. (전신인 motion_web 의
MIDI 녹화·모션 스튜디오는 삭제됐습니다.)

**쓰는 법** : [사용법](docs/사용법.md) · 설치가 끝난 뒤에는 웹 화면
`운영` → `사용법` 에서도 이 문서와 사용법을 그대로 읽을 수 있습니다.

## 웹 접속 주소 · 다른 PC 나 노트북에서

미니 PC 가 로봇에 붙어 있으면 화면·키보드를 꽂기 어렵습니다 · **같은 망(같은 Wi-Fi)에 있는 아무
PC·노트북의 브라우저**로 들어가면 됩니다 · 미니 PC 를 열 일이 없게 화면·터미널을 모두 웹으로 냅니다.

| 무엇 | 주소 | 어느 PC |
|---|---|---|
| 로봇 웹 (모터 · 재생 · 매핑 · 스케줄) | `http://<IP>:8000` | 로봇 PC 전부 |
| 스피커 웹 | `http://<IP>:8100` | 스피커 PC |
| 터미널 (명령 치기) | 로봇 웹 「터미널」 탭 · 또는 `http://<IP>:8081` | 로봇 PC · 스피커 PC(2026-10-09 뒤 `install_speaker.sh` 한 번) |
| PC 성능 (btop) | 로봇 웹 「PC 성능」 탭 · 또는 `http://<IP>:8080` | 로봇 PC · 스피커 PC(같음) |

- 뒤 숫자(**포트**)는 PC 번호가 아니라 프로그램마다 **늘 같은 값**입니다 · floating1 이든 floating4 든 로봇 웹은 `:8000`
- PC 마다 다른 것은 앞부분(IP 또는 이름)뿐입니다
- `https` 가 아니라 **`http`** · 이름과 숫자 사이는 점이 아니라 **콜론 `:`**

```text
http://192.168.0.14:8000      ← IP 로 (가장 확실)
http://floating4.local:8000   ← PC 이름 + .local 로 (안 열리면 IP 로)
http://localhost:8000         ← 그 PC 자신의 화면에서
```

- **IP 를 모를 때** · 아는 PC 하나(보통 마스터)의 로봇 웹 → `PC 연동 설정` 탭 → 「같은 망 PC」 표에 PC 마다 주소가 나오고
  「화면 열기」 를 누르면 그 PC 웹이 새 탭으로 열립니다 · 그 PC 터미널에서는 `hostname -I` · 또는 `bash scripts/check.sh` 의 「웹 :8000」 줄
- `.local` 이름은 우분투 기본 이름 찾기(mDNS)라 망에 따라 막힐 수 있습니다 · 그때는 IP 로
- IP 가 바뀌면 북마크가 깨집니다 · 공유기에서 PC 마다 **고정 IP(DHCP 예약)** 를 걸어 두는 것을 권합니다(아래 7. 네트워크)
- 같은 망이 아니면(회사망 ↔ 현장 Wi-Fi 따로) 열리지 않습니다 · 접속하는 노트북을 로봇 PC 와 같은 Wi-Fi 에 붙입니다

## 구성

```text
Web UI  ←  Blender 가 내보낸 애니메이션(.json)
  ↓
motion_web_bridge
  ↓
motion_runtime / motion_supervisor / motion_state_monitor / motion_schedule
  ↓
motion_system motor_manager_node
  ↓
EtherLab·IgH EtherCAT / Dynamixel
```

| 구성요소 | 관리 방식 | 역할 |
|---|---|---|
| web_bridge · web_ui | 이 저장소 | 웹 화면 · 웹 API · 프로젝트·서비스 관리 |
| motion_runtime · motion_supervisor · motion_state_monitor · motion_schedule | 이 저장소 | 재생 · 최종 모터 명령 중재 · 상태 · 스케줄 |
| motion_coordination (+interfaces) | 이 저장소 | PC 간 상태 공유·실행 조정 |
| motion_system | 이 저장소 (합친 외부 코드 · 명시 요청 때만 수정) | Motor Manager와 저수준 모터 드라이버 |
| EtherLab/IgH EtherCAT | PC에 별도 설치 | AC Servo EtherCAT 통신 |

작업공간 구조:

```text
ros2_ws/
├── config/                         # PC 전역 설정 (프로젝트와 분리)
│   └── motion_coordination.example.yaml
├── scripts/                        # 설치·빌드·재시작 스크립트 · dev_preview.py(UI 미리보기)
├── docs/                           # 사용법 · 운영·DDS 검증 문서
├── src/web_bridge                  # 웹 API (파이썬 패키지명 motion_web_bridge)
├── src/web_ui                      # 웹 화면 (바닐라 JS · 패널 조각)
├── src/motion_common               # 공용 규칙 (토픽·스케줄 저장소·판정)
├── src/motion_runtime              # 재생 · 조인트 연결 · 회차 기록
├── src/motion_supervisor           # 최종 모터 명령 중재 (조그·페이더·재생)
├── src/motion_state_monitor        # 장비 상태 수집 · launch
├── src/motion_schedule             # 재생 스케줄
├── src/motion_coordination         # PC 간 상태 공유·실행 조정
├── src/motion_coordination_interfaces  # DDS 메시지 정의
└── src/motion_system               # 모터 통신층 · 합친 외부 코드 (VENDORED.md)
```

## 검증 기준 버전

아래 값은 **2026-08-11** 기준 개발 PC에서 확인한 조합입니다. EtherCAT
커널과 NIC 드라이버는 새 PC의 하드웨어에 맞아야 합니다.

| 대상 | 검증 버전 |
|---|---|
| Ubuntu | 22.04.5 LTS |
| Linux kernel | 6.8.0-124-generic |
| ROS 2 | Humble (`/opt/ros/humble`) |
| Python | 3.10.12 |
| Git | 2.34.1 |
| CMake | 3.22.1 |
| colcon-core | 0.20.1 |
| colcon-common-extensions (apt) | 0.3.0 |
| FastAPI | 0.63.0 |
| Uvicorn | 0.15.0 |
| PyYAML | 5.4.1 |
| EtherLab/IgH EtherCAT Master | 1.6.9 (`1.6.9-8-gbeb2bf07`) |
| Motion Web packages | 0.1.0 |
| Motion Control Studio packages | 0.1.0 |
| Motion Coordination packages | 0.1.0 |
| Motion Coordination Interfaces | 0.1.0 |
| Motion System | 저장소 안 코드 (원본 `5ec1909` · `src/motion_system/VENDORED.md`) |

애플리케이션 `package.xml` 버전(0.1.0)만으로는 전체 호환 조합을 식별할 수
없습니다. 실제 설치 조합은 **이 저장소의 Git 커밋 하나**입니다 · Motion System 도
같은 커밋 안에 들어 있습니다(2026-10-02 서브모듈에서 합침).

운영 브랜치 · `main`

## Git 저장소

- 전체 설치 저장소: `https://github.com/y0ung-GMLAB/robot_web.git`
- Motion System: 서브모듈이 아니라 이 저장소 안 코드 (2026-10-02 합침)
  · 출처 커밋 · `src/motion_system/VENDORED.md`
  · 원본 `https://github.com/kimjoonho-git/motion_system_ros2.git` ← `https://github.com/SeonilChoi/motion_system.git`

한 번에 받습니다 · 서브모듈 없음 · `src/motion_system` 은 명시 요청 때만 수정합니다.

**합치기 전(서브모듈 시절)에 설치한 PC** 는 `install.sh` 갱신 대신 폴더 교체로
옮깁니다 · 옛 `src/motion_system` 체크아웃이 새 파일과 겹칩니다.

> **설치가 끝난 뒤 쓰는 법은 [사용법](docs/사용법.md) 을 보세요.**

## 새 PC 설치 · 우분투 설치 직후부터

> **처음이면 [설치 101](docs/설치_101.md) 부터** · 우분투만 깔린 PC 에서 로봇 PC 4대 + 스피커 PC 까지 · BIOS 등 사람이 할 일 포함 · 한 장짜리 순서표

### 한 줄 설치 (권장 · 2026-10-04)

우분투 22.04 를 깐 직후, **늘 쓸 계정**으로 로그인해 터미널에서 한 줄만 칩니다.

```bash
curl -fsSL https://raw.githubusercontent.com/y0ung-GMLAB/robot_web/main/scripts/bootstrap.sh | bash
```

- sudo 비밀번호 1회 · 시간대 질문 1회(Enter = 현재) · 모터 랜카드는 **IP 없는 유선 포트**를 자동으로 고릅니다(둘 이상이면 묻습니다)
- 아래 2~8단계를 전부 대신합니다 · 자동 업데이트·절전·화면 잠금 끄기 · 자동 로그인 · 로그아웃해도 유지(linger) ·
  EtherLab 설치(커널 업데이트 뒤 자동 재빌드) · `/etc/ethercat.conf`(MAC 기준) · 방화벽 같은 망 허용 · 코드 받기 · 빌드 · 서비스 등록
- 첫 설치는 중간에 **재부팅 1회**가 필요합니다 · 15초 뒤 스스로 재부팅하고, 자동 로그인 뒤 **저절로 이어서** 끝냅니다
  (기록 · `~/ros2_ws/log/site_setup/`) · 끝에 자가 점검표가 찍힙니다
- **수작업으로 남는 것** · 1단계 BIOS(전원 복구 시 켜기) · 웹에서 로봇 팩 업로드 · 모터 관리 → 전체 모터 검색 → 설정 적용
- **PC 이름** · 우분투 컴퓨터 이름(`hostname`)이 그대로 `이 PC ID` 가 됩니다(웹에서는 못 바꿈) · 이미 floating1 처럼 돼 있으면 그대로 · 바꾸려면 `-s -- --name floating1`
- **설치 확인** · `bash ~/ros2_ws/scripts/check.sh` (스피커 PC 는 `~/robot_web/scripts/check.sh`) · 읽기만 · `[확인]` 줄만 보면 됩니다
- **BIOS** · `Secure Boot` 를 끕니다 · 켜져 있으면 EtherCAT 커널 모듈이 안 올라갑니다 · 설치가 켜져 있으면 경고합니다
- **스피커 PC** 는 끝에 `-s -- --speaker` 를 붙입니다 · `... bootstrap.sh | bash -s -- --speaker` · 스피커 앱만 깔고 모터·웹은 깔지 않습니다 · 자세한 것은 [speaker_app/README.md](speaker_app/README.md)

| 상황 | 할 일 |
|---|---|
| 다른 용도로 쓰던 PC | 그대로 됩니다 · 있는 프로그램은 지우지 않고 더하기만 합니다 · 단 자동 로그인·자동 업데이트 끄기·절전 끄기는 전시 PC 전제라 적용됩니다 · 깨끗이 하려면 우분투 재설치 뒤 한 줄 |
| 이미 이 프로그램이 깔린 PC | 같은 한 줄 = 코드 갱신 + 현장 준비 점검 · 또는 전처럼 `bash scripts/install.sh` (현장 준비는 손대지 않음) |
| 인터넷이 안 되는 매장 | 한 줄 설치는 인터넷이 필요합니다 · 사무실에서 설치한 뒤 들고 가세요 |
| 미리 보기만 | `bash scripts/install.sh --site --dry-run` · 바꾸지 않고 할 일만 찍습니다 |
| 랜카드 지정 · 시간대 지정 | `SITE_ETHERCAT_NIC=enp2s0 SITE_TIMEZONE=Europe/Paris bash scripts/install.sh --site` |

아래는 **손으로 할 때**의 순서입니다 (한 줄 설치가 하는 일의 설명이기도 합니다).

### 준비할 것

| | |
|---|---|
| 운영체제 | **Ubuntu 22.04 LTS** · 다른 버전이면 설치가 중간에 멈춥니다 |
| 네트워크 | 인터넷 연결 |
| 계정 | 이 PC 를 늘 쓸 계정 하나 · **모든 단계를 그 계정으로** 합니다 |
| GitHub | 저장소가 비공개일 때만 사용자 이름과 **토큰** (계정 비밀번호로는 안 됩니다 · 6단계) · 공개 저장소면 필요 없음 |

### 전체 순서

**위에서부터 차례로** 합니다. 건너뛰면 뒤에서 막힙니다.

| | 단계 | 왜 |
|---|---|---|
| 1 | BIOS · 전원 들어오면 켜지게 | 정전 후 사람 없이 복구 |
| 2 | 저절로 방해되는 것 끄기 | 업데이트 창·화면 꺼짐·절전·WiFi 졸기가 전시를 망칩니다 |
| 3 | 전원만 넣으면 프로그램이 뜨게 | 없으면 켜도 아무것도 안 뜹니다 |
| 4 | 시간대 맞추기 | 스케줄 시각의 기준 · **설치 전에** 하면 편합니다 |
| 5 | EtherCAT 준비 | AC 서보를 쓸 때만 · 코드 받기 **전에** |
| 6 | 코드 받기 | |
| 7 | 설치 실행 → 재부팅 → **한 번 더** | 재부팅을 건너뛰면 덜 된 채로 끝납니다 |
| 8 | 확인 | |

3번과 7번의 재부팅이 가장 자주 걸리는 자리입니다.

---

### 1. BIOS · 전원 들어오면 켜지게

전원을 넣거나 정전이 복구되면 **사람 없이 스스로 켜져야** 합니다.

부팅 중 `Del` 또는 `F2` 로 BIOS 에 들어가, 전원 항목에서 다음을 찾아 바꿉니다.
이름은 메인보드마다 조금씩 다릅니다.

| 찾을 이름 | 값 |
|---|---|
| `Restore on AC Power Loss` / `AC Back` / `After Power Failure` | **Power On** |
| `Wake on LAN`, `Deep Sleep` | 필요 없으면 Disabled |

**확인** — 전원 케이블을 뽑았다 꽂아서 저절로 켜지는지 봅니다.

### 2. 저절로 방해되는 것 끄기

우분투는 그냥 두면 **업데이트 창을 띄우고, 한참 안 만지면 화면을 끕니다.**
전시 중에 그러면 안 됩니다.

아래 명령은 **PC 앞에 앉아서** 실행합니다. 화면 설정을 바꾸는 명령이라
원격 접속 창에서는 엉뚱한 곳에 적용될 수 있습니다.

```bash
# 자동 업데이트 끄기
sudo systemctl mask --now unattended-upgrades
sudo tee /etc/apt/apt.conf.d/20auto-upgrades >/dev/null <<'EOF'
APT::Periodic::Update-Package-Lists "0";
APT::Periodic::Unattended-Upgrade "0";
EOF
sudo sed -i 's/^Prompt=.*/Prompt=never/' /etc/update-manager/release-upgrades

# 화면 꺼짐·잠금·절전 끄기
gsettings set org.gnome.desktop.session idle-delay 0
gsettings set org.gnome.desktop.screensaver lock-enabled false
gsettings set org.gnome.desktop.screensaver idle-activation-enabled false
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'

# WiFi 를 쓴다면 절전 끄기 (유선만 쓰면 건너뜀)
#   랜카드가 틈틈이 졸면 PC 끼리 주고받는 신호가 늦거나 끊깁니다
nmcli connection modify "연결이름" 802-11-wireless.powersave 2
nmcli connection up "연결이름"

# 업데이트 알림 팝업 끄기
mkdir -p ~/.config/autostart
printf '[Desktop Entry]\nType=Application\nName=Update Notifier\nHidden=true\nX-GNOME-Autostart-enabled=false\n' \
  > ~/.config/autostart/update-notifier.desktop
```

**확인**

```bash
gsettings get org.gnome.desktop.session idle-delay     # uint32 0
systemctl is-enabled unattended-upgrades               # masked
iwconfig 2>/dev/null | grep -i "power management"      # off (WiFi 를 쓸 때)
```

> `연결이름` 은 `nmcli connection show` 로 확인합니다. WiFi 이름과 같습니다.

> 전원 버튼을 잘못 눌러 꺼지는 것까지 막으려면
> `gsettings set org.gnome.settings-daemon.plugins.power power-button-action 'nothing'` ·
> 대신 버튼으로 끌 수 없게 되니 현장에 맞춰 정하세요.

### 3. 전원만 넣으면 프로그램이 뜨게

이 프로그램은 **로그인한 사람 밑에서 도는 방식**입니다. 그래서 그냥 두면
누군가 로그인하기 전까지 아무것도 안 뜹니다. 전시장처럼 사람이 없는 곳에서는
두 가지를 켜야 합니다.

- **자동 로그인** — 켜지면 사람 없이 저절로 로그인합니다
- **로그아웃해도 계속 돌게** — 화면이 잠기거나 로그아웃돼도 프로그램이 안 꺼집니다

```bash
# 로그아웃해도 계속 돌게
sudo loginctl enable-linger "$USER"

# 자동 로그인 켜기
sudo nano /etc/gdm3/custom.conf
```

`[daemon]` 아래에 두 줄을 넣습니다. `사용자이름` 은 실제 계정명으로 바꿉니다.

```ini
[daemon]
AutomaticLoginEnable=true
AutomaticLogin=사용자이름
```

**확인**

```bash
loginctl show-user "$USER" | grep Linger     # Linger=yes 가 나와야 합니다
grep AutomaticLogin /etc/gdm3/custom.conf    # 적어 넣은 두 줄이 보여야 합니다
```

### 4. 시간대 맞추기

스케줄은 **이 PC 의 시각**을 기준으로 돕니다. 인터넷에 연결해도 **시간대는
저절로 안 바뀝니다.**

```bash
timedatectl                                    # Time zone 확인
timedatectl list-timezones | grep Seoul        # 도시 이름 찾기
sudo timedatectl set-timezone Asia/Seoul
```

- 반드시 **도시 이름**(`Europe/Paris`)으로 잡습니다. 그래야 서머타임을
  운영체제가 알아서 처리합니다. `UTC+2` 같은 고정값은 1년에 두 번 손봐야 합니다.
- 우분투 `설정 → 날짜 및 시간` 에서 골라도 됩니다. **「자동 시간대」는 끈 채로**
  두세요. 전시 중에 저절로 바뀌면 스케줄이 튑니다.
- **설치 전에** 해두면 편합니다. 나중에 바꾸면 프로그램을 다시 올려야 합니다.

### 5. EtherCAT 준비 · AC 서보를 쓸 때만

**코드를 받기 전에 끝내야 합니다.** 설치 명령은 EtherCAT 이 깔려 있는지
확인만 하고, 없으면 멈춥니다.

설치 방법은 [2. EtherLab/IgH EtherCAT 준비](#2-etherlabigh-ethercat-준비)를
따릅니다. 설치한 뒤 **어느 랜카드를 모터에 쓸지** 지정합니다.

```bash
ip link                        # 랜카드 이름 확인 (예: enp1s0)
sudo nano /etc/ethercat.conf
```

```ini
MASTER0_DEVICE="enp1s0"
DEVICE_MODULES="generic"
UPDOWN_INTERFACES="enp1s0"
```

**확인**

```bash
sudo systemctl enable --now ethercat
ethercat master                # Phase 가 보이면 정상
ethercat slaves                # 연결한 드라이브가 보여야 합니다
```

비어 있으면 랜선 위치와 `MASTER0_DEVICE` 이름을 다시 봅니다.

### 6. 코드 받기

갓 설치한 우분투에는 `git` 이 없을 수 있습니다. 먼저 깔아 둡니다.

```bash
sudo apt update
sudo apt install -y git
```

```bash
cd ~
git clone -b main https://github.com/y0ung-GMLAB/robot_web.git ros2_ws
cd ~/ros2_ws
```

GitHub 사용자 이름과 **토큰**을 물어봅니다. **계정 비밀번호로는 안 됩니다.**

토큰은 GitHub 웹에서 만듭니다 — `Settings → Developer settings →
Personal access tokens` · 만든 뒤 한 번만 보이니 적어 두세요.

### 7. 설치 실행

```bash
cd ~/ros2_ws
bash scripts/install.sh
```

몇십 분 걸립니다. 이 한 줄이 아래를 다 합니다.

- ROS 2 설치 (따로 깔 필요 없습니다)
- 최신 코드 받기
- 필요한 프로그램 설치
- 계정 권한·언어 맞추기
- 전체 빌드
- **모터가 끊기지 않게 하는 권한 설정** (7-1 참고)
- 전원을 켜면 저절로 뜨도록 등록

> `git pull` 을 앞에 붙이지 마세요. 코드가 갈라진 PC 에서는 `git pull` 이
> 실패하면서 **설치가 아예 안 돕니다.** 코드 받기는 이 명령이 알아서 합니다.

#### 7-1. 재부팅 안내가 나오면 (거의 반드시 나옵니다)

```text
실시간 우선순위 권한 설정 필요 · 현재 rtprio=0
설정 파일 작성: /etc/security/limits.d/99-motion-control.conf
실시간 권한 설정 완료 · PC 재부팅 후 설치 명령을 다시 실행하세요.
```

모터는 정해진 박자에 맞춰 신호를 받아야 합니다. 그 박자를 지키려면 이
프로그램이 **다른 프로그램보다 먼저 처리되는 권한**을 가져야 하는데, 새 PC 에는
그 권한이 없습니다. 없으면 박자를 놓쳐 **모터가 떨리거나 멈춥니다.**

권한을 주는 파일은 설치 명령이 대신 써 줍니다. 다만 **재부팅해야 적용됩니다.**

```bash
sudo reboot
```

재부팅한 뒤 확인하고 **같은 명령을 다시** 실행합니다.

```bash
ulimit -r                          # 99 가 나와야 합니다
cd ~/ros2_ws
bash scripts/install.sh
```

끝에 `설치 완료` 가 찍히면 됩니다. **여기서 재부팅을 건너뛰면 설치가 덜 된
채로 끝납니다.**

### 8. 확인

```bash
systemctl --user status --no-pager motion-control.service motion-coordination.service
```

둘 다 `active (running)` 이어야 합니다. 그다음 웹 화면(`http://localhost:8000`)에서:

| 보는 곳 | 정상 |
|---|---|
| 상단 배지 | 🟢 `스케줄러: …` |
| `모터 관리` | 축이 보이고 연결 상태 정상 |
| `📅 모션 스케줄` 상단 | `🕒 PC 시각: …` 시간대가 현지와 같음 |

마지막으로 **전원을 껐다 켜서** 사람 손 없이 웹 화면까지 올라오는지 봅니다.
여기까지 되면 설치 끝입니다.

---

### 설치 뒤에 하는 일 (웹 화면에서)

설정 파일을 손으로 만질 일은 없습니다.

| 무엇 | 어디서 |
|---|---|
| 모터 축 등록·설정 | `모터 관리` |
| PC 묶어 쓰기 (연동) | `PC 연동` |
| 모션 편집·실행 | `모션 데이터` · `모션 실행` |
| 스케줄 | `📅 모션 스케줄` |

연동을 쓰려면 **묶을 PC 들이 같은 공유기(같은 네트워크)에 붙어 있어야**
합니다. 서로 다른 망에 있으면 상대를 못 찾습니다. 이건 설치할 때 정해지는
것이라 웹 화면에서는 못 고칩니다.

그래도 서로 못 찾으면 **방화벽**을 봅니다. 우분투는 기본이 「들어오는 것 막기」
입니다.

```bash
sudo ufw status                        # 켜져 있는지 확인
sudo ufw allow from 192.168.0.0/16     # 같은 망 안에서는 허용 (대역은 현장에 맞게)
```

---

### 안 될 때 먼저 볼 곳

| 증상 | 원인 | 할 일 |
|---|---|---|
| 전원 넣어도 아무것도 안 뜸 | 자동 로그인이 안 켜짐 | 3단계 |
| 모터가 떨리거나 멈춤 | 권한 설정 안 됨 | `ulimit -r` 이 99 인지 · 7-1 |
| `ethercat slaves` 가 비어 있음 | 랜카드 지정 | 5단계 |
| 전시 중 화면이 꺼짐 | 화면보호기 | 2단계 |
| 업데이트 창이 뜸 | 자동 업데이트 | 2단계 |
| 스케줄이 엉뚱한 시각에 돎 | 시간대 | 4단계 |
| 다른 PC 가 「통신 단절」 | 그룹 ID·Domain ID 다름 · 다른 공유기 · 방화벽 | 웹 `PC 연동` · `sudo ufw status` |
| 연동이 자꾸 끊기거나 느림 | WiFi 절전이 켜짐 | 2단계의 `powersave 2` |
| `git: command not found` | git 이 안 깔림 | 6단계 첫 명령 |
| 설치 중 인증 실패 | 계정 비밀번호를 넣음 | GitHub **토큰**을 넣어야 합니다 |
| 예전에 설치한 PC 가 켜져도 안 뜸 | `--site` 없이 설치(자동 로그인·linger 없음) | `loginctl show-user $USER -p Linger` 가 `no` 면 `bash scripts/install.sh --site` 한 번 |

### 꼭 알아 둘 것 · 현장 (2026-10-07)

- **전원을 넣으면 로봇이 스스로 움직인다** · 켜짐 → 자동 로그인 → 서비스 3개 → 서보 자동 ON →
  운전 모드가 `스케줄` 이고 운영 시간 안이면 초기 위치 이동 → 재생(연동이면 마스터가 시작) ·
  정비할 때는 웹에서 `수동` 또는 `오프` 로 바꾸거나 모터 전원을 따로 내린 뒤 다가간다
- 정전 복구 자동 기동은 **BIOS(1단계) + 자동 로그인·linger(3단계)** 둘 다 있어야 한다 · 하나라도 없으면 PC 는 켜져도 프로그램이 안 뜬다 ·
  확인은 전원 케이블 뽑았다 꽂기(버튼 누르지 않기)
- 연동하는 PC 는 **모두 같은 버전** · 하나만 갱신하면 그 PC 는 「버전 불일치」 로 빠진다
- **모든 MINAS 드라이브는 앱솔루트(Pr0.15 = 0)여야 한다** · 공장값은 인크리멘털일 수 있다(2026-10-07 실물 3축 모두 인크리멘털) · 설치 때 `모터 관리` → `앱솔루트 설정 (전체)` → 화면 안내대로 드라이브 전원 재투입 2회 → 「완료」 → 기준점 캡처(낱개로는 `앱솔루트 방식` 0 → 재투입 → `다회전 클리어` → 재투입) · 인크리멘털이면 전원이 꺼졌다 켜질 때마다 위치 기준이 틀어진다
  - **2026-10-07 부터 확인 안 되면 모든 모터 동작이 막힌다**(수정 목록 62) · 서보 ON · 조그 · 재생 · 스케줄 · 그룹까지 · 상단 빨간 칸 「앱솔루트 미확인」 · **갱신 전에 그 PC 의 MINAS 드라이브를 모두 앱솔루트로 바꿔 둘 것** · 안 그러면 갱신 직후 매장 재생이 멈춘다
- MINAS 엔코더는 배터리 백업 절대값 · 재부팅·정전 뒤 기준점 다시 캡처 필요 없음 · 단 MINAS `다회전 클리어` 나 다이나믹셀 다회전(모드 4) `재부팅` 뒤에는 위치를 확인하고 필요하면 다시 캡처
- 저장소는 공개 · 받을 때 로그인 필요 없음 · **비밀번호·토큰·매장 정보는 저장소에 넣지 않는다**
- 실물 확인이 안 끝난 기능 목록 · `docs/실물_확인_대기.md`

### 이미 설치된 PC 갱신

```bash
cd ~/ros2_ws
bash scripts/install.sh
```

**갱신 명령은 이 한 줄입니다.** 모든 PC 에서 같습니다. 연동해서 쓰는 PC 는
**전부** 갱신해야 서로 붙습니다.

**웹에서 한 번에 (2026-10-08~)** · 아무 로봇 PC 웹 → `실행` → `PC 연동 설정` → 「같은 망 PC」 아래
**`모든 PC 업데이트`** · 같은 망의 연결된 로봇 PC 마다 `install.sh --code-only`(코드 받기 → 빌드 →
서비스 재시작 · 관리자 비밀번호 없이)를 돌리고 표에 진행·버전(옛 → 새)·마지막 줄을 보여 줍니다.

- 재생 중인 PC 는 거절 · 이 PC 는 맨 마지막(화면이 잠깐 끊겼다 돌아옴) · 운영 시간 밖에
- 새 시스템 패키지가 필요한 갱신이면 그 PC 가 「실패 · 새 시스템 패키지가 필요합니다」 → 그 PC 터미널(웹 터미널 탭도 됨)에서 위 한 줄
- 스피커 PC 도 같이 합니다(2026-10-08 · 수정 목록 80) · 옛 스피커 앱이라 「터미널에서」 로 나오면 그 PC 터미널에서 `bash ~/robot_web/scripts/install_speaker.sh` 한 번
- **이 기능이 들어간 버전을 한 번은 PC 마다 받아야** 그 뒤부터 웹으로 됩니다(처음 한 번은 위 한 줄)

작업공간 경로를 모르면:

```bash
find ~ -maxdepth 3 -type d -path '*/src/motion_web' 2>/dev/null
```

## 0. ROS 2 Humble 설치

Ubuntu 22.04 데스크톱 환경에 ROS 2 Humble을 설치합니다. 이미 설치된 PC라면 이 단계를 건너뜁니다.

```bash
# 1. 로케일 설정 (UTF-8)
sudo apt update && sudo apt install locales
sudo locale-gen en_US en_US.UTF-8
sudo update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
export LANG=en_US.UTF-8

# 2. Ubuntu Universe 저장소 활성화
sudo apt install software-properties-common
sudo add-apt-repository universe

# 3. ROS 2 GPG 키 및 저장소 추가
sudo apt update && sudo apt install curl -y
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" | sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null

# 4. ROS 2 패키지 설치
sudo apt update
sudo apt install -y ros-humble-desktop
```

## 1. 기본 환경 준비

Ubuntu 22.04와 ROS 2 Humble을 먼저 설치합니다. 다음은 현재 작업공간에서
직접 사용하는 기본 도구와 Python 실행 패키지입니다.

```bash
sudo apt update
sudo apt install -y \
  git build-essential cmake \
  gcc-12 g++-12 ethtool \
  python3-rosdep python3-colcon-common-extensions \
  python3-fastapi python3-uvicorn python3-yaml chrony \
  btop ttyd
```

Dynamixel 직렬 통신을 사용하는 계정에는 필요한 그룹 권한을
추가합니다. 변경 후에는 로그아웃하거나 재부팅해야 적용됩니다.

```bash
sudo usermod -aG dialout,audio "$USER"
```

## 1-1. Ubuntu 원격 접속 (GNOME RDP) 설정

여러 대의 PC에 RDP 접속 환경을 일관되게 구성하려면 xrdp 대신 Ubuntu 기본 GNOME RDP를 사용합니다.

1. **자동 로그인 켜기**: `설정 → 사용자`에서 Automatic Login: ON
2. **화면 잠금 끄기**: `설정 → Privacy → Screen Lock`에서 Automatic Screen Lock: OFF, Suspend 후 화면 잠금: OFF
3. **절전 모드 끄기**: `설정 → Power`에서 Screen Blank: Never, Automatic Suspend: Off
4. **원격 데스크톱 켜기**: `설정 → Sharing → Remote Desktop`에서 Remote Desktop: ON, Remote Control: ON
5. **Keyring 암호 해제**: `seahorse` 실행 → Default keyring 자체의 Change Password 실행 → 기존 암호 입력 후 새 암호는 빈칸으로 저장 (경고 허용)

**부팅 시 RDP 자동 실행 서비스 등록**

```bash
mkdir -p ~/.local/bin ~/.config/systemd/user

# 1. RDP 자격증명 스크립트 생성 (<사용자명>과 <RDP비밀번호> 변경)
cat << 'EOF' > ~/.local/bin/setup-rdp-after-login.sh
#!/bin/bash
sleep 5
/usr/bin/grdctl rdp set-credentials <사용자명> '<RDP비밀번호>'
/usr/bin/grdctl rdp enable
/bin/systemctl --user restart gnome-remote-desktop.service
EOF
chmod 700 ~/.local/bin/setup-rdp-after-login.sh

# 2. 사용자 Systemd 서비스 등록
cat << 'EOF' > ~/.config/systemd/user/rdp-after-login.service
[Unit]
Description=Configure GNOME RDP after automatic login
After=gnome-remote-desktop.service
Wants=gnome-remote-desktop.service

[Service]
Type=oneshot
ExecStart=%h/.local/bin/setup-rdp-after-login.sh
RemainAfterExit=yes

[Install]
WantedBy=default.target
EOF

# 3. 서비스 활성화
systemctl --user daemon-reload
systemctl --user enable rdp-after-login.service
```

설정 후 재부팅하면 사용자 조작 없이 백그라운드에서 GNOME RDP가 자동 실행됩니다.

## 2. EtherLab/IgH EtherCAT 준비

EtherLab은 Git 작업공간에 포함되지 않으며 PC마다 별도로 설치합니다. 현재
검증 버전은 1.6.9입니다.

먼저 EtherCAT 전용 랜카드의 **MAC 주소**와 커널 드라이버를 확인해야 합니다. (랜카드 이름은 재부팅 시 수시로 변경될 수 있으므로, 설정 파일에는 반드시 고유한 MAC 주소를 사용하는 것이 꼬임 방지에 필수적입니다.)

**1. 랜카드 이름 및 MAC 주소 찾기**
```bash
ip -br link
```
*(출력 예시: `enp2s0    UP    00:11:22:33:44:55 ...` 에서 3번째 항목인 `00:11:22:33:44:55`가 MAC 주소입니다)*

**2. 커널 드라이버 이름 찾기**
```bash
# 위에서 찾은 랜카드 이름(예: enp2s0)을 대입합니다.
ethtool -i enp2s0
```
*(출력 중 `driver: r8169` 또는 `driver: e1000e`, `driver: igc` 등의 값을 확인합니다)*

EtherLab 소스 빌드에는 다음 도구가 필요합니다.

```bash
sudo apt install -y autoconf automake libtool pkg-config build-essential git gcc-12 g++-12 ethtool librtmidi-dev
git clone https://gitlab.com/etherlab.org/ethercat.git
```

빌드할 때는 해당 PC의 커널 버전과 드라이버 지원 여부에 맞춰 모듈을 설정해야 합니다.
특히 Ubuntu 22.04의 최신 Linux 6.8+ 커널 환경에서는 r8169 등 전용 드라이버 모듈 빌드가 실패할 수 있으므로 **범용(generic) 모드** 사용을 권장합니다.

```bash
cd ethercat
./bootstrap

# 커널 6.8+ 환경 또는 전용 드라이버 빌드 실패 시 범용(generic) 모드로 빌드 (권장):
./configure --disable-8139too --enable-generic=yes

# (참고) 커널 버전이 낮고 전용 드라이버가 빌드되는 경우:
# ./configure --disable-8139too --enable-generic=no --enable-r8169=yes

make all modules
sudo make modules_install install
sudo depmod
```

설정 파일은 빌드 방식에 따라 `/etc/ethercat.conf` 또는 `/usr/local/etc/ethercat.conf` 경로에 생성됩니다. 설정 파일 경로를 확인한 후 편집합니다.

```bash
# 설정 파일 경로 확인
ls -l /etc/ethercat.conf /usr/local/etc/ethercat.conf 2>/dev/null
```

설정 파일 편집 시, 장치 이름(enp~ 등) 대신 **위에서 확인한 MAC 주소**를 기입해야 재부팅 시 꼬임 현상을 방지할 수 있습니다.

```text
MASTER0_DEVICE="<랜카드의 MAC 주소 예: 00:11:22:33:44:55>"
DEVICE_MODULES="generic"
UPDOWN_INTERFACES="<EtherCAT-NIC-이름>"
```

일반 계정(`ros2` 등)에서 `sudo` 없이 모터에 접근하려면 udev 권한 설정이 필수입니다. 서비스 시작 전 권한을 설정합니다.

```bash
# 1. udev 권한 규칙 등록
echo 'KERNEL=="EtherCAT[0-9]*", MODE="0666"' | sudo tee /etc/udev/rules.d/99-ethercat.rules
sudo udevadm control --reload-rules
sudo udevadm trigger
```

설정·권한 적용 후 EtherCAT 서비스 시작 및 동작 확인:

```bash
# 2. 서비스 시작 및 모듈 로드 확인
sudo systemctl enable --now ethercat
lsmod | grep ec_master
ls -l /dev/EtherCAT0

# 3. 마스터 및 서보 슬레이브 응답 확인
ethercat version
ethercat master
ethercat slaves
```

`ethercat slaves`의 실제 장치 표시는 서보 전원, 배선과 Slave 연결 상태에
따라 달라집니다. 일반 LAN과 EtherCAT에는 절대로 동일한 랜카드를 혼용하지 마십시오.

## 3. 전체 소스 설치

저장소(`main`) 하나를 받습니다 · Motion System 도 그 안에 있습니다(서브모듈 없음).

```bash
cd ~
git clone -b main \
  https://github.com/y0ung-GMLAB/robot_web.git ros2_ws
cd ~/ros2_ws
```

이미 복제한 저장소라면 설치 명령 하나로 `main` 최신까지 맞춰집니다.
손으로 `git pull` 할 필요가 없습니다.

```bash
cd ~/ros2_ws
bash scripts/install.sh
```

DDS 그룹 연동 설정(`config/motion_coordination.yaml`)은 **웹 화면 `PC 연동`
에서 저장하면 이 파일이 만들어집니다.** 손으로 만들 필요가 없습니다.

`config/motion_coordination.example.yaml` 은 항목을 확인할 때 보는 예시입니다.

## 4. ROS 의존성 설치와 빌드

### 4-1. 최초 설치 (PC에 작업공간을 처음 만든 경우)

`rosdep`을 처음 사용하는 PC에서만 초기화한 뒤 의존성을 설치합니다.

```bash
cd ~/ros2_ws
source /opt/ros/humble/setup.bash
sudo rosdep init    # 이미 초기화되어 있으면 생략
rosdep update
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
source install/setup.bash
```

### 4-2. 코드 갱신 (이미 설치된 PC)

이미 설치된 PC도 설치 때와 같은 명령 하나만 사용합니다.

```bash
cd ~/ros2_ws
bash scripts/install.sh
```

동작:

```text
Git 최신 코드 수신
필수 프로그램 확인
전체 colcon 빌드
ROS 2 daemon stop/start
자동실행 서비스 등록
motion-control.service 재시작
motion-coordination.service 재시작
```

로컬 수정 파일이 있으면 자동 Git 수신만 건너뛰고 나머지 설치·빌드는 계속
진행합니다. Git 수신을 일부러 막으려면 아래처럼 실행합니다.

```bash
MOTION_WEB_SKIP_GIT_PULL=1 bash scripts/install.sh
```

`GroupCommand` 같은 DDS 메시지 정의가 바뀐 경우에는
통합 설치 스크립트가 메시지 인터페이스 빌드와 `ros2 daemon` 초기화를 함께
수행합니다.

(기존 `scripts/sync_branch.sh` 스크립트를 통한 특정 브랜치 동기화 기능도 여전히 지원됩니다.)

`update.sh`는 호환용 별칭입니다. 내부에서 같은 `install.sh`를 실행합니다.

### 4-3. 커밋·푸시 (개발 PC)

```bash
cd ~/ros2_ws
MOTION_WEB_BRANCH=main bash scripts/commit_branch.sh "커밋 메시지" --push
```

`--push` 없이 커밋만 하려면 마지막 `--push`를 빼면 됩니다. 이 스크립트는
`src/motion_system` 에 커밋 안 된 변경이 있으면 중단합니다.

수동으로 커밋할 때는 [8. Git 작업 방법](#8-git-작업-방법)을 따릅니다.

### 4-4. Codex 자동 설치·업데이트 지시문

다른 PC에서 Codex에게 작업을 맡길 때는 아래 문장을 그대로 전달합니다.

최초 설치:

```text
README의 최초 설치 절차대로 이 PC에 설치해줘.
src/motion_system은 명시 요청 없으면 수정하지 마.
실행 검증과 실물 검증을 구분해서 보고해줘.
```

기존 PC 업데이트:

```text
README의 코드 갱신 절차대로 bash scripts/install.sh를 실행해줘.
Git 수신, 전체 빌드, ros2 daemon 초기화, 서비스 재시작 여부를 확인해줘.
src/motion_system은 명시 요청 없으면 수정하지 마.
실행 검증과 실물 검증을 구분해서 보고해줘.
```

Codex가 수정이나 설치를 수행한 뒤에는 변경 파일, 실행한 명령, 성공·실패
결과와 실물 검증 여부를 분리해서 확인합니다.

## 5. 자동실행 등록

최초 설치는 통합 설치 스크립트가 자동실행 서비스까지 등록합니다.

```bash
cd ~/ros2_ws
bash scripts/install.sh
```

서비스만 다시 등록해야 하는 특수 상황에서는 아래 명령을 사용할 수 있습니다.
일반 사용자는 위 `install.sh` 하나만 사용합니다.

```bash
cd ~/ros2_ws
bash src/web_bridge/deploy/install_user_service.sh
```

`실시간 우선순위 권한 설정 필요`가 표시되면 설치 스크립트가
`/etc/security/limits.d/99-motion-control.conf`를 작성합니다. PC를 재부팅한 뒤
같은 명령을 다시 실행합니다.

로그인 전 부팅 단계부터 실행하려면 PC마다 최초 한 번 다음 설정을 추가합니다.

```bash
sudo loginctl enable-linger "$(id -un)"
```

이후에는 재부팅할 때 다음 서비스가 자동으로 실행됩니다.

- `motion-control.service`: 웹·프로젝트·모션 제어 서비스 (`LimitRTPRIO=99`, `LimitMEMLOCK=infinity` 적용 - 하위 모터 재시작 스크립트 및 런타임 RT 권한 보장)
- `motion-motor.service`: 검증된 프로젝트 모터 실행 설정이 있을 때 Motor Manager (`LimitRTPRIO=99`, `LimitMEMLOCK=infinity` 적용)
- `motion-coordination.service`: PC 간 DDS 그룹 상태 공유·실행 조정
- `motion-terminal.service`: 웹 「터미널」 탭 (`ttyd` · 포트 8081 · `ttyd` 가 있을 때만)
- `motion-btop.service`: 웹 「PC 성능 (btop)」 탭 (`ttyd` · 포트 8080 · `ttyd`·`btop` 이 있을 때만)

### 무인 연동 구동 설정 절차 (켜면 스케줄대로)

자세한 화면 설명은 [사용법](docs/사용법.md) 8장(여러 대 묶기) · 9장(스케줄).

1. **모든 PC** · `실행` → `PC 연동 설정` · 같은 `그룹 ID`·`DDS Domain ID` · PC 마다 다른 `이 PC ID` ·
   한 대만 역할 `마스터` · `설정 저장·연동 재시작`
2. **마스터 PC** · `2. 그룹 참가 PC` 표에 모든 PC 가 🟢 정상이고 `버전 (Git)` 이 같은지 확인 →
   `현재 접속 PC로 명단 확정` (명단 = 와야 할 PC)
3. **마스터 PC** · 스케줄(운영 시간) 등록 · 운전 모드 `스케줄`(기본)
4. **켜기만 하면** · 운영 시간 안이면 마스터가 그룹 실행을 시작 · 꺼져 있거나 알람·수동/오프 모드인 PC 는
   **빼고 나머지로** 시작(표 `제외 · 이유` · `🔴 미접속` · 마스터 웹 「모터 동작 로그」 → `그룹 연동` 에 기록) ·
   빠졌던 PC 는 돌아오면 도는 중에도 다음 회차부터 다시 들어감(회차 맞춤 · 연속 재생)

웹 UI의 **터미널** · **PC 성능 (btop)** 탭은 별도 서비스(`ttyd`)로 돕니다 · `install_user_service.sh` 가
`ttyd`·`btop` 이 깔려 있으면 자동으로 등록합니다 (`sudo apt install btop ttyd` 후 `bash scripts/install.sh`).
터미널 서비스는 설치 중에도 멈추지 않습니다 · 설치를 치고 있는 창이 바로 그 서비스일 수 있기 때문입니다.

새 PC에 검증된 모터 실행 설정이 없으면 웹(`motion-control.service`)은 정상 실행되지만 `motion-motor.service` 시작은 보류(inactive/dead)됩니다. 이는 모터 무단 구동을 방지하는 **정상 동작**입니다. 브라우저 창은 자동으로 열리지 않습니다.

## 6. 실행과 상태 확인

```bash
systemctl --user start motion-control.service
systemctl --user status motion-control.service motion-motor.service motion-coordination.service
```

로그 확인:

```bash
journalctl --user -u motion-control.service -n 100
journalctl --user -u motion-motor.service -n 100
journalctl --user -u motion-coordination.service -n 100
```

> [!TIP]
> 웹 서비스(`motion-control.service`)에서 프로젝트 적용 및 백그라운드 프로세스 재시작 중 발생한 ROS 노드 오류나 저수준 에러 로그는 작업공간의 **`log/web_apply_restart/restart-*.log`** 파일에서도 확인할 수 있습니다. ROS 2 노드 자체 로그는 `~/.ros/log/` 가 아니라 작업공간 **`log/ros/`** 에 남습니다(`ROS_LOG_DIR`). 두 폴더 모두 서비스 시작 때 **14일**이 지난 항목을 삭제합니다(`LOG_RETENTION_DAYS` 로 변경).

웹 접속(자세히는 맨 위 [웹 접속 주소](#웹-접속-주소--다른-pc-나-노트북에서)):

- 현재 PC: `http://localhost:8000`
- 다른 PC: `http://<이-PC의-IP>:8000` · 또는 `http://<PC이름>.local:8000`

서비스 등록 상태 확인:

```bash
loginctl show-user "$(id -un)" -p Linger
systemctl --user is-enabled motion-control.service motion-motor.service motion-coordination.service
ss -ltnp | grep ':8000'
```

### 6-1. PC 연동 업데이트 문제 해결

`GROUP_START_REJECTED`와 함께 다음 형태의 오류가 나오면 다른 PC의 DDS 메시지
산출물이 구버전일 가능성이 큽니다.

```text
'GroupCommand' object has no attribute 'target_cycle_count'
```

조치 순서:

```bash
cd ~/ros2_ws
bash scripts/install.sh
systemctl --user status motion-coordination.service motion-control.service
journalctl --user -u motion-coordination.service -n 80
```

확인 기준:

```text
motion_coordination_interfaces 빌드 완료
ros2 daemon stop/start 완료
motion-coordination.service 재시작 완료
motion-control.service 재시작 완료
브라우저 Ctrl+F5 후 DDS 그룹 참가 상태 확인
```

여러 PC 중 한 대만 업데이트해도 메시지 구조가 맞지 않으면 연동이 실패할 수
있습니다. PC 연동에 참가하는 모든 PC에서 같은 Git 커밋과 같은 메시지 빌드
상태를 맞춥니다.

## 7. 네트워크 주의사항

- PC마다 서로 다른 IP 주소와 hostname을 사용합니다.
- 고정 IP 또는 공유기의 DHCP 예약을 권장합니다.
- 서로 다른 PC는 같은 `8000` 포트를 사용해도 IP가 다르면 충돌하지 않습니다.
- 같은 PC에서 다른 프로그램이 `8000` 포트를 사용하면 웹 서비스가 시작되지
  않습니다.
- 웹은 `0.0.0.0:8000`에 바인딩되므로 신뢰할 수 있는 내부망에서만 사용합니다.
- 방화벽은 운영 PC가 있는 내부 대역만 허용하고 인터넷에 직접 노출하지 않습니다.
- 서비스 3개(`motion-control` · `motion-motor` · `motion-coordination`)는 모두
  `ROS_LOCALHOST_ONLY=0`으로 실행합니다(`MOTION_GROUP_NETWORK=1` 기본 · §6-96).
  남의 ROS 장비와 섞이지 않는 근거는 PC 이름공간(`/<PC이름>/...`)과 그룹 전용
  DDS 도메인(기본 21)입니다. 한 PC 안에 가두려면 서비스 환경에
  `MOTION_GROUP_NETWORK=0`을 주면 `ROS_LOCALHOST_ONLY=1`이 됩니다.
- PC 간에는 그룹 참가 상태·고수준 실행 트리거·완료·오류만 전송합니다. 프로젝트
  파일, 모션 데이터와 모터 목표값은 전송하지 않습니다.
- 각 PC 웹의 `장비 연동 상태 → DDS 그룹 연동`에서 서로 다른 `이 PC ID`, 같은
  `그룹 ID`와 `DDS Domain ID`를 저장한 뒤 사용자가 직접 `그룹 참가`를 누릅니다.
- 그룹 실행은 **마스터 PC 한 대만** 시작합니다(손으로든 스케줄로든 · 정지는 아무 PC 에서나).
  시작할 때 **지금 정상인 PC 만** 참가시키고 나머지는 이유와 함께 뺍니다(통신 단절·응답 지연·
  미접속·Servo 알람·오프/수동 모드·버전 불일치·명단 외 · 준비 거절·준비 응답 없음).
  뺀 PC 는 마스터 웹 「모터 동작 로그」 의 `그룹 연동` 에 남습니다.
- 그룹 실행 동기화에 시스템 UTC·NTP는 사용하지 않습니다. 실행마다 DDS 왕복
  측정으로 각 PC의 monotonic 트리거를 맞춥니다. (`chrony` 패키지는 OS
  시간 유지용이며 그룹 트리거 동기화와는 무관합니다.)
- 같은 Wi-Fi 구간에서 ROS 2 DDS UDP 통신을 허용해야 하며, 무선 공유기의 AP
  isolation 기능은 꺼야 합니다.
- Wi-Fi 로 연동할 때 (2026-10-07) · 로봇 PC 전용 공유기·SSID · 5 GHz · **채널 고정**(자동 채널 변경 끄기) ·
  PC 마다 Wi-Fi 절전 끄기(2단계) · 고정 IP · 그룹 시작은 시계 맞춤 불확실성이 20 ms 를 넘으면 그 회차를 시작하지
  않으므로(`docs/DDS_MULTI_PC_VALIDATION.md`) 흔들림이 크면 유선·전력선(PLC)·점대점 무선 브리지를 검토 ·
  현장 확인 항목 `docs/실물_확인_대기.md` 3-1
- 동기 실행 코드는 포함되지만 실제 여러 PC와 모터의 시작 오차는 실물 검증 전입니다.

## 8. Git 작업 방법

코드·문서·설정 예시는 상위 저장소(`main`)에서 함께 커밋합니다.

```bash
cd ~/ros2_ws
git add -A
git commit -m "변경 내용"
git push origin main
```

Motion System(`src/motion_system`)도 같은 저장소 안 코드라 같은 커밋으로 올립니다 ·
명시적으로 요청받았을 때만 수정하고, 바꾼 내용은 `src/motion_system/VENDORED.md` 「이후 수정」 표에 적습니다.

관련 문서:

- [`docs/SYSTEM_OPERATION_FLOW.md`](docs/SYSTEM_OPERATION_FLOW.md) — 실행·DDS
  그룹 연동 흐름
- [`docs/DDS_MULTI_PC_VALIDATION.md`](docs/DDS_MULTI_PC_VALIDATION.md) — 2PC
  실물 검증 절차

## 제외 대상

다음 실행 데이터와 생성 파일은 Git에 포함하지 않습니다.

```text
build/
install/
log/
backups/
motion_projects/
motion_data/
```
