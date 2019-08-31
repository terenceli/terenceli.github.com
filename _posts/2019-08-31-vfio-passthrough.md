---
layout: post
title: "qemu VM device passthrough using VFIO, the code analysis"
description: "VFIO"
category: 技术
tags: [虚拟化, qemu]
---
{% include JB/setup %}


QEMU uses VFIO to assign physical devices to VMs. When using vfio, the qemu command line should add following option:

        -device vfio-pci,host=00:12.0,id=net0

This adds a vfio-pci device sets the physical device's path to 'host'. As we have said in the [VFIO driver analysis](https://terenceli.github.io/%E6%8A%80%E6%9C%AF/2019/08/21/vfio-driver-analysis) post VFIO decomposes the physical device as a set of userspace API and recomposes the physical device's resource. So the most work of the vfio-pci device's realization 'vfio_realize' is to decompose the physical device and setup the relation of the physical device's resource with the virtual machine.


<h3> Bind the device to a domain </h3>

The physical device which will be assigned to VM has been bind to vfio-pci, the group in '/dev/vfio/' has been created. So 'vfio_realize' first check the device and get the device's groupid. Then it call 'vfio_get_group'. Following is the call chain of this function.

        vfio_get_group
                ->qemu_open("/dev/vfio/$groupid")
                ->vfio_connect_container
                        ->qemu_open("/dev/vfio/vfio")
                        ->vfio_init_container
                                ->ioctl(VFIO_GROUP_SET_CONTAINER)
                                ->ioctl(VFIO_SET_IOMMU)
                        ->vfio_kvm_device_add_group
                        ->memory_listener_register


'vfio_get_group' first open the group file in '/dev/vfio/$groupid'. 'vfio_connect_container' opens a new container and calls 'vfio_init_container' to add this vfio group to the container. After 'vfio_init_container', the device has been related with a conatiner. And the root iommu's root table has been setup.

'vfio_kvm_device_add_group' bridges the 'kvm' subsystem and 'iommu' subsystem. In the final 'vfio_connect_container' it registers a 'vfio_memory_listener' to listen the memory layout change event. In the 'region_add' callback it calls 'vfio_dma_map' to setup the gpa(iova)->hpa. When the guest uses the gpa in DMA programming, the iommu can translate this gpa to hpa and access the physical memory directly.


<h3> Populate the device's resource </h3>

After setting the device's DMA remapping, 'vfio_realize' will get the device's resource and use these resources to reconstruct the vfio-pci device. 

First 'vfio_get_device' get the vfio device's fd by calling 'ioctl(VFIO_GROUP_GET_DEVICE_FD)' with the assigned device' name. Then 'vfio_get_device' calls 'ioctl(VFIO_DEVICE_GET_INFO)' on the device fd and get the basic info of the device. 

        struct vfio_device_info {
                __u32	argsz;
                __u32	flags;
        #define VFIO_DEVICE_FLAGS_RESET	(1 << 0)	/* Device supports reset */
        #define VFIO_DEVICE_FLAGS_PCI	(1 << 1)	/* vfio-pci device */
        #define VFIO_DEVICE_FLAGS_PLATFORM (1 << 2)	/* vfio-platform device */
        #define VFIO_DEVICE_FLAGS_AMBA  (1 << 3)	/* vfio-amba device */
        #define VFIO_DEVICE_FLAGS_CCW	(1 << 4)	/* vfio-ccw device */
        #define VFIO_DEVICE_FLAGS_AP	(1 << 5)	/* vfio-ap device */
                __u32	num_regions;	/* Max region index + 1 */
                __u32	num_irqs;	/* Max IRQ index + 1 */
        };

Return to 'vfio_realize', after 'vfio_get_device' it calls 'vfio_populate_device' to populate the device's resource. 'vfio_populate_device' get the 6 BAR region info and 1 PCI config region info and 1 vga region info(If has). 'vfio_region_setup' is called to populated the BAR region. Every region is strored in a 'VFIORegion'.

        typedef struct VFIORegion {
        struct VFIODevice *vbasedev;
        off_t fd_offset; /* offset of region within device fd */
        MemoryRegion *mem; /* slow, read/write access */
        size_t size;
        uint32_t flags; /* VFIO region flags (rd/wr/mmap) */
        uint32_t nr_mmaps;
        VFIOMmap *mmaps;
        uint8_t nr; /* cache the region number for debug */
        } VFIORegion;

