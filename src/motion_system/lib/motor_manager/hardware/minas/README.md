# minas

Panasonic MINAS driver mapping for `motor_manager`.

`minas::MinasDriver` derives from `motor_interface::MotorDriver` and provides:

- YAML loading for MINAS SDO items and PDO interfaces
- CiA402-style enable/disable state transitions
- set-point acknowledge handling
- raw/physical unit conversion for position, velocity, and effort

Select this driver with:

```yaml
drivers:
  - id: 0
    type: minas
    param_file: ../param
```

The driver loads `<param_file>/minas.yaml`.

## Configuration values used by the driver

The following `driver_config_t` fields are substituted into YAML items when matching semantic IDs are found:

| Semantic ID | Value source | Conversion |
| --- | --- | --- |
| `ID_MAX_EFFORT` | `unit_effort` | `2.0 / unit_effort * 100.0` as `uint16_t`. |
| `ID_MIN_POSITION_LIMIT` | `lower` | degrees to encoder counts. |
| `ID_MAX_POSITION_LIMIT` | `upper` | degrees to encoder counts. |
| `ID_MAX_MOTOR_SPEED` | `speed` | copied as `uint32_t`. |
| `ID_PROFILE_VELOCITY` | `profile_velocity` | degree/s to counts. |
| `ID_PROFILE_ACCELERATION` | `profile_acceleration` | degree/s^2 to counts. |
| `ID_PROFILE_DECELERATION` | `profile_deceleration` | degree/s^2 to counts. |
| `ID_MAX_ACCELERATION` | `acceleration` | degree/s^2 to counts. |
| `ID_MAX_DECELERATION` | `deceleration` | degree/s^2 to counts. |

Other YAML item values are copied according to their declared `type`.

## YAML format

```yaml
items:
  - { id: 30, index: 0x6060, subindex: 0x00, size: 1, value: 1, type: s8 }
interfaces:
  - { id: 98, index: 0x1600 }
  - { id: 0, index: 0x6040, subindex: 0x00, size: 2, type: u16 }
  - { id: 99, index: 0x1A00 }
  - { id: 4, index: 0x6041, subindex: 0x00, size: 2, type: u16 }
```

`ID_RXPDO` (`98`) and `ID_TXPDO` (`99`) are marker rows. Other rows become PDO entries. RX entries are counted when `id <= ID_TARGET_EFFORT`; remaining entries are counted as TX entries.

## Runtime behavior

| Function | Description |
| --- | --- |
| `loadParameters(param_file)` | Loads `items` and `interfaces` from YAML and fills driver entry tables. |
| `isEnabled(data, driver_state, out)` | Advances the CiA402 state machine from `Fault` through `OperationEnabled`. |
| `isDisabled(data, driver_state, out)` | Writes the current disable command until `SwitchOnDisabled` is reached. |
| `isReceived(data, out)` | When set-point acknowledge is present, writes `0x000F` to `out` and returns `true`. |
| `position(int32_t)` / `position(double)` | Converts encoder counts to degrees and degrees to counts. |
| `velocity(int32_t)` / `velocity(double)` | Converts count-based velocity to degree/s and degree/s to counts. |
| `effort(int16_t)` / `effort(double)` | Converts raw effort to Nm and Nm to raw effort. |

## Controlword values

The implementation uses MINAS-specific controlword constants internally:

| Name | Value |
| --- | --- |
| `CW_SHUTDOWN` | `0x0006` |
| `CW_SWITCH_ON` | `0x0007` |
| `CW_ENABLE_OPERATION` | `0x000F` |
| `CW_DISABLE_VOLTAGE` | `0x0000` |
| `CW_DISABLE_OPERATION` | `0x0007` |
| `CW_FAULT_RESET` | `0x0080` |
