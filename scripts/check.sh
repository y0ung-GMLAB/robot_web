#!/usr/bin/env bash
# 설치 확인 · 이 PC 가 전시 준비가 됐는지 한 장으로 · 로봇 PC · 스피커 PC 자동 구분 · docs/설치_101.md 6
#
#   로봇 PC   · bash ~/ros2_ws/scripts/check.sh
#   스피커 PC · bash ~/robot_web/scripts/check.sh
#
# 바꾸는 것 없음 · 읽기만 · 몇 번 쳐도 된다 · [확인] 줄만 보면 된다
# 사람 눈으로만 알 수 있는 것(BIOS · 소리 · 모터 움직임)은 끝에 따로 적는다
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
FAILED=0

row() {
  local ok="$1" what="$2" detail="$3"
  if [[ "${ok}" == "1" ]]; then
    printf '  [OK]   %s · %s\n' "${what}" "${detail}"
  else
    printf '  [확인] %s · %s\n' "${what}" "${detail}"
    FAILED=$((FAILED + 1))
  fi
}
info() { printf '  [정보] %s · %s\n' "$1" "$2"; }
http_json() { curl -s --max-time 5 "$1" 2>/dev/null || true; }
# JSON 에서 값 하나 · 점으로 이은 경로 · 없으면 빈 문자열
jget() {
  python3 -c '
import json, sys
try:
    value = json.loads(sys.argv[1])
    for key in sys.argv[2].split("."):
        value = value[int(key)] if isinstance(value, list) else value.get(key)
    print("" if value is None else (json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value))
except Exception:
    print("")
' "$1" "$2"
}

if systemctl --user cat motion-control.service >/dev/null 2>&1; then
  ROLE=robot
elif systemctl --user cat speaker-app.service >/dev/null 2>&1; then
  ROLE=speaker
else
  ROLE=none
fi

echo "========================================="
echo "설치 확인 · $(hostname) · $(date '+%Y-%m-%d %H:%M')"
echo "========================================="

echo "공통"
ip_addr="$(ip -o -4 route get 1.1.1.1 2>/dev/null | awk '{for (i = 1; i <= NF; i++) if ($i == "src") print $(i + 1)}' || true)"
row "$([[ -n "${ip_addr}" ]] && echo 1 || echo 0)" "공유기 연결 (IP)" "${ip_addr:-없음 · 랜선·Wi-Fi 확인}"
case "${ROLE}" in
  robot) row 1 "역할" "로봇 PC" ;;
  speaker) row 1 "역할" "스피커 PC" ;;
  *) row 0 "역할" "설치 안 됨 · docs/설치_101.md 2 또는 3" ;;
esac
head_line="$(git -C "${WORKSPACE_DIR}" log --oneline -1 2>/dev/null || echo '')"
if timeout 15 git -C "${WORKSPACE_DIR}" fetch -q origin main 2>/dev/null; then
  if [[ "$(git -C "${WORKSPACE_DIR}" rev-parse HEAD 2>/dev/null)" == "$(git -C "${WORKSPACE_DIR}" rev-parse origin/main 2>/dev/null)" ]]; then
    row 1 "코드 (최신 main)" "${head_line}"
  else
    row 0 "코드 (최신 main)" "${head_line} · 최신 아님 · 갱신 · docs/설치_101.md 5"
  fi
else
  info "코드" "${head_line:-git 아님} · 인터넷이 안 돼 최신인지 못 봄"
fi
row "$(loginctl show-user "$(id -un)" 2>/dev/null | grep -q '^Linger=yes' && echo 1 || echo 0)" "로그아웃해도 유지 (linger)" "$(loginctl show-user "$(id -un)" 2>/dev/null | grep '^Linger=' || echo 미상)"
row "$(systemctl is-enabled unattended-upgrades 2>/dev/null | grep -q masked && echo 1 || echo 0)" "자동 업데이트 꺼짐" "$(systemctl is-enabled unattended-upgrades 2>/dev/null; true)"
info "시간대" "$(timedatectl show -p Timezone --value 2>/dev/null || echo 미상) · $(date '+%H:%M')"

