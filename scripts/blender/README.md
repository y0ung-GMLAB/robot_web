# Blender 애니메이션 내보내기

`animation_export.py` · Blender 본 애니메이션 → 애니메이션 파일(.json) · 로봇 무관.
터미널(Blender) 세션 소유 · 파일 형식 기준 = `src/motion_common/motion_common/motion_table.py`.

## 쓰는 법

1. .blend 를 연다 (애니메이션 하나 = .blend 하나 · 파일 이름 = 애니메이션 이름)
2. Text Editor → Open → `animation_export.py` → Run Script
3. 폴더 고르기 창 → 출력 폴더 선택 (마지막 폴더 기억 · 씬 속성 `anim_export_dir`)

출력

| 파일 | 내용 |
|---|---|
| `<이름>.json` | 애니메이션 파일 · 웹 업로드용 · 값 rad |
| `report/<이름>_limits.json` | 조인트별 MotorLimit · 클립 최소/최대 · 첫 프레임 (deg) |
| `report/<이름>_check.json` | 속도·가속 초과 구간 · MotorLimit 에 걸린 샘플 (deg) |

- 씬 50 fps 권장 · 1 프레임 = 20 ms = 파일 1행 · 다른 fps 면 경고 후 재샘플
- 초과 구간 · 타임라인 마커 `ANIM! ...` · Empty `AnimSpeedCheck` 의 `<본>_vel_pct` / `<본>_acc_pct` 곡선 (Graph Editor · 100 = 한계 · 80 부터 경고)
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
- 본 속성 · 리포트 · Blender 안 검사 deg
- 스택 rad 전환 (`docs/수정_목록.md` 6) 전에는 스택이 값을 deg 로 읽음 → 그 전에 로봇 PC 에 올리지 말 것

## 창 없이 실행

```
blender -b X.blend --python-expr "OUT_DIR=r'D:\out'; exec(open(r'scripts/blender/animation_export.py', encoding='utf-8').read())"
```

- 전역 · `OUT_DIR` 출력 폴더 · `EXPORT_NAME` 파일 이름 · `ARMATURE` 아마추어 오브젝트 이름 (`joint_name` 본 있는 아마추어가 여러 개일 때)
