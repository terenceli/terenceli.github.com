---
layout: post
title: "Analysis of a 0x5c BSOD caused by timer interrupt in KVM when VMs reboot"
description: ""
category: 技术
tags: [虚拟化, windows内核]
---
{% include JB/setup %}

* [Issue Description](#0)

* [Analysis in Windows kernel side](#1)

* [Analysis in KVM side](#2)

* [Reference](#3)


<h2 id="0">Issue Description</h2>

Recently I was assigned a BOSD caused by rebooting the Windows guest in KVM. I have made a deep analysis of it.
Though I'm not 100% satisfied with the final conclude, it still makes sense and is a good explaination. I have got a lot of help from Wei Wang of intel, Vadim Rozenfeld of redhat, and Paolo Bonzini of redhat, many thanks to them.

This issue is quite directly. Though not every time it causes BSOD, we reboot the Windows guest several times it will almost got BSOD with 0x5c(0x10b,3,0,0). Here is the summary infomation. 

        FOLLOWUP_IP: 
        nt!InitBootProcessor+12a
        fffff800`01c01d0a 413ac6          cmp     al,r14b

        SYMBOL_STACK_INDEX:  6

        SYMBOL_NAME:  nt!InitBootProcessor+12a

        FOLLOWUP_NAME:  MachineOwner

        MODULE_NAME: nt

        IMAGE_NAME:  ntkrnlmp.exe

        DEBUG_FLR_IMAGE_TIMESTAMP:  59b946d1

        IMAGE_VERSION:  6.1.7601.23915

        FAILURE_BUCKET_ID:  X64_0x5C_HAL_CLOCK_INTERRUPT_NOT_RECEIVED_nt!InitBootProcessor+12a

        BUCKET_ID:  X64_0x5C_HAL_CLOCK_INTERRUPT_NOT_RECEIVED_nt!InitBootProcessor+12a

        ANALYSIS_SOURCE:  KM

        FAILURE_ID_HASH_STRING:  km:x64_0x5c_hal_clock_interrupt_not_received_nt!initbootprocessor+12a

        FAILURE_ID_HASH:  {829a944d-7639-05f1-a55f-2677354a890e}


        kd> kb
        # RetAddr           : Args to Child                                                           : Call Site
        00 fffff800`017b9662 : 00000000`0000010b fffff800`01854cc0 00000000`00000065 fffff800`01705514 : nt!DbgBreakPointWithStatus
        01 fffff800`017ba44e : 00000000`00000003 00000000`00000000 fffff800`01705d70 00000000`0000005c : nt!KiBugCheckDebugBreak+0x12
        02 fffff800`016c8f04 : 00000000`00000001 fffff800`0161e0b3 00000000`00002a43 00000000`00000000 : nt!KeBugCheck2+0x71e
        03 fffff800`0161e2b4 : 00000000`0000005c 00000000`0000010b 00000000`00000003 00000000`00000000 : nt!KeBugCheckEx+0x104
        04 fffff800`016442a3 : 00000000`00000001 fffff800`0080e4b0 fffff800`0080e4b0 00000000`00000001 : hal!HalpInitializeClock+0x1c9
        05 fffff800`01c01d0a : fffff800`0080e4b0 fffff800`0080e4b0 fffff800`013d8780 fffff800`016c0c86 : hal!HalpInitSystem+0x29b
        06 fffff800`0191cfa3 : fffff800`00000000 fffff800`01846e80 fffff800`013d8780 00000000`00000001 : nt!InitBootProcessor+0x12a
        07 fffff800`0190a8a6 : 00000000`00000230 fffff800`02b28588 fffff800`013d8b30 00000001`00000000 : nt!KiInitializeKernel+0x833
        08 00000000`00000000 : 00000000`00000000 00000000`00000000 00000000`00000000 00000000`00000000 : nt!KiSystemStartup+0x196

It is obvious function 'HalpInitializeClock' has failed and causes a bugcheck. Disassemb this and it easy to find out this bugcheck is caused when it calls function 'HalpWaitForPhase0ClockTick' and the later function return failed.

        kd> uf HalpInitializeClock
        hal!HalpInitializeClock:
        fffff800`01bff0ec 4889742408      mov     qword ptr [rsp+8],rsi
        fffff800`01bff0f1 9c              pushfq
        fffff800`01bff0f2 4883ec50        sub     rsp,50h
        fffff800`01bff0f6 488b0503600100  mov     rax,qword ptr [hal!_security_cookie (fffff800`01c15100)]
        fffff800`01bff0fd 4833c4          xor     rax,rsp
        fffff800`01bff100 4889442440      mov     qword ptr [rsp+40h],rax
        fffff800`01bff105 8b0dc1a20100    mov     ecx,dword ptr [hal!HalpClockSource (fffff800`01c193cc)]
        ...
        hal!HalpInitializeClock+0x19c:
        fffff800`01bff287 b9b80b0000      mov     ecx,0BB8h
        fffff800`01bff28c e8e3fdffff      call    hal!HalpWaitForPhase0ClockTick (fffff800`01bff074)
        fffff800`01bff291 84c0            test    al,al
        fffff800`01bff293 7520            jne     hal!HalpInitializeClock+0x1ca (fffff800`01bff2b5)

        hal!HalpInitializeClock+0x1aa:
        fffff800`01bff295 4c630530a10100  movsxd  r8,dword ptr [hal!HalpClockSource (fffff800`01c193cc)]
        fffff800`01bff29c 488364242000    and     qword ptr [rsp+20h],0
        fffff800`01bff2a2 4533c9          xor     r9d,r9d
        fffff800`01bff2a5 418d495c        lea     ecx,[r9+5Ch]
        fffff800`01bff2a9 ba0b010000      mov     edx,10Bh
        fffff800`01bff2ae ff153c000100    call    qword ptr [hal!_imp_KeBugCheckEx (fffff800`01c0f2f0)]
        fffff800`01bff2b4 cc              int     3
        ...
        fffff800`01bff2da c3              ret

So just copy+paste "HalpWaitForPhase0ClockTick" in the Google, you will find this bugzilla:

        https://bugzilla.redhat.com/show_bug.cgi?id=1387054

Seems the same, just differently in the bugcheck's second parameter which is '1' in the bugzilla but is '3' in our BSOD. So I find the patch:

        https://github.com/torvalds/linux/commit/4114c27d450bef228be9c7b0c40a888e18a3a636#diff-3e935e2004c0c48a7a669085ee75f1b1


And applied this patch, reboot guest several times, no BSOD. This process just take me ten minutes and seems life is OK again. Over? Ofcourse not, I'm curious about this issue and want to know more under the surface of this BSOD.


<h2 id="1">Analysis in Windows kernel side</h2>

Let's look at more in detail about the backtrack in windbg.

If you have some backgroud of Windows startup, you should know that this backtrack show the BSOD happend in the Phase0 initialization. In this phase initialization, only one processor get initialized which called boot processor. In the backtrack, we can see Windows is initializing the Clock. From the summary of BSOD, we see "x64\_0x5c\_hal\_clock\_interrupt\_not\_received\_nt" this indicate the issue, the windows doesn't received interrupts.

Let's see the disassemble of function "HalpWaitForPhase0ClockTick". This is the main logic of this function.

        char __fastcall HalpWaitForPhase0ClockTick(unsigned int a1)
        {
        unsigned __int64 v1; // rbx

        v1 = ((unsigned __int64)((HalpProc0TSCHz * (unsigned __int64)a1 * (unsigned __int128)0x624DD2F1A9FBE77ui64 >> 64)
                                + ((unsigned __int64)(HalpProc0TSCHz * a1
                                                    - (HalpProc0TSCHz
                                                    * (unsigned __int64)a1
                                                    * (unsigned __int128)0x624DD2F1A9FBE77ui64 >> 64)) >> 1)) >> 9)
            + __rdtsc();
        HalpProcessorFence();
        if ( HalpPhase0ClockInterruptCount )
            return 1;
        while ( __rdtsc() <= v1 )
        {
            if ( HalpPhase0ClockInterruptCount )
            return 1;
        }
        return 0;
        }

        char HalpHpetClockInterruptStub()
        {
        ++HalpPhase0ClockInterruptCount;
        return 1;
        }

Here 'HalpPhase0ClockInterruptCount' counts the clock interrupt count, it will increment every timer interrupt. It is easy to understand that this function is waiting interrupt within v1 times (from the redhat bugzilla, it's 3s). From Vadim Rozenfeld, I know this is a common technique in Windows kernel that the HAL initialization process waits for some period of time which considered to be enough to complete this initialization action, in this case it's the clock. So the BSOD in Windows kernel is clear, when the guest try to initialize the clock, it waits some time(3s) to ensure timer interrupt has been triggered(through HalpPhase0ClockInterruptCount). But it doesn't wait this interrupt and think the clock hasn't worked in a good state so triggers this BSOD. 

 
<h2 id="2">Analysis in KVM side</h2>

As we have know the story in Windows side let's look at the KVM side. 
Though I'm familiar with CPU/Memory/Device virtualization in qemu/kvm stack, to be honest, I'm not familiar the interrupt virtualizaton. Let's see the patch [KVM: x86: reset RVI upon system reset](https://github.com/torvalds/linux/commit/4114c27d450bef228be9c7b0c40a888e18a3a636#diff-3e935e2004c0c48a7a669085ee75f1b1), the commit says 

        "A bug was reported as follows: when running Windows 7 32-bit guests on qemu-kvm,
        sometimes the guests run into blue screen during reboot. The problem was that a
        guest's RVI was not cleared when it rebooted. This patch has fixed the problem."


This patch clear the RVI when reboot. First let's look at the reboot path.

        kvm_vcpu_ioctl(CPU(s->cpu), KVM_SET_LAPIC, &kapic);
        
        -->kvm_vcpu_ioctl_set_lapic
        -->kvm_apic_post_state_restore
        -->vmx_hwapic_irr_update
        -->vmx_set_rvi

The later two function was added by the patch. 
Here is a brief introduction of some registers:

    IRR: Interrupt Request Register, if the nth bit is set, the LAPIC has received the nth interrupt but not deliver it to CPU
    RVI: Requesting virtual interrupt, This is the low byte of the guest interrupt status. The processor
    treats this value as the vector of the highest priority virtual interrupt that is requesting service.
    SVI: Servicing virtual interrupt, This is the high byte of the guest interrupt status. The processor
    treats this value as the vector of the highest priority virtual interrupt that is in service.
    EOI: End of Interrupt, the software write this register in the end of interrupt handler to notify the virtual apic deliver next interrupt.
    ISR: In-Service Register, if the nth bit is set, the CPU has processed the nth interrupt, but not complete

RVI and SVI is in the virtual apic only, they characterize part of the guest’s virtual-APIC state and
does not correspond to any processor or APIC registers.
The general process is this, interrupt was set in IRR, then RVI, when the guest process interrupt, and set the ISR, when it finish the interrupt dispatch it writes EOI register to notifiy virtual apic to deliver another interrupt.

In this BSOD case, the RVI register is not clear and it has higher priority than the timer interrupt, as it is in the eary of Windows initialization, there maybe no corresponding interrupt procedure for the obsolete RVI interrupt so no handler can handle it. As the RVI interrupt has higher priority than timer interrupt, and the ISR in virtual apic can't be get clear, the virtual apic will not deliver the timer interrupt and make the Widnows BSOD.


<h2 id="3">Reference</h2>

1. SDM 24.4.2

2. Mctrain's Blog: [中断处理的那些事儿](http://ytliu.info/blog/2016/12/24/zhong-duan-chu-li-de-na-xie-shi-er/)