if [[ "${ROLE}" == "robot" ]]; then
  echo
  echo "로봇 PC"
  if [[ -f /etc/gdm3/custom.conf ]] && grep -q '^AutomaticLoginEnable=true' /etc/gdm3/custom.conf; then
    row 1 "자동 로그인" "$(grep '^AutomaticLogin=' /etc/gdm3/custom.conf)"
  else
    row 0 "자동 로그인" "꺼짐 · bash ${WORKSPACE_DIR}/scripts/install.sh --site"
  fi
  rt="$(ulimit -r 2>/dev/null || echo 0)"
  row "$([[ "${rt}" == "unlimited" || "${rt}" -ge 99 ]] && echo 1 || echo 0)" "실시간 권한 (ulimit -r)" "${rt} (99 필요 · 재부팅 뒤 적용)"
  if command -v mokutil >/dev/null 2>&1; then
    sb="$(mokutil --sb-state 2>/dev/null | head -1 || true)"
    row "$(printf '%s' "${sb}" | grep -qi enabled && echo 0 || echo 1)" "Secure Boot 꺼짐" "${sb:-미상} · 켜져 있으면 BIOS 에서 끄기"
  fi
  for unit in motion-control motion-coordination motion-motor; do
    state="$(systemctl --user is-active "${unit}.service" 2>/dev/null; true)"
    detail="${state:-unknown}"
    [[ "${unit}" == "motion-motor" && "${state}" != "active" ]] && detail="${detail} · 모터 설정 적용 전이면 정상(웹 모터 관리 → 저장 → 장비에 적용)"
    row "$([[ "${state}" == "active" ]] && echo 1 || echo 0)" "${unit}" "${detail}"
  done
  if ethercat master >/dev/null 2>&1; then
    phase="$(ethercat master 2>/dev/null | awk -F: '/Phase/ { gsub(/^ +/, "", $2); print $2; exit }')"
    slaves="$(ethercat slaves 2>/dev/null | wc -l)"
    row 1 "EtherCAT master" "${phase:-?}"
    row "$([[ "${slaves}" -gt 0 ]] && echo 1 || echo 0)" "EtherCAT 드라이브" "${slaves}대 · 0 이면 드라이브 전원·모터 랜선"
  else
    row 0 "EtherCAT master" "응답 없음 · Secure Boot · sudo systemctl status ethercat"
  fi

  status="$(http_json http://localhost:8000/api/status)"
  row "$([[ -n "${status}" ]] && echo 1 || echo 0)" "웹 :8000" "$([[ -n "${status}" ]] && echo "http://${ip_addr:-localhost}:8000" || echo '응답 없음 · motion-control')"
  if [[ -n "${status}" ]]; then
    absolute="$(jget "${status}" minas_absolute_blocker)"
    row "$([[ -z "${absolute}" ]] && echo 1 || echo 0)" "앱솔루트 (MINAS)" "${absolute:-정상 또는 MINAS 없음}"
    blocker="$(jget "${status}" motor_action_blocker)"
    if [[ -n "${blocker}" && "${blocker}" != "{}" ]]; then
      info "모터 동작 막힘 사유" "$(printf '%s' "${blocker}" | head -c 140)"
    fi
  fi

  coord="$(http_json http://127.0.0.1:8011/status)"
  if [[ -z "${coord}" ]]; then
    row 0 "PC 연동 서비스" "응답 없음 · motion-coordination"
  else
    pc_id="$(jget "${coord}" config.pc_id)"
    enabled="$(jget "${coord}" config.enabled)"
    group="$(jget "${coord}" config.group_id)"
    domain="$(jget "${coord}" config.dds_domain_id)"
    joined="$(jget "${coord}" joined)"
    row "$([[ "${pc_id}" == "$(hostname)" ]] && echo 1 || echo 0)" "이 PC ID" "${pc_id} $([[ "${pc_id}" == "$(hostname)" ]] && echo '(= 컴퓨터 이름)' || echo "· 컴퓨터 이름 $(hostname) 과 다름 · config/motion_coordination.yaml 의 pc_id")"
    row "$([[ "${enabled}" == "True" && -n "${group}" ]] && echo 1 || echo 0)" "연동 설정" "사용=${enabled} · 그룹=${group:-없음} · Domain=${domain} · 웹 PC 연동 설정"
    row "$([[ "${joined}" == "True" ]] && echo 1 || echo 0)" "그룹 참가" "$([[ "${joined}" == "True" ]] && echo 참가 || echo '나감 · 웹 PC 연동 설정 → 연동 참가')"
    python3 - "${coord}" <<'PY'
