"""애니메이션 목록은 바뀐 파일만 다시 읽는다 · 수정 목록 5-3 (2026-10-06)"""

import os

from motion_web_bridge import motion_file_analysis

CONTENT = '{"type":"motion_header","fields":["frame","time_sec","id","value"]}\n[1,0.0,"a",1.0]\n'


def test_unchanged_files_are_not_parsed_again(tmp_path, monkeypatch):
    motion_file_analysis._SUMMARY_CACHE.clear()
    path = tmp_path / 'a.json'
    path.write_text(CONTENT, encoding='utf-8')
    calls = []
    real = motion_file_analysis.analyze_motion_json
    monkeypatch.setattr(
        motion_file_analysis, 'analyze_motion_json',
        lambda content, *, include_records: calls.append(include_records) or real(content, include_records=include_records),
    )

    first = motion_file_analysis.motion_file_entry(path, include_detail=False)
    second = motion_file_analysis.motion_file_entry(path, include_detail=False)

    assert calls == [False]
    assert first['analysis'] == second['analysis']
    second['analysis']['valid'] = 'changed by caller'
    assert motion_file_analysis.motion_file_entry(path, include_detail=False)['analysis']['valid'] is True


def test_a_changed_file_is_read_again_and_detail_is_never_cached(tmp_path, monkeypatch):
    motion_file_analysis._SUMMARY_CACHE.clear()
    path = tmp_path / 'a.json'
    path.write_text(CONTENT, encoding='utf-8')
    calls = []
    real = motion_file_analysis.analyze_motion_json
    monkeypatch.setattr(
        motion_file_analysis, 'analyze_motion_json',
        lambda content, *, include_records: calls.append(include_records) or real(content, include_records=include_records),
    )

    motion_file_analysis.motion_file_entry(path, include_detail=False)
    path.write_text(CONTENT + '[2,0.02,"a",2.0]\n', encoding='utf-8')
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    refreshed = motion_file_analysis.motion_file_entry(path, include_detail=False)
    motion_file_analysis.motion_file_entry(path, include_detail=True)

    assert calls == [False, False, True]
    assert refreshed['analysis']['valid_records'] == 2
