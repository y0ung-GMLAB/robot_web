string group_id
string execution_id
string command_id
string coordinator_id
string command
uint64 sequence
uint32 cycle_number
builtin_interfaces/Time sent_at
int64 scheduled_monotonic_ns
string[] participant_ids
string repeat_mode
float64 dwell_sec
bool initialization_only
string run_mode
uint32 target_cycle_count
string sync_mode
string stop_reason
# 스피커 연동 · 수정 목록 38 · 2026-10-07
# 이 시작의 애니메이션 파일(마스터 · PC 1대면 그 PC) · 스피커가 애니메이션마다 음원을 고른다
string motion_file_id
# 이 메시지를 보낸 순간부터 모션 시작까지 남은 초 · 그룹은 +(미리 보냄) · PC 1대는 -(이미 시작)
# 스피커는 받은 시각 + 이 값 + 자기 오프셋에 재생한다 · 두 경우 시각이 같아진다
float64 start_delay_sec
