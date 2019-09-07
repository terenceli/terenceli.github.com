---
layout: post
title: "A brief overview of cloud-hypervisor, a modern VMM"
description: "cloud-hypervisor"
category: 技术
tags: [虚拟化]
---
{% include JB/setup %}


<h3> Background </h3>

Several months ago, intel made the cloud-hypervisor open sourced. The cloud-hypervisor's development is driven by the idea that in modern world we need a more light, more security, and more efficiency VMM. The traditional solution of cloud virtual machine is qemu and kvm. In cloud, we just need an environment to run workloads, there is no need to pay for the legacy devices which qemu emulates. Also qemu is written using C which is considered harmful. Rust is a security language which is a good choice to build next-generation VMM. Google implements the first Rust-based light VMM called crosvm which is in Fuchsia operating system. Then aws develops his own light VMM called firecracked which is based of crosvm. After the birth of crosvm and firecracker, some companies realize that there are lots of reduplication in crosvm and firecracker, also if someone wants to write a Rust-based VMM, it need do these reduplication again. To get avoid this, these companies setup a rust-vmm project. rust-vmm abstracts the common virtualization components which implements a Rust-based VMM required to be crate. These components contains kvm wrapper, virtio devices and some utils, etc. People who wants to implement a Rust-based VMM can util these components. This makes write a Rust-based VMM very easy. 

Cloud-hypervisor is developed under this background by intel. It uses some code of rust-vmm(vm-memory, kvm_ioctls), firecracker and crosvm. The [cloud-hypervisor's page](https://github.com/intel/cloud-hypervisor) contains the detailed usage info.


<h3> Architecture </h3>

As we know, qemu emulates a whole machine system. Below is a diagram of the i440fx architecture(from qemu sites).

![](/assets/img/cloud_hypervisor/1.png)

As we can see the topology of qemu emulates is nearly same as the physical machine. We need a i440fx motherboard, the pci host bridge, the pci bus bus tree, the superio controller and isa bus tree. 

However we don't need this compilcated emulation. The most that we need for cloud workloads is computing, networking, storage. So cloud-hypervisor has following architecture. 

![](/assets/img/cloud_hypervisor/2.png)

As we can see, the cloud-hypervisor's architecutre is very easy, it even has no abstract of motherboard. It has just several virtio devices, no isa bus, no PCI bus tree. Following shows the pci devices.


![](/assets/img/cloud_hypervisor/4.png)

<h3> Some code </h3>

Following diagram shows the basic function callchains.

![](/assets/img/cloud_hypervisor/3.png)

Some of the notes:

cloud-hypervisor utils several rust-vmm components, such as vm-memory(for memory region), vm-allocator(for memory space and irq allocation), kvm-bindings(for kvm ioctl), linux-loader(for loading kernel elf file) and so on.

Like firecracker, cloud-hypervisor loads the kernel to VM's space and set the vcpu's PC to startup_64(entrypoint of vmlinux). Also cloud-hypervisor implements a firmware loader.

The memory region and irq resource is managed by a BTree.

Implement a legacy device (i8042) to shutdown the VM.

There are also some other interesting things in cloud-hypervisor/rust-vmm/firecracker/crosvm.

Anyway, the cloud-hypervisor has a clear architecture, it reduces the complexity of devices/buses which qemu has to emulate.  


