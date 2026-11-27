string group_id
string pc_id
string boot_id
string display_name
uint64 sequence
builtin_interfaces/Time sent_at
bool joined
bool is_master
bool execution_active
string execution_id
uint32 cycle_number
string state
string trigger_sync_state
float64 trigger_sync_uncertainty_ms
int32 servo_alarm_grade
string motion_phase
string display_step
float64 motion_elapsed_sec
float64 motion_duration_sec
float64 motion_progress_ratio
uint32 current_cycle
string operation_mode
string web_url
uint32 protocol_version
# 그룹을 지금 시작 못 하는 이유(설정 없음 · 모터 끊김 · 조그 · 페이더 · 단독 재생) · 비면 됨 ·
# 마스터가 선택 때 미리 뺀다 · 약속 번호 8 · 2026-10-14 · 수정 목록 136
string start_blocker
# 시간표 재생 · 이 PC 가 가진 그룹 설정 버전 · 상태 JSON(가장 긴 클립 + 초기 이동 · 따르는 시간표 · 회차 · 단계 ·
# 쉬는 이유) · 마스터가 자동 회차 간격 · PC 별 상태 표시에 쓴다 · 2026-11-09 · 수정 목록 186 · 약속 번호 13
uint64 timetable_version
string timetable_report
