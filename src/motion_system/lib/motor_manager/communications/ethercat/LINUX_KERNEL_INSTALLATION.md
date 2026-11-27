# Linux kernel installation guide

## English Version

This document describes how to install a Linux RT kernel.

If an RT kernel is not required, skip only the RT patch step and continue the rest of the installation.

### Linux Version

- Linux 6.4.6
- Linux RT patch 6.4.6-rt8

### Requirements

```bash
sudo apt update
sudo apt install -y build-essential bc ca-certificates gnupg2 libssl-dev libelf-dev bison flex dwarves fakeroot ncurses-dev xz-utils wget
sudo apt install -y rt-tests stress cpufrequtils htop
sudo apt install -y vim
```

### Downloads

```bash
mkdir ~/linux-kernel
cd ~/linux-kernel

wget https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.4.6.tar.xz
tar -xf linux-6.4.6.tar.xz
```

### RT Patch

```bash
wget https://cdn.kernel.org/pub/linux/kernel/projects/rt/6.4/patch-6.4.6-rt8.patch.xz
cd linux-6.4.6
xzcat ../patch-6.4.6-rt8.patch.xz | patch -p1
```

### Kernel Configuration

```bash
cp /boot/config-$(uname -r) .config
scripts/config --disable SYSTEM_TRUSTED_KEYS
scripts/config --disable SYSTEM_REVOCATION_KEYS
```

For RT settings, run:

```bash
make menuconfig
```

In `General setup` -> `Preemption Model`, select `Fully Preemptible Kernel (Real-Time)`, then save and exit.

### Build

```bash
make olddefconfig
make -j$(nproc)
sudo make modules_install
sudo make install
```

### GRUB Setting

```bash
sudo vim /etc/default/grub
```

```bash
# vim
GRUB_DEFAULT=saved
GRUB_SAVEDEFAULT=true
```

```bash
grep "menuentry '" /boot/grub/grub.cfg

sudo grub-set-default "Advanced options for Ubuntu>Ubuntu, with Linux 6.4.6-rt8"
sudo update-grub
sudo reboot
```

## Korean Version

이 문서에선 리눅스 RT 커널 설치 가이드를 다룬다.

RT 커널을 사용하지 않을 경우, RT Patch 과정만 제외하고 설치한다.

### Linux Version

- Linux 6.4.6
- Linux RT 패치 6.4.6-rt8

### Requirements

```bash
sudo apt update
sudo apt install -y build-essential bc ca-certificates gnupg2 libssl-dev libelf-dev bison flex dwarves fakeroot ncurses-dev xz-utils wget
sudo apt install -y rt-tests stress cpufrequtils htop
sudo apt install -y vim
```

### Downloads

```bash
mkdir ~/linux-kernel
cd ~/linux-kernel

wget https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-6.4.6.tar.xz
tar -xf linux-6.4.6.tar.xz
```

### RT Patch

```bash
wget https://cdn.kernel.org/pub/linux/kernel/projects/rt/6.4/patch-6.4.6-rt8.patch.xz
cd linux-6.4.6
xzcat ../patch-6.4.6-rt8.patch.xz | patch -p1
```

### Kernel Configuration

```bash
cp /boot/config-$(uname -r) .config
scripts/config --disable SYSTEM_TRUSTED_KEYS
scripts/config --disable SYSTEM_REVOCATION_KEYS
```

RT 세팅이라면, 아래 명령어를 실행한다.

```bash
make menuconfig
```

`General setup` -> `Preemption Model`에서 `Fully Preemptible Kernel (Real-Time)`을 선택 후 저장 및 종료한다.

### Build

```bash
make olddefconfig
make -j$(nproc)
sudo make modules_install
sudo make install
```

### GRUB Setting

```bash
sudo vim /etc/default/grub
```

```bash
# vim
GRUB_DEFAULT=saved
GRUB_SAVEDEFAULT=true
```

```bash
grep "menuentry '" /boot/grub/grub.cfg

sudo grub-set-default "Advanced options for Ubuntu>Ubuntu, with Linux 6.4.6-rt8"
sudo update-grub
sudo reboot
```
