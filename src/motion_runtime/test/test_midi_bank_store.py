import yaml

from motion_runtime.midi_bank_store import (
    BLOCK_END,
    BLOCK_START,
    load_midi_banks,
    render_with_midi_banks,
    save_midi_banks,
)


STATE = {
    'version': 1,
    'active_bank_id': 'bank_1',
    'banks': [{'bank_id': 'bank_1', 'name': 'Bank 1', 'mappings': []}],
}


def test_midi_yaml_block_preserves_existing_motion_mapping_text(tmp_path):
    original = (
        'file_id: show_mapping.yaml\n'
        'motion_file_id: show.json\n'
        'mappings: []\n'
    )
    mapping_file = tmp_path / 'show_mapping.yaml'
    mapping_file.write_text(original, encoding='utf-8')

    backup = save_midi_banks(mapping_file, STATE)
    saved = mapping_file.read_text(encoding='utf-8')

    assert backup.read_text(encoding='utf-8') == original
    assert saved.startswith(original.rstrip() + '\n\n')
    assert saved.count(BLOCK_START) == 1
    assert saved.count(BLOCK_END) == 1
    assert load_midi_banks(mapping_file) == STATE


def test_unmarked_midi_section_is_replaced_without_changing_mapping_prefix():
    existing = (
        'file_id: show_mapping.yaml\n'
        'mappings: []\n'
        'midi_banks:\n'
        '  version: 1\n'
        '  active_bank_id: old\n'
        '  banks: []\n'
        'motion_file_id: show.json\n'
    )

    rendered = render_with_midi_banks(existing, STATE)
    parsed = yaml.safe_load(rendered)

    assert rendered.startswith('file_id: show_mapping.yaml\nmappings: []\n')
    assert rendered.endswith('motion_file_id: show.json\n')
    assert parsed['midi_banks'] == STATE
    assert rendered.count('midi_banks:') == 1


def test_repeated_saves_in_same_second_keep_distinct_history_files(tmp_path, monkeypatch):
    mapping_file = tmp_path / 'show_mapping.yaml'
    history_dir = tmp_path / 'history'
    mapping_file.write_text('mappings: []\n', encoding='utf-8')
    monkeypatch.setattr(
        'motion_runtime.midi_bank_store.time.strftime',
        lambda _format: '20260716-200000',
    )

    first = save_midi_banks(mapping_file, STATE, history_dir)
    second = save_midi_banks(mapping_file, STATE, history_dir)

    assert first != second
    assert first.is_file()
    assert second.is_file()


def test_history_folder_is_capped_at_fifty_backups(tmp_path):
    """저장마다 한 벌 남기되 분류별 50개까지만 · 수정 목록 21-3 (2026-10-03)."""
    mapping_file = tmp_path / 'show_mapping.yaml'
    mapping_file.write_text('file_id: show_mapping.yaml\nmappings: []\n', encoding='utf-8')
    history = tmp_path / 'runtime' / 'history' / 'motion_axis_matching'
    for index in range(55):
        stale = history / f'20250101-{index:06d}-show_mapping.yaml'
        stale.parent.mkdir(parents=True, exist_ok=True)
        stale.write_text(str(index), encoding='utf-8')
    save_midi_banks(mapping_file, STATE, history)
    names = sorted(p.name for p in history.iterdir())
    assert len(names) == 50
    assert names[0] == '20250101-000006-show_mapping.yaml'   # 가장 오래된 6개가 빠졌다
    assert names[-1].endswith('-show_mapping.yaml') and not names[-1].startswith('20250101')


def test_backup_next_to_the_file_is_never_pruned(tmp_path):
    """이력 폴더를 안 주면 원본 옆에 백업한다 · 그 폴더는 정리 대상이 아니다."""
    mapping_file = tmp_path / 'show_mapping.yaml'
    mapping_file.write_text('file_id: show_mapping.yaml\nmappings: []\n', encoding='utf-8')
    for index in range(60):
        (tmp_path / f'other-{index}.yaml').write_text('x', encoding='utf-8')
    save_midi_banks(mapping_file, STATE)
    assert len(list(tmp_path.glob('other-*.yaml'))) == 60
