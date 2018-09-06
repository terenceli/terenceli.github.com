---
layout: post
title: "QEMU interrupt emulation"
description: "QEMU software interrupt emulation"
category: 技术
tags: [虚拟化, QEMU]
---
{% include JB/setup %}

I have written a blog about kvm interrupt emulation. As we know, the QEMU can emulation the whole system, in this blog, I will disscuss how the QEMU emulate the interrupt chip of a virtual machine. In this blog, we assume that all of the irqchip is emulated in QEMU, set the qemu command line with '-machine kernel-irqchip=split' can achive this.

<h3> Interrupt controller initialization </h3>

The function 'pc\_init1' first allocates the 'pcms->gsi' to represent the interrupt delivery start point. 

    pcms->gsi = qemu_allocate_irqs(gsi_handler, gsi_state, GSI_NUM_PINS);
    
    qemu_irq *qemu_allocate_irqs(qemu_irq_handler handler, void *opaque, int n)
    {
        return qemu_extend_irqs(NULL, 0, handler, opaque, n);
    }
    
    qemu_irq *qemu_extend_irqs(qemu_irq *old, int n_old, qemu_irq_handler handler,
                               void *opaque, int n)
    {
        qemu_irq *s;
        int i;
    
        if (!old) {
            n_old = 0;
        }
        s = old ? g_renew(qemu_irq, old, n + n_old) : g_new(qemu_irq, n);
        for (i = n_old; i < n + n_old; i++) {
            s[i] = qemu_allocate_irq(handler, opaque, i);
        }
        return s;
    }

This function allocates 24 'qemu\_irq' struct and the handler is set to 'gsi\_handler'. Here 'gsi' is the abbreviation of 'global system interrupts'.

Later, in 'i440fx\_init', this 'gsi' is assigned to 'piix3->pic', it also calls 'pci\_bus\_irqs' to set the pci bus's 'set\_irq' and 'get\_irq' function.

        pci_bus_irqs(b, piix3_set_irq, pci_slot_get_pirq, piix3,
                PIIX_NUM_PIRQS);

'piix3\_set\_irq' function finally calls 'piix3\_\set\_irq\_pic', which we can see calls the 'piix3->pic' which is the 'gsi'.

    static void piix3_set_irq_pic(PIIX3State *piix3, int pic_irq)
    {
        qemu_set_irq(piix3->pic[pic_irq],
                     !!(piix3->pic_levels &
                        (((1ULL << PIIX_NUM_PIRQS) - 1) <<
                         (pic_irq * PIIX_NUM_PIRQS))));
    }

Return to 'pc\_init1', it calls 'isa\_bus\_irqs', this function set the ISA bus's irqs to 'gsi'.

        isa_bus_irqs(isa_bus, pcms->gsi);


As we emulate irqchip in QEMU, it calls 'i8259\_init', it first calls 'pc\_allocate\_cpu\_irq' to allocate a parent\_irq. 'pic\_irq\_request' is used as this irq's handler.

        if (kvm_pic_in_kernel()) {
            i8259 = kvm_i8259_init(isa_bus);
        } else if (xen_enabled()) {
            i8259 = xen_interrupt_controller_init();
        } else {
            i8259 = i8259_init(isa_bus, pc_allocate_cpu_irq());
        }
        
    qemu_irq pc_allocate_cpu_irq(void)
    {
        return qemu_allocate_irq(pic_irq_request, NULL, 0);
    }

In order to understand function 'i8259\_init', we need first to look at the i8259 realize function.


    static void pic_realize(DeviceState *dev, Error **errp)
    {
        PICCommonState *s = PIC_COMMON(dev);
        PICClass *pc = PIC_GET_CLASS(dev);
    
        memory_region_init_io(&s->base_io, OBJECT(s), &pic_base_ioport_ops, s,
                              "pic", 2);
        memory_region_init_io(&s->elcr_io, OBJECT(s), &pic_elcr_ioport_ops, s,
                              "elcr", 1);
    
        qdev_init_gpio_out(dev, s->int_out, ARRAY_SIZE(s->int_out));
        qdev_init_gpio_in(dev, pic_set_irq, 8);
    
        pc->parent_realize(dev, errp);
    }

