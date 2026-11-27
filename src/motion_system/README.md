# Motion System

This repository is a ROS 2 workspace source tree for motor control and related
operator interfaces. It includes a YAML-configured motor manager, ROS 2 bridge
nodes, controller input support, MIDI control support, and an iAHRS IMU driver.

hi
## Clone

Clone this repository as the `src` directory of a colcon workspace:

```bash
mkdir -p ~/colcon_ws
cd ~/colcon_ws
git clone --recurse-submodules https://github.com/SeonilChoi/motion_system.git src
```

If the repository was cloned without submodules, initialize them later:

```bash
cd ~/colcon_ws/src
git submodule update --init --recursive
```

## Build

Install ROS 2 and source your ROS environment first. The examples below assume
ROS 2 Humble:

```bash
cd ~/colcon_ws
source /opt/ros/humble/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
source install/setup.bash
```

For a motor-manager-only build:

```bash
colcon build --symlink-install --packages-up-to motion_control_bridge
```

## Launch

Launch the motor manager with the default example config:

```bash
source /opt/ros/humble/setup.bash
source ~/colcon_ws/install/setup.bash
ros2 launch motion_control_bridge motor_manager_node.launch.py
```

Use a specific motor configuration:

```bash
ros2 launch motion_control_bridge motor_manager_node.launch.py \
  config_file:=~/colcon_ws/src/ros2/motion_system_ros2/motion_control_bridge/config/example_socketcan_cubemars.yaml
```

Other useful launch commands:

```bash
# RQt motor control UI with motor manager
ros2 launch motion_control_rqt display_motor_manager_node.launch.py

# Behringer X-Touch MIDI bridge
ros2 launch xtouch_midi xtouch_node.launch.py

# MIDI-to-motor command bridge
ros2 launch motion_control_midi motion_control_midi_node.launch.py

# iAHRS IMU driver
ros2 launch iahrs_driver iahrs_driver.py

# PlayStation controller teleop
ros2 launch p9n_bringup teleop.launch.py hw_type:=DualSense
```

## Available Communication Methods

Motor communication backends:

- `ethercat`: IgH EtherCAT based cyclic motor communication.
- `canopen`: CANopen over SocketCAN.
- `socketcan`: raw SocketCAN communication.
- `serial`: serial communication for Dynamixel Protocol 2.0 devices.
- `dynamixel`: accepted as a Dynamixel-oriented master type in the motor
  manager configuration.

ROS and device interfaces:

- ROS 2 topics/services for motor commands, motor status, IMU data, and reset
  services.
- MIDI input/output for Behringer X-Touch devices.
- Linux joystick input for PlayStation controllers.
- Serial IMU communication for iAHRS devices.

## Available Drivers

Motor drivers supported by `motor_manager`:

- `dynamixel`
- `cubemars`
- `minas` for Panasonic MINAS drives
- `zeroerr` for ZeroErr drives

Device/interface drivers included in this workspace:

- `iahrs_driver`: iAHRS IMU ROS 2 driver.
- `p9n`: PlayStation controller interface for DualShock3, DualShock4, and
  DualSense controllers.
- `xtouch_midi`: Behringer X-Touch MIDI bridge.

Example motor configuration files are available in:

```text
ros2/motion_system_ros2/motion_control_bridge/config/
```
