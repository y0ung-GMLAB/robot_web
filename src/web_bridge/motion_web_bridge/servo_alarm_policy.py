"""Panasonic MINAS A6B servo-alarm catalog and project policy helpers."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, Iterable

# 표 자체는 motion_common 에 하나 · 화면 글(motion_state_monitor)과 같이 쓴다 · 수정 목록 166 ·
# 여기서 다시 내보낸다(bridge_node · 시험)
from motion_common.minas_alarms import (  # noqa: F401
    CATALOG_VERSION,
    GRADE_DEFINITIONS,
    SERVO_ALARM_CATALOG,
    UNKNOWN_ALARM_GRADE,
    grade_action,
)

_CATALOG_BY_CODE = {entry['code']: entry for entry in SERVO_ALARM_CATALOG}


def normalize_overrides(value: Any) -> Dict[str, int]:
    if not isinstance(value, dict):
        return {}
    normalized: Dict[str, int] = {}
    for key, grade in value.items():
        try:
            code = int(str(key).split('.', 1)[0])
            parsed_grade = int(grade)
        except (TypeError, ValueError):
            continue
        if code not in _CATALOG_BY_CODE or parsed_grade not in (1, 2, 3):
            continue
        normalized[str(code)] = parsed_grade
    return normalized


def effective_grade_map(overrides: Any = None) -> Dict[str, int]:
    normalized = normalize_overrides(overrides)
    return {
        str(entry['code']): int(normalized.get(str(entry['code']), entry['default_grade']))
        for entry in SERVO_ALARM_CATALOG
    }


def policy_revision(
    effective_grades: Dict[str, int],
    catalog_version: int = CATALOG_VERSION,
) -> str:
    canonical = json.dumps(
        {
            'catalog_version': int(catalog_version),
            'grades': {
                str(key): int(value)
                for key, value in sorted(
                    effective_grades.items(),
                    key=lambda item: int(item[0]),
                )
            },
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(',', ':'),
    )
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def catalog_payload(overrides: Any = None) -> list[Dict[str, Any]]:
    normalized = normalize_overrides(overrides)
    rows = []
    for entry in SERVO_ALARM_CATALOG:
        key = str(entry['code'])
        project_grade = normalized.get(key)
        rows.append({
            **entry,
            'project_grade': project_grade,
            'effective_grade': int(project_grade or entry['default_grade']),
            'action': grade_action(project_grade or entry['default_grade']),
            'modified': project_grade is not None,
        })
    return rows


def configured_counts(entries: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    counts = {'1': 0, '2': 0, '3': 0, 'modified': 0}
    for entry in entries:
        grade = str(int(entry.get('effective_grade') or UNKNOWN_ALARM_GRADE))
        counts[grade] = counts.get(grade, 0) + 1
        if entry.get('modified'):
            counts['modified'] += 1
    return counts
