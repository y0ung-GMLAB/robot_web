# motor_interface

## English Version

`motor_interface` provides the C++ abstraction layer used for motor control. It is composed of `MotorMaster`, `MotorController`, and `MotorDriver`.

`MotorMaster` represents a fieldbus master, `MotorController` represents one slave or node connected to that master, and `MotorDriver` separates vendor-specific hardware logic from the controller. Transport-specific driver hooks, such as `serial::SerialDriver` and `socketcan::SocketcanDriver`, are implemented outside this core abstraction.

### Build

```bash
colcon build --packages-select motor_manager
```

### API

#### `MotorMaster`

`MotorMaster` holds one fieldbus master.

##### `MAX_MASTER_SIZE`

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `MAX_MASTER_SIZE` | `uint8_t` | Maximum number of masters that can be configured. | `8` |

##### `master_config_t`

`master_config_t` is used to initialize a master and stores master-specific configuration.

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `id` | `uint8_t` | Master ID. | `0` |
| `number_of_slaves` | `uint8_t` | Number of controllers owned by the master. | `0` |
| `ethercat_master_index` | `unsigned int` | EtherCAT-only master index. | `0` |
| `can_interface_index` | `unsigned int` | CAN-only device index. | `0` |
| `can_bitrate` | `unsigned int` | CAN-only bitrate value. | `0` |
| `serial_port` | `std::string` | Serial-only port name. | ` ` |
| `serial_baudrate` | `unsigned int` | Serial-only baudrate. | `0` |

##### functions

| Function | Purpose |
| --- | --- |
| `initialize()` | Initialize the master. |
| `activate()` | Start communication. |
| `deactivate()` | Stop communication. |
| `transmit()` | Transmit bus data. |
| `receive()` | Receive bus data. |
| `apply_application_time(time)` | Apply the cycle timestamp. |
| `save_clock()` | Synchronize and save the bus clock. |
| `id()` | Return the master ID. |
| `number_of_slaves()` | Return the number of slaves owned by the master. |

---

#### `MotorController`

`MotorController` holds one slave or node, and each controller owns one master and one driver.

##### `MAX_CONTROLLER_SIZE`

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `MAX_CONTROLLER_SIZE` | `uint8_t` | Maximum number of controllers that can be configured. | `32` |

##### `slave_config_t`

`slave_config_t` is used to initialize a controller and stores controller-specific configuration.

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `controller_index` | `uint8_t` | Motor controller index. | `0` |
| `master_id` | `uint8_t` | ID of the master that owns the controller. | `0` |
| `driver_id` | `uint8_t` | Driver ID used by the controller. | `0` |
| `alias` | `uint16_t` | EtherCAT-only alias value. | `0` |
| `position` | `uint16_t` | EtherCAT-only ring position value. | `0` |
| `vendor_id` | `uint32_t` | EtherCAT-only vendor ID. | `0` |
| `product_id` | `uint32_t` | EtherCAT-only product ID. | `0` |
| `can_id` | `uint8_t` | CANopen or SocketCAN device ID value. | `0` |
| `bus_id` | `uint8_t` | Serial device ID value. | `0` |
| `profile_mode` | `uint8_t` | `0`: position, `1`: velocity, `2`: effort. | `0` |

##### functions

| Function | Purpose |
| --- | --- |
| `initialize()` | Initialize the controller. |
| `enable()` | Put the motor into the `Enable` state. |
| `disable()` | Put the motor into the `Disable` state. |
| `check(status)` | Check the current motor status. |
| `write(command)` | Write a command to the motor. |
| `read(status)` | Read the motor status. |
| `master_id()` | Return the master ID. |
| `driver_id()` | Return the driver ID. |
| `registerEntries()` | Register items and interfaces. |
| `writeData(rx_interfaces, number_of_rx_interfaces)` | Write data to registered interfaces. |
| `readData(tx_interfaces, number_of_tx_interfaces)` | Read data from registered interfaces. |

---