In 'pic\_realize' function, the most import function is 'qdev\_init\_gpio\_out' and 'qdev\_init\_gpio\_in'. 


        void qdev_init_gpio_out(DeviceState *dev, qemu_irq *pins, int n)
        {
            qdev_init_gpio_out_named(dev, pins, NULL, n);
        }
        
        void qdev_init_gpio_out_named(DeviceState *dev, qemu_irq *pins,
                                    const char *name, int n)
        {
            int i;
            NamedGPIOList *gpio_list = qdev_get_named_gpio_list(dev, name);
        
            assert(gpio_list->num_in == 0 || !name);
        
            if (!name) {
                name = "unnamed-gpio-out";
            }
            memset(pins, 0, sizeof(*pins) * n);
            for (i = 0; i < n; ++i) {
                gchar *propname = g_strdup_printf("%s[%u]", name,
                                                gpio_list->num_out + i);
        
                object_property_add_link(OBJECT(dev), propname, TYPE_IRQ,
                                        (Object **)&pins[i],
                                        object_property_allow_set_link,
                                        OBJ_PROP_LINK_UNREF_ON_RELEASE,
                                        &error_abort);
                g_free(propname);
            }
            gpio_list->num_out += n;
        }


 'qdev\_init\_gpio\_out' function add a link property named 'unamed-gpio-out[0]' and set the link *child to 'address of 's->int_out'. Likely , 'qdev\_init\_gpio\_in' adds 8 'unamed-gpio-in[0]' link property.

Return back function 'i8259\_init'.


        qemu_irq *i8259_init(ISABus *bus, qemu_irq parent_irq)
        {
            qemu_irq *irq_set;
            DeviceState *dev;
            ISADevice *isadev;
            int i;
        
            irq_set = g_new0(qemu_irq, ISA_NUM_IRQS);
        
            isadev = i8259_init_chip(TYPE_I8259, bus, true);
            dev = DEVICE(isadev);
        
            qdev_connect_gpio_out(dev, 0, parent_irq);
            for (i = 0 ; i < 8; i++) {
                irq_set[i] = qdev_get_gpio_in(dev, i);
            }
        
            isa_pic = dev;
        
            isadev = i8259_init_chip(TYPE_I8259, bus, false);
            dev = DEVICE(isadev);
        
            qdev_connect_gpio_out(dev, 0, irq_set[2]);
            for (i = 0 ; i < 8; i++) {
                irq_set[i + 8] = qdev_get_gpio_in(dev, i);
            }
        
            slave_pic = PIC_COMMON(dev);
        
            return irq_set;
        }


First create the master pic and set the output  pin ('s->int_out') to the 'parent\_irq', this is done through function 'qdev\_connect\_gpio\_out\_named' which set the 'unamed-gpio-out[0]' link property. Then create the slave pic and set its out pin to the master's second in pin. Finally return the 'irq\_set', this is all of the pic's 'qemu\_irq'. 

Then these 'qemu\_irq' is assigned to 'gsi\_state' and calls 'ioapic\_init\_gsi' to initialize the IOAPIC.

    void ioapic_init_gsi(GSIState *gsi_state, const char *parent_name)
    {
        DeviceState *dev;
        SysBusDevice *d;
        unsigned int i;
    
        if (kvm_ioapic_in_kernel()) {
            dev = qdev_create(NULL, "kvm-ioapic");
        } else {
            dev = qdev_create(NULL, "ioapic");
        }
        if (parent_name) {
            object_property_add_child(object_resolve_path(parent_name, NULL),
                                      "ioapic", OBJECT(dev), NULL);
        }
        qdev_init_nofail(dev);
        d = SYS_BUS_DEVICE(dev);
        sysbus_mmio_map(d, 0, IO_APIC_DEFAULT_ADDRESS);
    
        for (i = 0; i < IOAPIC_NUM_PINS; i++) {
            gsi_state->ioapic_irq[i] = qdev_get_gpio_in(dev, i);
        }
    }

Here create the ioapic device and set the 'gsi\_state->ioapic\_irq' with the ioapic's 'qemu\_irq'. The later is created in the realize of ioapic device. The handler is 'ioapic\_set\_irq'.

<h3> Interrupt delivery </h3>

Let's take a PCI device's interrupt delivery as an example. The PCI device can call 'pci\_set\_irq' to issue an interrupt to the kernel. 

    void pci_set_irq(PCIDevice *pci_dev, int level)
    {
        int intx = pci_intx(pci_dev);
        pci_irq_handler(pci_dev, intx, level);
    }
    static inline int pci_intx(PCIDevice *pci_dev)
    {
        return pci_get_byte(pci_dev->config + PCI_INTERRUPT_PIN) - 1;
    }
    
    static void pci_irq_handler(void *opaque, int irq_num, int level)
    {
        PCIDevice *pci_dev = opaque;
        int change;
    
        change = level - pci_irq_state(pci_dev, irq_num);
        if (!change)
            return;
    
        pci_set_irq_state(pci_dev, irq_num, level);
        pci_update_irq_status(pci_dev);
        if (pci_irq_disabled(pci_dev))
            return;
        pci_change_irq_level(pci_dev, irq_num, change);
    }
    
    static void pci_change_irq_level(PCIDevice *pci_dev, int irq_num, int change)
    {
        PCIBus *bus;
        for (;;) {
            bus = pci_get_bus(pci_dev);
            irq_num = bus->map_irq(pci_dev, irq_num);
            if (bus->set_irq)
                break;
            pci_dev = bus->parent_dev;
        }
        bus->irq_count[irq_num] += change;
        bus->set_irq(bus->irq_opaque, irq_num, bus->irq_count[irq_num] != 0);
    }

