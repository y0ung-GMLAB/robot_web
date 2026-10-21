# feetech

- Feetech STS 직렬 버스 서보 드라이버 · robot_web 수정 목록 158 (2026-10-21)
- 구조 · `FeetechDriver` = `DynamixelDriver` 와 같은 param yaml · 모델 파일 방식 · param yaml `protocol.packet: scs` 필수
- 패킷 · `FF FF ID LEN INST 파라미터 CHK` · CHK = ~(ID + LEN + INST + 파라미터) · 주소 1 바이트
- 묶음 · Sync Read 0x82 · Sync Write 0x83
- 금지 · Torque Enable 128(현재 위치를 중앙으로 보정) · RESET 0x06(공장 초기화) · 이 드라이버는 둘 다 보내지 않음
- 위치 · 0~4095 = 한 바퀴 · 2048 = 0° · 부호-크기(bit 15) · `sign_bit: 15`
- 제어표 · `control_table/sts.model` · 공개 SDK·LeRobot 표 기준 · **실물 미검증**
- 모델 번호 · `control_table/feetech.model` · 777 STS3215 · 2825 STS3250
- 실물 확인 · `docs/SERIAL_SERVO_DESIGN.md` §9 F-1~F-5
