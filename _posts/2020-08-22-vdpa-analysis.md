---
layout: post
title: "vDPA kernel framework introduction"
description: "vdpa"
category: 技术
tags: [内核, 虚拟化]
---
{% include JB/setup %}


Virtual data path acceleration(vDPA) is a new technogy to acclerate the performance (like other hardware offloading). A vDPA device is a device whose datapath compiles with the virtio spec but whose controlpath is vendor-specific. 

The vDPA device can be implemented by a device of PF, VF, VDEV, SF. In order to support the vDPA device and hide the complexity of the hardware, vDPA kernel framework has been implemented. Following is the overview architecure which from [vDPA Kernel Framework Part #1: vDPA Bus for Abstracting Hardware](https://www.redhat.com/en/blog/vdpa-kernel-framework-part-1-vdpa-bus-abstracting-hardware).

![](/assets/img/vdpa/1.png)

The vDPA framework is used to abstract the vDPA devices and present them as a virtio device to vhost/virtio subsystem. There are three component in vDPA framework.

<h3> vDPA bus </h3>

The code is in 'drivers/vdpa/vdpa.c'. The vDPA bus can be used to hold the several types of vdpa bus drivers and vdpa devices.
Some of the export function:

* '__vdpa_alloc_device': This is called from the vDPA device driver, it allocates vdpa device, the 'vdpa_config_ops' parameter is used to specify the vendor-specific operations. These operations include 'virtqueue ops', 'device ops', 'dma ops'.

* 'vdpa_register_device': register a vDPA device

* '__vdpa_register_driver': register a vDPA bus driver



vDPA bus is registered when the system is startup.


<h3> vDPA device driver </h3>

vDPA device driver is used to communicate directly with the vDPA device through the vendor specific method and present a vDPA abstract device to the vDPA bus. There are currently two vDPA device driver. 

* ifcvf device driver: in drivers/vdpa/ifcvf directory. This is currently the only vDPA hardware device driver in upstream.
* vdpa simulator: in drivers/vdpa/vdpa_sim directory. This is just a vDPA simulator device driver.

In the dirver's probe function, it will call 'vdpa_register_device' to register a vDPA device. 





<h3> vDPA bus driver </h3>

vDPA bus driver is used to connect the vDPA bus to vhost and virtio subsystem. There are two types of vDPA bus drivers.

* vhost vdpa bus driver: the code is in 'drivers/vhost/vdpa.c'. This driver connects the vDPA bus to the vhost subsystem and presents export a vhost char device to userspace. The userspace can then use this vhost dev to bypass the host kernel.

* virtio vdpa bus driver: the code is in 'drivers/virtio/virtio_vdpa.c'. This driver abstract the vdpa device to a virtio device. It creates a virtio device in the virtio bus. 



Following shows the data structure relations.


![](/assets/img/vdpa/2.png)