There are a little PCI-specific knowledge I will not discuss just focus the interrupt instead. 
In the last function 'pci\_change\_irq\_level', it calls the PCI bus' 'map\_irq' to get the irq number and then call 'set\_irq' which as we know is 'piix3\_set\_irq'. This function calls 'piix3\_set\_irq\_pic'.

    static void piix3_set_irq_pic(PIIX3State *piix3, int pic_irq)
    {
        qemu_set_irq(piix3->pic[pic_irq],
                     !!(piix3->pic_levels &
                        (((1ULL << PIIX_NUM_PIRQS) - 1) <<
                         (pic_irq * PIIX_NUM_PIRQS))));
    }

The piix3->pic is the gsi and the handler is 'gsi\_handler'.


    void gsi_handler(void *opaque, int n, int level)
    {
        GSIState *s = opaque;
    
        DPRINTF("pc: %s GSI %d\n", level ? "raising" : "lowering", n);
        if (n < ISA_NUM_IRQS) {
            qemu_set_irq(s->i8259_irq[n], level);
        }
        qemu_set_irq(s->ioapic_irq[n], level);
    }

Choose the interrupt controller according the irq number and aclls the corresponding handler. Take ioapic\_irq as for example, the handler is 'ioapic\_set\_irq'. In this function it calls 'ioapic\_service' to delivery interrupt to the LAPIC. This is through 'stl\_le\_phys', this will cause the apic's MMIO write function being called, which is 'apic\_mem\_writel'.  APIC can call 'apic\_update\_irq' to process interrupt. THen 'cpu\_interrupt'  and finally 'kvm\_handle\_interrupt' is called.

    static void kvm_handle_interrupt(CPUState *cpu, int mask)
    {
        cpu->interrupt_request |= mask;
    
        if (!qemu_cpu_is_self(cpu)) {
            qemu_cpu_kick(cpu);
        }
    }

Here set the 'cpu->interrupt\_request' then in the next enter the guest, the QEMU will call ioctl with 'KVM\_INTERRUPT' ioctl to inject the interrupt to the guest. 

