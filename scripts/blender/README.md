# Blender 애니메이션 내보내기

`animation_export.py` · Blender 본 애니메이션 → 애니메이션 파일(.json) · 로봇 무관.
터미널(Blender) 세션 소유 · 파일 형식 기준 = `src/motion_common/motion_common/motion_table.py`.

## 쓰는 법

1. .blend 를 연다 (애니메이션 하나 = .blend 하나 · 파일 이름 = 애니메이션 이름)
2. Text Editor → Open → `animation_export.py` → Run Script (Blender 켤 때마다 한 번)
3. 3D 뷰 사이드바(N) → **`Robot` 탭**
   - **속도 검사** · 파일 안 쓰고 검사만 (아래 창·마커·곡선 그대로 · 저장 안 한 .blend 도 됨)
   - **내보내기** · 폴더 고르기 창 → 출력 폴더 선택 (마지막 폴더 기억 · 씬 속성 `anim_export_dir`)
- Text 의 `Register` 체크 + 환경설정 `Save & Load → Auto Run Python Scripts` 가 켜져 있으면 파일 열 때 탭이 바로 생김 (Run Script 안 해도 됨)
- 2026-10-16 전 버전은 Run Script 하면 바로 폴더 창이 떴음 · 지금은 탭만 등록

출력

| 파일 | 내용 |
|---|---|
| `<이름>.json` | 애니메이션 파일 · 웹 업로드용 · 값 rad |
| `report/<이름>_limits.json` | 조인트별 MotorLimit · 클립 최소/최대 · 첫 프레임 (deg) |
| `report/<이름>_check.json` | 속도·가속 초과 구간 · MotorLimit 에 걸린 샘플 (deg) |

- 씬 50 fps 권장 · 1 프레임 = 20 ms = 파일 1행 · 다른 fps 면 경고 후 재샘플
- 속도·가속 한계(본 속성)의 **100% 를 넘는 곳이 하나라도 있으면 `<이름>.json` 을 쓰지 않음** (리포트·마커만 · 같은 폴더의 이전 `.json` 은 그대로 남음) · 80~100% 는 경고만 (2026-10-13)
  - PC 조인트 매핑의 최대 속도·가속도와 같은 값으로 두면 Blender 에서 통과한 파일은 PC 에서도 거부되지 않음 (PC 는 같은 20 ms 차분)
- 끝나면 창 · 조인트별 최대 % (속도 · 가속) · 100% 넘은 구간 (Blender 프레임)
- 초과 구간 · 타임라인 마커 `ANIM! ...` · Empty `AnimSpeedCheck` 의 `<본>_vel_pct` / `<본>_acc_pct` 곡선 (Graph Editor · 100 = 한계 · 80 부터 경고)
  - 마커는 색을 따로 못 줌 → **`ANIM! ERR` 마커만 선택 상태**(밝게)로 남김 (다른 마커 선택은 해제)
  - **문제 구간을 만든 본 애니메이션 키**(앞 키 ~ 뒤 키)의 키 종류를 바꿔 색 표시 · **Extreme = 빨강 (100% 초과) · Jitter = 분홍 (80~100%)**
    · 복사 본(Eye_Yaw_R ← Eye_Yaw_L)은 원본 키에 · 다시 검사하면 지난 표시는 일반 키로 되돌림 → **Extreme / Jitter 키 종류는 평소에 쓰지 말 것**
  - `AnimSpeedCheck` 의 `ANIM_issue` 채널 · 같은 키 종류 · 값 = 최대 % · % 곡선은 프레임마다 굽지 않고 필요한 점만 베지어 (오차 1%)
  - 색은 테마 · 이 PC 는 시작 스크립트가 Blender 켤 때 넣음 (Extreme 빨강 · Jitter 분홍 · 선택된 마커 빨강 · `THEME_COLORS = False` 로 끔)
