# common_motor_interface

## English Version

`common_motor_interface` provides the shared payload type used to exchange
`motion_control_msgs/msg/MotorStatus` data with `motor_manager`.

Each `motor_frame_t` contains the command or status data for one motor
controller.

### Build

```bash
colcon build --packages-select common_motor_interface
```

### API

#### `MAX_INTERFACE_SIZE`

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `MAX_INTERFACE_SIZE` | `uint8_t` | Maximum number of interface IDs that can be used by one control command. | `16` |

#### `motor_frame_t`

`motor_frame_t` is a payload that can hold either motor command data or motor
status data.

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `number_of_target_interfaces` | `uint8_t` | Number of active interface IDs in the current control command. | `0` |
| `target_interface_id` | `uint8_t[]` | Interface IDs used by the current control command. | zeros |
| `controller_index` | `uint8_t` | Unique index of the motor controller. | `0` |
| `controlword` | `uint16_t` | CiA-402 control word. | `0` |
| `statusword` | `uint16_t` | CiA-402 status word. | `0` |
| `errorcode` | `uint16_t` | Driver error code. | `0` |
| `position` | `double` | Position value, such as degrees or millimeters. | `0` |
| `velocity` | `double` | Velocity value, such as degrees per second or millimeters per second. | `0` |
| `effort` | `double` | Effort value, such as Nm or N. | `0` |

### Usage

```cpp
#include "common_motor_interface/motor_frame.hpp"
#include "motor_interface/motor_driver.hpp"

motor_interface::motor_frame_t frame{};
frame.controller_index = 0;
frame.number_of_target_interfaces = 2;
frame.target_interface_id[0] = motor_interface::ID_CONTROLWORD;
frame.target_interface_id[1] = motor_interface::ID_TARGET_POSITION;
frame.controlword = 0x000F;
frame.position = 1.0;
```

## Korean Version

ROS2의 `motor_status_msg`의 데이터를 `motor_manager`에게 공유할 때 사용하는
인터페이스.

한 개의 모터의 상태 혹은 명령을 담는다.

### Build

```bash
colcon build --packages-select common_motor_interface
```

### API

#### `MAX_INTERFACE_SIZE`

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `MAX_INTERFACE_SIZE` | `uint8_t` | 현재 제어 입력에서 사용할 인터페이스 수의 최대값 | `16` |

#### `motor_frame_t`

`motor_frame_t`는 모터의 상태나 명령을 담을 수 있는 페이로드이다.

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `number_of_target_interfaces` | `uint8_t` | 현재 제어 입력에서 사용할 인터페이스 수 | `0` |
| `target_interface_id` | `uint8_t[]` | 현재 제어 입력에서 사용할 인터페이스 ID | zeros |
| `controller_index` | `uint8_t` | 제어할 `motor_controller` 인덱스 | `0` |
| `controlword` | `uint16_t` | CiA-402 control word | `0` |
| `statusword` | `uint16_t` | CiA-402 status word | `0` |
| `errorcode` | `uint16_t` | 드라이버의 에러 코드 | `0` |
| `position` | `double` | 위치 값 (e.g. degree, mm) | `0` |
| `velocity` | `double` | 속도 값 (e.g. degree/s, mm/s) | `0` |
| `effort` | `double` | 힘 값 (e.g. Nm, N) | `0` |

### Usage

```cpp
#include "common_motor_interface/motor_frame.hpp"
#include "motor_interface/motor_driver.hpp"

motor_interface::motor_frame_t frame{};
frame.controller_index = 0;
frame.number_of_target_interfaces = 2;
frame.target_interface_id[0] = motor_interface::ID_CONTROLWORD;
frame.target_interface_id[1] = motor_interface::ID_TARGET_POSITION;
frame.controlword = 0x000F;
frame.position = 1.0;
```
