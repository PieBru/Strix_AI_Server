#!/usr/bin/env python3
"""nvme-health.py [dev] — read the NVMe SMART/Health log without smartctl or nvme-cli.

Neither tool is installed on either box and pacman needs the uplink, so this issues the
admin Get Log Page command (LID 02) straight to the character device. Read-only: GET
LOG PAGE cannot modify anything, but it does need root, hence `sudo -n` / `echo pw |
sudo -S`. Run it as the wear canary next to the /proc/diskstats baseline in
~/logs/nvme-write-baseline.txt — percentage_used is the drive's own estimate, the
diskstats line is our measured write rate.

  sudo python3 scripts/nvme-health.py            # /dev/nvme0
"""
import ctypes
import fcntl
import struct
import sys

# NVME_IOCTL_ADMIN_CMD = _IOWR('N', 0x41, struct nvme_passthru_cmd /*72 bytes*/)
ADMIN_CMD = 0xC0484E41
LOG_HEALTH = 0x02
LOG_BYTES = 512
# struct nvme_passthru_cmd, packed, exactly 72 bytes: the ioctl NUMBER encodes that
# size, so a 68-byte buffer is rejected as "buffer overflow" before the driver looks at
# anything else. Offsets: opcode/flags/cmd_flags 0, nsid 4, cdw2 8, cdw3 12, metadata 16,
# addr 24, metadata_len 32, data_len 36, cdw10..cdw15 40..60, timeout 64, result 68.
CMD = "=BBH" + "I" * 3 + "QQ" + "I" * 10
assert struct.calcsize(CMD) == 72, struct.calcsize(CMD)  # the ioctl number promises 72


def health(dev="/dev/nvme0"):
    buf = ctypes.create_string_buffer(LOG_BYTES)
    numd = LOG_BYTES // 4 - 1  # cdw10: [31:16] dwords-1, [7:0] log identifier
    cmd = struct.pack(
        CMD,
        0x02,  # opcode: Get Log Page (read-only by construction)
        0, 0,  # flags, command_flags
        0xFFFFFFFF,  # nsid: all namespaces
        0, 0,  # cdw2, cdw3
        0,  # metadata
        ctypes.addressof(buf),  # addr
        0,  # metadata_len
        LOG_BYTES,  # data_len
        (numd << 16) | LOG_HEALTH,  # cdw10
        0, 0, 0, 0, 0,  # cdw11..cdw15
        0,  # timeout_ms (0 = driver default)
        0,  # result (written by the driver)
    )
    with open(dev, "rb") as fd:
        fcntl.ioctl(fd, ADMIN_CMD, cmd)
    return buf.raw


def u64(raw, off):
    return struct.unpack_from("<Q", raw, off)[0]


def main():
    raw = health(sys.argv[1] if len(sys.argv) > 1 else "/dev/nvme0")
    k = lambda n: f"{n:,}"
    # Data Units Written is in 1000 x 512-byte units (NVMe base spec).
    duw = u64(raw, 48) * 1000 * 512
    print(f"critical_warning   = {raw[0]}")
    print(f"composite_temp     = {struct.unpack_from('<H', raw, 1)[0] - 273} C")
    print(f"available_spare    = {raw[3]}%  (threshold {raw[4]}%)")
    print(f"percentage_used    = {raw[5]}%   <- the drive's own wear estimate")
    print(f"data_units_written = {k(duw)} bytes ({duw / 2**40:.2f} TiB host writes)")
    print(f"host_write_cmds    = {k(u64(raw, 80))}")
    print(f"power_on_hours     = {k(u64(raw, 128))}")
    print(f"power_cycles       = {k(u64(raw, 112))}")
    print(f"unsafe_shutdowns   = {k(u64(raw, 144))}")
    print(f"err_log_entries    = {k(u64(raw, 160))}")


if __name__ == "__main__":
    main()