#### `MotorDriver`

`MotorDriver` holds hardware information and separates vendor-provided hardware control logic from `MotorController`.

##### `MAX_DRIVER_SIZE`

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `MAX_DRIVER_SIZE` | `uint8_t` | Maximum number of drivers that can be configured. | `8` |

##### `entry_table_t`

`entry_table_t` stores information for an item configured on the motor or an interface registered for communication.

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `MAX_DATA_SIZE` | `uint8_t` | Maximum data size, for example 4 bytes. | `4` |
| `DataType` | `enum class` | Entry data type, for example `U32`. | ` ` |
| `id` | `uint8_t` | Unique entry ID. | `0` |
| `index` | `uint16_t` | Entry index, for example `0x6040`. | `0` |
| `subindex` | `uint8_t` | Entry subindex, for example `0x01`. | `0` |
| `type` | `DataType` | Entry data type. | ` ` |
| `size` | `uint8_t` | Entry data size. | `0` |
| `data` | `uint8_t[MAX_DATA_SIZE]` | Entry data buffer. | zeros |

##### `MAX_ITEM_SIZE`

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `MAX_ITEM_SIZE` | `uint8_t` | Maximum number of items that can be configured on one motor. | `32` |

##### `Entry IDs`

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `ID_CONTROLWORD` | `uint8_t` | Entry ID for the CiA-402 control word. | `0` |
| `ID_TARGET_POSITION` | `uint8_t` | Entry ID for target position. | `1` |
| `ID_TARGET_VELOCITY` | `uint8_t` | Entry ID for target velocity. | `2` |
| `ID_TARGET_EFFORT` | `uint8_t` | Entry ID for target effort. | `3` |
| `ID_STATUSWORD` | `uint8_t` | Entry ID for the CiA-402 status word. | `4` |
| `ID_ERRORCODE` | `uint8_t` | Entry ID for the driver error code. | `5` |
| `ID_CURRENT_POSITION` | `uint8_t` | Entry ID for current position. | `6` |
| `ID_CURRENT_VELOCITY` | `uint8_t` | Entry ID for current velocity. | `7` |
| `ID_CURRENT_EFFORT` | `uint8_t` | Entry ID for current effort. | `8` |
| `ID_TARGET_KP` | `uint8_t` | Entry ID for target proportional gain. | `9` |
| `ID_TARGET_KD` | `uint8_t` | Entry ID for target derivative gain. | `10` |
| `ID_CURRENT_TEMPERATURE` | `uint8_t` | Entry ID for current temperature. | `11` |
| `ID_OPERATING_MODE` | `uint8_t` | Entry ID for operation mode. | `30` |
| `ID_MAX_EFFORT` | `uint8_t` | Entry ID for max effort. | `50` |
| `ID_MIN_POSITION_LIMIT` | `uint8_t` | Entry ID for the minimum position limit. | `51` |
| `ID_MAX_POSITION_LIMIT` | `uint8_t` | Entry ID for the maximum position limit. | `52` |
| `ID_MAX_MOTOR_SPEED` | `uint8_t` | Entry ID for max motor speed. | `53` |
| `ID_PROFILE_VELOCITY` | `uint8_t` | Entry ID for profile velocity. | `54` |
| `ID_PROFILE_ACCELERATION` | `uint8_t` | Entry ID for profile acceleration. | `55` |
| `ID_PROFILE_DECELERATION` | `uint8_t` | Entry ID for profile deceleration. | `56` |
| `ID_MAX_ACCELERATION` | `uint8_t` | Entry ID for max acceleration. | `57` |
| `ID_MAX_DECELERATION` | `uint8_t` | Entry ID for max deceleration. | `58` |
| `ID_RXPDO` | `uint8_t` | Entry ID for RXPDO. | `98` |
| `ID_TXPDO` | `uint8_t` | Entry ID for TXPDO. | `99` |

##### `DriverState`

`DriverState` is an enum class that stores the current driver state.

