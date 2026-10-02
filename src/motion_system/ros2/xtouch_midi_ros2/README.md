# xtouch_midi_ros2

## English Version

`xtouch_midi_ros2` is a ROS 2 bridge for the Behringer X-Touch Extender.

### Requirements

```bash
bash ./requirements/install_requirements.sh
```

```bash
sudo usermod -aG audio $USER
```

After logging out and back in, check that your user is in the `audio` group.

```bash
groups
```

### Build

```bash
cd ~/colcon_ws

source /opt/ros/humble/setup.bash
colcon build --symlink-install
```

### Run

```bash
source ./install/setup.bash
ros2 launch xtouch_midi xtouch_node.launch.py
```

### Topic

| Name | Type | Payload |
| --- | --- | --- |
| `/xtouch/midi` | `midi_msgs/msg/Midi` | Full 8-channel button, touch, fader, and dial state |

### `Midi.msg`

| Name | Type |
| --- | --- |
| `btn0` | `bool[]` |
| `btn1` | `bool[]` |
| `btn2` | `bool[]` |
| `btn3` | `bool[]` |
| `touch` | `bool[]` |
| `channel` | `int32[]` |
| `dial` | `int32[]` |

## Korean Version

`xtouch_midi_ros2`는 Behringer X-Touch Extender를 위한 ROS 2 bridge이다.

### Requirements

```bash
bash ./requirements/install_requirements.sh
```

```bash
sudo usermod -aG audio $USER
```

로그아웃 / 로그인 후 아래 명령어로 `audio`가 group에 있는지 확인한다.

```bash
groups
```

### Build

```bash
cd ~/colcon_ws

source /opt/ros/humble/setup.bash
colcon build --symlink-install
```

### Run

```bash
source ./install/setup.bash
ros2 launch xtouch_midi xtouch_node.launch.py
```

### Topic

| Name | Type | Payload |
| --- | --- | --- |
| `/xtouch/midi` | `midi_msgs/msg/Midi` | Full 8-channel button, touch, fader, and dial state |

### `Midi.msg`

| Name | Type |
| --- | --- |
| `btn0` | `bool[]` |
| `btn1` | `bool[]` |
| `btn2` | `bool[]` |
| `btn3` | `bool[]` |
| `touch` | `bool[]` |
| `channel` | `int32[]` |
| `dial` | `int32[]` |
