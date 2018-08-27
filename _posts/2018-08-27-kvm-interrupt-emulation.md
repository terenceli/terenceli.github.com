---
layout: post
title: "kvm interrupt emulation"
description: "kvm interrupt"
category: 技术
tags: [kvm]
---
{% include JB/setup %}

<h3> External interrupt </h3>

First of all, let's clarify the external interrupt in kvm. This kind of interrupt means the interrupt for the host. kvm will be caused vm-exit when the CPU receives the external interrupt. THis is configured by flag PIN\_BASED\_EXT\_INTR\_MASK which is write to the VMCS's pin-based VM-execution control field in function setup\_vmcs\_config. When the external interrupts comes, it will call handle\_external\_intr callback.

	kvm_x86_ops->handle_external_intr(vcpu);

For intel CPU, this is the 'vmx\_handle\_external\_intr'.

	static void vmx_handle_external_intr(struct kvm_vcpu *vcpu)
	{
		u32 exit_intr_info = vmcs_read32(VM_EXIT_INTR_INFO);

		/*
		* If external interrupt exists, IF bit is set in rflags/eflags on the
		* interrupt stack frame, and interrupt will be enabled on a return
		* from interrupt handler.
		*/
		if ((exit_intr_info & (INTR_INFO_VALID_MASK | INTR_INFO_INTR_TYPE_MASK))
				== (INTR_INFO_VALID_MASK | INTR_TYPE_EXT_INTR)) {
			unsigned int vector;
			unsigned long entry;
			gate_desc *desc;
			struct vcpu_vmx *vmx = to_vmx(vcpu);
	#ifdef CONFIG_X86_64
			unsigned long tmp;
	#endif

			vector =  exit_intr_info & INTR_INFO_VECTOR_MASK;
			desc = (gate_desc *)vmx->host_idt_base + vector;
			entry = gate_offset(*desc);
			asm volatile(
	#ifdef CONFIG_X86_64
				"mov %%" _ASM_SP ", %[sp]\n\t"
				"and $0xfffffffffffffff0, %%" _ASM_SP "\n\t"
				"push $%c[ss]\n\t"
				"push %[sp]\n\t"
	#endif
				"pushf\n\t"
				"orl $0x200, (%%" _ASM_SP ")\n\t"
				__ASM_SIZE(push) " $%c[cs]\n\t"
				"call *%[entry]\n\t"
				:
	#ifdef CONFIG_X86_64
				[sp]"=&r"(tmp)
	#endif
				:
				[entry]"r"(entry),
				[ss]"i"(__KERNEL_DS),
				[cs]"i"(__KERNEL_CS)
				);
		} else
			local_irq_enable();
	}

Here check is there a valid external interrupt exists(INTR\_INFO\_VALID\_MASK ). If there is,  just call the host interrupt handler.  

That's so easy, no mysterious.

<h3> Interrupt delivery methods </h3>

There are  three generations of interrupt delivery and servicing on Intel architecture: XT-PIC for legacy uni-processor (UP) systems, IO-APIC for modern UP and multi-processor (MP) systems, and MSI.

<h4> XT-PIC </h4>
XT-PIC is the oldest form of interrupt delivery. It uses two intel 8259 PIC chips and each PIC chips has eight interrupts. 

![](/assets/img/kvminterrupt/1.png)

When a connected device needs servicing by the CPU, it drives the signal on the interrupt pin to which it is connected. The 8259 PIC in turn drives the interrupt line into the CPU. From the Intel 8259 PIC, the OS is able to determine what interrupt is pending. The CPU masks that interrupt and begins running the ISR associated with it. The ISR will check with the device with which it is associated for a pending interrupt. If the device has a pending interrupt, then the ISR will clear the Interrupt Request (IRQ) pending and begin servicing the device. Once the ISR has completed servicing the device, it will schedule a tasklet if more processing is needed and return control back to the OS, indicating that it handled an interrupt. Once the OS has serviced the interrupt, it will unmask the interrupt from the Intel 8259 PIC and run any tasklet which has been scheduled. 

<h4> IO-APIC </h4>

When intel developed multiprocessor, he also introduced the concept of a Local-APIC (Advanced PIC) in the CPU and IO-APICs connected to devices.  each IO-APIC (82093) has 24 interrupt lines. The IO-APCI provides backwards compatibility with the older XT-PIC model. As a result, the lower 16 interrupts are usually dedicated to their assignments under the XT-PIC model. This assignment of interrupts provides only eight additional interrupts, which forces sharing.The following is the sequence for IO-APIC delivery and servicing: 
• A device needing servicing from the CPU drives the interrupt line into the IO-APIC associated with it. 
• The IO-APIC writes the interrupt vector associated with its driven interrupt line into the Local APIC of the CPU.
 • The interrupted CPU begins running the ISRs associated with the interrupt vector it received. 
