# EtherCAT

## English Version

`ethercat` is an IgH EtherCAT-based communication wrapper library composed of `EthercatMaster` and `EthercatController`.

`EthercatMaster` derives from `motor_interface::MotorMaster`, and `EthercatController` derives from `motor_interface::MotorController`.

### Requirements

1. Install `ethtool`

```bash
sudo apt update
sudo apt install ethtool
```

2. Check the network interface

```bash
ip address
```

Check the LAN-related network interface, such as `eth0`, `enp1s0`, or `enp2s0`.

3. Check the Linux kernel driver for Ethernet

```bash
ethtool -i enp1s0
```

Check the Ethernet driver name, such as `e1000e`, `igb`, `igc`, or `r8169`.

4. Install the Linux kernel

Install a Linux kernel that matches the detected driver by referring to [A table of supported hardware](https://docs.etherlab.org/ethercat/1.6/doxygen/devicedrivers.html).

Refer to [Linux kernel installation](https://github.com/SeonilChoi/motor_manager/blob/main/communications/ethercat/LINUX_KERNEL_INSTALLATION.md) for the kernel installation method.

5. Install dependencies

```bash
sudo apt update
sudo apt install -y autoconf automake libtool pkg-config build-essential git
```

6. Clone the EtherCAT repository

```bash
git clone https://gitlab.com/etherlab.org/ethercat.git
cd ethercat
```

7. Build the EtherCAT library

```bash
./bootstrap
./configure --sysconfdir=/etc --prefix=/opt/etherlab --enable-eoe=no --enable-cycles=yes --enable-hrtimer=yes --enable-${Linux kernel driver e.g. e1000e, igc}=yes
```

Set the option with the Linux kernel driver checked above, such as `--enable-e1000e=yes` or `--enable-igc=yes`.

```bash
make all modules
sudo make modules_install install
sudo depmod
```

8. Configuration

```bash
sudo apt install vim
sudo vim /etc/ethercat.conf
```

Enter the network interface and kernel driver information.

Example:

```bash
MASTER0_DEVICE="eth0"

DEVICE_MODULES="e1000e"
```

9. Start EtherCAT

```bash
sudo systemctl start ethercat

echo 'export PATH=$PATH:/opt/etherlab/bin:/opt/etherlab/sbin' >> ~/.bashrc
source ~/.bashrc

sudo ln -s /opt/etherlab/sbin/ethercatctl /usr/local/sbin/ethercatctl
sudo ln -s /opt/etherlab/bin/ethercat /usr/local/bin/ethercat
```

10. Verify the EtherCAT installation

```bash
sudo ethercatctl restart
```

If a slave device is connected, run:

```bash
ethercat slaves
```

If the slave information is displayed, the installation succeeded.

---

### Device setup

```bash
sudo ethercatctl restart
sudo chmod 666 /dev/EtherCAT0
```

---

### YAML fields

Example:

```yaml
masters:
  - id: 0
    type: ethercat
    number_of_slaves: 1
    ethercat_master_index: 0
    slaves:
      - controller_index: 0
        master_id: 0
        driver_id: 0
        alias: 1
        position: 0
        vendor_id: 0x5a65726f
        product_id: 0x00029252
        profile_mode: 0
```

`alias`, `position`, `vendor_id`, and `product_id` can be checked with the command below.

```bash
ethercat slaves --verbose
```

---

### `EthercatMaster`

| Function | Purpose |
| --- | --- |
| `master()` | Returns `ec_master_t*`. |
| `domain()` | Returns `ec_domain_t*`. |
| `domain_pd()` | Returns the domain process data. |
| `master_index()` | Returns the master index. |

---

### `EthercatController`

| Function | Purpose |
| --- | --- |
| `addSlaveConfigSdos()` | Configures entries through SDO. |
| `addSlaveConfigPdos()` | Registers entries through PDO. |

## Korean Version

`ethercat`은 IgH EtherCAT 기반 통신 Wrapper 라이브러리로, `EthercatMaster`와 `EthercatController`로 구성된다.

`EthercatMaster`는 `motor_interface::MotorMaster`를 상속하고, `EthercatController`는 `motor_interface::MotorController`를 상속한다.

### Requirements

1. Install `ethtool`

```bash
sudo apt update
sudo apt install ethtool
```

2. Check network interface

```bash
ip address
```

`eth0`, `enp1s0`, `enp2s0` 등 LAN 포트 관련 네트워크 인터페이스를 확인한다.

3. Check Linux kernel driver for Ethernet

```bash
ethtool -i enp1s0
```

`e1000e`, `igb`, `igc`, `r8169` 등을 확인한다.

4. Install Linux kernel

[A table of supported hardware](https://docs.etherlab.org/ethercat/1.6/doxygen/devicedrivers.html)에서 해당 드라이버에 맞는 Linux 커널을 설치해야 사용 가능하다.

Linux 커널 설치 방법은 [리눅스 커널 설치](https://github.com/SeonilChoi/motor_manager/blob/main/communications/ethercat/LINUX_KERNEL_INSTALLATION.md)를 참고한다.

5. Install dependencies

```bash
sudo apt update
sudo apt install -y autoconf automake libtool pkg-config build-essential git
```

6. Clone ethercat repository

```bash
git clone https://gitlab.com/etherlab.org/ethercat.git
cd ethercat
```

7. Build ethercat library

```bash
./bootstrap
./configure --sysconfdir=/etc --prefix=/opt/etherlab --enable-eoe=no --enable-cycles=yes --enable-hrtimer=yes --enable-${Linux kernel driver e.g. e1000e, igc}=yes
```

`--enable-e1000e=yes`, `--enable-igc=yes` 등 위에서 확인한 Linux kernel driver로 설정한다.

```bash
make all modules
sudo make modules_install install
sudo depmod
```

8. Configuration

```bash
sudo apt install vim
sudo vim /etc/ethercat.conf
```

네트워크 인터페이스와 kernel driver 정보를 입력한다.

예시:

```bash
MASTER0_DEVICE="eth0"

DEVICE_MODULES="e1000e"
```

9. Start ethercat

```bash
sudo systemctl start ethercat

echo 'export PATH=$PATH:/opt/etherlab/bin:/opt/etherlab/sbin' >> ~/.bashrc
source ~/.bashrc

sudo ln -s /opt/etherlab/sbin/ethercatctl /usr/local/sbin/ethercatctl
sudo ln -s /opt/etherlab/bin/ethercat /usr/local/bin/ethercat
```

10. Verify ethercat installation

```bash
sudo ethercatctl restart
```

만약 slave 장치가 연결되어 있다면 아래 명령어를 실행한다.

```bash
ethercat slaves
```

slave 정보가 표시되면 설치에 성공한 것이다.

---

### Device setup

```bash
sudo ethercatctl restart
sudo chmod 666 /dev/EtherCAT0
```

---

### YAML fields

예시:

```yaml
masters:
  - id: 0
    type: ethercat
    number_of_slaves: 1
    ethercat_master_index: 0
    slaves:
      - controller_index: 0
        master_id: 0
        driver_id: 0
        alias: 1
        position: 0
        vendor_id: 0x5a65726f
        product_id: 0x00029252
        profile_mode: 0
```

`alias`, `position`, `vendor_id`, `product_id`는 아래 명령어를 통해 확인 가능하다.

```bash
ethercat slaves --verbose
```

---

### `EthercatMaster`

| Function | Purpose |
| --- | --- |
| `master()` | `ec_master_t*`를 반환한다. |
| `domain()` | `ec_domain_t*`를 반환한다. |
| `domain_pd()` | `domain process data`를 반환한다. |
| `master_index()` | `master index`를 반환한다. |

---

### `EthercatController`

| Function | Purpose |
| --- | --- |
| `addSlaveConfigSdos()` | SDO로 엔트리를 설정한다. |
| `addSlaveConfigPdos()` | PDO로 엔트리를 등록한다. |