import json, sys
pcs = json.loads(sys.argv[1]).get("network_pcs") or []
others = [p for p in pcs if not p.get("is_local")]
def mark(ok):
    return "[OK]  " if ok else "[확인]"
if not pcs:
    print("  [확인] 같은 망 PC · 목록 없음 · 이 PC 코드가 옛것")
else:
    print("  [정보] 같은 망 PC · %d대 보임 (이 PC 빼고 · 로봇 3 + 스피커 1 = 4 가 정상)" % len(others))
    for p in others:
        ok = p.get("online") and not p.get("version_differs") and not p.get("protocol_mismatch")
        role = "스피커" if p.get("role") == "speaker" else ("로봇 · 마스터" if p.get("is_master") else "로봇")
        note = []
        if not p.get("online"):
            note.append("끊김 %ss" % int(p.get("age_sec") or 0))
        if p.get("version_differs"):
            note.append("버전 다름 %s" % p.get("git_hash"))
        if p.get("protocol_mismatch"):
            note.append("약속 번호 %s" % p.get("protocol_version"))
        print("         %s %-12s %-10s %-15s %s" % (mark(ok), p.get("pc_id"), role, p.get("address") or "-", " · ".join(note) or "정상"))
PY
    if python3 -c 'import json,sys; d=json.loads(sys.argv[1]); sys.exit(0 if any((not p.get("is_local")) and not (p.get("online") and not p.get("version_differs") and not p.get("protocol_mismatch")) for p in d.get("network_pcs") or []) else 1)' "${coord}"; then
      FAILED=$((FAILED + 1))
    fi
  fi
fi