It contains the following values: `Fault`, `SwitchOnDisabled`, `ReadyToSwitchOn`, `SwitchedOn`, `OperationEnabled`.

##### `driver_config_t`

`driver_config_t` stores vendor-provided hardware information and is used when initializing a driver.

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `id` | `uint8_t` | Driver ID. | `0` |
| `pulse_per_revolution` | `uint32_t` | Number of pulses per revolution. | `0` |
| `rated_effort` | `double` | Rated effort, such as Nm or N. | `0` |
| `unit_effort` | `double` | Unit scale per rated effort. | `0` |
| `lower` | `double` | Minimum position limit, such as degree or mm. | `0` |
| `upper` | `double` | Maximum position limit, such as degree or mm. | `0` |
| `speed` | `double` | Speed limit, such as degree/s or mm/s. | `0` |
| `acceleration` | `double` | Acceleration limit, such as degree/s^2 or mm/s^2. | `0` |
| `deceleration` | `double` | Deceleration limit, such as degree/s^2 or mm/s^2. | `0` |
| `profile_velocity` | `double` | Profile velocity, such as degree/s or mm/s. | `0` |
| `profile_acceleration` | `double` | Profile acceleration, such as degree/s^2 or mm/s^2. | `0` |
| `profile_deceleration` | `double` | Profile deceleration, such as degree/s^2 or mm/s^2. | `0` |
| `profile_position_value` | `int8_t` | Operation-mode value for profile position mode. | `0` |
| `profile_velocity_value` | `int8_t` | Operation-mode value for profile velocity mode. | `0` |
| `profile_effort_value` | `int8_t` | Operation-mode value for profile effort mode. | `0` |

##### functions

| Function | Purpose |
| --- | --- |
| `loadParameters(param_file)` | Load parameters. |
| `isEnabled(data, driver_state, out)` | Check whether the motor is in the `Enable` state. |
| `isDisabled(data, driver_state, out)` | Check whether the motor is in the `Disable` state. |
| `isReceived(data, out)` | Check whether the motor received the control input correctly. |
| `position(value)` | Return or convert a position value. |
| `velocity(value)` | Return or convert a velocity value. |
| `effort(value)` | Return or convert an effort value. |
| `items()` | Return the items configured on the driver. |
| `interfaces()` | Return the interfaces registered on the driver. |
| `number_of_items()` | Return the number of configured items. |
| `number_of_interfaces()` | Return the number of registered interfaces. |
| `number_of_rx_interfaces()` | Return the number of registered RX interfaces. |
| `number_of_tx_interfaces()` | Return the number of registered TX interfaces. |
| `profile_position_value()` | Return the value used to set profile position mode. |
| `profile_velocity_value()` | Return the value used to set profile velocity mode. |
| `profile_effort_value()` | Return the value used to set profile effort mode. |

> [!NOTE]
> An `item` is an entry used to configure a motor during initialization, such as through SDO. An `interface` is an entry that is continuously transmitted or received, such as through PDO.

## Korean Version

`motor_interface`는 모터 제어를 위한 C++ 추상화 계층이다. `MotorMaster`, `MotorController`, `MotorDriver`로 구성된다.

`MotorMaster`는 필드버스 마스터를 의미하고, `MotorController`는 해당 마스터에 연결된 하나의 슬레이브 혹은 노드를 의미한다. `MotorDriver`는 제조사가 제공하는 하드웨어 제어 로직을 `MotorController`와 분리하는 역할을 한다.

`serial::SerialDriver`, `socketcan::SocketcanDriver` 같은 통신 방식별 드라이버 훅은 이 core 추상화 밖에서 구현한다.

### Build

```bash
colcon build --packages-select motor_manager
```

### API

#### `MotorMaster`

`MotorMaster`는 하나의 필드버스 마스터를 담는다.

##### `MAX_MASTER_SIZE`

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `MAX_MASTER_SIZE` | `uint8_t` | 가능한 마스터 수의 최대값 | `8` |

##### `master_config_t`

