"""3D 계산 임시 파일(`x.sim.pending.json`)이 애니메이션 목록에 「오류」 로 보이던 것 · 수정 목록 120 (마)

실물 2026-10-13 S-8 · 업로드 뒤 3D 계산 시작 → 목록에 `floating4_dir_test.sim.pending.json` ·
「오류 · motion data rows not found」 · 3D 준비됨 뒤에도 남음.
계산 기록 두 가지(`.sim.meta.json` · `.sim.pending.json`)는 애니메이션이 아니다.
"""

from pathlib import Path

from motion_web_bridge import animation_preview, motion_file_analysis


class _Repo:
    def __init__(self, project_id):
        self._id = project_id

    def selected_project_id(self):
        return self._id


def test_listing_skips_both_sim_records(tmp_path):
    files_dir = tmp_path / 'p1' / 'motions'
    files_dir.mkdir(parents=True)
    (files_dir / 'show.json').write_text(
        '{"type":"motion_header","rotation_unit":"rad","fields":["frame","time_sec","id","value"]}\n[1,0.0,"a",0.0]\n',
        encoding='utf-8',
    )
    (files_dir / 'show.sim.meta.json').write_text('{}', encoding='utf-8')
    (files_dir / 'show.sim.pending.json').write_text('{}', encoding='utf-8')
    (files_dir / 'show.SIM.PENDING.json').write_text('{}', encoding='utf-8')
    listing = motion_file_analysis.list_motion_files(_Repo('p1'), tmp_path)
    assert [entry['id'] for entry in listing['files']] == ['show.json']


def test_suffixes_match_the_files_preview_writes():
    result = Path('motions/show.sim.npz')
    assert motion_file_analysis.is_sim_record(animation_preview.meta_path_for(result).name)
    assert motion_file_analysis.is_sim_record(animation_preview.pending_path_for(result).name)
    assert not motion_file_analysis.is_sim_record('show.json')
    assert not motion_file_analysis.is_sim_record('simple.json')
