"""로봇 팩 · 로봇마다 다른 값을 한 폴더(zip)로 · 형식 검사 단일 구현

미니 PC 1대 = 로봇 1대 · 플랫폼(스택)은 로봇을 모른다 · 축 구성·모터·감속기·
드라이브·환경·MuJoCo 모델은 팩 하나로 묶여 PC 전역 `robot_pack/` 에 놓인다.
웹 업로드 검사(브리지)와 sim 실행기(`scripts/sim`)가 **같은 검사**를 쓴다.

    pack.yaml       name, version, created
                    scene_glb: {animations: [floating_narration_all]}   # scene.glb 가 담은 애니메이션 (수정 목록 60)
    robot.yaml      axes: [{joint, motion_id, motor, reducer, ratio, range_deg, servo_bw_hz}]
                    drive: {profile_velocity_deg_s, profile_accel_deg_s2}   # 모터축 기준
                    env:   {settle_body, settle_s, torsion_k, torsion_c,
                            camera: {lookat, distance, azimuth, elevation}}
    catalog/        motors.yaml · reducers.yaml · 팩에서 쓰는 항목 사본 (팩 단독 실행)
    model.xml       MuJoCo 모델 (+ meshes/)
    robot.urdf      참고용 (선택)
    preview.yaml    미리보기 명령 (선택 · config/animation_preview.example.yaml 형식)
    scene.glb       웹 3D 「Blender 뷰」 장면 (선택 · glTF 2.0 바이너리 · 수정 목록 50)

각도는 칸 이름대로 deg 다 · 사람(터미널 세션)이 적는 계약이라 스택 안쪽이 rad 로
옮겨 간 뒤에도(수정 목록 6) 형식은 그대로 두고, 읽는 쪽이 이름을 보고 바꾼다 · 6-7.

순수 Python + PyYAML · rclpy 비의존 · 브리지(ROS Python)와 uv 실행기 양쪽에서 import.
모델 로드(MuJoCo)는 여기서 하지 않는다 · 실행기 `sim_run.py --check` 몫.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

__all__ = [
    'Axis',
    'SCENE_GLB_MAX_BYTES',
    'SCENE_GLB_NAME',
    'check_scene_glb',
    'scene_glb_path',
    'INSTALLED_NAME',
    'PACK_DIRNAME',
    'PackReport',
    'REQUIRED_FILES',
    'Robot',
    'current_fingerprint',
    'inspect_pack',
    'load_catalog',
    'load_robot',
    'pack_fingerprint',
    'pack_root',
    'read_installed',
    'read_pack_info',
    'validate_catalog',
    'validate_pack_dir',
]

#: PC 전역 팩 위치 · `<workspace>/robot_pack/` (PC 1대 = 로봇 1대 · 프로젝트별이 아니다)
PACK_DIRNAME = 'robot_pack'
REQUIRED_FILES = ('pack.yaml', 'robot.yaml', 'model.xml')
CATALOG_FILES = ('motors.yaml', 'reducers.yaml')
#: 설치 기록 · 팩 내용이 아니다 · 지문에서 뺀다
INSTALLED_NAME = '.installed.json'

#: 모터 종류별 필수 수치 · 새 종류는 여기에 한 줄
MOTOR_TYPE_FIELDS: Dict[str, Tuple[str, ...]] = {
    'ac_servo': ('rated_rpm', 'max_rpm', 'rated_torque_nm', 'peak_torque_nm', 'rotor_inertia_kgm2'),
    'dynamixel': ('max_rpm', 'stall_torque_nm'),
}
REDUCER_FIELDS = ('ratio', 't2n_nm', 't2b_nm', 'max_input_rpm')

_JOINT_NAME = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


@dataclass(frozen=True)
class Axis:
    joint: str
    motion_id: str
    motor: str
    reducer: Optional[str]
    ratio: float
    range_deg: Tuple[float, float]
    servo_bw_hz: float
    motor_spec: Dict[str, Any] = field(default_factory=dict)
    reducer_spec: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Robot:
    name: str
    version: str
    axes: Tuple[Axis, ...]
    profile_velocity_deg_s: float
    profile_accel_deg_s2: float
    settle_body: str
    settle_s: float
    torsion_k: float
    torsion_c: float
    camera: Dict[str, Any]
    model_path: Path
    pack_dir: Path


@dataclass
class PackReport:
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    info: Dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors


# --------------------------------------------------------------------------- #
# 읽기
# --------------------------------------------------------------------------- #

def _load_yaml(path: Path, errors: List[str]) -> Any:
    try:
        return yaml.safe_load(path.read_text(encoding='utf-8'))
    except OSError as exc:
        errors.append(f'{path.name} · 읽기 실패: {exc}')
    except yaml.YAMLError as exc:
        errors.append(f'{path.name} · YAML 오류: {exc}')
    return None


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _require_number(where: str, payload: Dict[str, Any], key: str, errors: List[str], *, positive=False, non_negative=False) -> Optional[float]:
    value = _number(payload.get(key))
    if value is None:
        errors.append(f'{where} · {key} · 숫자 필요')
        return None
    if positive and value <= 0:
        errors.append(f'{where} · {key} · 0보다 커야 함 ({value:g})')
        return None
    if non_negative and value < 0:
        errors.append(f'{where} · {key} · 0 이상이어야 함 ({value:g})')
        return None
    return value


def pack_root(workspace_root: Path) -> Path:
    return Path(workspace_root) / PACK_DIRNAME


def read_installed(pack_dir: Path) -> Dict[str, Any]:
    """설치 기록(.installed.json) · 없거나 깨졌으면 빈 dict."""
    try:
        payload = json.loads((Path(pack_dir) / INSTALLED_NAME).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def read_pack_info(pack_dir: Path) -> Dict[str, Any]:
    """pack.yaml 의 name·version·created · 없거나 틀리면 빈 dict."""
    try:
        payload = yaml.safe_load((Path(pack_dir) / 'pack.yaml').read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        key: str(payload[key])
        for key in ('name', 'version', 'created')
        if payload.get(key) is not None
    }


# --------------------------------------------------------------------------- #
# 카탈로그
# --------------------------------------------------------------------------- #

def validate_catalog(motors: Any, reducers: Any, where: str = 'catalog') -> List[str]:
    """모터·감속기 카탈로그 형식 · 스택 `catalog/` 와 팩 `catalog/` 공용."""
    errors: List[str] = []
    if not isinstance(motors, dict):
        errors.append(f'{where}/motors.yaml · 이름: {{...}} 형태의 표 필요')
        motors = {}
    if not isinstance(reducers, dict):
        errors.append(f'{where}/reducers.yaml · 이름: {{...}} 형태의 표 필요')
        reducers = {}
    for name, spec in motors.items():
        label = f'{where}/motors.yaml · {name}'
        if not isinstance(spec, dict):
            errors.append(f'{label} · 항목이 표가 아님')
            continue
        kind = spec.get('type')
        fields = MOTOR_TYPE_FIELDS.get(kind)
        if fields is None:
            errors.append(f'{label} · type 알 수 없음 ({kind!r}) · 허용: {", ".join(MOTOR_TYPE_FIELDS)}')
            continue
        for key in fields:
            _require_number(label, spec, key, errors, positive=True)
    for name, spec in reducers.items():
        label = f'{where}/reducers.yaml · {name}'
        if not isinstance(spec, dict):
            errors.append(f'{label} · 항목이 표가 아님')
            continue
        for key in REDUCER_FIELDS:
            _require_number(label, spec, key, errors, positive=True)
    return errors


def load_catalog(catalog_dir: Path) -> Tuple[Dict[str, Any], Dict[str, Any], List[str]]:
    """(motors, reducers, errors) · 파일이 없으면 오류."""
    errors: List[str] = []
    catalog_dir = Path(catalog_dir)
    loaded: List[Any] = []
    for name in CATALOG_FILES:
        path = catalog_dir / name
        if not path.is_file():
            errors.append(f'catalog/{name} · 파일 없음')
            loaded.append({})
            continue
        loaded.append(_load_yaml(path, errors) or {})
    motors, reducers = loaded
    errors += validate_catalog(motors, reducers)
    return (motors if isinstance(motors, dict) else {}), (reducers if isinstance(reducers, dict) else {}), errors


# --------------------------------------------------------------------------- #
# 팩 검사
# --------------------------------------------------------------------------- #

def _check_axes(axes: Any, motors: Dict[str, Any], reducers: Dict[str, Any], report: PackReport) -> None:
    errors = report.errors
    if not isinstance(axes, list) or not axes:
        errors.append('robot.yaml · axes · 축 목록 필요')
        return
    joints, ids = set(), set()
    for index, axis in enumerate(axes):
        where = f'robot.yaml · axes[{index}]'
        if not isinstance(axis, dict):
            errors.append(f'{where} · 항목이 표가 아님')
            continue
        joint = axis.get('joint')
        if not isinstance(joint, str) or not _JOINT_NAME.match(joint):
            errors.append(f'{where} · joint · 영문·숫자·_ 이름 필요 ({joint!r})')
        elif joint in joints:
            errors.append(f'{where} · joint 중복 ({joint})')
        else:
            joints.add(joint)
            where = f'robot.yaml · {joint}'
        motion_id = axis.get('motion_id')
        if not isinstance(motion_id, str) or not motion_id.strip():
            errors.append(f'{where} · motion_id · 문자열 필요 ({motion_id!r})')
        elif motion_id in ids:
            errors.append(f'{where} · motion_id 중복 ({motion_id})')
        else:
            ids.add(motion_id)
        motor = axis.get('motor')
        if motor not in motors:
            errors.append(f'{where} · motor · 팩 catalog/motors.yaml 에 없음 ({motor!r})')
        reducer = axis.get('reducer')
        if reducer is not None and reducer not in reducers:
            errors.append(f'{where} · reducer · 팩 catalog/reducers.yaml 에 없음 ({reducer!r})')
        ratio = _require_number(where, axis, 'ratio', errors, positive=True)
        if ratio is not None and reducer in reducers:
            catalog_ratio = _number(reducers[reducer].get('ratio'))
            if catalog_ratio is not None and abs(catalog_ratio - ratio) > 1e-9:
                report.warnings.append(
                    f'{where} · ratio {ratio:g} ≠ 카탈로그 {reducer} {catalog_ratio:g} · 팩 값 사용'
                )
        _require_number(where, axis, 'servo_bw_hz', errors, positive=True)
        span = axis.get('range_deg')
        if (
            not isinstance(span, list) or len(span) != 2
            or _number(span[0]) is None or _number(span[1]) is None
        ):
            errors.append(f'{where} · range_deg · [최소, 최대] 숫자 두 개 필요')
        elif float(span[0]) >= float(span[1]):
            errors.append(f'{where} · range_deg · 최소 < 최대 필요 ({span})')


def _check_env(env: Any, errors: List[str]) -> None:
    if not isinstance(env, dict):
        errors.append('robot.yaml · env · 표 필요')
        return
    body = env.get('settle_body')
    if not isinstance(body, str) or not body.strip():
        errors.append('robot.yaml · env · settle_body · 바디 이름 필요')
    _require_number('robot.yaml · env', env, 'settle_s', errors, non_negative=True)
    _require_number('robot.yaml · env', env, 'torsion_k', errors, non_negative=True)
    _require_number('robot.yaml · env', env, 'torsion_c', errors, non_negative=True)
    camera = env.get('camera')
    if not isinstance(camera, dict):
        errors.append('robot.yaml · env · camera · 표 필요')
        return
    lookat = camera.get('lookat')
    if not isinstance(lookat, list) or len(lookat) != 3 or any(_number(v) is None for v in lookat):
        errors.append('robot.yaml · env · camera · lookat · [x, y, z] 필요')
    _require_number('robot.yaml · env · camera', camera, 'distance', errors, positive=True)
    _require_number('robot.yaml · env · camera', camera, 'azimuth', errors)
    _require_number('robot.yaml · env · camera', camera, 'elevation', errors)


def inspect_pack(pack_dir: Path) -> PackReport:
    """팩 폴더 전체 검사 · 오류(교체 거부)와 경고(표시만)를 나눈다."""
    pack_dir = Path(pack_dir)
    report = PackReport()
    errors = report.errors
    if not pack_dir.is_dir():
        errors.append(f'팩 폴더 없음: {pack_dir}')
        return report
    for name in REQUIRED_FILES:
        if not (pack_dir / name).is_file():
            errors.append(f'{name} · 파일 없음')
    if errors:
        return report

    pack = _load_yaml(pack_dir / 'pack.yaml', errors)
    if isinstance(pack, dict):
        for key in ('name', 'version', 'created'):
            if pack.get(key) is None or not str(pack.get(key)).strip():
                errors.append(f'pack.yaml · {key} · 값 필요')
        report.info = read_pack_info(pack_dir)
    elif pack is not None:
        errors.append('pack.yaml · 표 필요')

    motors, reducers, catalog_errors = load_catalog(pack_dir / 'catalog')
    errors += catalog_errors

    robot = _load_yaml(pack_dir / 'robot.yaml', errors)
    if robot is None:
        return report
    if not isinstance(robot, dict):
        errors.append('robot.yaml · 표 필요')
        return report
    _check_axes(robot.get('axes'), motors, reducers, report)
    drive = robot.get('drive')
    if not isinstance(drive, dict):
        errors.append('robot.yaml · drive · 표 필요')
    else:
        _require_number('robot.yaml · drive', drive, 'profile_velocity_deg_s', errors, positive=True)
        _require_number('robot.yaml · drive', drive, 'profile_accel_deg_s2', errors, positive=True)
    _check_env(robot.get('env'), errors)

    preview = pack_dir / 'preview.yaml'
    if preview.is_file():
        payload = _load_yaml(preview, errors)
        if payload is not None and not isinstance(payload, dict):
            errors.append('preview.yaml · 표 필요')
    scene_glb = scene_glb_path(pack_dir)
    if scene_glb is not None:
        errors += check_scene_glb(scene_glb)
        if not scene_glb_animations(pack_dir):
            report.warnings.append(
                'pack.yaml · scene_glb.animations 없음 · Blender 뷰 꺼짐 '
                '(scene.glb 가 담은 애니메이션 이름을 적으면 그 애니메이션에서만 켜짐)'
            )
    return report


#: 선택 파일 · 웹 3D 「Blender 뷰」 장면 · Blender 가 작업 PC 에서 내보낸 glTF 2.0 바이너리 · 수정 목록 50
#:
#: 헤드 4대 + 애니메이션 + 매장 오브제를 월드 배치 그대로 · 같은 파일을 모든 PC 팩에 넣는다 ·
#: 없으면 웹 3D 는 MuJoCo 뷰만 · 팩 zip 상한(50 MB) 안에 다른 파일과 같이 들어가야 해서 45 MB 까지
SCENE_GLB_NAME = 'scene.glb'
SCENE_GLB_MAX_BYTES = 45 * 1024 * 1024
_GLB_MAGIC = b'glTF'


def scene_glb_path(pack_dir: Path) -> Optional[Path]:
    """팩에 Blender 뷰 장면이 있으면 그 경로 · 없으면 None (검사는 `inspect_pack`)"""
    path = Path(pack_dir) / SCENE_GLB_NAME
    return path if path.is_file() else None


def scene_glb_animations(pack_dir: Path) -> List[str]:
    """scene.glb 가 담은 애니메이션 이름 · `pack.yaml` `scene_glb: {animations: [...]}` · 수정 목록 60

    glb 의 클립 이름은 리그 이름(`FH_Rig_1` …)이라 어떤 애니메이션인지 알 수 없다 · 사람이 적는다 ·
    이름 = 애니메이션 파일 이름(확장자 뺌) · 안 적힌 옛 팩은 빈 목록 → 화면이 Blender 뷰를 끈다.
    """
    try:
        payload = yaml.safe_load((Path(pack_dir) / 'pack.yaml').read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError):
        return []
    scene = payload.get('scene_glb') if isinstance(payload, dict) else None
    names = scene.get('animations') if isinstance(scene, dict) else None
    if isinstance(names, str):
        names = [names]
    if not isinstance(names, list):
        return []
    return [str(name).strip() for name in names if str(name or '').strip()]


def check_scene_glb(path: Path) -> List[str]:
    """glTF 바이너리 머리말(12 바이트)과 크기만 본다 · 내용(메쉬·애니메이션)은 브라우저가 읽는다"""
    where = SCENE_GLB_NAME
    try:
        size = path.stat().st_size
        with open(path, 'rb') as handle:
            header = handle.read(12)
    except OSError as exc:
        return [f'{where} · 읽기 실패: {exc}']
    errors = []
    if size > SCENE_GLB_MAX_BYTES:
        errors.append(f'{where} · 크기 초과: {size / 1e6:.1f} MB > {SCENE_GLB_MAX_BYTES / 1e6:.0f} MB (감량해서 다시 내보내기)')
    if len(header) < 12 or header[:4] != _GLB_MAGIC:
        return errors + [f'{where} · glTF 바이너리(.glb)가 아닙니다 (Blender 내보내기 형식 glTF Binary)']
    version = int.from_bytes(header[4:8], 'little')
    length = int.from_bytes(header[8:12], 'little')
    if version != 2:
        errors.append(f'{where} · glTF 버전 {version} · 2 만 읽습니다')
    if length != size:
        errors.append(f'{where} · 파일이 잘렸습니다 (머리말 {length} 바이트 · 실제 {size} 바이트)')
    return errors


def validate_pack_dir(pack_dir: Path) -> List[str]:
    """오류 목록만 · 비면 통과."""
    return inspect_pack(pack_dir).errors


def load_robot(pack_dir: Path) -> Robot:
    """검사를 통과한 팩을 실행기용 값으로 · 오류면 ValueError (이유 전부)."""
    pack_dir = Path(pack_dir).resolve()
    report = inspect_pack(pack_dir)
    if report.errors:
        raise ValueError('로봇 팩 오류:\n  ' + '\n  '.join(report.errors))
    motors, reducers, _ = load_catalog(pack_dir / 'catalog')
    robot = yaml.safe_load((pack_dir / 'robot.yaml').read_text(encoding='utf-8'))
    axes = tuple(
        Axis(
            joint=axis['joint'],
            motion_id=axis['motion_id'],
            motor=axis['motor'],
            reducer=axis.get('reducer'),
            ratio=float(axis['ratio']),
            range_deg=(float(axis['range_deg'][0]), float(axis['range_deg'][1])),
            servo_bw_hz=float(axis['servo_bw_hz']),
            motor_spec=dict(motors[axis['motor']]),
            reducer_spec=dict(reducers.get(axis.get('reducer')) or {}),
        )
        for axis in robot['axes']
    )
    drive, env = robot['drive'], robot['env']
    info = report.info
    return Robot(
        name=info.get('name', ''),
        version=info.get('version', ''),
        axes=axes,
        profile_velocity_deg_s=float(drive['profile_velocity_deg_s']),
        profile_accel_deg_s2=float(drive['profile_accel_deg_s2']),
        settle_body=env['settle_body'],
        settle_s=float(env['settle_s']),
        torsion_k=float(env['torsion_k']),
        torsion_c=float(env['torsion_c']),
        camera=dict(env['camera']),
        model_path=pack_dir / 'model.xml',
        pack_dir=pack_dir,
    )


def pack_fingerprint(pack_dir: Path) -> str:
    """팩 내용 지문(sha256) · 버전을 안 올려도 내용이 바뀌면 달라진다."""
    pack_dir = Path(pack_dir)
    digest = hashlib.sha256()
    for path in sorted(p for p in pack_dir.rglob('*') if p.is_file()):
        relative = path.relative_to(pack_dir).as_posix()
        if relative == INSTALLED_NAME:
            continue
        digest.update(relative.encode('utf-8') + b'\0')
        digest.update(path.read_bytes())
        digest.update(b'\0')
    return digest.hexdigest()


#: 손으로 놓은 팩(설치 기록 없음)의 지문 · {팩 경로: (파일 서명, 지문)} · 수정 목록 5-4
#: 목록 요청마다 파일 수만큼 팩 전체(메쉬 포함)를 다시 읽던 것을 1회로 · 파일
#: 이름·크기·수정시각이 하나라도 바뀌면 다시 계산한다
_FINGERPRINT_CACHE: Dict[str, Tuple[Tuple[Tuple[str, int, int], ...], str]] = {}


def _pack_signature(pack_dir: Path) -> Tuple[Tuple[str, int, int], ...]:
    """팩 파일들의 (상대경로 · 크기 · mtime_ns) · 내용을 읽지 않는다."""
    rows = []
    for path in sorted(p for p in pack_dir.rglob('*') if p.is_file()):
        relative = path.relative_to(pack_dir).as_posix()
        if relative == INSTALLED_NAME:
            continue
        stat = path.stat()
        rows.append((relative, int(stat.st_size), int(stat.st_mtime_ns)))
    return tuple(rows)


def cached_pack_fingerprint(pack_dir: Path) -> str:
    """`pack_fingerprint` 와 같은 값 · 파일 서명이 같으면 다시 읽지 않는다."""
    pack_dir = Path(pack_dir)
    key = str(pack_dir.resolve())
    signature = _pack_signature(pack_dir)
    cached = _FINGERPRINT_CACHE.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1]
    digest = pack_fingerprint(pack_dir)
    _FINGERPRINT_CACHE[key] = (signature, digest)
    return digest


def current_fingerprint(pack_dir: Path) -> str:
    """지금 놓인 팩의 지문 · 설치 기록 우선 · 손으로 놓은 팩이면 계산(1회 · 기억) · 팩 없으면 ''."""
    pack_dir = Path(pack_dir)
    if not (pack_dir / 'robot.yaml').is_file():
        return ''
    recorded = str(read_installed(pack_dir).get('fingerprint') or '')
    return recorded or cached_pack_fingerprint(pack_dir)