`master_config_t`는 마스터를 초기화할 때 사용하며, 마스터의 정보를 담는다.

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `id` | `uint8_t` | 마스터 ID | `0` |
| `number_of_slaves` | `uint8_t` | 마스터가 가질 `controller`의 수 | `0` |
| `ethercat_master_index` | `unsigned int` | EtherCAT 전용 마스터 인덱스 | `0` |
| `can_interface_index` | `unsigned int` | CAN 전용 장치 인덱스 | `0` |
| `can_bitrate` | `unsigned int` | CAN 전용 비트레이트 | `0` |
| `serial_port` | `std::string` | Serial 전용 포트 이름 | ` ` |
| `serial_baudrate` | `unsigned int` | Serial 전용 보드레이트 | `0` |

##### functions

| Function | Purpose |
| --- | --- |
| `initialize()` | 마스터를 초기화한다. |
| `activate()` | 통신을 시작한다. |
| `deactivate()` | 통신을 멈춘다. |
| `transmit()` | 버스 데이터를 전송한다. |
| `receive()` | 버스 데이터를 수신한다. |
| `apply_application_time(time)` | 사이클 타임스텝을 적용한다. |
| `save_clock()` | 버스 시간을 동기화 및 저장한다. |
| `id()` | 마스터 ID를 반환한다. |
| `number_of_slaves()` | 마스터가 가진 슬레이브 수를 반환한다. |

---

#### `MotorController`

`MotorController`는 슬레이브 혹은 노드를 담으며, 하나의 마스터와 하나의 드라이버를 갖는다.

##### `MAX_CONTROLLER_SIZE`

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `MAX_CONTROLLER_SIZE` | `uint8_t` | 가능한 컨트롤러 수의 최대값 | `32` |

##### `slave_config_t`

`slave_config_t`는 컨트롤러를 초기화할 때 사용하며, 컨트롤러의 정보를 담는다.

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `controller_index` | `uint8_t` | `motor_controller` 인덱스 | `0` |
| `master_id` | `uint8_t` | `motor_controller`가 속한 마스터 ID | `0` |
| `driver_id` | `uint8_t` | `motor_controller`의 드라이버 ID | `0` |
| `alias` | `uint16_t` | EtherCAT 전용 alias 값 | `0` |
| `position` | `uint16_t` | EtherCAT 전용 ring position 값 | `0` |
| `vendor_id` | `uint32_t` | EtherCAT 전용 vendor ID 값 | `0` |
| `product_id` | `uint32_t` | EtherCAT 전용 product ID 값 | `0` |
| `can_id` | `uint8_t` | CANopen 혹은 SocketCAN 장치 ID 값 | `0` |
| `bus_id` | `uint8_t` | Serial 장치 ID 값 | `0` |
| `profile_mode` | `uint8_t` | `0`: 위치, `1`: 속도, `2`: 힘 | `0` |

##### functions

| Function | Purpose |
| --- | --- |
| `initialize()` | 컨트롤러를 초기화한다. |
| `enable()` | 모터를 `Enable` 상태로 만든다. |
| `disable()` | 모터를 `Disable` 상태로 만든다. |
| `check(status)` | 현재 모터 상태를 검사한다. |
| `write(command)` | 모터에 명령을 쓴다. |
| `read(status)` | 모터의 상태를 읽는다. |
| `master_id()` | 마스터 ID를 반환한다. |
| `driver_id()` | 드라이버 ID를 반환한다. |
| `registerEntries()` | 아이템과 인터페이스를 등록한다. |
| `writeData(rx_interfaces, number_of_rx_interfaces)` | 등록된 인터페이스에 데이터를 쓴다. |
| `readData(tx_interfaces, number_of_tx_interfaces)` | 등록된 인터페이스의 데이터를 읽는다. |

---

#### `MotorDriver`

`MotorDriver`는 하드웨어 정보를 담으며, 제조사가 제공하는 하드웨어 제어 로직을 `MotorController`와 분리하는 역할을 한다.

