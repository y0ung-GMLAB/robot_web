"""Integrated project-service launch wiring contracts."""

from __future__ import annotations

import ast
from pathlib import Path


LAUNCH_FILE = (
    Path(__file__).resolve().parents[1] / 'launch' / 'project_services.launch.py'
)


def _node_parameters() -> dict[str, dict[str, str]]:
    tree = ast.parse(LAUNCH_FILE.read_text(encoding='utf-8'))
    result: dict[str, dict[str, str]] = {}
    for call in ast.walk(tree):
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
            continue
        if call.func.id != 'Node':
            continue
        keywords = {keyword.arg: keyword.value for keyword in call.keywords}
        executable = keywords.get('executable')
        parameters = keywords.get('parameters')
        if not isinstance(executable, ast.Constant) or not isinstance(
            executable.value, str
        ):
            continue
        node_parameters: dict[str, str] = {}
        if (
            isinstance(parameters, ast.List)
            and parameters.elts
            and isinstance(parameters.elts[0], ast.Dict)
        ):
            for key, value in zip(
                parameters.elts[0].keys,
                parameters.elts[0].values,
            ):
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    continue
                if (
                    isinstance(value, ast.Call)
                    and isinstance(value.func, ast.Name)
                    and value.func.id == 'LaunchConfiguration'
                    and value.args
                    and isinstance(value.args[0], ast.Constant)
                ):
                    node_parameters[key.value] = str(value.args[0].value)
        result[executable.value] = node_parameters
    return result


def test_studio_and_midi_nodes_stay_deleted():
    """스튜디오·MIDI 노드는 삭제됐다 · launch 에 몰래 돌아오면 안 된다."""
    parameters = _node_parameters()

    assert set(parameters) == {
        'motion_mapping_manager', 'motion_run_manager',
        'motion_schedule_node', 'motion_web_bridge',
    }
    assert 'request_topic' not in parameters['motion_run_manager']
    assert 'response_topic' not in parameters['motion_run_manager']
    for executable, node_parameters in parameters.items():
        for key in node_parameters:
            assert 'studio' not in key and 'midi' not in key, (
                f'{executable} 가 {key} 를 아직 받습니다'
            )
