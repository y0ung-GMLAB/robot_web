"""Blender 내보내기 파일(헤더 + 대괄호 행 · JSON Lines)에 「경고 · strict JSON 형식은 아니지만…」 · 수정 목록 120 (S-8)

그 형식이 표준 모션 파일이다(웹 녹화도 같은 형식) · 경고가 아니라 알림(notes)으로.
첫 줄이 motion_header 가 아닌 다른 헤더+행 텍스트는 그대로 경고.
"""

from motion_web_bridge import motion_file_analysis

BLENDER = (
    '{"title":"t","type":"motion_header","rotation_unit":"rad","fields":["frame","time_sec","id","value"]}\n'
    '[1, 0.0, "Neck_Yaw", 0.0, "Neck_Pitch", 0.0]\n'
    '[2, 0.02, "Neck_Yaw", 0.001, "Neck_Pitch", 0.0]\n'
)


def test_blender_jsonl_gives_note_not_warning():
    result = motion_file_analysis.analyze_motion_json(BLENDER, include_records=False)
    assert result['valid'] is True
    assert result['warnings'] == []
    assert any('JSON Lines' in note for note in result['notes'])


def test_other_header_text_still_warns():
    text = 'frame,time_sec,id,value\n[1, 0.0, "a", 0.0]\n[2, 0.02, "a", 0.0]\n'
    result = motion_file_analysis.analyze_motion_json(text, include_records=False)
    assert result['total_records'] == 2
    assert any('strict JSON' in warning for warning in result['warnings'])
    assert result['notes'] == []