Let's see a backtrack of interrupt delivery to make a more deep impression.


    (gdb) bt
    #0  apic_mem_write (opaque=0x61600000a280, addr=16388, val=33, size=4)
        at /home/test/qemu/hw/intc/apic.c:756
    #1  0x000055ce1f7241fd in memory_region_write_accessor (mr=0x61600000a300, 
        addr=16388, value=0x7f329b8f8188, size=4, shift=0, mask=4294967295, 
        attrs=...) at /home/test/qemu/memory.c:526
    #2  0x000055ce1f7244d6 in access_with_adjusted_size (addr=16388, 
        value=0x7f329b8f8188, size=4, access_size_min=1, access_size_max=4, 
        access_fn=0x55ce1f72404f <memory_region_write_accessor>, 
        mr=0x61600000a300, attrs=...) at /home/test/qemu/memory.c:593
    #3  0x000055ce1f72b2cc in memory_region_dispatch_write (mr=0x61600000a300, 
        addr=16388, data=33, size=4, attrs=...) at /home/test/qemu/memory.c:1473
    #4  0x000055ce1f65021b in address_space_stl_internal (
        as=0x55ce2142c940 <address_space_memory>, addr=4276109316, val=33, 
        attrs=..., result=0x0, endian=DEVICE_LITTLE_ENDIAN)
        at /home/test/qemu/memory_ldst.inc.c:349
    #5  0x000055ce1f65047f in address_space_stl_le (
        as=0x55ce2142c940 <address_space_memory>, addr=4276109316, val=33, 
        attrs=..., result=0x0) at /home/test/qemu/memory_ldst.inc.c:386
    #6  0x000055ce1f80aff5 in stl_le_phys (
        as=0x55ce2142c940 <address_space_memory>, addr=4276109316, val=33)
        at /home/test/qemu/include/exec/memory_ldst_phys.inc.h:103
    #7  0x000055ce1f80c8af in ioapic_service (s=0x61b000002a80)
        at /home/test/qemu/hw/intc/ioapic.c:136
    ---Type <return> to continue, or q <return> to quit---
    #8  0x000055ce1f80cb35 in ioapic_set_irq (opaque=0x61b000002a80, vector=15, 
        level=1) at /home/test/qemu/hw/intc/ioapic.c:175
    #9  0x000055ce1fbe79a0 in qemu_set_irq (irq=0x60600006a880, level=1)
        at hw/core/irq.c:45
    #10 0x000055ce1f8bfb1c in gsi_handler (opaque=0x612000007540, n=15, level=1)
        at /home/test/qemu/hw/i386/pc.c:120
    #11 0x000055ce1fbe79a0 in qemu_set_irq (irq=0x6060000414e0, level=1)
        at hw/core/irq.c:45
    #12 0x000055ce1fc8a0f3 in bmdma_irq (opaque=0x6250001c3e10, n=0, level=1)
        at hw/ide/pci.c:222
    #13 0x000055ce1fbe79a0 in qemu_set_irq (irq=0x606000091280, level=1)
        at hw/core/irq.c:45
    #14 0x000055ce1fc7ba3c in qemu_irq_raise (irq=0x606000091280)
        at /home/test/qemu/include/hw/irq.h:16
    #15 0x000055ce1fc7bb20 in ide_set_irq (bus=0x6250001c32c0)
        at /home/test/qemu/include/hw/ide/internal.h:568
    #16 0x000055ce1fc7fa75 in ide_atapi_cmd_reply_end (s=0x6250001c3338)
        at hw/ide/atapi.c:319
    #17 0x000055ce1fc7902c in ide_data_readl (opaque=0x6250001c32c0, addr=368)
        at hw/ide/core.c:2389
    #18 0x000055ce1f713e32 in portio_read (opaque=0x614000002040, addr=0, size=4)
        at /home/test/qemu/ioport.c:180
    #19 0x000055ce1f7239bb in memory_region_read_accessor (mr=0x614000002040, 
    ---Type <return> to continue, or q <return> to quit---
        addr=0, value=0x7f329b8f8790, size=4, shift=0, mask=4294967295, attrs=...)
        at /home/test/qemu/memory.c:435
    #20 0x000055ce1f7244d6 in access_with_adjusted_size (addr=0, 
        value=0x7f329b8f8790, size=4, access_size_min=1, access_size_max=4, 
        access_fn=0x55ce1f723913 <memory_region_read_accessor>, mr=0x614000002040, 
        attrs=...) at /home/test/qemu/memory.c:593
    #21 0x000055ce1f72aa42 in memory_region_dispatch_read1 (mr=0x614000002040, 
        addr=0, pval=0x7f329b8f8790, size=4, attrs=...)
        at /home/test/qemu/memory.c:1392
    #22 0x000055ce1f72ac25 in memory_region_dispatch_read (mr=0x614000002040, 
        addr=0, pval=0x7f329b8f8790, size=4, attrs=...)
        at /home/test/qemu/memory.c:1423
    #23 0x000055ce1f64cd0c in flatview_read_continue (fv=0x60600017f120, addr=368, 
        attrs=..., buf=0x7f329e50c004 "", len=4, addr1=0, l=4, mr=0x614000002040)
        at /home/test/qemu/exec.c:3293
    #24 0x000055ce1f64d028 in flatview_read (fv=0x60600017f120, addr=368, 
        attrs=..., buf=0x7f329e50c004 "", len=4) at /home/test/qemu/exec.c:3331
    #25 0x000055ce1f64d0ed in address_space_read_full (
        as=0x55ce2142c8c0 <address_space_io>, addr=368, attrs=..., 
        buf=0x7f329e50c004 "", len=4) at /home/test/qemu/exec.c:3344
    #26 0x000055ce1f64d1c4 in address_space_rw (
        as=0x55ce2142c8c0 <address_space_io>, addr=368, attrs=..., 
        buf=0x7f329e50c004 "", len=4, is_write=false)
    ---Type <return> to continue, or q <return> to quit---
        at /home/test/qemu/exec.c:3374
    #27 0x000055ce1f770021 in kvm_handle_io (port=368, attrs=..., 
        data=0x7f329e50c000, direction=0, size=4, count=2)
        at /home/test/qemu/accel/kvm/kvm-all.c:1731
    #28 0x000055ce1f7712f9 in kvm_cpu_exec (cpu=0x631000028800)
        at /home/test/qemu/accel/kvm/kvm-all.c:1971
    #29 0x000055ce1f6e5650 in qemu_kvm_cpu_thread_fn (arg=0x631000028800)
        at /home/test/qemu/cpus.c:1257
    #30 0x000055ce20354746 in qemu_thread_start (args=0x603000024a60)
        at util/qemu-thread-posix.c:504
    #31 0x00007f32a175b6db in start_thread (arg=0x7f329b8f9700)
        at pthread_create.c:463
    #32 0x00007f32a148488f in clone ()
    