# PREEMPT_RT Kernel Build Guide (Ubuntu 22.04)

## 1. Install dependencies
```
sudo apt update
sudo apt install -y build-essential libncurses-dev libssl-dev flex bison libelf-dev bc dwarves
```

## 2. Get kernel + RT patch
```
mkdir ~/rt_kernel && cd ~/rt_kernel

wget https://mirrors.edge.kernel.org/pub/linux/kernel/v6.x/linux-6.8.tar.xz
wget https://mirrors.edge.kernel.org/pub/linux/kernel/projects/rt/6.8/patch-6.8-rt8.patch.xz
```

## 3. Extract and patch
```
tar -xf linux-6.8.tar.xz
xz -d patch-6.8-rt8.patch.xz

cd linux-6.8
patch -p1 < ../patch-6.8-rt8.patch
```

## 4. Base config
```
cp /boot/config-$(uname -r) .config
make olddefconfig
```

## 5. Configure RT kernel
```
make menuconfig
```

Set:
- General setup → Preemption Model → Fully Preemptible Kernel (RT)

Ensure:
```
CONFIG_PREEMPT_RT=y
```

## 6. Disable ALL certificate / signing sources (CRITICAL)
Edit:
```
nano .config
```

Set EXACTLY:
```
CONFIG_MODULE_SIG=n
CONFIG_MODULE_SIG_ALL=n
CONFIG_MODULE_SIG_FORCE=n
CONFIG_MODULE_SIG_KEY=""
CONFIG_SYSTEM_TRUSTED_KEYS=""
CONFIG_SYSTEM_REVOCATION_KEYS=""
CONFIG_SYSTEM_BLACKLIST_KEYRING=n
CONFIG_SYSTEM_BLACKLIST_KEYS=""
CONFIG_SYSTEM_REVOCATION_LIST=""
CONFIG_SECONDARY_TRUSTED_KEYRING=n
CONFIG_SYSTEM_TRUSTED_KEYRING=n
CONFIG_INTEGRITY=n
CONFIG_IMA=n
CONFIG_EVM=n
```

Apply:
```
make olddefconfig
```

## 7. Build kernel
```
make -j$(nproc)
```

## 8. Install kernel
```
sudo make modules_install
sudo make install
```

## 9. Update GRUB
```
sudo update-grub
```

## 10. Ensure GRUB menu is visible
Edit:
```
sudo nano /etc/default/grub
```

Set:
```
GRUB_TIMEOUT_STYLE=menu
GRUB_TIMEOUT=5
GRUB_HIDDEN_TIMEOUT=0
GRUB_HIDDEN_TIMEOUT_QUIET=false
```

Then:
```
sudo update-grub
```

## 11. Disable Secure Boot (REQUIRED)
In BIOS/UEFI:
- Secure Boot → Disabled

## 12. Reboot
```
sudo reboot
```

Select:
- Linux 6.8.0-rt8

## 13. Verify
```
uname -a
```

Must show:
- PREEMPT_RT
