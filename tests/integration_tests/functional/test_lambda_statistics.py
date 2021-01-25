import logging
import platform
import tempfile
import json
import os
import pytest
from test_balloon import _test_rss_memory_lower, copy_util_to_rootfs
from conftest import _test_images_s3_bucket
from framework.artifacts import ArtifactCollection, NetIfaceConfig
from framework.builder import MicrovmBuilder, SnapshotBuilder, SnapshotType
from framework.microvms import VMNano
from framework.utils import get_firecracker_version_from_toml
import host_tools.network as net_tools  # pylint: disable=import-error
import host_tools.drive as drive_tools


# Define 2 net device configurations.
net_ifaces = [NetIfaceConfig(),
              NetIfaceConfig(host_ip="192.168.1.1",
                             guest_ip="192.168.1.2",
                             tap_name="tap1",
                             dev_name="eth1")
            ]

# Define 3 scratch drives.
scratch_drives = ["vdb", "vdc", "vdd"]

def create_snapshot_helper(bin_cloner_path, logger, target_version=None,
                           drives=None, ifaces=None,
                           vcpu_count = 1, mem_size_mib = 128,
                           fc_binary=None, jailer_binary=None,
                           balloon=False, diff_snapshots=False):
    """Create a snapshot with many devices."""
    vm_instance = VMNano.spawn(bin_cloner_path, False,
                               fc_binary, jailer_binary,
                               net_ifaces=ifaces,
                               diff_snapshots=diff_snapshots,
                               vcpu_count=vcpu_count, mem_size_mib=mem_size_mib)
    vm = vm_instance.vm

    if diff_snapshots is False:
        snapshot_type = SnapshotType.FULL
    else:
        # Version 0.24 and greater has Diff and ballon support.
        snapshot_type = SnapshotType.DIFF

    if balloon:
        # Copy balloon test util.
        copy_util_to_rootfs(vm_instance.disks[0].local_path(), 'fillmem')

        # Add a memory balloon with stats enabled.
        response = vm.balloon.put(
            amount_mb=0,
            deflate_on_oom=True,
            stats_polling_interval_s=1
        )
        assert vm.api_session.is_status_no_content(response.status_code)

    # Disk path array needed when creating the snapshot later.
    disks = [vm_instance.disks[0].local_path()]
    test_drives = [] if drives is None else drives

    # Add disks.
    for scratch in test_drives:
        # Add a scratch 64MB RW non-root block device.
        scratchdisk = drive_tools.FilesystemFile(tempfile.mktemp(), size=64)
        vm.add_drive(scratch, scratchdisk.path)
        disks.append(scratchdisk.path)

        # Workaround FilesystemFile destructor removal of file.
        scratchdisk.path = None

    vm.start()

    # Iterate and validate connectivity on all ifaces after boot.
    for iface in net_ifaces:
        vm.ssh_config['hostname'] = iface.guest_ip
        ssh_connection = net_tools.SSHConnection(vm.ssh_config)
        exit_code, _, _ = ssh_connection.execute_command("sync")
        assert exit_code == 0

    # Mount scratch drives in guest.
    for blk in scratch_drives:
        # Create mount point and mount each device.
        cmd = "mkdir -p /mnt/{blk} && mount /dev/{blk} /mnt/{blk}".format(
            blk=blk
        )
        exit_code, _, _ = ssh_connection.execute_command(cmd)
        assert exit_code == 0

        # Create file using dd using O_DIRECT.
        # After resume we will compute md5sum on these files.
        dd = "dd if=/dev/zero of=/mnt/{}/test bs=4096 count=10 oflag=direct"
        exit_code, _, _ = ssh_connection.execute_command(dd.format(blk))
        assert exit_code == 0

        # Unmount the device.
        cmd = "umount /dev/{}".format(blk)
        exit_code, _, _ = ssh_connection.execute_command(cmd)
        assert exit_code == 0

    # Create a snapshot builder from a microvm.
    snapshot_builder = SnapshotBuilder(vm)

    snapshot = snapshot_builder.create(disks,
                                       vm_instance.ssh_key,
                                       target_version=target_version,
                                       snapshot_type=snapshot_type,
                                       net_ifaces=net_ifaces)
    #logger.debug("========== Firecracker create snapshot log ==========")
    #logger.debug(vm.log_data)
    response = vm.machine_cfg.get()
    assert vm.api_session.is_status_ok(response.status_code)
    response_json = response.json()
    logger.info(response_json)
    vm.kill()
    return snapshot

import re

def test_restore_snapshot_times(bin_cloner_path, vcpu_cnt, mem_size):
    logger = logging.getLogger("restore_snapshot_times")

    snapshot = create_snapshot_helper(bin_cloner_path, logger,
                                drives=scratch_drives,
                                ifaces=net_ifaces,
                                vcpu_count = int(vcpu_cnt),
                                mem_size_mib = int(mem_size))

    for i in range(0,100):
        builder = MicrovmBuilder(bin_cloner_path)
        microvm, _ = builder.build_from_snapshot(snapshot,
                                                    resume=True,
                                                    enable_diff_snapshots=False)

        #logger.info("========== Firecracker restore snapshot log ==========")
        #logger.info(microvm.log_data)
        LOG_LINE_REGEX = "-&%-.*-&%-"
        matches = re.findall(LOG_LINE_REGEX, microvm.log_data)
        for match in matches:
            logger.info(match)
        microvm.kill()