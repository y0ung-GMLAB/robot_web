"""애니 변환본 · 등록 때 한 번 변환해 디스크에 · 준비 검사 · 그룹 준비 · 재생 목록은 읽기만 · 수정 목록 208

원인 · 준비 검사 · 그룹 준비 · 재생 목록 짓기가 그때마다 모션 파일(JSONL · NY 920 s × 20 조인트 ≈ 25 MB)을
읽고 20 ms 재샘플 · 범위 자르기 · 속도 검사를 했다 · 재생 · ROS 응답과 같은 프로세스(GIL 하나)에서 ·
메모리 캐시는 서비스가 다시 뜨면 비어 재부팅 뒤 첫 그룹 시작이 느렸다(174) · 그 비용을 시간 · 쉬어 가기로
가렸다(164 · 170 · 171 · 174).

이제 · 무거운 일(파일 읽기 · 재샘플)은 **별도 프로세스**가 한 번 하고 결과를 디스크에 둔다 · 이 프로세스는
읽기(ms)만 한다 · 키가 맞으면 재부팅 · 서비스 재시작 뒤에도 그대로 쓴다.

자리 · `<프로젝트>/runtime/plan_artifacts/<애니 파일 이름>/` (`motion_common.paths.plan_artifacts_dir`)

    tracks-<키 해시>.rwplan    이 PC 매핑 조인트만 · 조인트별 배열(프레임 · 시각 · 값 · 줄 번호) · rad · 시각 순
    samples-<키 해시>.rwplan   통째 재생 · 20 ms 재샘플(범위 · 모터 한계로 자른 모터 목표 · 조인트 값) +
                               속도·가속 거절 사유
    segment-<키 해시>.rwplan   구간 재생 것 · 따로 셈(통째 것을 밀어내지 않게)

    종류마다 최근 `KEEP` 개만 남긴다 · 애니 삭제 · 이름 바꾸기 · 프로젝트 삭제 때 폴더째 지운다(브리지)

파일 한 개 모양 · 값은 지금 계획과 같은 double(`array('d')`) · 프레임 · 줄 번호는 `array('q')`

    MAGIC 8 B · 머리 길이 8 B(little endian) · 머리 JSON(8 B 맞춤) · 칸 바이트를 차례로
    머리 · format · kind · key(키 글자 전체) · byteorder · columns[{name, typecode, count}] ·
           payload_bytes · crc32(칸 바이트 전체) · meta(조인트 순서 · 모터축 · 거절 사유)

키 · 메모리 캐시 키 그대로(파일 경로 · 크기 · 수정 시각 ns · 조인트 묶음 · 구간 · 주기 · 축마다 매핑 줄 전체 ·
모터 번호 · 모터 한계) + 계산에 드는 모듈 소스 지문(`code_fingerprint` · 업데이트로 식이 바뀌면 다시 변환) +
파이썬 판 · byteorder · 모터 위치 · 알람 · 서보는 안 든다(174 와 같다)

깨진 파일(전원 꺼짐 · 쓰다 만 것) · 임시 이름에 쓰고 fsync 뒤 `os.replace` · 읽을 때 길이 · crc32 · 키를
보고 하나라도 틀리면 지우고 다시 변환한다.

변환 · `python3 -c ...main()` 자식 프로세스(nice 10) · 일을 pickle 로 받아 변환본을 쓴다 · 실패하면
(프로세스를 못 띄움 · 읽기 오류) 이 프로세스에서 지금까지와 같은 함수로 계산한다(같은 오류 · 같은 값).
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import mmap
import os
import pickle
import struct
import subprocess
import sys
import threading
import time
import traceback
import uuid
import zlib
from array import array
from pathlib import Path
from typing import Any, Callable, List, Mapping, Optional, Sequence, Tuple

from motion_common import motion_tracks, paths as common_paths

from .packed_samples import PackedSamples

#: 파일 모양 판 · 모양을 바꾸면 올린다(키에도 든다)
FORMAT = 1
MAGIC = b'RWPLAN\x00\x01'
SUFFIX = '.rwplan'
TEMP_PREFIX = '.tmp-'
#: 종류마다 남길 개수 · 매핑을 바꿔 가며 써도 최근 것은 남게
KEEP = {'tracks': 2, 'samples': 2, 'segment': 2}
#: 쓰다 만 임시 파일 · 이보다 오래되면 지운다(다른 스레드가 쓰는 중인 것은 안 건드리게)
TEMP_MAX_AGE_SEC = 3600.0
#: 변환 자식 프로세스 · 이 프로세스(재생 · ROS 응답)와 GIL 을 나누지 않는다 · 끄면 이 프로세스에서(시험)
COMPILE_IN_SUBPROCESS = True
#: 자식 프로세스 제한 시간 · 데스크톱 920 s × 20 조인트 파일이 약 0.6 s · 미니 PC · 몇 시간짜리 파일도 넉넉하게 ·
#: 넘으면 자식을 끝내고 이 프로세스에서
COMPILE_TIMEOUT_SEC = 300.0
#: 자식 프로세스 우선순위 · 재생 · 다른 노드보다 뒤
CHILD_NICE = 10

_HEAD = struct.Struct('<8sQ')
_TYPECODES = ('d', 'q')

#: 계산 결과에 드는 모듈 · 소스가 바뀌면(업데이트) 지문이 바뀌어 변환본을 다시 만든다
_CODE_MODULES = (
    'motion_common.joint_mapping',
    'motion_common.motion_segment',
    'motion_common.motion_table',
    'motion_common.motion_tracks',
    'motion_common.rate_check',
    'motion_common.units',
    'motion_common.values',
    'motion_common.wire_units',
    'motion_runtime.motion_file_reader',
    'motion_runtime.motion_run_rules',
    'motion_runtime.packed_samples',
    'motion_runtime.plan_artifact',
    'motion_runtime.plan_builder',
)

_fingerprint_lock = threading.Lock()
_fingerprint: Optional[str] = None
_fingerprint_done = False

Log = Callable[[str], None]


class _Corrupt(Exception):
    """변환본이 깨졌다 · 지우고 다시 변환"""


def code_fingerprint() -> Optional[str]:
    """계산에 드는 모듈 소스의 해시 · 한 번만 · 못 읽으면 None(그때는 변환본을 안 쓴다)"""
    global _fingerprint, _fingerprint_done
    with _fingerprint_lock:
        if not _fingerprint_done:
            digest = hashlib.sha256()
            try:
                for name in _CODE_MODULES:
                    spec = importlib.util.find_spec(name)
                    origin = getattr(spec, 'origin', None)
                    if not origin or not str(origin).endswith('.py'):
                        raise LookupError(name)
                    digest.update(name.encode('utf-8') + b'\0')
                    digest.update(Path(origin).read_bytes())
                _fingerprint = digest.hexdigest()[:16]
            except (ImportError, LookupError, OSError, ValueError):
                _fingerprint = None
            _fingerprint_done = True
        return _fingerprint


# --------------------------------------------------------------------------- #
# 자리 · 키
# --------------------------------------------------------------------------- #

def store_for(motion_file_path: Any) -> Optional['ArtifactStore']:
    """그 애니의 변환본 자리 · 프로젝트 `motions/` 안의 파일만(스튜디오 임시 · 시험 파일은 None)"""
    if motion_file_path is None:
        return None
    try:
        path = Path(motion_file_path)
        motions_dir = path.parent
        project_dir = motions_dir.parent
        if motions_dir.name != 'motions' or not (project_dir / 'project.json').is_file():
            return None
    except (OSError, TypeError, ValueError):
        return None
    if code_fingerprint() is None:
        return None
    return ArtifactStore(common_paths.plan_artifacts_dir(project_dir) / path.name)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (set, frozenset)):
        return sorted(str(item) for item in value)
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    return value


def key_text(what: str, ingredient: Any) -> Optional[str]:
    """키 글자 · 메모리 캐시 키(튜플)를 JSON 으로 + 지문 · 파이썬 판 · byteorder · 못 만들면 None"""
    if ingredient is None:
        return None
    fingerprint = code_fingerprint()
    if fingerprint is None:
        return None
    payload = {
        'what': what,
        'format': FORMAT,
        'code': fingerprint,
        'python': f'{sys.version_info[0]}.{sys.version_info[1]}',
        'byteorder': sys.byteorder,
        'key': _jsonable(ingredient),
    }
    try:
        return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- #
# 파일 한 개 · 쓰기 · 읽기
# --------------------------------------------------------------------------- #

def _fsync_dir(directory: Path) -> None:
    try:
        fd = os.open(str(directory), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _write_artifact(
    path: Path, kind: str, key: str, columns: Sequence[Tuple[str, array]], meta: Mapping[str, Any],
) -> None:
    crc = 0
    total = 0
    specs = []
    for name, column in columns:
        if column.typecode not in _TYPECODES:
            raise ValueError(f'변환본 칸 종류 {column.typecode}')
        crc = zlib.crc32(column, crc)
        total += column.itemsize * len(column)
        specs.append({'name': name, 'typecode': column.typecode, 'count': len(column)})
    header = {
        'format': FORMAT,
        'kind': kind,
        'key': key,
        'byteorder': sys.byteorder,
        'columns': specs,
        'payload_bytes': total,
        'crc32': crc,
        'meta': dict(meta),
        'created_at': time.time(),
    }
    raw = json.dumps(header, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    raw += b' ' * ((-(_HEAD.size + len(raw))) % 8)
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    temp = directory / f'{TEMP_PREFIX}{kind}-{os.getpid()}-{uuid.uuid4().hex[:12]}'
    try:
        with open(temp, 'wb') as handle:
            handle.write(_HEAD.pack(MAGIC, len(raw)))
            handle.write(raw)
            for _name, column in columns:
                handle.write(column)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    except BaseException:
        try:
            temp.unlink()
        except OSError:
            pass
        raise
    _fsync_dir(directory)


def _read_artifact(path: Path, kind: str, key: str) -> Optional[Tuple[dict, List[array]]]:
    """(머리, 칸 배열들) · 파일이 없으면 None · 깨졌으면 `_Corrupt`"""
    try:
        handle = open(path, 'rb')
    except FileNotFoundError:
        return None
    with handle:
        size = os.fstat(handle.fileno()).st_size
        if size < _HEAD.size:
            raise _Corrupt(f'길이 {size} B')
        try:
            mapped = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
        except (OSError, ValueError) as exc:
            raise _Corrupt(str(exc)) from exc
    try:
        with memoryview(mapped) as view:
            magic, header_len = _HEAD.unpack_from(view, 0)
            if magic != MAGIC:
                raise _Corrupt('머리 표식')
            start = _HEAD.size + header_len
            if start > size:
                raise _Corrupt('머리 길이')
            with view[_HEAD.size:start] as part:
                header = json.loads(bytes(part).decode('utf-8'))
            if (
                header.get('format') != FORMAT or header.get('kind') != kind
                or header.get('byteorder') != sys.byteorder
            ):
                raise _Corrupt('판 · 종류 · byteorder')
            if header.get('key') != key:
                raise _Corrupt('키')
            if header.get('payload_bytes') != size - start:
                raise _Corrupt(f'길이 {size - start} / {header.get("payload_bytes")} B')
            with view[start:] as body:
                if zlib.crc32(body) != header.get('crc32'):
                    raise _Corrupt('crc32')
            columns = []
            offset = start
            for spec in header.get('columns') or []:
                typecode = spec['typecode']
                if typecode not in _TYPECODES:
                    raise _Corrupt(f'칸 종류 {typecode}')
                column = array(typecode)
                nbytes = column.itemsize * int(spec['count'])
                if offset + nbytes > size:
                    raise _Corrupt('칸 길이')
                with view[offset:offset + nbytes] as part:
                    column.frombytes(part)
                offset += nbytes
                columns.append(column)
            if offset != size:
                raise _Corrupt('남는 바이트')
            return header, columns
    except _Corrupt:
        raise
    except (KeyError, TypeError, ValueError, struct.error) as exc:
        raise _Corrupt(f'{type(exc).__name__}: {exc}') from exc
    finally:
        mapped.close()


# --------------------------------------------------------------------------- #
# 조인트별 배열 · 재샘플 ↔ 칸
# --------------------------------------------------------------------------- #

def _tracks_columns(tracks: motion_tracks.MotionTracks) -> Tuple[list, dict]:
    columns = []
    joints = []
    for index, (motion_id, track) in enumerate(tracks.tracks.items()):
        joints.append(str(motion_id))
        columns += [
            (f'{index}.frames', track.frames),
            (f'{index}.times', track.times),
            (f'{index}.values', track.values),
            (f'{index}.rows', track.rows),
        ]
    return columns, {'joints': joints}


def _tracks_from(header: dict, columns: List[array]) -> motion_tracks.MotionTracks:
    joints = [str(item) for item in header['meta']['joints']]
    if len(columns) != 4 * len(joints):
        raise _Corrupt('조인트 칸 수')
    result = {}
    for index, motion_id in enumerate(joints):
        frames, times, values, rows = columns[4 * index:4 * index + 4]
        if (
            (frames.typecode, times.typecode, values.typecode, rows.typecode) != ('q', 'd', 'd', 'q')
            or not len(frames) == len(times) == len(values) == len(rows)
        ):
            raise _Corrupt(f'조인트 {motion_id} 칸')
        result[motion_id] = motion_tracks.JointTrack.from_arrays(motion_id, frames, times, values, rows)
    return motion_tracks.MotionTracks(result)


def _samples_columns(samples: PackedSamples, rate_error: str) -> Tuple[list, dict]:
    times, absolute, positions, values = samples.columns()
    columns = [('times', times), ('absolute', absolute)]
    columns += [(f'position.{index}', column) for index, column in enumerate(positions)]
    columns += [(f'value.{index}', column) for index, column in enumerate(values)]
    return columns, {
        'motor_axes': list(samples.motor_axes),
        'motion_ids': list(samples.motion_ids),
        'rate_error': str(rate_error or ''),
        'sample_count': len(samples),
    }


def _samples_from(header: dict, columns: List[array]) -> Tuple[PackedSamples, str]:
    meta = header['meta']
    motor_axes = [int(item) for item in meta['motor_axes']]
    motion_ids = [str(item) for item in meta['motion_ids']]
    count = len(motor_axes)
    if len(columns) != 2 + 2 * count or any(column.typecode != 'd' for column in columns):
        raise _Corrupt('샘플 칸 수')
    try:
        samples = PackedSamples.from_columns(
            motor_axes, motion_ids, columns[0], columns[1], columns[2:2 + count], columns[2 + count:],
        )
    except ValueError as exc:
        raise _Corrupt(str(exc)) from exc
    return samples, str(meta.get('rate_error') or '')


# --------------------------------------------------------------------------- #
# 자리 하나 · 애니 파일 하나
# --------------------------------------------------------------------------- #

class ArtifactStore:
    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory)

    def path(self, kind: str, key: str) -> Path:
        digest = hashlib.sha256(key.encode('utf-8')).hexdigest()[:24]
        return self.directory / f'{kind}-{digest}{SUFFIX}'

    def load(self, kind: str, key: str, decode: Callable[[dict, List[array]], Any], log: Optional[Log] = None) -> Any:
        """맞는 변환본 · 없으면 None · 깨졌으면 지우고 None"""
        path = self.path(kind, key)
        try:
            found = _read_artifact(path, kind, key)
            if found is None:
                return None
            return decode(*found)
        except (_Corrupt, KeyError, TypeError, ValueError) as exc:
            self._discard(path, f'{type(exc).__name__}: {exc}', log)
            return None
        except OSError as exc:
            if log is not None:
                log(f'[애니 변환] 변환본 읽기 실패 · {path.name} · {exc}')
            return None

    def save(self, kind: str, key: str, columns: Sequence[Tuple[str, array]], meta: Mapping[str, Any]) -> Path:
        path = self.path(kind, key)
        _write_artifact(path, kind, key, columns, meta)
        self.prune(kind, keep=path)
        return path

    def prune(self, kind: str, keep: Optional[Path] = None) -> None:
        """그 종류는 최근 `KEEP` 개만 · 오래된 임시 파일도 · 실패는 그냥 둔다"""
        try:
            entries = []
            for item in self.directory.iterdir():
                name = item.name
                try:
                    stat = item.stat()
                except OSError:
                    continue
                if name.startswith(TEMP_PREFIX):
                    if time.time() - stat.st_mtime > TEMP_MAX_AGE_SEC:
                        item.unlink(missing_ok=True)
                    continue
                if name.startswith(f'{kind}-') and name.endswith(SUFFIX) and item != keep:
                    entries.append((stat.st_mtime_ns, item))
        except OSError:
            return
        entries.sort(reverse=True)
        room = max(KEEP.get(kind, 1) - (1 if keep is not None else 0), 0)
        for _mtime, item in entries[room:]:
            try:
                item.unlink(missing_ok=True)
            except OSError:
                pass

    def _discard(self, path: Path, reason: str, log: Optional[Log]) -> None:
        if log is not None:
            log(f'[애니 변환] 변환본이 깨져 다시 만듭니다 · {path.name} · {reason}')
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# 불러오기 · 없으면 변환
# --------------------------------------------------------------------------- #

def _save_quietly(store: ArtifactStore, kind: str, key: str, encoded: Tuple[list, dict], log: Optional[Log]) -> None:
    columns, meta = encoded
    try:
        store.save(kind, key, columns, meta)
    except OSError as exc:
        # 디스크가 차거나 권한 · 계획은 그대로 쓴다 · 다음에 다시 변환한다
        if log is not None:
            log(f'[애니 변환] 변환본 저장 실패 · {store.directory.name} · {exc}')


def load_or_compile_tracks(
    store: ArtifactStore,
    token: Any,
    source_path: Any,
    motion_ids: Optional[frozenset],
    parse_here: Callable[[], motion_tracks.MotionTracks],
    log: Optional[Log] = None,
) -> Tuple[motion_tracks.MotionTracks, str]:
    """(조인트별 배열, 출처) · 출처 `artifact`(디스크) · `compiled`(자식 프로세스) · `parsed`(이 프로세스)"""
    key = key_text('tracks', token)
    if key is None:
        return parse_here(), 'parsed'
    found = store.load('tracks', key, _tracks_from, log)
    if found is not None:
        return found, 'artifact'
    if COMPILE_IN_SUBPROCESS and _run_child({
        'job': 'tracks',
        'directory': str(store.directory),
        'key': key,
        'source': str(source_path),
        'ids': None if motion_ids is None else sorted(str(item) for item in motion_ids),
    }, log):
        found = store.load('tracks', key, _tracks_from, log)
        if found is not None:
            return found, 'compiled'
    tracks = parse_here()
    _save_quietly(store, 'tracks', key, _tracks_columns(tracks), log)
    return tracks, 'parsed'


def load_or_compile_samples(
    store: ArtifactStore,
    samples_key: Any,
    segment_active: bool,
    sample_inputs: Mapping[str, Any],
    compute_here: Callable[[], Tuple[PackedSamples, str]],
    log: Optional[Log] = None,
) -> Tuple[Tuple[PackedSamples, str], str]:
    """((샘플, 거절 사유), 출처) · `sample_inputs` = `_sample_plan` 인자(axes · groups · start · end · period)"""
    key = key_text('samples', samples_key)
    if key is None:
        return compute_here(), 'computed'
    kind = 'segment' if segment_active else 'samples'
    found = store.load(kind, key, _samples_from, log)
    if found is not None:
        return found, 'artifact'
    if COMPILE_IN_SUBPROCESS and _run_child({
        'job': 'samples',
        'directory': str(store.directory),
        'key': key,
        'kind': kind,
        **dict(sample_inputs),
    }, log):
        found = store.load(kind, key, _samples_from, log)
        if found is not None:
            return found, 'compiled'
    result = compute_here()
    _save_quietly(store, kind, key, _samples_columns(*result), log)
    return result, 'computed'


# --------------------------------------------------------------------------- #
# 자식 프로세스
# --------------------------------------------------------------------------- #

def _child_env() -> dict:
    """자식이 이 프로세스와 같은 모듈을 읽게 · 패키지 뿌리를 PYTHONPATH 앞에"""
    env = dict(os.environ)
    roots = []
    for name in ('motion_runtime', 'motion_common'):
        module = sys.modules.get(name)
        location = getattr(module, '__file__', None)
        if location:
            root = str(Path(location).resolve().parent.parent)
            if root not in roots:
                roots.append(root)
    existing = env.get('PYTHONPATH', '')
    env['PYTHONPATH'] = os.pathsep.join(roots + ([existing] if existing else []))
    return env


#: 자식 시작 명령 · `-m` 으로 띄우면 이 모듈이 `__main__` 으로 한 벌 더 생겨 함수로 부른다
_CHILD_CODE = 'import sys; from motion_runtime.plan_artifact import main; sys.exit(main())'


def _run_child(job: Mapping[str, Any], log: Optional[Log]) -> bool:
    """자식 프로세스로 변환 · 성공이면 참 · 실패면 거짓(부르는 쪽이 이 프로세스에서 계산)"""
    try:
        data = pickle.dumps(dict(job), protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as exc:  # noqa: BLE001 · 못 넘기면 이 프로세스에서
        if log is not None:
            log(f'[애니 변환] 자식 프로세스에 넘길 수 없음 · {type(exc).__name__}: {exc} · 이 프로세스에서 변환')
        return False
    try:
        completed = subprocess.run(
            [sys.executable, '-c', _CHILD_CODE],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=COMPILE_TIMEOUT_SEC,
            env=_child_env(),
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        if log is not None:
            log(f'[애니 변환] 자식 프로세스 실행 실패 · {type(exc).__name__}: {exc} · 이 프로세스에서 변환')
        return False
    reply: dict = {}
    for line in reversed(completed.stdout.decode('utf-8', 'replace').splitlines()):
        try:
            candidate = json.loads(line)
        except ValueError:
            continue
        if isinstance(candidate, dict):
            reply = candidate
            break
    if completed.returncode == 0 and reply.get('ok'):
        return True
    # 읽기 오류(ValueError · 쓸 줄 없음 등)는 이 프로세스에서 같은 오류가 다시 난다 · 알릴 것 없음
    if log is not None and reply.get('error_type') != 'ValueError':
        tail = completed.stderr.decode('utf-8', 'replace').strip().splitlines()[-3:]
        log(
            f'[애니 변환] 자식 프로세스 실패(종료 {completed.returncode}) · '
            f'{reply.get("error_type", "")} {reply.get("error", "")} · {" | ".join(tail)} · 이 프로세스에서 변환'
        )
    return False


def _compile_job(job: Mapping[str, Any]) -> None:
    store = ArtifactStore(Path(job['directory']))
    if job['job'] == 'tracks':
        from .motion_file_reader import parse_motion_tracks

        tracks = parse_motion_tracks(Path(job['source']), job.get('ids'))
        columns, meta = _tracks_columns(tracks)
        store.save('tracks', job['key'], columns, meta)
        return
    if job['job'] == 'samples':
        # 이 프로세스의 계획과 같은 함수 · 같은 인자 · 같은 파이썬 → 같은 double
        from .plan_builder import _sample_plan

        samples, rate_error = _sample_plan(
            job['axes'], job['groups'], job['start_time'], job['end_time'], job['period_sec'],
        )
        columns, meta = _samples_columns(samples, rate_error)
        store.save(job['kind'], job['key'], columns, meta)
        return
    raise ValueError(f'모르는 변환 일 {job.get("job")}')


def main() -> int:
    """자식 프로세스 · 표준 입력 pickle 일 하나 → 변환본 · 표준 출력 마지막 줄 JSON"""
    try:
        os.nice(CHILD_NICE)
    except (AttributeError, OSError):
        pass
    started = time.perf_counter()
    try:
        job = pickle.load(sys.stdin.buffer)
        _compile_job(job)
    except Exception as exc:  # noqa: BLE001 · 부모가 이 프로세스에서 다시 한다
        traceback.print_exc(file=sys.stderr)
        print(json.dumps({'ok': False, 'error_type': type(exc).__name__, 'error': str(exc)[:500]}), flush=True)
        return 1
    print(json.dumps({'ok': True, 'ms': round((time.perf_counter() - started) * 1000.0, 1)}), flush=True)
    return 0
