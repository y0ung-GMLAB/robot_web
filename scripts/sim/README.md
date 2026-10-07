# 공용 sim 실행기 · 로봇 팩

로봇 무관 MuJoCo 실행기 · 로봇 값은 전부 **로봇 팩**(`robot.yaml`)에서 읽음.

- `sim_run.py` · 계산 · CSV + npz + 요약 출력
- `replay_run.py` · npz 재생 (실시간 · 키 조작)
- `view_run.py` · 계산 없이 바로 보기 (물리 · kinematic)
- `sim_core.py` · 공용 드라이브 에뮬(pp/interp) · 부하 관성 PID · 정착 · 비틀림
- 형식 검사 · `src/motion_common/motion_common/robot_pack.py` (웹 업로드 검사와 공용)
- 카탈로그 · `catalog/motors.yaml` · `catalog/reducers.yaml`

## 실행 (uv · 시스템 pip 설치 금지)

```
uv run --no-project --with mujoco --with numpy --with pyyaml python scripts/sim/sim_run.py PACK_DIR MOTION.json [OUT.csv]
uv run --no-project --with mujoco --with numpy --with pyyaml python scripts/sim/sim_run.py --check PACK_DIR
uv run --no-project --with mujoco --with numpy --with pyyaml python scripts/sim/replay_run.py RUN.npz [FPS] [--pack PACK_DIR]
uv run --no-project --with mujoco --with numpy --with pyyaml python scripts/sim/view_run.py PACK_DIR MOTION.json [interp|pp] [FPS] [kinematic]
```

- OUT 생략 · `<애니메이션 .json 뺀 경로>.sim.csv` · npz 는 csv 옆
- npz 키 · `qpos t twist n_frames model motion ref`
- 환경변수 (팩 값보다 우선) · `FH_REF`(pp|interp) · `FH_VMAX` · `FH_AMAX` · `FH_BASE_IZZ` · `FH_TORSION_K` · `FH_TORSION_C` · `FH_REC_HZ`
- timestep · 팩 `model.xml` 의 `<option timestep>`

## 로봇 팩 형식 (터미널 세션과 공유하는 계약)

```
pack.yaml       name, version, created · scene.glb 가 있으면 scene_glb: {animations: [애니메이션 파일 이름(확장자 뺌)]}
robot.yaml      axes: [{joint, motion_id, motor, reducer, ratio, range_deg: [min, max], servo_bw_hz}]
                drive: {profile_velocity_deg_s, profile_accel_deg_s2}     # 모터축 기준
                env:   {settle_body, settle_s, torsion_k, torsion_c,
                        camera: {lookat: [x, y, z], distance, azimuth, elevation}}
catalog/        motors.yaml · reducers.yaml · 팩에서 쓰는 항목 사본 (팩 단독 실행)
model.xml       MuJoCo 모델 + meshes/
robot.urdf      참고용 (선택)
preview.yaml    precompute/preview 명령 (선택 · config/animation_preview.example.yaml 형식)
scene.glb       웹 3D 「Blender 뷰」 장면 (선택 · glTF 2.0 바이너리 · 45 MB 까지 · 수정 목록 50)
```

- `axes` 순서 = 실행기 축 순서 · `joint` = model.xml joint 이름 · actuator 는 `act_<joint>`
- 각도 단위 · 팩은 사람이 적는 파일이라 **칸 이름에 단위를 붙인 deg** 그대로다(`range_deg` ·
  `profile_velocity_deg_s` · `profile_accel_deg_s2` · `camera.azimuth/elevation`) · 스택 안쪽은 rad
  (수정 목록 6) 이지만 팩 형식은 바꾸지 않는다 · 읽는 쪽이 이름대로 바꾼다(실행기 → MuJoCo rad ·
  조인트 매핑 비교 → deg) · 환경변수 `FH_VMAX`·`FH_AMAX` 도 모터축 deg/s · deg/s² · 6-7 (2026-10-06)
- `motion_id` · 애니메이션 파일 id 와 **완전 일치** · 파일에 없으면 0° 유지 + 경고
- `motor` · `reducer` · 팩 `catalog/` 의 항목 이름 · 감속기 없는 축은 `reducer: null`
- `ratio` ≠ 카탈로그 감속비 · 경고만 (팩 값 사용)
- `settle_body` · 정착·흔들림·비틀림 측정 바디 · 그 위에 free joint 가 없으면 정착 감쇠 생략
- preview.yaml 치환 · `{stack}` 스택 루트 · `{pack}` 팩 폴더 · `{motion_path}` `{motion_stem}` `{result}` `{fps}`
- preview.yaml `cwd` 생략 · 팩 폴더
- scene.glb · Blender 가 작업 PC 에서 glTF Binary 로 내보낸 장면(헤드 4대 + 애니메이션 + 매장 오브제 · 월드 배치 그대로) ·
  같은 파일을 모든 PC 팩에 넣는다 · 있으면 웹 3D 에 「Blender 뷰」 체크가 생기고 실제 재생 시각을 따라 애니메이션을 그린다 ·
  담기지 않는 것 · 오디오 · Blender 화면 설정 · 절차적 재질(굽거나 단순색으로) · Area 라이트 · HDRI(조명은 웹에서) ·
  검사 · 머리말(glTF 2) · 길이 · 크기만 · 좌표는 glTF 기본(Y-up · Blender 내보내기 기본값 +Y Up)
- scene.glb 를 넣으면 `pack.yaml` 에 그 장면이 담은 애니메이션 이름을 적는다 · 예) `scene_glb: {animations: [floating_narration_all]}` ·
  웹은 지금 보는 애니메이션이 이 목록에 있을 때만 「Blender 뷰」 를 켠다 · 안 적으면 Blender 뷰가 꺼지고 팩 검사가 경고한다 · 수정 목록 60

## 웹 업로드

시스템 정보 → 로봇 팩 · 팩 폴더 또는 zip 놓기 (「폴더 고르기」 가능) → 서버 검사 → 통과 시 교체

- 폴더는 화면이 zip(무압축)으로 묶어 같은 길로 보냄 · 숨김 파일(.git 등) 제외

- 위치 · `<workspace>/robot_pack/` (PC 전역) · 이전 팩 1개 `robot_pack.prev/`
- 검사 · zip 50 MB · 풀린 합계 200 MB · 파일 2000개 · `..`/절대경로/링크/암호 거부 · 형식 · `sim_run.py --check`
- 최상위 폴더 하나로 감싼 zip 허용 (그 폴더가 팩 루트)
- 팩 교체 · 기존 `.sim.npz` 결과 「다시 계산 필요」 (`.sim.meta.json` 의 팩 지문 비교)
- 모터 설정 · 모션축 설정 · 변경 없음 · 「모션축 설정과 비교」는 표시만
