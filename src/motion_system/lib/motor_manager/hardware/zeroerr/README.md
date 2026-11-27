# Zeroerr

## English Version

`zeroerr` is a hardware driver library for controlling ZeroErr eRob motors with `motor_manager`.

`ZeroerrDriver` derives from `motor_interface::MotorDriver`.

### Configuration

Example:

```yaml
drivers:
  - id: 0
    pulse_per_revolution: 524288
    rated_effort: 25.0
    unit_effort: 0.001
    lower: -57.2957795131
    upper: 57.2957795131
    speed: 2000
    acceleration: 85.9436692696
    deceleration: 85.9436692696
    profile_velocity: 85.9436692696
    profile_acceleration: 85.9436692696
    profile_deceleration: 85.9436692696
    profile_position_value: 1
    profile_velocity_value: 3
    profile_effort_value: 4
    type: zeroerr
    param_file: ../param
```

### Parameter

Example:

```yaml
items:
  - { id: 30, index: 0x6060, subindex: 0x00, size: 1, value: 1,       type: s8  } # Operation Mode
  - { id: 31, index: 0x607F, subindex: 0x00, size: 4, value: 2000000, type: u32 } # Max profile velocity
  - { id: 51, index: 0x607D, subindex: 0x01, size: 4, value: 0,       type: s32 } # Min software position limit
  - { id: 52, index: 0x607D, subindex: 0x02, size: 4, value: 0,       type: s32 } # Max software position limit
  - { id: 54, index: 0x6081, subindex: 0x00, size: 4, value: 0,       type: u32 } # Profile velocity
  - { id: 55, index: 0x6083, subindex: 0x00, size: 4, value: 0,       type: u32 } # Profile acceleration
  - { id: 56, index: 0x6084, subindex: 0x00, size: 4, value: 0,       type: u32 } # Profile deceleration

interfaces:
  - { id: 98, index: 0x1600                                     } # RxPDO
  - { id: 0,  index: 0x6040, subindex: 0x00, size: 2, type: u16 } # Controlword
  - { id: 1,  index: 0x607A, subindex: 0x00, size: 4, type: s32 } # Target position
  - { id: 2,  index: 0x60FF, subindex: 0x00, size: 4, type: s32 } # Target velocity
  - { id: 3,  index: 0x6071, subindex: 0x00, size: 2, type: s16 } # Target effort
  - { id: 99, index: 0x1A00                                     } # TxPDO
  - { id: 4,  index: 0x6041, subindex: 0x00, size: 2, type: u16 } # Statusword
  - { id: 5,  index: 0x603F, subindex: 0x00, size: 2, type: u16 } # Error code
  - { id: 6,  index: 0x6064, subindex: 0x00, size: 4, type: s32 } # Position actual value
  - { id: 7,  index: 0x606C, subindex: 0x00, size: 4, type: s32 } # Velocity actual value
  - { id: 8,  index: 0x6077, subindex: 0x00, size: 2, type: s16 } # Effort actual value
```

### Entries

#### Items

| Name                        | Index    | Sub-index | Type  | ID   |
| --------------------------- | -------- | --------- | ----- | ---- |
| Operation mode              | `0x6060` | `0x00`    | `s8`  | `30` |
| Max profile velocity        | `0x607F` | `0x00`    | `u32` | `31` |
| Min software position limit | `0x607D` | `0x01`    | `s32` | `51` |
| Max software position limit | `0x607D` | `0x02`    | `s32` | `52` |
| Profile velocity            | `0x6081` | `0x00`    | `u32` | `54` |
| Profile acceleration        | `0x6083` | `0x00`    | `u32` | `55` |
| Profile deceleration        | `0x6084` | `0x00`    | `u32` | `56` |

#### Interfaces

| Name                  | Index    | Sub-index | Type  | ID   |
| --------------------- | -------- | --------- | ----- | ---- |
| RxPDO                 | `0x1600` |           |       | `98` |
| Controlword           | `0x6040` | `0x00`    | `u16` | `0`  |
| Target position       | `0x607A` | `0x00`    | `s32` | `1`  |
| Target velocity       | `0x60FF` | `0x00`    | `s32` | `2`  |
| Target effort         | `0x6071` | `0x00`    | `s16` | `3`  |
| TxPDO                 | `0x1A00` |           |       | `99` |
| Statusword            | `0x6041` | `0x00`    | `u16` | `4`  |
| Error code            | `0x603F` | `0x00`    | `u16` | `5`  |
| Position actual value | `0x6064` | `0x00`    | `s32` | `6`  |
| Velocity actual value | `0x606C` | `0x00`    | `s32` | `7`  |
| Effort actual value   | `0x6077` | `0x00`    | `s16` | `8`  |