##### `MAX_DRIVER_SIZE`

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `MAX_DRIVER_SIZE` | `uint8_t` | 가능한 드라이버 수의 최대값 | `8` |

##### `entry_table_t`

`entry_table_t`는 모터에 설정할 아이템이나 등록한 인터페이스의 정보를 담는 인터페이스이다.

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `MAX_DATA_SIZE` | `uint8_t` | 데이터의 최대 사이즈 (e.g. 4 bytes) | `4` |
| `DataType` | `enum class` | 데이터 타입을 의미하는 enum 클래스 (e.g. `U32`) | ` ` |
| `id` | `uint8_t` | 고유한 엔트리 ID | `0` |
| `index` | `uint16_t` | 엔트리 인덱스 (e.g. `0x6040`) | `0` |
| `subindex` | `uint8_t` | 엔트리 서브 인덱스 (e.g. `0x01`) | `0` |
| `type` | `DataType` | 엔트리 데이터 타입 | ` ` |
| `size` | `uint8_t` | 엔트리 데이터 사이즈 | `0` |
| `data` | `uint8_t[MAX_DATA_SIZE]` | 엔트리 데이터 버퍼 | zeros |

##### `MAX_ITEM_SIZE`

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `MAX_ITEM_SIZE` | `uint8_t` | 모터에 설정 가능한 아이템 수의 최대값 | `32` |

##### `Entry IDs`

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `ID_CONTROLWORD` | `uint8_t` | CiA-402 control word의 엔트리 ID | `0` |
| `ID_TARGET_POSITION` | `uint8_t` | target position의 엔트리 ID | `1` |
| `ID_TARGET_VELOCITY` | `uint8_t` | target velocity의 엔트리 ID | `2` |
| `ID_TARGET_EFFORT` | `uint8_t` | target effort의 엔트리 ID | `3` |
| `ID_STATUSWORD` | `uint8_t` | CiA-402 status word의 엔트리 ID | `4` |
| `ID_ERRORCODE` | `uint8_t` | driver error code의 엔트리 ID | `5` |
| `ID_CURRENT_POSITION` | `uint8_t` | current position의 엔트리 ID | `6` |
| `ID_CURRENT_VELOCITY` | `uint8_t` | current velocity의 엔트리 ID | `7` |
| `ID_CURRENT_EFFORT` | `uint8_t` | current effort의 엔트리 ID | `8` |
| `ID_TARGET_KP` | `uint8_t` | target proportional gain의 엔트리 ID | `9` |
| `ID_TARGET_KD` | `uint8_t` | target derivative gain의 엔트리 ID | `10` |
| `ID_CURRENT_TEMPERATURE` | `uint8_t` | current temperature의 엔트리 ID | `11` |
| `ID_OPERATING_MODE` | `uint8_t` | operation mode의 엔트리 ID | `30` |
| `ID_MAX_EFFORT` | `uint8_t` | max effort의 엔트리 ID | `50` |
| `ID_MIN_POSITION_LIMIT` | `uint8_t` | min position limit의 엔트리 ID | `51` |
| `ID_MAX_POSITION_LIMIT` | `uint8_t` | max position limit의 엔트리 ID | `52` |
| `ID_MAX_MOTOR_SPEED` | `uint8_t` | max motor speed의 엔트리 ID | `53` |
| `ID_PROFILE_VELOCITY` | `uint8_t` | profile velocity의 엔트리 ID | `54` |
| `ID_PROFILE_ACCELERATION` | `uint8_t` | profile acceleration의 엔트리 ID | `55` |
| `ID_PROFILE_DECELERATION` | `uint8_t` | profile deceleration의 엔트리 ID | `56` |
| `ID_MAX_ACCELERATION` | `uint8_t` | max acceleration의 엔트리 ID | `57` |
| `ID_MAX_DECELERATION` | `uint8_t` | max deceleration의 엔트리 ID | `58` |
| `ID_RXPDO` | `uint8_t` | RXPDO의 엔트리 ID | `98` |
| `ID_TXPDO` | `uint8_t` | TXPDO의 엔트리 ID | `99` |