if [[ "${ROLE}" == "speaker" ]]; then
  echo
  echo "스피커 PC"
  state="$(systemctl --user is-active speaker-app.service 2>/dev/null; true)"
  row "$([[ "${state}" == "active" ]] && echo 1 || echo 0)" "speaker-app" "${state:-unknown}"
  row "$([[ -f "${WORKSPACE_DIR}/install/motion_coordination_interfaces/share/motion_coordination_interfaces/msg/PcPresence.msg" ]] && echo 1 || echo 0)" "그룹 메시지 빌드" "$([[ -d "${WORKSPACE_DIR}/install/motion_coordination_interfaces" ]] && echo "${WORKSPACE_DIR}/install" || echo '없음 · bash scripts/install_speaker.sh')"
  port="$(python3 -c 'import os,sys; sys.path.insert(0, sys.argv[1] + "/speaker_app/backend"); import config; print(config.load()["web"]["port"])' "${WORKSPACE_DIR}" 2>/dev/null || echo 8100)"
  # 웹 터미널 · 웹 관리 권한 · 로봇 PC 와 같은 것 (수정 목록 89)
  tstate="$(systemctl --user is-active motion-terminal.service 2>/dev/null; true)"
  row "$([[ "${tstate}" == "active" ]] && echo 1 || echo 0)" "웹 터미널 :8081" "${tstate:-없음} $([[ "${tstate}" == "active" ]] || echo '· bash scripts/install_speaker.sh (ttyd 설치 · 관리자 비밀번호)')"
  pkla="/etc/polkit-1/localauthority/50-local.d/50-robot-web.pkla"
  row "$(grep -qs "unix-user:$(id -un)$" "${pkla}" && echo 1 || echo 0)" "웹 Wi-Fi·시간대 권한" "$(grep -qs "unix-user:$(id -un)$" "${pkla}" && echo 있음 || echo '없음 · bash scripts/allow_web_admin.sh')"
  sstate="$(http_json "http://localhost:${port}/api/state")"
  row "$([[ -n "${sstate}" ]] && echo 1 || echo 0)" "스피커 화면 :${port}" "$([[ -n "${sstate}" ]] && echo "http://${ip_addr:-localhost}:${port}" || echo '응답 없음 · journalctl --user -u speaker-app')"
  if [[ -n "${sstate}" ]]; then
    mode="$(jget "${sstate}" mode)"
    row "$([[ "${mode}" == "dds" ]] && echo 1 || echo 0)" "연동 모드" "${mode} $([[ "${mode}" == "dds" ]] || echo '· 스피커 화면 모드 → 연동 모드')"
    init_ok="$(jget "${sstate}" dds_init.ok)"
    dds="$(jget "${sstate}" dds_status)"
    row "$([[ "${init_ok}" == "True" ]] && echo 1 || echo 0)" "DDS 시작" "${init_ok:-?} $(jget "${sstate}" dds_init.error)"
    row "$([[ "${dds}" == "connected" ]] && echo 1 || echo 0)" "로봇 PC 신호" "${dds} $([[ "${dds}" == "connected" ]] || echo '· 로봇 PC 가 켜져 있고 연동 참가했는지 · 그룹 ID · Domain ID')"
    info "그룹 · Domain · 이름" "$(jget "${sstate}" config.group_id) · $(jget "${sstate}" config.domain_id) · $(jget "${sstate}" config.pc_name)"
    files="$(jget "${sstate}" files)"
    count="$(python3 -c 'import json,sys; print(len(json.loads(sys.argv[1] or "[]")))' "${files:-[]}" 2>/dev/null || echo 0)"
    default="$(jget "${sstate}" config.file_name)"
    row "$([[ "${count}" -gt 0 && -n "${default}" ]] && echo 1 || echo 0)" "음원" "${count}개 · 기본 ${default:-없음 · 스피커 화면에서 추가}"
    device="$(jget "${sstate}" config.device)"
    card="$(printf '%s' "${device}" | sed -n 's/^plughw:\([0-9]*\),\([0-9]*\)$/\1 \2/p')"
    if [[ -n "${card}" ]] && aplay -l 2>/dev/null | grep -q "^card ${card% *}:.*device ${card#* }:"; then
      row 1 "출력 장치" "${device} · $(aplay -l 2>/dev/null | grep "^card ${card% *}:.*device ${card#* }:" | head -1 | cut -c1-60)"
    else
      row 0 "출력 장치" "${device} 없음 · 스피커 꽂고 bash scripts/install_speaker.sh 또는 스피커 화면에서 고르기"
    fi
  fi
fi

echo
if [[ "${FAILED}" -eq 0 ]]; then
  echo "결과 · 모두 OK"
else
  echo "결과 · [확인] ${FAILED}개 · 그 줄의 안내대로 하고 다시 실행"
fi
echo
echo "👤 사람 눈으로 확인 (이 스크립트가 못 봄)"
echo "  · 전원 케이블을 뽑았다 꽂으면 저절로 켜지고 화면이 다시 뜬다 (BIOS 전원 복구)"
if [[ "${ROLE}" == "robot" ]]; then
  echo "  · 애니메이션 한 번 재생 · 튐·처짐 없음 · 마스터면 「같은 망 PC」 에 5대 · 그룹 실행 때 소리 같이"
elif [[ "${ROLE}" == "speaker" ]]; then
  echo "  · 스피커 화면 「기본 음원 테스트 재생」 으로 소리가 난다 · 로봇이 재생하면 소리가 같이 난다"
fi
[[ "${FAILED}" -eq 0 ]]