When we unbind the physical device from its driver, and rebind it with vfio-pci driver, the resource of device is released. Here the 'fd_offset' represent the offset within the device fd doing mmap. 'mem' is used for qemu to represent on IO region. 

Calling ioctl(VFIO_DEVICE_GET_REGION_INFO) on the device fd we can get the region info, the most important is regions's size, flags, fd_offset, and index.

After getting the io region info, 'vfio_populate_device' gets the PCI configuration region.

Later in the 'vfio_realize' it calls 'vfio_bars_prepare' and 'vfio_bars_register' to mmap the device's io region to usespace. 'vfio_bars_prepare' calls 'vfio_bar_prepare' for every io region.
'vfio_bar_prepare' get the info of the io region such as "the IO region is ioport or mmio", "the mem type of thsi IO region'. 'vfio_bars_register' calls 'vfio_bar_register' on every io region. 'vfio_bar_register' initialize a MemoryRegion and calls 'vfio_region_mmap' to mmap the device io region to userspace. Finally 'vfio_bar_register' calls 'pci_register_bar' to register BAR for vfio-pci device. Here we can see the parameter of 'pci_register_bar' is from the physical device.

        static void vfio_bar_register(VFIOPCIDevice *vdev, int nr)
        {
        VFIOBAR *bar = &vdev->bars[nr];
        char *name;

        if (!bar->size) {
                return;
        }

        bar->mr = g_new0(MemoryRegion, 1);
        name = g_strdup_printf("%s base BAR %d", vdev->vbasedev.name, nr);
        memory_region_init_io(bar->mr, OBJECT(vdev), NULL, NULL, name, bar->size);
        g_free(name);

        if (bar->region.size) {
                memory_region_add_subregion(bar->mr, 0, bar->region.mem);

                if (vfio_region_mmap(&bar->region)) {
                error_report("Failed to mmap %s BAR %d. Performance may be slow",
                                vdev->vbasedev.name, nr);
                }
        }

        pci_register_bar(&vdev->pdev, nr, bar->type, bar->mr);
        }


Following figure shows the data structure of VFIORegion.

![](/assets/img/vfio3/1.png)


Here we can see, the vfio-pci IO region actually has the backend qemu's virtual memory. It is the IO region of the physical device mapped into the userspace. In normal qemu virtual device case, the IO region is not backed with a region of virtual memory, so when the guest access these IO region, it traps into the qemu by EPT misconfiguration. For vfio-pci virtual device, its IO region has a backend virtual memory, so when the qemu setup the EPT map, this will also setup these IO region. When the guest access the vfio-pci device's IO region. It just accesses the physical device IO region. Remember the userspace IO region of vfio-pci device is mammped from the physical device. 



<h3> Config the device </h3>

In 'vfio_populate_device' it will get the PCI configuration region's size and offset within the vfio device fd. In 'vfio_realize' after 'vfio_populate_device' it calls 'pread' to read the device's PCI config region and store it in 'vdev->pdev.config'. 

        ret = pread(vdev->vbasedev.fd, vdev->pdev.config,
                        MIN(pci_config_size(&vdev->pdev), vdev->config_size),
                        vdev->config_offset);


'vfio_realize' then allocates a 'emulated_config_bits'space. This space contains the bits to indicate which 'PCI config region' is used when the guest access the vfio pci device's pci config region. If the byte(bits) in the 'emulated_config_bits' is set, 'vdev->pdev.config' is used, if it is not set, the qemu will access the physical device's PCI config region.

'vfio_realize' configures the vfio pci device according the physical device, for example reading the 'PCI_VENDOR_ID' to assign to 'vdev->vendor_id', and the 'PCI_DEVICE_ID' to assign to 'vdev->device_id'. 'vfio_pci_size_rom', 'vfio_msix_early_setup', 'vfio_add_capabilities' just operates the PCI configuration region.

