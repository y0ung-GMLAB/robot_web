# 같은 공유기 망의 PC 알림 · 그룹 참가와 상관없이 2초마다 · 마스터 화면 「같은 망 PC」 표
# 로봇 PC(연동 노드)와 스피커 PC(speaker_app)가 보낸다 · 같은 DDS 도메인이어야 보인다
# 새 메시지라 기존 그룹 메시지 형식(약속 번호)과는 상관없다
string pc_id
string display_name
# robot | speaker
string role
string address
string web_url
string group_id
bool joined
bool is_master
string boot_id
string git_hash
uint32 protocol_version
builtin_interfaces/Time sent_at
