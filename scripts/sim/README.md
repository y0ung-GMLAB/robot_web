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
pack.yaml       name, version, created
robot.yaml      axes: [{joint, motion_id, motor, reducer, ratio, range_deg: [min, max], servo_bw_hz}]
                drive: {profile_velocity_deg_s, profile_accel_deg_s2}     # 모터축 기준
                env:   {settle_body, settle_s, torsion_k, torsion_c,
                        camera: {lookat: [x, y, z], distance, azimuth, elevation}}
catalog/        motors.yaml · reducers.yaml · 팩에서 쓰는 항목 사본 (팩 단독 실행)
model.xml       MuJoCo 모델 + meshes/
robot.urdf      참고용 (선택)
preview.yaml    precompute/preview 명령 (선택 · config/animation_preview.example.yaml 형식)
```

- `axes` 순서 = 실행기 축 순서 · `joint` = model.xml joint 이름 · actuator 는 `act_<joint>`
- `motion_id` · 애니메이션 파일 id 와 **완전 일치** · 파일에 없으면 0° 유지 + 경고
- `motor` · `reducer` · 팩 `catalog/` 의 항목 이름 · 감속기 없는 축은 `reducer: null`
- `ratio` ≠ 카탈로그 감속비 · 경고만 (팩 값 사용)
- `settle_body` · 정착·흔들림·비틀림 측정 바디 · 그 위에 free joint 가 없으면 정착 감쇠 생략
- preview.yaml 치환 · `{stack}` 스택 루트 · `{pack}` 팩 폴더 · `{motion_path}` `{motion_stem}` `{result}` `{fps}`
- preview.yaml `cwd` 생략 · 팩 폴더

## 웹 업로드

시스템 정보 → 로봇 팩 · zip 놓기 → 서버 검사 → 통과 시 교체

- 위치 · `<workspace>/robot_pack/` (PC 전역) · 이전 팩 1개 `robot_pack.prev/`
- 검사 · zip 50 MB · 풀린 합계 200 MB · 파일 2000개 · `..`/절대경로/링크/암호 거부 · 형식 · `sim_run.py --check`
- 최상위 폴더 하나로 감싼 zip 허용 (그 폴더가 팩 루트)
- 팩 교체 · 기존 `.sim.npz` 결과 「다시 계산 필요」 (`.sim.meta.json` 의 팩 지문 비교)
- 모터 설정 · 모션축 설정 · 변경 없음 · 「모션축 설정과 비교」는 표시만
