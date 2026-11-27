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
# 초기 위치 이동 시간(초) · 마스터 재생 화면에서 고른 5/7/10 · 0 이면 PC마다 조인트 매핑 값 · 2026-10-12
float64 initial_move_time_sec
# 구간 재생 · 재생 목록 1번을 이 파일 시각(초)부터 · 2026-10-16 · 약속 번호 10
# 0 이면 처음부터 · PC 마다 제 1번을 같은 시각으로 자른다 · 스피커는 음원을 이 시각부터 튼다
float64 segment_start_sec
# 구간 끝(파일 시각 · 초) · 0 이면 끝까지 · 스피커는 (끝 − 시작) 초 뒤 멈춘다
float64 segment_end_sec
# 진행 PC 의 운영시간이 끝나는 시각(유닉스 초) · 0 = 운영시간 아님 · 2026-11-08 · 약속 번호 12
# 진행 PC 가 안 보일 때 참가 PC 는 제 스케줄 대신 이 값으로 스스로 이을지 정한다 · 수정 목록 182
float64 operating_until_unix_sec