Each ISR for a shared interrupt is run to find the device needing service. 
Each device has its IRQ pending bit checked, and the requesting device has its bit cleared. 

<h4> Message Signaled Interrupts (MSI) </h4>
The MSI model eliminates the devices’ need to use the IO-APIC, allowing every device to write directly to the CPU’s Local-APIC. The MSI model supports 224 interrupts, and, with this high number of interrupts, IRQ sharing is no longer allowed. The following is the sequence for MSI delivery and servicing: 
• A device needing servicing from the CPU generates an MSI, writing the interrupt vector directly into the Local-APIC of the CPU servicing it. 
• The interrupted CPU begins running the ISR associated with the interrupt vector it received. The device is serviced without any need to check and clear an IRQ pending bit  

Following picture shows the relations of the three methods(From https://cloud.tencent.com/developer/article/1087271).

![](/assets/img/kvminterrupt/2.png)

For the hardware the interrupt is generated by the device itself, so in virtualization environment the interrupt is generated in the device emulation. It can be generated both in qemu (device emulation implementation in userspace) kvm (device emulation implementation in kernel space). 

The device emulation trigger an irq(< 16) and this will be both deliveried to i8259 and io-apic, and io-apic format the interrupt message and routing it to lapic. So there are three interrupt controller device need be emulated, the i8259, the io-apic and the lapic device. All of these devices can be implemented in qemu or in kvm all pic and io-apic in qemu and lapic in kvm.

Let's first talk about the implementation in kvm. 

<h3> KVM impplements the irqchip </h3>

<h4> The initialization of PIC and IO-APIC </h4>

PIC and IO-APIC is created by the VM ioctl 'KVM\_CREATE\_IRQCHIP'. It's called in 'kvm\_irqchip\_create' in qemu  and is implemented in 'kvm\_arch\_vm\_ioctl' in kvm.
pic is created by function 'kvm\_create\_pic' and assigned to the 'kvm->arch.vpic'. In the creation function, it allocates 'kvm\_pic' and also register the device's read/write ops.

Follow on the pic, it creates ioapic using function 'kvm\_ioapic\_init', like pic, the creation function allocates a 'kvm\_ioapic' and register the read/write ops and also, assign this to the 'kvm->arch.vioapic'. 

After create the pic and ioapic, it calls 'kvm\_setup\_default\_irq\_routing' to setup the routing table. 

	int kvm_setup_default_irq_routing(struct kvm *kvm)
	{
		return kvm_set_irq_routing(kvm, default_routing,
					   ARRAY_SIZE(default_routing), 0);
	}

	int kvm_set_irq_routing(struct kvm *kvm,
				const struct kvm_irq_routing_entry *ue,
				unsigned nr,
				unsigned flags)
	{
		struct kvm_irq_routing_table *new, *old;
		u32 i, j, nr_rt_entries = 0;
		int r;

		for (i = 0; i < nr; ++i) {
			if (ue[i].gsi >= KVM_MAX_IRQ_ROUTES)
				return -EINVAL;
			nr_rt_entries = max(nr_rt_entries, ue[i].gsi);
		}

		nr_rt_entries += 1;

		new = kzalloc(sizeof(*new) + (nr_rt_entries * sizeof(struct hlist_head))
			      + (nr * sizeof(struct kvm_kernel_irq_routing_entry)),
			      GFP_KERNEL);

		if (!new)
			return -ENOMEM;

		new->rt_entries = (void *)&new->map[nr_rt_entries];

		new->nr_rt_entries = nr_rt_entries;
		for (i = 0; i < KVM_NR_IRQCHIPS; i++)
			for (j = 0; j < KVM_IRQCHIP_NUM_PINS; j++)
				new->chip[i][j] = -1;

		for (i = 0; i < nr; ++i) {
			r = -EINVAL;
			if (ue->flags)
				goto out;
			r = setup_routing_entry(new, &new->rt_entries[i], ue);
			if (r)
				goto out;
			++ue;
		}

		mutex_lock(&kvm->irq_lock);
		old = kvm->irq_routing;
		kvm_irq_routing_update(kvm, new);
		mutex_unlock(&kvm->irq_lock);

		synchronize_rcu();

		new = old;
		r = 0;

	out:
		kfree(new);
		return r;
	}

'kvm\_irq\_routing\_entry' represents the irq routing entry. The default\_routing is defined as follows.

	static const struct kvm_irq_routing_entry default_routing[] = {
		ROUTING_ENTRY2(0), ROUTING_ENTRY2(1),
		ROUTING_ENTRY2(2), ROUTING_ENTRY2(3),
		ROUTING_ENTRY2(4), ROUTING_ENTRY2(5),
		ROUTING_ENTRY2(6), ROUTING_ENTRY2(7),
		ROUTING_ENTRY2(8), ROUTING_ENTRY2(9),
		ROUTING_ENTRY2(10), ROUTING_ENTRY2(11),
		ROUTING_ENTRY2(12), ROUTING_ENTRY2(13),
		ROUTING_ENTRY2(14), ROUTING_ENTRY2(15),
		ROUTING_ENTRY1(16), ROUTING_ENTRY1(17),
		ROUTING_ENTRY1(18), ROUTING_ENTRY1(19),
		ROUTING_ENTRY1(20), ROUTING_ENTRY1(21),
		ROUTING_ENTRY1(22), ROUTING_ENTRY1(23),
	} 

For the irq < 16, it has two entries, one for pic and one for ioapic. The ioapic entry is in the front.

	#define IOAPIC_ROUTING_ENTRY(irq) \
		{ .gsi = irq, .type = KVM_IRQ_ROUTING_IRQCHIP,	\
		  .u.irqchip.irqchip = KVM_IRQCHIP_IOAPIC, .u.irqchip.pin = (irq) }
	#define ROUTING_ENTRY1(irq) IOAPIC_ROUTING_ENTRY(irq)

	#ifdef CONFIG_X86
	#  define PIC_ROUTING_ENTRY(irq) \
		{ .gsi = irq, .type = KVM_IRQ_ROUTING_IRQCHIP,	\
		  .u.irqchip.irqchip = SELECT_PIC(irq), .u.irqchip.pin = (irq) % 8 }
	#  define ROUTING_ENTRY2(irq) \
		IOAPIC_ROUTING_ENTRY(irq), PIC_ROUTING_ENTRY(irq)

	Here irqchip is 0,1 for pic and 2 for ioapic.
	Goto function 'kvm\_set\_irq\_routing', this functions allocates a 'kvm\_irq\_routing\_table'.

	struct kvm_irq_routing_table {
		int chip[KVM_NR_IRQCHIPS][KVM_IRQCHIP_NUM_PINS];
		struct kvm_kernel_irq_routing_entry *rt_entries;
		u32 nr_rt_entries;
		/*
		* Array indexed by gsi. Each entry contains list of irq chips
		* the gsi is connected to.
		*/
		struct hlist_head map[0];
	};

Here 'KVM\_NR\_IRQCHIPS' is 3, means two pic chips and one io-apic chip. 'KVM\_IRQCHIP\_NUM\_PINS' is 24 means the ioapic has 24 pins.  Every irq has one 'kvm\_kernel\_irq\_routing\_entry'.

For every 'kvm\_irq\_routing\_entry', it calls 'setup\_routing\_entry' to initialize the 'kvm\_kernel\_irq\_routing\_entry'. 

	static int setup_routing_entry(struct kvm_irq_routing_table *rt,
				       struct kvm_kernel_irq_routing_entry *e,
				       const struct kvm_irq_routing_entry *ue)
	{
		int r = -EINVAL;
		struct kvm_kernel_irq_routing_entry *ei;

		/*
		* Do not allow GSI to be mapped to the same irqchip more than once.
		* Allow only one to one mapping between GSI and MSI.
		*/
		hlist_for_each_entry(ei, &rt->map[ue->gsi], link)
			if (ei->type == KVM_IRQ_ROUTING_MSI ||
			    ue->type == KVM_IRQ_ROUTING_MSI ||
			    ue->u.irqchip.irqchip == ei->irqchip.irqchip)
				return r;

		e->gsi = ue->gsi;
		e->type = ue->type;
		r = kvm_set_routing_entry(rt, e, ue);
		if (r)
			goto out;

		hlist_add_head(&e->link, &rt->map[e->gsi]);
		r = 0;
	out:
		return r;
	}

'kvm\_set\_routing\_entry's work is to set the set callback function.  For pic irq, sets the set to 'kvm\_set\_pic\_irq', for ioapic irq, sets it to 'kvm\_set\_ioapic\_irq'. For the entry has the same gsi irq, it will linked by the field 'link' of 'kvm\_kernel\_irq\_routing\_entry'.

	int kvm_set_routing_entry(struct kvm_irq_routing_table *rt,
				  struct kvm_kernel_irq_routing_entry *e,
				  const struct kvm_irq_routing_entry *ue)
	{
		int r = -EINVAL;
		int delta;
		unsigned max_pin;

		switch (ue->type) {
		case KVM_IRQ_ROUTING_IRQCHIP:
			delta = 0;
			switch (ue->u.irqchip.irqchip) {
			case KVM_IRQCHIP_PIC_MASTER:
				e->set = kvm_set_pic_irq;
				max_pin = PIC_NUM_PINS;
				break;
			case KVM_IRQCHIP_PIC_SLAVE:
				e->set = kvm_set_pic_irq;
				max_pin = PIC_NUM_PINS;
				delta = 8;
				break;
			case KVM_IRQCHIP_IOAPIC:
				max_pin = KVM_IOAPIC_NUM_PINS;
				e->set = kvm_set_ioapic_irq;
				break;
			default:
				goto out;
			}
		...
		}

		r = 0;
	out:
		return r;
	}

Following show the structure relation. 

	 kvm
	 +-------------+
	 |             |
	 |             |
	 |             |
	 +-------------+           +---------------------+
	 |irq_routing  +---------> |     chip            |
	 +-------------+           +---------------------+
	 |             |           |     rt_entries      +----------+
	 |             |           +---------------------+          |
	 |             |           |     nr_rt_entries   |          |
	 +-------------+           +---------------------+          |
	                           |     hlist_head ...  |          |
	                           |                     |          |
	                           |                     |          |
	                           |                     |          |
	                           +---------------------+ <--------+
	kvm_kernel_irq_routing_entry                     |
	                           |                     |
	                           +---------------------+
	                           |                     |
	                           |  k^m_set_pic_irq    |
	                           +---------------------+
	                           |                     |
	                           |                     |
	                           +---------------------+
	                           |                     |
	                           |                     |
	                           +---------------------+


<h4> Interrupt injection </h4>

The devices generate interrupt by calling function 'kvm\_set\_irq' in kvm. 

	int kvm_set_irq(struct kvm *kvm, int irq_source_id, u32 irq, int level,
			bool line_status)
	{
		struct kvm_kernel_irq_routing_entry *e, irq_set[KVM_NR_IRQCHIPS];
		int ret = -1, i = 0;
		struct kvm_irq_routing_table *irq_rt;

		trace_kvm_set_irq(irq, level, irq_source_id);

		/* Not possible to detect if the guest uses the PIC or the
		* IOAPIC.  So set the bit in both. The guest will ignore
		* writes to the unused one.
		*/
		rcu_read_lock();
		irq_rt = rcu_dereference(kvm->irq_routing);
		if (irq < irq_rt->nr_rt_entries)
			hlist_for_each_entry(e, &irq_rt->map[irq], link)
				irq_set[i++] = *e;
		rcu_read_unlock();

		while(i--) {
			int r;
			r = irq_set[i].set(&irq_set[i], kvm, irq_source_id, level,
					   line_status);
			if (r < 0)
				continue;

			ret = r + ((ret < 0) ? 0 : ret);
		}

		return ret;
	}

First find all the 'kvm\_kernel\_irq\_routing\_entry' with the same irq and then call the set callback function. As we have seen, this can set can be 'kvm\_set\_ioapic\_irq' or 'kvm\_set\_pic\_irq'.  Let's first talk about the pic situation.

	static int kvm_set_pic_irq(struct kvm_kernel_irq_routing_entry *e,
				   struct kvm *kvm, int irq_source_id, int level,
				   bool line_status)
	{
	#ifdef CONFIG_X86
		struct kvm_pic *pic = pic_irqchip(kvm);
		return kvm_pic_set_irq(pic, e->irqchip.pin, irq_source_id, level);
	#else
		return -1;
	#endif
	}

	int kvm_pic_set_irq(struct kvm_pic *s, int irq, int irq_source_id, int level)
	{
		int ret, irq_level;

		BUG_ON(irq < 0 || irq >= PIC_NUM_PINS);

		pic_lock(s);
		irq_level = __kvm_irq_line_state(&s->irq_states[irq],
						irq_source_id, level);
		ret = pic_set_irq1(&s->pics[irq >> 3], irq & 7, irq_level);
		pic_update_irq(s);
		trace_kvm_pic_set_irq(irq >> 3, irq & 7, s->pics[irq >> 3].elcr,
				      s->pics[irq >> 3].imr, ret == 0);
		pic_unlock(s);

		return ret;
	}

The edge trigger need to call twice of 'kvm\_set\_irq'.  The first is to trigger the interrupt and the second is to prepare for next time.

In 'pic\_unlock' it will kick off the vcpu and the cpu can have chance to handle the interrupt.

	static void pic_unlock(struct kvm_pic *s)
		__releases(&s->lock)
	{
		bool wakeup = s->wakeup_needed;
		struct kvm_vcpu *vcpu, *found = NULL;
		int i;

		s->wakeup_needed = false;

		spin_unlock(&s->lock);

		if (wakeup) {
			kvm_for_each_vcpu(i, vcpu, s->kvm) {
				if (kvm_apic_accept_pic_intr(vcpu)) {
					found = vcpu;
					break;
				}
			}

			if (!found)
				return;

			kvm_make_request(KVM_REQ_EVENT, found);
			kvm_vcpu_kick(found);
		}
	}

	void kvm_vcpu_kick(struct kvm_vcpu *vcpu)
	{
		int me;
		int cpu = vcpu->cpu;
		wait_queue_head_t *wqp;

		wqp = kvm_arch_vcpu_wq(vcpu);
		if (waitqueue_active(wqp)) {
			wake_up_interruptible(wqp);
			++vcpu->stat.halt_wakeup;
		}

		me = get_cpu();
		if (cpu != me && (unsigned)cpu < nr_cpu_ids && cpu_online(cpu))
			if (kvm_arch_vcpu_should_kick(vcpu))
				smp_send_reschedule(cpu);
		put_cpu();
	}

	static void native_smp_send_reschedule(int cpu)
	{
		if (unlikely(cpu_is_offline(cpu))) {
			WARN_ON(1);
			return;
		}
		apic->send_IPI_mask(cpumask_of(cpu), RESCHEDULE_VECTOR);
	}

Send an IPI interrupt to the CPU and later the CPU can process the interrupt.
Later in 'vcpu\_enter\_guest', it will call 'inject\_pending\_event'. In 'kvm\_cpu\_has\_extint', the PIC output has been set to 1, so it will call 'kvm\_queue\_interrupt' and 'kvm\_x86\_ops->set\_irq'. The latter callback is 'vmx\_inject\_irq'. 

	static void vmx_inject_irq(struct kvm_vcpu *vcpu)
	{
		struct vcpu_vmx *vmx = to_vmx(vcpu);
		uint32_t intr;
		int irq = vcpu->arch.interrupt.nr;

		trace_kvm_inj_virq(irq);

		++vcpu->stat.irq_injections;
		if (vmx->rmode.vm86_active) {
			int inc_eip = 0;
			if (vcpu->arch.interrupt.soft)
				inc_eip = vcpu->arch.event_exit_inst_len;
			if (kvm_inject_realmode_interrupt(vcpu, irq, inc_eip) != EMULATE_DONE)
				kvm_make_request(KVM_REQ_TRIPLE_FAULT, vcpu);
			return;
		}
		intr = irq | INTR_INFO_VALID_MASK;
		if (vcpu->arch.interrupt.soft) {
			intr |= INTR_TYPE_SOFT_INTR;
			vmcs_write32(VM_ENTRY_INSTRUCTION_LEN,
				     vmx->vcpu.arch.event_exit_inst_len);
		} else
			intr |= INTR_TYPE_EXT_INTR;
		vmcs_write32(VM_ENTRY_INTR_INFO_FIELD, intr);
	}

Here we can see the interrupt has been written to the VMCS. Notice in 'kvm\_cpu\_get\_interrupt', after the callchain 'kvm\_cpu\_get\_extint'->'kvm\_pic\_read\_irq'->'pic\_intack'. The last function sets the isr and clear the irr. This means the CPU is preparing to process the interrupt(anyway, the cpu will enter guest quickly).

	static inline void pic_intack(struct kvm_kpic_state *s, int irq)
	{
		s->isr |= 1 << irq;
		/*
		* We don't clear a level sensitive interrupt here
		*/
		if (!(s->elcr & (1 << irq)))
			s->irr &= ~(1 << irq);

		if (s->auto_eoi) {
			if (s->rotate_on_auto_eoi)
				s->priority_add = (irq + 1) & 7;
			pic_clear_isr(s, irq);
		}

	}


This is the story of PIC emulation. Now let's see 'kvm\_set\_ioapic\_irq'. This function just calls 'kvm\_ioapic\_set\_irq'. After 'ioapic\_service'->'ioapic\_deliver'->'kvm\_irq\_delivery\_to\_apic', we finally delivery the interrupt to lapic. This function tries to find a vcpu to delivery to. Then call 'kvm\_apic\_set\_irq' to set the lapic's irq. 

This is the story of interrupt (software) virtualization. As we can see, every interrupt needs VM-exit. This  makes a heavy overhead of virtualization. Next time we will see how hardware asistant the interrupt virtualization. 