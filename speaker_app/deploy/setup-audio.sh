#!/usr/bin/env bash
# 사운드 장치 독점 설정 — 새 PC 설치 시 1회만 실행한다.
#
# 이 앱은 aplay(ALSA)로 장치를 직접 연다. PulseAudio가 같은 장치를 붙잡고 있으면
# aplay가 "Device or resource busy"로 실패해 소리가 전혀 나지 않는다.
# 스피커 전용 PC이므로 PulseAudio를 봉인해 장치를 앱 전용으로 만든다.
# (데스크톱 소리는 나지 않게 된다 — 의도한 동작이다)

set -e

systemctl --user mask --now speech-dispatcher.service speech-dispatcher.socket
systemctl --user mask --now pulseaudio.service pulseaudio.socket
pkill -x pulseaudio || true

# 클라이언트가 PulseAudio를 되살리지 못하게 한다
mkdir -p "$HOME/.config/pulse"
grep -q '^autospawn' "$HOME/.config/pulse/client.conf" 2>/dev/null \
  || echo 'autospawn = no' >> "$HOME/.config/pulse/client.conf"

echo
echo "완료. 이 PC의 사운드 카드 목록:"
aplay -l | grep '^card' || true
echo
echo "config/speaker.yaml 의 audio.device 를 위 카드 번호에 맞춰라."
echo "  예) card 1, device 0  ->  plughw:1,0"
echo "웹 UI 설정에서 바꿔도 된다."
