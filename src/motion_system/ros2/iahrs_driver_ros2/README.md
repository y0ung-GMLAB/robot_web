# iahrs_driver_ros2

ROS 2 C++ driver for the iAHRS IMU.

This repository contains two ROS 2 packages:

- `interfaces`: custom service definitions.
- `iahrs_driver`: serial IMU driver node.

The driver reads the IMU from `/dev/IMU`, publishes `sensor_msgs/msg/Imu` data, and provides a reset service.

## Supported ROS 2 Versions

- Foxy
- Humble
- Jazzy

## Device Setup

The driver expects the IMU serial device to be available as `/dev/IMU`.
Create a udev rule so the USB serial device keeps the same name after reconnecting.

1. Add your user to the `dialout` group:

   ```bash
   sudo usermod -a -G dialout $USER
   ```

   Log out and log back in after running this command.

2. Find the USB device information:

   ```bash
   lsusb
   udevadm info -a -n /dev/ttyUSB0 | grep '{serial}'
   ```

   Replace `/dev/ttyUSB0` with the actual port if your device uses another number.

3. Create a udev rule:

   ```bash
   sudo nano /etc/udev/rules.d/99-iahrs.rules
   ```

   Example rule:

   ```text
   KERNEL=="ttyUSB*", ATTRS{idVendor}=="0403", ATTRS{idProduct}=="6015", ATTRS{serial}=="DM03L0C6", MODE:="0666", GROUP:="dialout", SYMLINK+="IMU"
   ```

   Update `idVendor`, `idProduct`, and `serial` for your device.

4. Reload udev rules:

   ```bash
   sudo udevadm control --reload-rules
   sudo udevadm trigger
   ```

5. Check the device link:

   ```bash
   ls -l /dev/IMU
   ```

## Build

From the root of your ROS 2 workspace:

```bash
colcon build --packages-up-to iahrs_driver
source install/setup.bash
```

If you want to build the packages separately:

```bash
colcon build --packages-select interfaces
source install/setup.bash
colcon build --packages-select iahrs_driver
source install/setup.bash
```

## Run

Launch the driver:

```bash
ros2 launch iahrs_driver iahrs_driver.py
```

Or run the node directly:

```bash
ros2 run iahrs_driver iahrs_driver
```

## ROS Interfaces

Published topics:

- `imu/data` (`sensor_msgs/msg/Imu`)
- `/tf` (`base_link` to `imu_link`, enabled when `m_bSingle_TF_option` is `true`)

Service:

- `all_data_reset` (`interfaces/srv/ImuReset`)

Call the reset service:

```bash
ros2 service call /all_data_reset interfaces/srv/ImuReset "{}"
```

## Parameters

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `m_bSingle_TF_option` | `bool` | `true` in the launch file | Publish the `base_link` to `imu_link` transform. |

## Reference

- Blog post: <https://blog.naver.com/zzang0736/223204708311>