Then 'vfio_realize' setup the device's interrupt process.

        if (vfio_pci_read_config(&vdev->pdev, PCI_INTERRUPT_PIN, 1)) {
                vdev->intx.mmap_timer = timer_new_ms(QEMU_CLOCK_VIRTUAL,
                                                        vfio_intx_mmap_enable, vdev);
                pci_device_set_intx_routing_notifier(&vdev->pdev, vfio_intx_update);
                ret = vfio_intx_enable(vdev, errp);
                if (ret) {
                goto out_teardown;
                }
        }



Here 'pci_device_set_intx_routing_notifier' is called to register a 'intx_routing_notifier'. We need this because the host bridge of the guest may change the assigned device's INTx to irq mapping. 

        static int vfio_intx_enable(VFIOPCIDevice *vdev, Error **errp)
        {
        uint8_t pin = vfio_pci_read_config(&vdev->pdev, PCI_INTERRUPT_PIN, 1);
        Error *err = NULL;
        int32_t fd;
        int ret;


        if (!pin) {
                return 0;
        }

        vfio_disable_interrupts(vdev);

        vdev->intx.pin = pin - 1; /* Pin A (1) -> irq[0] */
        pci_config_set_interrupt_pin(vdev->pdev.config, pin);

        #ifdef CONFIG_KVM
        /*
        * Only conditional to avoid generating error messages on platforms
        * where we won't actually use the result anyway.
        */
        if (kvm_irqfds_enabled() && kvm_resamplefds_enabled()) {
                vdev->intx.route = pci_device_route_intx_to_irq(&vdev->pdev,
                                                                vdev->intx.pin);
        }
        #endif

        ret = event_notifier_init(&vdev->intx.interrupt, 0);
        if (ret) {
                error_setg_errno(errp, -ret, "event_notifier_init failed");
                return ret;
        }
        fd = event_notifier_get_fd(&vdev->intx.interrupt);
        qemu_set_fd_handler(fd, vfio_intx_interrupt, NULL, vdev);

        if (vfio_set_irq_signaling(&vdev->vbasedev, VFIO_PCI_INTX_IRQ_INDEX, 0,
                                VFIO_IRQ_SET_ACTION_TRIGGER, fd, &err)) {
                error_propagate(errp, err);
                qemu_set_fd_handler(fd, NULL, NULL, vdev);
                event_notifier_cleanup(&vdev->intx.interrupt);
                return -errno;
        }

        vfio_intx_enable_kvm(vdev, &err);
        if (err) {
                warn_reportf_err(err, VFIO_MSG_PREFIX, vdev->vbasedev.name);
        }

        vdev->interrupt = VFIO_INT_INTx;

        trace_vfio_intx_enable(vdev->vbasedev.name);
        return 0;
        }

'vfio_intx_enable' set the vfio pci device's interrupt. This function initialize an EventNotifier 'vdev->intx.interrupt'.  The 'read' of this event notifier is 'vfio_intx_interrupt'. Then 'vfio_intx_enable' calls 'vfio_set_irq_signaling' to set the fd as the interrupt eventfd. When host device receives interrupt, it will signal in this eventfd. The handler of this fd which is 'vfio_intx_interrupt' will handle this interrupt. This is the common case, but it is not efficient. So 'vfio_intx_enable_kvm' is called. 

kvm has a mechanism called irqfd. qemu can call ioctl(KVM_IRQFD) with 'kvm_irqfd' parameter to connect a irq and a fd.

        struct kvm_irqfd irqfd = {
                .fd = event_notifier_get_fd(&vdev->intx.interrupt),
                .gsi = vdev->intx.route.irq,
                .flags = KVM_IRQFD_FLAG_RESAMPLE,
        };

When the 'fd' has was signaled, the kvm subsystem will inject a 'gsi' interrupt to the VM. The irqfd bypass the userspace qemu and inject interrupt in kernel directly.

'vfio_intx_enable_kvm' is used to setup the interrupt fd's irqfd. Notice here is a resample fd. In the vfio device interrupt handler in kernel, it will disable the interrupt. When the guest completes the interrupt dispatch, it will trigger an EOI and then the vfio can signal an event in the resample fd and reenable the interrupt again.

After doing some of the quirk work, 'vfio_realize' calls 'vfio_register_err_notifier' and 'vfio_register_req_notifier' to register two EventNotifier. Error EventNotifier is signaled when the physical has unrecoveralbe error detected. And req EventNotifier is signaled to unplug the vfio pci device. 



