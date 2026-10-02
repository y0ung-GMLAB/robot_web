# robots

## English

`Robot` is composed of `Scheduler`, `Planner`, and `Controller` to support a hierarchical robot control structure.

`Scheduler` manages the `State` transitions caused by an `Action` and tracks the progress of each `State`.

`Planner` computes the control input required for the purpose of each `State`.

`Controller` converts the computed control input into the actual hardware command.

## Robot List

| Robot | Status |
| --- | --- |
| `RockingChair` | :white_check_mark: |

## Usage

```python
from robots.robot import Robot
from robots.robot import Scheduler
```

## API

### `Scheduler`

| Function | Purpose |
| --- | --- |
| `get_state_frame()` | Returns the current `state_frame`. |
| `progress(t)` | Computes the progress value for the current time `t`. |
| `step()` | Advances the internal time by `dt`. |
| `tick(action_frame, duration)` | Applies `action_frame` to the current `State` and checks whether an event occurred. |

### `Planner`

| Function | Purpose |
| --- | --- |
| `set_initial_state(initial_state)` | Sets the initial state. |
| `update_goal_state(goal_state)` | Updates the goal state. |
| `eval(progress, duration, action)` | Computes the command for the given `Action` at the current progress. |

### `Controller`

To be updated.

### `robot_config_t`

| Name | Type | Meaning |
| --- | --- | --- |
| `index` | `int` | Index of the robot. |
| `name` | `str` | Name of the robot. |
| `controller_indices` | `List[int]` | Indices of the `controller`s used by the robot. |
| `target_interface_ids` | `List[List[int]]` | IDs of the `target_interface`s controlled by each `controller`. |
| `home_positions` | `List[float]` | Home position for each `controller`. |
| `home_duration` | `float` | `duration` value used in the `HOMING` state. |
| `move_duration` | `float` | `duration` value used in the `OPERATING` state. |
| `init_controlword` | `int` | Initial `controlword` value used to create the robot's default joint command. |
| `motion_data_file_path` | `str` | Path to the motion data used in the `OPERATING` state. Relative paths are resolved from the robot config file directory by `RobotManager`. |

### `Robot`

| Function | Purpose |
| --- | --- |
| `controller_indices` | Returns the indices of the robot's `controller`s. |
| `number_of_target_interfaces` | Returns the number of `target_interface_ids` for each `controller`. |
| `target_interface_ids` | Returns the `target_interface_ids` for each `controller`. |
| `updateJointStatus(joint_status)` | Updates the robot's `curr_joint_status`. |
| `get_state_frame()` | Returns the current frame from the robot's `scheduler`. |
| `set_action_frame(action_frame)` | Applies the current `action_frame` to the robot and returns the control command. |

## Korean

`Robot`은 계층적 로봇 제어 구조 설계를 위해 `Scheduler`, `Planner`, `Controller`로 구성된다.

`Scheduler`는 `Action`에 따른 `State` 전환을 관리하고, 각 `State`별 진행도를 관장한다.

`Planner`는 `State`별 목적에 따른 제어 입력을 계산한다.

`Controller`는 계산된 제어 입력을 실제 하드웨어 명령으로 변환하는 역할을 한다.

## Robot List

| Robot | Status |
| --- | --- |
| `RockingChair` | :white_check_mark: |

## Usage

```python
from robots.robot import Robot
from robots.robot import Scheduler
```

## API

### `Scheduler`

| Function | Purpose |
| --- | --- |
| `get_state_frame()` | 현재 `state_frame`을 반환한다. |
| `progress(t)` | 현재 시간 `t`에 대한 진행도를 계산한다. |
| `step()` | 내부 시간을 `dt`만큼 다음 스텝으로 진행한다. |
| `tick(action_frame, duration)` | 현재 `State`에 `action_frame`을 적용하고 이벤트 발생 여부를 확인한다. |

### `Planner`

| Function | Purpose |
| --- | --- |
| `set_initial_state(initial_state)` | 초기 상태를 설정한다. |
| `update_goal_state(goal_state)` | 목표 상태를 업데이트한다. |
| `eval(progress, duration, action)` | 현재 진행도에서 `Action`에 따른 명령을 계산한다. |

### `Controller`

업데이트 예정

### `robot_config_t`

| Name | Type | Meaning |
| --- | --- | --- |
| `index` | `int` | 로봇의 인덱스 |
| `name` | `str` | 로봇의 이름 |
| `controller_indices` | `List[int]` | 로봇이 사용하는 `controller`의 인덱스 |
| `target_interface_ids` | `List[List[int]]` | 각 `controller`에서 제어할 `target_interface`의 ID |
| `home_positions` | `List[float]` | 각 `controller`의 홈 위치 |
| `home_duration` | `float` | `HOMING` 상태에서 사용할 `duration` 값 |
| `move_duration` | `float` | `OPERATING` 상태에서 사용할 `duration` 값 |
| `init_controlword` | `int` | 로봇의 기본 joint command를 만들 때 사용할 초기 `controlword` 값 |
| `motion_data_file_path` | `str` | `OPERATING` 상태에서 사용할 모션 데이터 경로. 상대 경로는 `RobotManager`가 robot config 파일 위치를 기준으로 해석한다. |

### `Robot`

| Function | Purpose |
| --- | --- |
| `controller_indices` | 로봇의 `controller` 인덱스를 반환한다. |
| `number_of_target_interfaces` | 각 `controller`의 `target_interface_ids` 수를 반환한다. |
| `target_interface_ids` | 각 `controller`의 `target_interface_ids`를 반환한다. |
| `updateJointStatus(joint_status)` | 로봇의 `curr_joint_status`를 업데이트한다. |
| `get_state_frame()` | 로봇의 `scheduler`에서 현재 frame을 반환한다. |
| `set_action_frame(action_frame)` | 현재 `action_frame`을 로봇에 반영하고 제어 명령을 반환한다. |
