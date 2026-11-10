"""조인트 최대 속도·가속도 검사 · 재생 계획과 녹화 저장이 같은 잣대 · 수정 목록 5-2 · 156

재생 계획(`plan_builder`)이 쓰던 것을 옮겼다 · X-Touch 녹화(브리지)가 저장 전에 같은 검사를
해서 「저장은 됐는데 재생 거절」 이 없게 한다.

    axes     [{motion_id, row}]  · row = 조인트 매핑 줄(상한 칸)
             재생 계획은 더 싣는다(없어도 됨) · motion_limit_lower_rad · motion_limit_upper_rad(매핑 범위) ·
             source_motion_min_rad · source_motion_max_rad(자르기 전 애니 값) → 범위로 잘린 곳이면 이유에 덧붙임 · 168
    samples  [{time_sec, motion_values: {motion_id: 조인트 rad}}]
"""

from __future__ import annotations

from . import joint_mapping, units

_deg = units.rad_to_deg

#: 잘린 값은 범위 끝값 그대로다(min/max) · 소수 반올림만 견딘다
_AT_LIMIT_RAD = 1e-9


def _deg_text(value_rad: float) -> str:
    """-15.0 → 「−15」 · -15.82 → 「−15.82」 · 글자용"""
    text = f'{abs(_deg(value_rad)):.2f}'.rstrip('0').rstrip('.')
    return f'−{text}' if value_rad < 0 and text != '0' else text


def _finite(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number == number and abs(number) != float('inf') else None


def _clip_hint(axis, values, indexes) -> str:
    """가장 나쁜 표본이 매핑 범위로 잘린 값에 걸리면 덧붙일 말 · 아니면 빈 글 · 수정 목록 168

    재생 계획은 매핑 범위로 자른 뒤 잰다 · 범위를 넘는 애니는 자른 자리에서 꺾여 가속도가 튄다 ·
    (실물 2026-11-02 · f2_neck_yaw 최소 −15.82° · 범위 ±15 → 21 deg/s² · 원래 애니는 8.9) ·
    거절은 그대로 · 고칠 곳이 애니 범위(또는 매핑 범위)라는 것만 알린다
    """
    lower = _finite(axis.get('motion_limit_lower_rad'))
    upper = _finite(axis.get('motion_limit_upper_rad'))
    source_min = _finite(axis.get('source_motion_min_rad'))
    source_max = _finite(axis.get('source_motion_max_rad'))
    clipped_low = lower is not None and source_min is not None and source_min < lower - _AT_LIMIT_RAD
    clipped_high = upper is not None and source_max is not None and source_max > upper + _AT_LIMIT_RAD
    if not clipped_low and not clipped_high:
        return ''
    # 그 속도·가속도를 만든 표본들 · 자른 자리의 꺾임이면 범위 끝값이 이 안에 있다
    touched = [values[index] for index in indexes if 0 <= index < len(values)]
    hit_low = clipped_low and any(abs(value - lower) <= _AT_LIMIT_RAD for value in touched)
    hit_high = clipped_high and any(abs(value - upper) <= _AT_LIMIT_RAD for value in touched)
    if not hit_low and not hit_high:
        return ''
    low_text = _deg_text(lower) if lower is not None else ''
    high_text = _deg_text(upper) if upper is not None else ''
    over = []
    if hit_low:
        over.append(f'최소 {_deg_text(source_min)}°')
    if hit_high:
        over.append(f'최대 {_deg_text(source_max)}°')
    return f'매핑 범위({low_text}~{high_text}°)에서 잘린 곳 · 애니가 범위를 넘음({", ".join(over)})'


def rate_limit_error(axes, samples, period_sec: float) -> str:
    """조인트 최대 속도·가속도를 넘는 애니메이션이면 거부 사유 · 수정 목록 5-2 (2026-10-06)

    전에는 어느 계층도 속도·가속도를 보지 않았다 · 너무 빠른 애니메이션은 모터가
    못 따라가 「도달 실패」 로 끝나거나 기구에 무리가 갔다. 조인트 매핑에 축별
    상한을 적으면(비우면 검사 안 함) 재생 계획(20 ms 재샘플 · 매핑 범위로 자른 값)
    의 차분으로 잰다 · 재생과 같은 값을 보므로 「검사는 통과했는데 실제로는 넘는다」 가 없다.
    """
    if len(samples) < 2 or period_sec <= 0:
        return ''
    problems = []
    # 배열 묶음(`PackedSamples`)이면 사전을 만들지 않고 칸을 바로 본다 · 같은 값 · 수정 목록 170
    time_column = getattr(samples, 'time_column', None)
    motion_column = getattr(samples, 'motion_column', None)
    packed = callable(time_column) and callable(motion_column)
    for axis in axes:
        row = axis.get('row') or {}
        # 상한·재는 값 모두 rad · 글에만 deg · 수정 목록 6
        max_velocity = joint_mapping.rate(row, 'max_velocity', units.RAD)
        max_acceleration = joint_mapping.rate(row, 'max_acceleration', units.RAD)
        if not max_velocity and not max_acceleration:
            continue
        motion_id = str(axis['motion_id'])
        if packed:
            values = [float(value) for value in motion_column(motion_id)]
            times = [float(value) for value in time_column()]
        else:
            values = [float(sample['motion_values'][motion_id]) for sample in samples]
            times = [float(sample['time_sec']) for sample in samples]
        # (속도, 시각, 뒤 표본 번호) · 번호는 범위로 잘린 곳인지 볼 때 · 168
        velocities = []
        for index in range(1, len(values)):
            dt = times[index] - times[index - 1]
            if dt <= 1e-9:
                continue
            velocities.append(((values[index] - values[index - 1]) / dt, times[index], index))
        if max_velocity:
            worst = max(velocities, key=lambda item: abs(item[0]), default=None)
            if worst and abs(worst[0]) > max_velocity * (1 + 1e-6):
                hint = _clip_hint(axis, values, (worst[2] - 1, worst[2]))
                problems.append(
                    f'{motion_id} 속도 {_deg(abs(worst[0])):.1f} deg/s > 상한 {round(_deg(max_velocity), 6):g} ({worst[1]:.2f} s)'
                    + (f' · {hint}' if hint else '')
                )
        if max_acceleration and len(velocities) > 1:
            accelerations = [
                ((velocities[i][0] - velocities[i - 1][0]) / max(velocities[i][1] - velocities[i - 1][1], 1e-9),
                 velocities[i][1], velocities[i - 1][2] - 1, velocities[i][2])
                for i in range(1, len(velocities))
            ]
            worst = max(accelerations, key=lambda item: abs(item[0]), default=None)
            if worst and abs(worst[0]) > max_acceleration * (1 + 1e-6):
                hint = _clip_hint(axis, values, range(worst[2], worst[3] + 1))
                problems.append(
                    f'{motion_id} 가속도 {_deg(abs(worst[0])):.0f} deg/s² > 상한 {round(_deg(max_acceleration), 6):g} ({worst[1]:.2f} s)'
                    + (f' · {hint}' if hint else '')
                )
    if not problems:
        return ''
    return '애니메이션이 조인트 매핑의 속도·가속도 상한을 넘습니다 · ' + ' · '.join(problems[:4])
