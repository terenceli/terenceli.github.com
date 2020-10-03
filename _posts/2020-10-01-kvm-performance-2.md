---
layout: post
title: "kvm performance optimization technologies, part two"
description: "kvm"
category: 技术
tags: [内核, 虚拟化]
---
{% include JB/setup %}


In full virtualization the guest OS doesn't aware of it is running in an VM. If the OS knows it is running in an VM it can do some optimizations to improve the performance. This is called para virtualization(pv). From a generally speaking, 
Any technology used in the guest OS that it is based the assumption that it is running in a VM can be called a pv technology. For example the virtio is a para framework, and the [apf](https://terenceli.github.io/%E6%8A%80%E6%9C%AF/2019/03/24/kvm-async-page-fault) is also a para feature. However in this post, I will not talk about these more complicated feature but some more small performance optimization feature in pv. 

One of the most important thing in VM optimization is to reduce the VM-exit as much as possible, the best is there is no VM-exit.


This is the second part of kvm performance optimization technoligies followin up the [part one](https://terenceli.github.io/%E6%8A%80%E6%9C%AF/2020/09/10/kvm-performance-1). This post contains the following pv optimization:

* PV unhalt
* Host/Guest halt poll
* Disable mwait/hlt/pause
* Exitless timer

<h3> PV unhalt </h3>

Its name maybe make confusion. In fact it's about spinlock.
In virtualization environment, the spinlock holder vcpu may be preempted by scheduler. The other vcpu which is try get the spinlock will be spinning until the holder vcpu is scheduled again which may be a quite long time.

The PV unhalt feature is used to set the pv_lock_ops to rewrite the native spinlock's function so it can be more optimizated. More reference can be found in [here](https://wiki.xen.org/wiki/Benchmarking_the_new_PV_ticketlock_implementation) and [here](http://www.xen.org/files/xensummitboston08/LHP.pdf).


Though the total implementation of pv spinlock is related with the spinlock implementation such as ticketlock and queued spinlock, the basic idea behind the pv spinlock is the same. That is instead of spining while the vcpu can't get the spinlock it will execute halt instruction and let the other vcpu got scheduled.


<h4> guest side </h4>

When the guest startup, 'kvm_spinlock_init' is used to initialize the pv spinlock.

        void __init kvm_spinlock_init(void)
        {
            /* Does host kernel support KVM_FEATURE_PV_UNHALT? */
            if (!kvm_para_has_feature(KVM_FEATURE_PV_UNHALT))
                return;

            if (kvm_para_has_hint(KVM_HINTS_REALTIME))
                return;

            /* Don't use the pvqspinlock code if there is only 1 vCPU. */
            if (num_possible_cpus() == 1)
                return;

            __pv_init_lock_hash();
            pv_ops.lock.queued_spin_lock_slowpath = __pv_queued_spin_lock_slowpath;
            pv_ops.lock.queued_spin_unlock =
                PV_CALLEE_SAVE(__pv_queued_spin_unlock);
            pv_ops.lock.wait = kvm_wait;
            pv_ops.lock.kick = kvm_kick_cpu;

            if (kvm_para_has_feature(KVM_FEATURE_STEAL_TIME)) {
                pv_ops.lock.vcpu_is_preempted =
                    PV_CALLEE_SAVE(__kvm_vcpu_is_preempted);
            }
        }

The most function is 'kvm_wait' and 'kvm_ick_cpu' by 'pv_wait'.

        static __always_inline void pv_wait(u8 *ptr, u8 val)
        {
            PVOP_VCALL2(lock.wait, ptr, val);
        }

Then it will execute the halt instruction in 'kvm_wait'.

        static void kvm_wait(u8 *ptr, u8 val)
        {
            unsigned long flags;

            if (in_nmi())
                return;

            local_irq_save(flags);

            if (READ_ONCE(*ptr) != val)
                goto out;

            /*
            * halt until it's our turn and kicked. Note that we do safe halt
            * for irq enabled case to avoid hang when lock info is overwritten
            * in irq spinlock slowpath and no spurious interrupt occur to save us.
            */
            if (arch_irqs_disabled_flags(flags))
                halt();
            else
                safe_halt();

        out:
            local_irq_restore(flags);
        }



When the vcpu can't get the spinlock, it will call wait callback. 
When the vcpu can get the spinlock, the 'kick' callback will be called by 'pv_kick'. The 'kvm_kick_cpu' will be called and this trigger a KVM_HC_KICK_CPU hypercall.

        static void kvm_kick_cpu(int cpu)
        {
            int apicid;
            unsigned long flags = 0;

            apicid = per_cpu(x86_cpu_to_apicid, cpu);
            kvm_hypercall2(KVM_HC_KICK_CPU, flags, apicid);
        }

<h4> kvm side </h4>

First of all, the kvm should expose the 'KVM_FEATURE_PV_UNHALT' to the guest.

        case KVM_CPUID_FEATURES:
            entry->eax = (1 << KVM_FEATURE_CLOCKSOURCE) |
                    (1 << KVM_FEATURE_NOP_IO_DELAY) |
                    (1 << KVM_FEATURE_CLOCKSOURCE2) |
                    (1 << KVM_FEATURE_ASYNC_PF) |
                    (1 << KVM_FEATURE_PV_EOI) |
                    (1 << KVM_FEATURE_CLOCKSOURCE_STABLE_BIT) |
                    (1 << KVM_FEATURE_PV_UNHALT) |
                    ...

When the guest execute halt instruction, the 'kvm_emulate_halt'->'kvm_vcpu_halt' will be called. This will set the 'vcpu->arch.mp_state to 'KVM_MP_STATE_HALTED'. Then 'vcpu_block' will be called to block this vcpu. 


        static inline int vcpu_block(struct kvm *kvm, struct kvm_vcpu *vcpu)
        {
            if (!kvm_arch_vcpu_runnable(vcpu) &&
                (!kvm_x86_ops.pre_block || kvm_x86_ops.pre_block(vcpu) == 0)) {
                srcu_read_unlock(&kvm->srcu, vcpu->srcu_idx);
                kvm_vcpu_block(vcpu);
                vcpu->srcu_idx = srcu_read_lock(&kvm->srcu);

                if (kvm_x86_ops.post_block)
                    kvm_x86_ops.post_block(vcpu);

                if (!kvm_check_request(KVM_REQ_UNHALT, vcpu))
                    return 1;
            }

            kvm_apic_accept_events(vcpu);
            switch(vcpu->arch.mp_state) {
            case KVM_MP_STATE_HALTED:
                vcpu->arch.pv.pv_unhalted = false;
                vcpu->arch.mp_state =
                    KVM_MP_STATE_RUNNABLE;
                /* fall through */
            case KVM_MP_STATE_RUNNABLE:
                vcpu->arch.apf.halted = false;
                break;
            case KVM_MP_STATE_INIT_RECEIVED:
                break;
            default:
                return -EINTR;
            }
            return 1;
        }


When the guest trigger 'KVM_HC_KICK_CPU' hypercall, 'kvm_pv_kick_cpu_op' and 'kvm_sched_yield' will be called.

        int kvm_emulate_hypercall(struct kvm_vcpu *vcpu)
        {
            case KVM_HC_KICK_CPU:
                kvm_pv_kick_cpu_op(vcpu->kvm, a0, a1);
                kvm_sched_yield(vcpu->kvm, a1);
        }

The 'kvm_pv_kick_cpu_op' will send an interrupt to the lapic.

        static void kvm_pv_kick_cpu_op(struct kvm *kvm, unsigned long flags, int apicid)
        {
            struct kvm_lapic_irq lapic_irq;

            lapic_irq.shorthand = APIC_DEST_NOSHORT;
            lapic_irq.dest_mode = APIC_DEST_PHYSICAL;
            lapic_irq.level = 0;
            lapic_irq.dest_id = apicid;
            lapic_irq.msi_redir_hint = false;

            lapic_irq.delivery_mode = APIC_DM_REMRD;
            kvm_irq_delivery_to_apic(kvm, NULL, &lapic_irq, NULL);
        }

Then in '__apic_accept_irq' it will kick the blocked vcpu.

        case APIC_DM_REMRD:
            result = 1;
            vcpu->arch.pv.pv_unhalted = 1;
            kvm_make_request(KVM_REQ_EVENT, vcpu);
            kvm_vcpu_kick(vcpu);
            break;

The 'kvm_vcpu_block' returns, it will set 'vcpu->arch.mp_state' to 'KVM_MP_STATE_RUNNABLE' and let the vcpu get the spinlock.


<h3> Host/Guest halt poll </h3>

Under some circumstances, the overhead of context switch from ide->running or running->idle is high, especially the halt instruction.
The host halt poll is that when the vcpu execute halt instruction and cause VM-exit, in the 'kvm_vcpu_block' function, it will poll for conditions before giving the cpu to scheduler.

        if (vcpu->halt_poll_ns && !kvm_arch_no_poll(vcpu)) {
            ktime_t stop = ktime_add_ns(ktime_get(), vcpu->halt_poll_ns);

            ++vcpu->stat.halt_attempted_poll;
            do {
                /*
                * This sets KVM_REQ_UNHALT if an interrupt
                * arrives.
                */
                if (kvm_vcpu_check_block(vcpu) < 0) {
                    ++vcpu->stat.halt_successful_poll;
                    if (!vcpu_valid_wakeup(vcpu))
                        ++vcpu->stat.halt_poll_invalid;
                    goto out;
                }
                poll_end = cur = ktime_get();
            } while (single_task_running() && ktime_before(cur, stop));
        }

This code is quite simple, if the condision has came, it will 'goto out' and the vcpu will not be blocked.

Guest halt poll is solution to avoid this overhead. It will poll in the guest kernel instead of the host kernel.
Compared with kvm halt poll, the guest halt poll also reduce the context switch from non-root mode to root-mode.

Before entering the halt, it will poll some time.

        static int __cpuidle poll_idle(struct cpuidle_device *dev,
                        struct cpuidle_driver *drv, int index)
        {
            u64 time_start = local_clock();

            dev->poll_time_limit = false;

            local_irq_enable();
            if (!current_set_polling_and_test()) {
                unsigned int loop_count = 0;
                u64 limit;

                limit = cpuidle_poll_time(drv, dev);

                while (!need_resched()) {
                    cpu_relax();
                    if (loop_count++ < POLL_IDLE_RELAX_COUNT)
                        continue;

                    loop_count = 0;
                    if (local_clock() - time_start > limit) {
                        dev->poll_time_limit = true;
                        break;
                    }
                }
            }
            current_clr_polling();

            return index;
        }

When sending IPI to cpu it will check whether the poll flag is setting, if it is, it just set the '_TIF_NEED_RESCHED'

        static bool set_nr_if_polling(struct task_struct *p)
        {
            struct thread_info *ti = task_thread_info(p);
            typeof(ti->flags) old, val = READ_ONCE(ti->flags);

            for (;;) {
                if (!(val & _TIF_POLLING_NRFLAG))
                    return false;
                if (val & _TIF_NEED_RESCHED)
                    return true;
                old = cmpxchg(&ti->flags, val, val | _TIF_NEED_RESCHED);
                if (old == val)
                    break;
                val = old;
            }
            return true;
        }

        void send_call_function_single_ipi(int cpu)
        {
            struct rq *rq = cpu_rq(cpu);

            if (!set_nr_if_polling(rq->idle))
                arch_send_call_function_single_ipi(cpu);
            else
                trace_sched_wake_idle_without_ipi(cpu);
        }

This will avoid the sending IPI interrupt.

There is a cpuid feature bit 'KVM_FEATURE_POLL_CONTROL' to control use which halt poll.
If this bit is set in the cpuid it means uses the host halt poll, otherwise it will uses the guest halt poll.

        void arch_haltpoll_enable(unsigned int cpu)
        {
            if (!kvm_para_has_feature(KVM_FEATURE_POLL_CONTROL)) {
                pr_err_once("kvm: host does not support poll control\n");
                pr_err_once("kvm: host upgrade recommended\n");
                return;
            }

            /* Enable guest halt poll disables host halt poll */
            smp_call_function_single(cpu, kvm_disable_host_haltpoll, NULL, 1);
        }
        EXPORT_SYMBOL_GPL(arch_haltpoll_enable);

        void arch_haltpoll_disable(unsigned int cpu)
        {
            if (!kvm_para_has_feature(KVM_FEATURE_POLL_CONTROL))
                return;

            /* Enable guest halt poll disables host halt poll */
            smp_call_function_single(cpu, kvm_enable_host_haltpoll, NULL, 1);
        }


<h3> Disable mwait/hlt/pause </h3>

In some workloads it will improve latency if the mwait/hlt/pause doesn't cause VM-exit. The userspace(qemu) can check and set per-VM capability(KVM_CAP_X86_DISABLE_EXITS) to not intercept mwait/hlt/pause instruction.

'kvm_arch' has following fields, the userspace can set these field:

        bool mwait_in_guest;
        bool hlt_in_guest;
        bool pause_in_guest;
        bool cstate_in_guest;

In the VM initialization, it will check these field and set the coressponding vmcs field. For example, the mwait and hlt case.

        u32 vmx_exec_control(struct vcpu_vmx *vmx)
        {
            ...
            if (kvm_mwait_in_guest(vmx->vcpu.kvm))
                exec_control &= ~(CPU_BASED_MWAIT_EXITING |
                        CPU_BASED_MONITOR_EXITING);
            if (kvm_hlt_in_guest(vmx->vcpu.kvm))
                exec_control &= ~CPU_BASED_HLT_EXITING;
            return exec_control;
        }

<h3> Exitless timer </h3>

This feature is also implemented by Wanpeng Li. Here is the [slides](https://static.sched.com/hosted_files/kvmforum2019/e3/Boosting%20Dedicated%20Instances%20by%20KVM%20Tax%20Cut.pdf). The patches is [here](https://patchwork.kernel.org/cover/11033533/).

Both programming timer in guest and the emulated timer fires will cause VM-exit. Exitless timer uses the housekeeping CPUs to delivery interrupt via posted-interrupt.

        static void apic_timer_expired(struct kvm_lapic *apic, bool from_timer_fn)
        {
            struct kvm_vcpu *vcpu = apic->vcpu;
            struct kvm_timer *ktimer = &apic->lapic_timer;

            if (atomic_read(&apic->lapic_timer.pending))
                return;

            if (apic_lvtt_tscdeadline(apic) || ktimer->hv_timer_in_use)
                ktimer->expired_tscdeadline = ktimer->tscdeadline;

            ...

            if (kvm_use_posted_timer_interrupt(apic->vcpu)) {
                if (apic->lapic_timer.timer_advance_ns)
                    __kvm_wait_lapic_expire(vcpu);
                kvm_apic_inject_pending_timer_irqs(apic);
                return;
            }

            atomic_inc(&apic->lapic_timer.pending);
            kvm_set_pending_timer(vcpu);
        }

'kvm_apic_inject_pending_timer_irqs' is used to inject the timer interrupt.

        static void kvm_apic_inject_pending_timer_irqs(struct kvm_lapic *apic)
        {
            struct kvm_timer *ktimer = &apic->lapic_timer;

            kvm_apic_local_deliver(apic, APIC_LVTT);
            if (apic_lvtt_tscdeadline(apic)) {
                ktimer->tscdeadline = 0;
            } else if (apic_lvtt_oneshot(apic)) {
                ktimer->tscdeadline = 0;
                ktimer->target_expiration = 0;
            }
        }

It just delivery a APIC_LVTT timer to the apic. It will go to the 'case APIC_DM_FIXED' in '__apic_accept_irq' then inject the timer interrupt through posted-interrupt.