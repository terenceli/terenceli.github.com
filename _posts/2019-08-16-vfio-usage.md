---
layout: post
title: "VFIO usage"
description: "VFIO"
category: 技术
tags: [虚拟化]
---
{% include JB/setup %}


VFIO is used to assign a physical IO device to the virtual machine. I will write some internal posts to explain how VFIO works. First of all, we need to know how to use VFIO. We will create a VMware workstation virtual machine(VM1), in the VMs, we will create a qemu virtual machine(VM2) and assign a device of VM1's to VM2.

<h3> 1 </h3>

Create a new network device for VM1 in VMware workstation, open the .vmx file with editor and change this new network's type from e1000 to vmxnet3.

        ethernet1.virtualDev = "vmxnet3"

<h3> 2 </h3>

Find the PCI address(BDF) in system(lspci -v)

        03:00.0 Ethernet controller: VMware VMXNET3 Ethernet Controller (rev 01)

<h3> 3 </h3>

Find the devices' iommu group, this is generated when iommu initializing.

        test@ubuntu:~$ ls -lh /sys/bus/pci/devices/0000:03:00.0/iommu_group/devices
        total 0
        lrwxrwxrwx 1 root root 0 Aug 16 08:22 0000:00:15.0 -> ../../../../devices/pci0000:00/0000:00:15.0
        lrwxrwxrwx 1 root root 0 Aug 16 08:22 0000:00:15.1 -> ../../../../devices/pci0000:00/0000:00:15.1
        lrwxrwxrwx 1 root root 0 Aug 16 08:22 0000:00:15.2 -> ../../../../devices/pci0000:00/0000:00:15.2
        lrwxrwxrwx 1 root root 0 Aug 16 08:22 0000:00:15.3 -> ../../../../devices/pci0000:00/0000:00:15.3
        lrwxrwxrwx 1 root root 0 Aug 16 08:22 0000:00:15.4 -> ../../../../devices/pci0000:00/0000:00:15.4
        lrwxrwxrwx 1 root root 0 Aug 16 08:22 0000:00:15.5 -> ../../../../devices/pci0000:00/0000:00:15.5
        lrwxrwxrwx 1 root root 0 Aug 16 08:22 0000:00:15.6 -> ../../../../devices/pci0000:00/0000:00:15.6
        lrwxrwxrwx 1 root root 0 Aug 16 08:22 0000:00:15.7 -> ../../../../devices/pci0000:00/0000:00:15.7
        lrwxrwxrwx 1 root root 0 Aug 16 08:22 0000:03:00.0 -> ../../../../devices/pci0000:00/0000:00:15.0/0000:03:00.0

In general, the devices of the same iommu group should assign the same domain. However, in this example, only our vmxnet network card is a PCI device, others are all PCI bridges, vfio-pci does not currently support PCI bridges.


<h3> 4 </h3>

Unbind the device with the driver

        echo 0000:01:10.0 >/sys/bus/pci/devices/0000:03:00.0/driver/unbind


<h3> 5 </h3>

Find the vendor and device ID

        test@ubuntu:~$ lspci -n -s 0000:03:00.0
        03:00.0 0200: 15ad:07b0 (rev 01)

<h3> 6 </h3>


Bind the device to vfio-pci driver(should modprobe vfio-pci firstly)

        echo 15ad 07b0 /sys/bus/pci/drivers/vfio-pci/new_id

Now we can see a new node created in '/dev/vfio/', this is the group id.

        test@ubuntu:~$ ls -l /dev/vfio/
        total 0
        crw------- 1 root root 243,   0 Aug 14 08:23 6
        crw-rw-rw- 1 root root  10, 196 Aug 14 08:23 vfio


<h3> 7 </h3>

start qemu with the assigned device. 

        x86_64-softmmu/qemu-system-x86_64 -m 1024 -smp 4 -hda /home/test/test.img --enable-kvm -vnc :0 --enable-kvm -device vfio-pci,host=03:00.0,id=net0

Now we can see the device in guest and it's driver is vmxnet3.

![](/assets/img/vfio1/1.png)

