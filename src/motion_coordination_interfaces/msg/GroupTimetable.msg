# 시간표 재생 · 그룹 설정 묶음 · 마스터가 바꿀 때 + 2 s 마다 · 2026-11-09 · 수정 목록 186 · 약속 번호 13
# 받은 PC 는 버전이 높으면(같은 버전 내용이 다르면 이름이 앞인 마스터 것) 디스크에 저장하고 따른다
string group_id
string pc_id
string boot_id
uint64 version
# 묶음 내용 · JSON(`motion_coordination.timetable.to_body`) · 재생 방식 · 회차 간격 · 운영시간 · 수동 시작 · 정지
string body
uint32 protocol_version
