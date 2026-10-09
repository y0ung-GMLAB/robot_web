"""애니메이션 MuJoCo(시뮬) 미리보기 · 계산과 재생을 현장 명령에 맡긴다 · P7

플랫폼은 로봇도 시뮬레이터도 모른다 · 로봇마다(플로팅 헤드, 다음 로봇…)
모델·스크립트가 다르므로, 여기는 **명령 틀과 결과 경로**만 안다 · 채우는
것은 각 PC 의 `config/animation_preview.yaml` 이다 (모터 불문 원칙과 같다).

두 단계다 · 뷰어는 **계산이 끝난 것만** 튼다:

    계산(precompute)   무거운 물리 시뮬 · 업로드되면 한 번 · 결과 파일을 남긴다
    재생(preview)      결과 파일을 그대로 튼다 · 가볍다 · 모터 재생과 동시 실행 가능

설정 (`config/animation_preview.example.yaml` 참고):

    precompute:
      command: [...]            # {motion_path} {motion_stem} 치환
      result: '{motion_stem}.sim.npz'   # 이 파일이 생기면 「계산 끝」
    preview:
      command: [...]            # (선택 · 서버는 쓰지 않음 · 개발 PC 참고용)
    cwd: ...                    # 명령 실행 폴더

`precompute` 가 없고 `preview`(또는 옛 `command`)만 있으면 계산 결과가 없는
구성(direct) · 웹 3D 는 그릴 것이 없다 · 상태만 알린다.

**로봇 팩 우선** · `robot_pack/preview.yaml` 이 있으면 그것을, 없으면
`config/animation_preview.yaml` 을 쓴다 · 치환 `{stack}` = 스택(워크스페이스)
루트 · `{pack}` = 팩 폴더 · 팩 쪽 설정의 cwd 기본값은 팩 폴더.

계산이 끝나면 결과 옆 `<결과>.meta.json` 에 그때의 팩(이름·버전·지문)을
남긴다 · 지금 팩과 지문이 다르면 `stale`(다시 계산 필요) · 보기는 허용.

계산은 끝났는지(결과 파일 존재)와 도는 중인지를 기억한다 · 계산의
stdout·stderr 는 `log/animation_preview/<애니메이션>.precompute.log` 에 남긴다.

**네이티브 뷰어 창은 없앴다**(수정 목록 7 · 2026-10-04) · 서버 PC 모니터에만
뜨는 창은 슬레이브·원격에서 보이지 않는다 · 보기는 브라우저가 한다
(`sim_scene.py` · `static/js/sim3d.js`) · `preview.command` 는 개발 PC 에서
`scripts/sim/replay_run.py` 를 손으로 돌릴 때 참고용으로만 남는다(서버는 쓰지 않는다).
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import shutil
import time
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from motion_common import robot_pack
from motion_common.store import atomic_write_json

CONFIG_NAME = 'animation_preview.yaml'
PACK_CONFIG_NAME = 'preview.yaml'
NOT_CONFIGURED_MESSAGE = (
    '미리보기 명령이 설정되지 않았습니다 · '
    '로봇 팩(preview.yaml)을 올리거나 config/animation_preview.yaml 을 만드세요 '
    '(본보기: config/animation_preview.example.yaml)'
)

#: 도는 계산들 · {결과 경로: Popen} · 끝난 것은 보일 때 거둔다
_RUNNING: Dict[str, subprocess.Popen] = {}
#: 마지막으로 끝난 계산의 종료 코드 · 실패를 「미계산」과 구별해 말한다
_LAST_RC: Dict[str, int] = {}
#: 도는 계산이 시작될 때의 팩 · 성공으로 끝나야 meta 로 남긴다
_PENDING_META: Dict[str, Dict[str, Any]] = {}
_LOCK = threading.Lock()
#: 계산 출력 기록 폴더 (워크스페이스 기준 · `log/` 는 커밋하지 않는다)
LOG_DIR_NAME = 'animation_preview'


def preview_config(workspace_root: Path) -> Optional[Dict[str, Any]]:
    """설정을 읽는다 · 팩 preview.yaml 우선 · 없거나 모양이 틀리면 None.

    돌려주는 dict 에 `_stack` · `_pack` (치환 값) · `_source` (pack|config) 를 싣는다.
    """
    workspace_root = Path(workspace_root)
    pack_dir = robot_pack.pack_root(workspace_root)
    pack_path = pack_dir / PACK_CONFIG_NAME
    source = 'pack' if pack_path.is_file() else 'config'
    path = pack_path if source == 'pack' else workspace_root / 'config' / CONFIG_NAME
    payload = _read_config(path)
    if payload is None:
        return None
    payload['_stack'] = str(workspace_root)
    payload['_pack'] = str(pack_dir)
    payload['_source'] = source
    if source == 'pack' and not payload.get('cwd'):
        payload['cwd'] = str(pack_dir)
    return payload


def _read_config(path: Path) -> Optional[Dict[str, Any]]:
    try:
        payload = yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError, yaml.YAMLError):
        return None
    if not isinstance(payload, dict):
        return None
    payload = dict(payload)
    preview = payload.get('preview')
    if not isinstance(preview, dict) and _valid_command(payload.get('command')):
        # 옛 모양 · 최상위 command 하나 = 계산 없는 구성(direct)
        payload['preview'] = {'command': payload['command']}
        preview = payload['preview']
    if isinstance(preview, dict) and not _valid_command(preview.get('command')):
        return None
    precompute = payload.get('precompute')
    if precompute is not None:
        if not isinstance(precompute, dict) or not _valid_command(precompute.get('command')):
            return None
        if not str(precompute.get('result') or '').strip():
            return None
    # 계산(precompute)도 참고용 preview 도 없으면 설정이 아니다
    if precompute is None and not isinstance(preview, dict):
        return None
    return payload


def _valid_command(command: Any) -> bool:
    return (
        isinstance(command, list)
        and bool(command)
        and all(isinstance(part, (str, int, float)) for part in command)
    )


def _fill(
    parts: List[Any], motion_path: Path, *,
    result: str = '', fps: Any = '', config: Optional[Dict[str, Any]] = None,
) -> List[str]:
    stem = str(motion_path)
    if stem.lower().endswith('.json'):
        stem = stem[: -len('.json')]
    config = config or {}
    return [
        str(part)
        .replace('{motion_path}', str(motion_path))
        .replace('{motion_stem}', stem)
        .replace('{result}', result)
        .replace('{fps}', str(fps))
        .replace('{stack}', str(config.get('_stack', '')))
        .replace('{pack}', str(config.get('_pack', '')))
        for part in parts
    ]


def result_path_for(config: Dict[str, Any], motion_path: Path) -> Optional[Path]:
    precompute = config.get('precompute')
    if not isinstance(precompute, dict):
        return None
    [template] = _fill([precompute['result']], Path(motion_path), config=config)
    return Path(template)


def meta_path_for(result: Path) -> Path:
    """`x.sim.npz` → `x.sim.meta.json` · 계산 당시 팩 기록."""
    return Path(result).with_suffix('.meta.json')


def pending_path_for(result: Path) -> Path:
    """`x.sim.npz` → `x.sim.pending.json` · 계산을 **시작할 때** 쓴 팩 기록 · 수정 목록 54

    팩 기록(`meta`)은 브리지가 끝난 계산을 거둘 때(`_reap`)만 썼다 · 긴 계산(9분 나레이션) 중에
    브리지가 다시 뜨면 거둘 사람이 없어 기록이 안 남고 결과가 영영 「다시 계산 필요」 였다 ·
    시작할 때 남겨 두고, 결과 파일이 그보다 새것이면 그 계산이 끝낸 것으로 본다.
    """
    return Path(result).with_suffix('.pending.json')


def _pack_stamp(workspace_root: Path) -> Dict[str, Any]:
    pack_dir = robot_pack.pack_root(workspace_root)
    info = robot_pack.read_pack_info(pack_dir)
    return {
        'name': info.get('name', ''),
        'version': info.get('version', ''),
        'fingerprint': robot_pack.current_fingerprint(pack_dir),
    }


def log_path_for(workspace_root: Path, motion_path: Path, kind: str) -> Path:
    """계산(precompute)·뷰어(preview) 출력 기록 파일 경로."""
    return Path(workspace_root) / 'log' / LOG_DIR_NAME / f'{Path(motion_path).stem}.{kind}.log'


def _open_log(workspace_root: Path, motion_path: Path, kind: str):
    """출력 기록 파일을 연다 · 못 열면 DEVNULL (기록 실패가 실행을 막지는 않는다).

    매 실행마다 새로 쓴다 · 마지막 실행의 사유만 남기면 된다.
    """
    path = log_path_for(workspace_root, motion_path, kind)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        return open(path, 'wb')
    except OSError:
        return subprocess.DEVNULL


def _close_log(handle: Any) -> None:
    if handle is not subprocess.DEVNULL:
        try:
            handle.close()   # 자식이 fd 를 물려받았다 · 부모 쪽만 닫는다
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 계산을 웹 서비스 밖에서 · 수정 목록 93-86 (실물 2026-10-09 · 실물 확인 대기 86)
# --------------------------------------------------------------------------- #
#
# 계산은 웹 서비스(motion-control)의 자식이었다 · 서비스를 다시 띄우면(설정 저장 · 업데이트 ·
# 시간대) 9분 나레이션 계산이 같은 순간 같이 죽었다 · systemd 사용자 작업으로 따로 띄워
# 서비스가 다시 떠도 계속 돈다 · 끝나면 종료 코드를 파일에 남긴다 · 다시 뜬 브리지는
# 시작 기록(pending)에 적힌 작업 이름으로 「아직 도는지」 를 묻고 다시 붙는다.

#: 「도는가」 를 systemctl 에 물은 결과를 이만큼 쓴다 · 목록이 파일마다 묻는다
_ACTIVE_CACHE_SEC = 2.0
_ACTIVE_CACHE: Dict[str, Any] = {}


def rc_path_for(result: Path) -> Path:
    """`x.sim.npz` → `x.sim.rc` · 따로 띄운 계산의 종료 코드"""
    return Path(result).with_suffix('.rc')


def job_unit_for(result: Path) -> str:
    digest = hashlib.sha1(str(result).encode('utf-8')).hexdigest()[:12]
    return f'robot-web-sim-{digest}'


def detach_available() -> bool:
    """systemd 사용자 세션이 있는 리눅스 · 아니면(개발 PC · 시험) 예전처럼 자식으로"""
    return bool(shutil.which('systemd-run') and os.environ.get('XDG_RUNTIME_DIR'))


def _unit_active(unit: str, run=subprocess.run) -> bool:
    now = time.monotonic()
    cached = _ACTIVE_CACHE.get(unit)
    if cached and now - cached[0] < _ACTIVE_CACHE_SEC:
        return cached[1]
    try:
        result = run(['systemctl', '--user', 'is-active', '--quiet', unit],
                     capture_output=True, text=True, timeout=5)
        active = getattr(result, 'returncode', 1) == 0
    except (OSError, subprocess.SubprocessError):
        active = False
    _ACTIVE_CACHE[unit] = (now, active)
    return active


class DetachedJob:
    """Popen 처럼 `poll()` 만 · 종료 코드 파일이 있으면 그 값 · 작업이 돌면 None · 둘 다 아니면 1"""

    def __init__(self, unit: str, rc_path: Path, *, run=subprocess.run) -> None:
        self.unit = unit
        self.rc_path = Path(rc_path)
        self._run = run

    def poll(self) -> Optional[int]:
        try:
            text = self.rc_path.read_text(encoding='utf-8').strip()
        except OSError:
            text = ''
        if text:
            try:
                return int(text)
            except ValueError:
                return 1
        if _unit_active(self.unit, self._run):
            return None
        # 작업이 사라졌는데 코드가 없다 · 막 끝나 파일을 쓰는 중일 수 있어 한 번 더 본다
        try:
            text = self.rc_path.read_text(encoding='utf-8').strip()
            return int(text) if text else 1
        except (OSError, ValueError):
            return 1


def spawn_detached(args: List[str], *, cwd: str, log_path: Path, result: Path,
                   run=subprocess.run) -> DetachedJob:
    unit = job_unit_for(result)
    rc_path = rc_path_for(result)
    rc_path.unlink(missing_ok=True)
    inner = (
        f'{" ".join(shlex.quote(str(a)) for a in args)} > {shlex.quote(str(log_path))} 2>&1; '
        f'echo $? > {shlex.quote(str(rc_path))}'
    )
    command = [
        'systemd-run', '--user', '--unit', unit, '--collect', '--quiet',
        f'--working-directory={cwd}', '/bin/bash', '-c', inner,
    ]
    completed = run(command, capture_output=True, text=True, timeout=15)
    if getattr(completed, 'returncode', 1) != 0:
        raise OSError(str(getattr(completed, 'stderr', '') or '').strip() or 'systemd-run 실패')
    _ACTIVE_CACHE.pop(unit, None)
    return DetachedJob(unit, rc_path, run=run)


def _adopt_detached(result: Path, *, run=subprocess.run) -> None:
    """브리지가 다시 떴다 · 시작 기록에 적힌 작업을 다시 붙든다 (도는 중이면 computing · 끝났으면 거둠)"""
    key = str(result)
    with _LOCK:
        if key in _RUNNING or key in _LAST_RC:
            return
    try:
        payload = json.loads(pending_path_for(result).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return
    unit = str(payload.get('unit') or '') if isinstance(payload, dict) else ''
    if not unit:
        return
    with _LOCK:
        _RUNNING.setdefault(key, DetachedJob(unit, rc_path_for(result), run=run))
        stamp = payload.get('pack')
        if isinstance(stamp, dict):
            _PENDING_META.setdefault(key, stamp)


def _reap() -> None:
    finished = []
    with _LOCK:
        for key in list(_RUNNING):
            code = _RUNNING[key].poll()
            if code is not None:
                _LAST_RC[key] = code
                del _RUNNING[key]
                finished.append((key, code, _PENDING_META.pop(key, None)))
    for key, code, meta in finished:
        if code == 0 and meta is not None:
            try:
                atomic_write_json(meta_path_for(Path(key)), {'pack': meta})
                pending_path_for(Path(key)).unlink(missing_ok=True)
            except OSError:
                pass  # 기록 실패 = 팩 정보 없음 = stale 로 보인다 · 안전한 쪽


def _pending_stamp(result: Path) -> Dict[str, Any]:
    """시작 때 쓴 기록 · 없거나 틀리면 빈 dict"""
    try:
        payload = json.loads(pending_path_for(result).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}
    stamp = payload.get('pack') if isinstance(payload, dict) else None
    return stamp if isinstance(stamp, dict) else {}


def _finished_after_pending(result: Path) -> Optional[bool]:
    """시작 기록이 있으면 · 결과 파일이 그 뒤에 써졌나 · 기록이 없으면 None"""
    pending = pending_path_for(result)
    try:
        started = pending.stat().st_mtime
    except OSError:
        return None
    try:
        return result.stat().st_mtime >= started
    except OSError:
        return False


def _stale_reason(workspace_root: Path, result: Path) -> str:
    """결과가 지금 팩과 다른 팩으로 계산됐으면 이유 · 같거나 팩이 없으면 ''."""
    pack_dir = robot_pack.pack_root(workspace_root)
    current = robot_pack.current_fingerprint(pack_dir)
    if not current:
        return ''
    try:
        meta = json.loads(meta_path_for(result).read_text(encoding='utf-8'))
        stamp = meta.get('pack') or {}
    except (OSError, ValueError, AttributeError):
        stamp = {}
    if (not isinstance(stamp, dict) or not stamp.get('fingerprint')) and _finished_after_pending(result):
        # 브리지가 다시 떠서 못 거둔 계산 · 시작 기록을 결과 기록으로 올린다 · 수정 목록 54
        stamp = _pending_stamp(result)
        if stamp.get('fingerprint'):
            try:
                atomic_write_json(meta_path_for(result), {'pack': stamp})
                pending_path_for(result).unlink(missing_ok=True)
            except OSError:
                pass
    if not isinstance(stamp, dict) or not stamp.get('fingerprint'):
        return '로봇 팩 기록 없는 계산 결과 · 다시 계산 필요'
    if stamp['fingerprint'] == current:
        return ''
    label = ' '.join(str(stamp.get(k) or '') for k in ('name', 'version')).strip() or '이전 팩'
    return f'로봇 팩 변경 · 다시 계산 필요 (계산 당시: {label})'


def preview_state(workspace_root: Path, motion_path: Path) -> Dict[str, Any]:
    """이 애니메이션의 MuJoCo 상태 · 화면 배지와 버튼이 이대로 그린다.

        unavailable  설정 없음
        direct       계산 없이 바로 트는 구성
        computing    계산 도는 중 (그레이)
        ready        계산 끝 · 같이 보기 가능
        stale        계산 끝 · 그 뒤 로봇 팩이 바뀜 · 다시 계산 필요 (보기는 허용)
        failed       마지막 계산이 실패함
        missing      아직 계산 안 함
    """
    config = preview_config(Path(workspace_root))
    if config is None:
        return {'state': 'unavailable', 'message': NOT_CONFIGURED_MESSAGE}
    result = result_path_for(config, Path(motion_path))
    if result is None:
        return {'state': 'direct'}
    _adopt_detached(result)
    _reap()
    key = str(result)
    with _LOCK:
        if key in _RUNNING:
            return {'state': 'computing'}
    with _LOCK:
        last_rc = _LAST_RC.get(key)
    has_result = result.is_file()
    log_name = log_path_for(Path(workspace_root), Path(motion_path), 'precompute').name
    # 실패를 먼저 본다 · 옛 결과가 있어도 마지막 계산이 실패했으면 「계산 실패」 · 보기는 옛 결과로 허용 · 수정 목록 54
    if last_rc not in (None, 0):
        return {
            'state': 'failed', 'has_result': has_result,
            'message': f'마지막 계산이 실패했습니다 (코드 {last_rc}) · 기록 {log_name}'
            + (' · 옛 결과 있음' if has_result else ''),
        }
    if last_rc is None and _finished_after_pending(result) is False:
        # 시작 기록보다 새 결과가 없고 도는 계산도 없다 · 브리지가 다시 뜨며 중간에 끊긴 계산
        return {
            'state': 'failed', 'has_result': has_result,
            'message': f'마지막 계산이 끝까지 가지 못했습니다(실패 또는 중간에 멈춤) · 기록 {log_name}'
            + (' · 옛 결과 있음' if has_result else ''),
        }
    if has_result:
        reason = _stale_reason(Path(workspace_root), result)
        if reason:
            return {'state': 'stale', 'message': reason}
        return {'state': 'ready'}
    return {'state': 'missing'}


def annotate_files(workspace_root: Path, files_dir: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    """파일 목록에 MuJoCo 상태를 싣는다 · 설정 없으면 손대지 않는다.

    상세 응답(`file` + `files`)도 같은 길로 싣는다 · 화면이 상세 응답의
    `files` 로 목록을 덮어쓰므로, 빠지면 파일을 고르는 순간 「MuJoCo 준비됨」이
    꺼지고 같이 보기 체크가 풀린다.
    """
    config = preview_config(Path(workspace_root))
    if config is None:
        return payload
    files = payload.get('files')
    entries = list(files) if isinstance(files, list) else []
    detail = payload.get('file')
    if isinstance(detail, dict):
        entries.append(detail)
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get('id'):
            continue
        entry['preview'] = preview_state(
            workspace_root, Path(files_dir) / str(entry['id']),
        )
    return payload


def launch_precompute(
    workspace_root: Path,
    motion_path: Path,
    *,
    spawn=None,
    detach: Optional[bool] = None,
    run=subprocess.run,
) -> Dict[str, Any]:
    """무거운 계산을 시작한다 · 이미 돌고 있으면 그대로 둔다.

    리눅스(systemd 사용자 세션)면 웹 서비스 밖 작업으로 띄운다(93-86) · `spawn` 을 주면(시험)
    예전처럼 자식으로.
    """
    if detach is None:
        detach = spawn is None and detach_available()
    if spawn is None:
        spawn = subprocess.Popen
    config = preview_config(Path(workspace_root))
    if config is None:
        return {'success': False, 'message': NOT_CONFIGURED_MESSAGE}
    result = result_path_for(config, Path(motion_path))
    if result is None:
        return {'success': True, 'message': '계산이 필요 없는 구성입니다 · 바로 재생됩니다'}
    motion_path = Path(motion_path)
    if not motion_path.is_file():
        return {'success': False, 'message': f'애니메이션 파일이 없습니다: {motion_path.name}'}
    _adopt_detached(result, run=run)
    _reap()
    key = str(result)
    with _LOCK:
        if key in _RUNNING:
            return {'success': True, 'message': f'이미 계산 중입니다: {motion_path.name}'}
    args = _fill(config['precompute']['command'], motion_path, result=key, config=config)
    cwd = str(config.get('cwd') or workspace_root)
    stamp = _pack_stamp(Path(workspace_root))
    unit = ''
    if detach:
        log_path = log_path_for(Path(workspace_root), motion_path, 'precompute')
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            handle = spawn_detached(args, cwd=cwd, log_path=log_path, result=result, run=run)
        except (OSError, subprocess.SubprocessError) as exc:
            return {'success': False, 'message': f'계산 시작 실패: {exc}'}
        unit = handle.unit
    else:
        log = _open_log(workspace_root, motion_path, 'precompute')
        try:
            handle = spawn(args, cwd=cwd, stdout=log, stderr=log, shell=False)
        except OSError as exc:
            _close_log(log)
            return {'success': False, 'message': f'계산 시작 실패: {exc}'}
        _close_log(log)
    with _LOCK:
        _RUNNING[key] = handle
        _LAST_RC.pop(key, None)
        _PENDING_META[key] = stamp
    try:
        atomic_write_json(pending_path_for(result), {'pack': stamp, 'started_at': time.time(), 'unit': unit})
    except OSError:
        pass  # 없으면 옛 동작(브리지가 거둘 때만 기록)
    return {
        'success': True,
        'message': f'MuJoCo 계산 시작: {motion_path.name} · 끝나면 같이 보기가 켜집니다',
    }