## Korean Version

`zeroerr`은 ZeroErr 사의 eRob 모터를 `motor_manager`에서 제어하기 위한 하드웨어 드라이버 라이브러리이다.

`ZeroerrDriver`는 `motor_interface::MotorDriver`를 상속한다.

### Configuration

예시:

```yaml
drivers:
  - id: 0
    pulse_per_revolution: 524288
    rated_effort: 25.0
    unit_effort: 0.001
    lower: -57.2957795131
    upper: 57.2957795131
    speed: 2000
    acceleration: 85.9436692696
    deceleration: 85.9436692696
    profile_velocity: 85.9436692696
    profile_acceleration: 85.9436692696
    profile_deceleration: 85.9436692696
    profile_position_value: 1
    profile_velocity_value: 3
    profile_effort_value: 4
    type: zeroerr
    param_file: ../param
```

### Parameter

예시:

```yaml
items:
  - { id: 30, index: 0x6060, subindex: 0x00, size: 1, value: 1,       type: s8  } # Operation Mode
  - { id: 31, index: 0x607F, subindex: 0x00, size: 4, value: 2000000, type: u32 } # Max profile velocity
  - { id: 51, index: 0x607D, subindex: 0x01, size: 4, value: 0,       type: s32 } # Min software position limit
  - { id: 52, index: 0x607D, subindex: 0x02, size: 4, value: 0,       type: s32 } # Max software position limit
  - { id: 54, index: 0x6081, subindex: 0x00, size: 4, value: 0,       type: u32 } # Profile velocity
  - { id: 55, index: 0x6083, subindex: 0x00, size: 4, value: 0,       type: u32 } # Profile acceleration
  - { id: 56, index: 0x6084, subindex: 0x00, size: 4, value: 0,       type: u32 } # Profile deceleration

interfaces:
  - { id: 98, index: 0x1600                                     } # RxPDO
  - { id: 0,  index: 0x6040, subindex: 0x00, size: 2, type: u16 } # Controlword
  - { id: 1,  index: 0x607A, subindex: 0x00, size: 4, type: s32 } # Target position
  - { id: 2,  index: 0x60FF, subindex: 0x00, size: 4, type: s32 } # Target velocity
  - { id: 3,  index: 0x6071, subindex: 0x00, size: 2, type: s16 } # Target effort
  - { id: 99, index: 0x1A00                                     } # TxPDO
  - { id: 4,  index: 0x6041, subindex: 0x00, size: 2, type: u16 } # Statusword
  - { id: 5,  index: 0x603F, subindex: 0x00, size: 2, type: u16 } # Error code
  - { id: 6,  index: 0x6064, subindex: 0x00, size: 4, type: s32 } # Position actual value
  - { id: 7,  index: 0x606C, subindex: 0x00, size: 4, type: s32 } # Velocity actual value
  - { id: 8,  index: 0x6077, subindex: 0x00, size: 2, type: s16 } # Effort actual value
```

### Entries

#### Items

| Name                        | Index    | Sub-index | Type  | ID   |
| --------------------------- | -------- | --------- | ----- | ---- |
| Operation mode              | `0x6060` | `0x00`    | `s8`  | `30` |
| Max profile velocity        | `0x607F` | `0x00`    | `u32` | `31` |
| Min software position limit | `0x607D` | `0x01`    | `s32` | `51` |
| Max software position limit | `0x607D` | `0x02`    | `s32` | `52` |
| Profile velocity            | `0x6081` | `0x00`    | `u32` | `54` |
| Profile acceleration        | `0x6083` | `0x00`    | `u32` | `55` |
| Profile deceleration        | `0x6084` | `0x00`    | `u32` | `56` |

#### Interfaces

| Name                  | Index    | Sub-index | Type  | ID   |
| --------------------- | -------- | --------- | ----- | ---- |
| RxPDO                 | `0x1600` |           |       | `98` |
| Controlword           | `0x6040` | `0x00`    | `u16` | `0`  |
| Target position       | `0x607A` | `0x00`    | `s32` | `1`  |
| Target velocity       | `0x60FF` | `0x00`    | `s32` | `2`  |
| Target effort         | `0x6071` | `0x00`    | `s16` | `3`  |
| TxPDO                 | `0x1A00` |           |       | `99` |
| Statusword            | `0x6041` | `0x00`    | `u16` | `4`  |
| Error code            | `0x603F` | `0x00`    | `u16` | `5`  |
| Position actual value | `0x6064` | `0x00`    | `s32` | `6`  |
| Velocity actual value | `0x606C` | `0x00`    | `s32` | `7`  |
| Effort actual value   | `0x6077` | `0x00`    | `s16` | `8`  |