- 검사하는 동안 리그 없는 컬렉션을 잠깐 빼서 계산 (3만 프레임 ~7 s) · 오브젝트 숨김·선택·컬렉션 설정은 그대로 되돌림
- Blender 켤 때 탭 자동 등록 (이 PC) · `%APPDATA%\Blender Foundation\Blender\5.2\scripts\startup\robot_anim_panel.py` 가 이 파일을 디스크에서 읽음
- .blend 안의 Text 는 디스크 파일의 **복사본** · 스크립트가 바뀌면 Text → Reload (Alt+R)

## 본 설정 (모터 하나 = 본 하나)

모터로 가는 본마다 포즈 본 커스텀 속성 (Bone Properties → Custom Properties).
`joint_name` 만 넣고 한 번 실행하면 나머지 칸이 툴팁과 함께 생긴다 (마우스 올리면 설명).

| 속성 | 예 | 뜻 |
|---|---|---|
| `joint_name` | `Neck_Pitch` · `1-1` | **필수** · 각 로봇 PC 웹 「조인트 매핑」의 조인트 이름과 완전히 같게 |
| `motor_axis` | `X` | **필수** · 본이 도는 로컬 축 X / Y / Z |
| `max_vel_deg_s` | `80` | 관절 최대 속도 deg/s · 0 = 검사 안 함 |
| `max_acc_deg_s2` | `1200` | 관절 최대 가속도 deg/s² · 0 = 검사 안 함 |

- 가동범위 · 본의 Limit Rotation 컨스트레인트 이름 `MotorLimit` (Owner Space LOCAL · Affect Transform)
- 관절 최대 속도 = 모터 최대 rpm × 6 ÷ 감속기어비 · 관절 최대 가속도 = 모터 가속도(deg/s²) ÷ 감속기어비
  - 감속기어비 = 감속기 + 추가 기어·링크까지 합친 전체 비
- 본 회전 = 실제 관절 움직임 · 감속기어비·부호·오프셋은 넣지 않음 (각 PC 조인트 매핑이 적용)
- 다른 본을 따라 도는 본 (Copy Rotation) 도 자기 `joint_name` 으로 같이 나감

### ID 정리

| 이름 | 무엇 | 누가 맞추나 |
|---|---|---|
| 조인트 이름 (`joint_name` · 코드상 `motion_id`) | 애니메이션 파일의 열 이름 | 애니메이터 (본 속성) |
| 모터 번호 (0부터) | PC 모터 설정 안의 순서 | 설치 (조인트 매핑이 조인트 → 모터 연결) |
| EtherCAT Alias | 드라이브 EEPROM 주소 | 설치 (모터 ↔ 실제 드라이브) |

## 단위

- 파일 값 rad · 헤더 `rotation_unit: "rad"` (2026-10-06 결정)
- 0 근처 · 1e-6 rad (0.00006°) 보다 작은 값은 정확히 0 으로 씀 · 값을 본 행렬에서 다시 계산해서 (Blender 행렬 float32) 키가 0 이어도 ~1e-7 rad 가 남기 때문 (2026-10-12)
- 본 속성 · 리포트 · Blender 안 검사 deg
- 스택은 헤더 `rotation_unit` 을 읽어 내부 단위로 바꿈 (`docs/수정_목록.md` 6-2) · rad·deg 파일 모두 재생 · 그 전 버전이 깔린 PC 에서는 rad 파일이 약 1/57 로 움직임

## 창 없이 실행

```
blender -b X.blend --python-expr "OUT_DIR=r'D:\out'; exec(open(r'scripts/blender/animation_export.py', encoding='utf-8').read())"
```

- 전역 · `OUT_DIR` 출력 폴더 · `EXPORT_NAME` 파일 이름 · `ARMATURE` 아마추어 오브젝트 이름 또는 이름 목록 (없으면 `joint_name` 본 있는 아마추어 전부)
- 아마추어 여러 개(로봇 여러 대 · 예 플로팅 4대) · 한 파일에 모두 · `joint_name` 은 전체에서 겹치면 안 됨 · 리포트·검사 곡선 이름은 「리그:본」