##### `DriverState`

`DriverState`는 현재 드라이버 상태를 담는 enum class이다.

구성은 아래와 같다: `Fault`, `SwitchOnDisabled`, `ReadyToSwitchOn`, `SwitchedOn`, `OperationEnabled`.

##### `driver_config_t`

`driver_config_t`는 제조사에서 제공하는 하드웨어 정보를 담고 있으며, 드라이버 초기화 시 사용된다.

| Name | Type | Meaning | Default |
| --- | --- | --- | --- |
| `id` | `uint8_t` | 드라이버의 ID | `0` |
| `pulse_per_revolution` | `uint32_t` | 회전 당 펄스 수 | `0` |
| `rated_effort` | `double` | 정격 힘 (e.g. Nm, N) | `0` |
| `unit_effort` | `double` | 정격 힘에 대한 단위 스케일 | `0` |
| `lower` | `double` | 최소 제한 위치 (e.g. degree, mm) | `0` |
| `upper` | `double` | 최대 제한 위치 (e.g. degree, mm) | `0` |
| `speed` | `double` | 제한 속도 (e.g. degree/s, mm/s) | `0` |
| `acceleration` | `double` | 제한 가속도 (e.g. degree/s^2, mm/s^2) | `0` |
| `deceleration` | `double` | 제한 감속도 (e.g. degree/s^2, mm/s^2) | `0` |
| `profile_velocity` | `double` | 프로파일 속도 (e.g. degree/s, mm/s) | `0` |
| `profile_acceleration` | `double` | 프로파일 가속도 (e.g. degree/s^2, mm/s^2) | `0` |
| `profile_deceleration` | `double` | 프로파일 감속도 (e.g. degree/s^2, mm/s^2) | `0` |
| `profile_position_value` | `int8_t` | 프로파일 위치 모드 설정 값 | `0` |
| `profile_velocity_value` | `int8_t` | 프로파일 속도 모드 설정 값 | `0` |
| `profile_effort_value` | `int8_t` | 프로파일 힘 모드 설정 값 | `0` |

##### functions

| Function | Purpose |
| --- | --- |
| `loadParameters(param_file)` | 파라미터를 불러온다. |
| `isEnabled(data, driver_state, out)` | 모터 상태가 `Enable`인지 확인한다. |
| `isDisabled(data, driver_state, out)` | 모터 상태가 `Disable`인지 확인한다. |
| `isReceived(data, out)` | 모터가 제어 입력을 잘 받았는지 확인한다. |
| `position(value)` | 위치 값을 반환하거나 변환한다. |
| `velocity(value)` | 속도 값을 반환하거나 변환한다. |
| `effort(value)` | 힘 값을 반환하거나 변환한다. |
| `items()` | 드라이버에 설정한 아이템을 반환한다. |
| `interfaces()` | 드라이버에 등록한 인터페이스를 반환한다. |
| `number_of_items()` | 설정한 아이템 수를 반환한다. |
| `number_of_interfaces()` | 등록한 인터페이스 수를 반환한다. |
| `number_of_rx_interfaces()` | 등록한 RX 인터페이스 수를 반환한다. |
| `number_of_tx_interfaces()` | 등록한 TX 인터페이스 수를 반환한다. |
| `profile_position_value()` | 프로파일 위치 모드 설정을 위한 값을 반환한다. |
| `profile_velocity_value()` | 프로파일 속도 모드 설정을 위한 값을 반환한다. |
| `profile_effort_value()` | 프로파일 힘 모드 설정을 위한 값을 반환한다. |

> [!NOTE]
> `item`은 SDO 등을 활용해 초기화 단계에서 모터를 설정하는 데 필요한 엔트리를 의미하며, `interface`는 PDO 등을 활용해 지속적으로 송수신할 엔트리를 의미한다.
