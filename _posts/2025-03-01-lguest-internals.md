---
layout: post
title: "lguest internals"
description: "lguest internals"
category: 技术
tags: [技术, 虚拟化]
---
{% include JB/setup %}

lguest is the simpliest x86 virtualization solution. It is a paravirt hypervisor.  In this post I will dive deep into the internals of lguest.

<h2> Related files </h2>

tools/lguest/lguest.c， lguest userspace tool just like QEMU.

drivers/lguest/core.c, the core code of lguest hypervisor, including the module initialization.

drivers/lguest/hypercalls.c, hypercall related handler.

drivers/lguest/interrupts_and_traps.c，guest interrupt code.

drivers/lguest/lguest_user.c, the /dev/lguest devices related code to interact with the userspace tool.

drivers/lguest/page_table.c, mostly the shadow page table management.

drivers/lguest/segments.c, the guest idt/gdt related code.

drivers/lguest/x86/core.c, the x86 arch code, the regs setup the entry to switcher.

drivers/lguest/x86/switcher_32.S, switcher code.



drivers/lguest is just like kvm code in kernel.



arch/x86/lguest is the guest code.

arch/x86/lguest/boot.c, lguest guest related code, like subarch init, pv ops.

arch/x86/lguest/head_32.S, the assembly code of lguest guest.

<h2> lguest architecture overview </h2>

Following pic shows the architecture of lguest. It contains three key components: the guest, the switcher and the lg.ko. 


![](/assets/img/lguestinternals/1.png)


The guest kernel runs on hardware ring 1 and the guest userspace runs on hardware ring 3. 
The switcher is used to 'switching' the worlds between host, guest user and guest kernel. The world switches can be triggered by a set of events such as interrupts and exceptions. The switcher comprises efficient and concise assembly code maped to identical address within host and guest kernel address spaces.
The lg.ko contains the the core hypervisor code. It exposes interface(/dev/lg) to userspace. It prepare guest environment and launch the guest and also process the guest exit events.


<h2> Switcher </h2>


Swticher is used to do world switch. It must be located at identical virtual address in guest kernel and host. The guest user and kernel share the same page table just like the traditional Linux. 
When load lg.ko, it will call 'map_switcher' to map the switcher code to host. The allocation contains TOTAL_SWITCHER_PAGES pages.


                #define TOTAL_SWITCHER_PAGES (1 + 2 * nr_cpu_ids)

                static __init int map_switcher(void)
                {
                ...
                        lg_switcher_pages = kmalloc(sizeof(lg_switcher_pages[0])
                                                * TOTAL_SWITCHER_PAGES,
                                                GFP_KERNEL);
                ...
                }


Every physical CPU will has two pages, these two pages is used to load and store vCPU state.
Following show lg_switcher_pages layout.


![](/assets/img/lguestinternals/2.png)


The really switcher page is just one page, and following it is per cpu two pages. 


                /* We have two pages shared with guests, per cpu.  */
                struct lguest_pages {
                        /* This is the stack page mapped rw in guest */
                        char spare[PAGE_SIZE - sizeof(struct lguest_regs)];
                        struct lguest_regs regs;

                        /* This is the host state & guest descriptor page, ro in guest */
                        struct lguest_ro_state state;
                } __attribute__((aligned(PAGE_SIZE)));

                /* This is a guest-specific page (mapped ro) into the guest. */
                struct lguest_ro_state {
                        /* Host information we need to restore when we switch back. */
                        u32 host_cr3;
                        struct desc_ptr host_idt_desc;
                        struct desc_ptr host_gdt_desc;
                        u32 host_sp;

                        /* Fields which are used when guest is running. */
                        struct desc_ptr guest_idt_desc;
                        struct desc_ptr guest_gdt_desc;
                        struct x86_hw_tss guest_tss;
                        struct desc_struct guest_idt[IDT_ENTRIES];
                        struct desc_struct guest_gdt[GDT_ENTRIES];
                };


The 'spare' and 'regs' field combines the stack for switcher. The 'regs' contains the guest register value.
The 'state' field is used to store host and guest state information.



<h2> CPU virtualization </h2>

Without hardware support, the guest traps to host in two ways: hypercall and interrupt/execption. The hypercall is implemented via interrupt.

Following pic shows the process of VM Exit and VM Entry. When the guest execute interrupt such as interrupt-based syscall or execption, the CPU transitions to swithcher code (in h_ring0) through the pre-defined handler in IDTR. In the switcher it first store the guest state and then restore the host state and then switch to host by calling switch_to_host. After completing the exit events the host call the switcher function switch_to_guest to enter guest, this will store the host state and load guest state.        

![](/assets/img/lguestinternals/3.png)




<h3> VM entry </h3>


In 'lguest_arch_host_init' the 'lguest_entry' struct is initialized as following:


                lguest_entry.offset = (long)switch_to_guest + switcher_offset();
                lguest_entry.segment = LGUEST_CS;


The 'offset' is set to 'switch_to_guest' address.
Then in 'run_guest_once', it will be used as the operand of lcall instruction.


                asm volatile("pushf; lcall *%4"
                        /*
                        * This is how we tell GCC that %eax ("a") and %ebx ("b")
                        * are changed by this routine.  The "=" means output.
                        */
                        : "=a"(clobber), "=b"(clobber)
                        /*
                        * %eax contains the pages pointer.  ("0" refers to the
                        * 0-th argument above, ie "a").  %ebx contains the
                        * physical address of the Guest's top-level page
                        * directory.
                        */
                        : "0"(pages), 
                        "1"(__pa(cpu->lg->pgdirs[cpu->cpu_pgd].pgdir)),
                        "m"(lguest_entry)
                        /*
                        * We tell gcc that all these registers could change,
                        * which means we don't have to save and restore them in
                        * the Switcher.
                        */
                        : "memory", "%edx", "%ecx", "%edi", "%esi");



This lcall will goto 'switch_to_guest' which is some assembly code. These code will do the host-guest switch.
Before lcall is executed, 'pushf' pushs the elfags into host stack. The 'lcall' instruction will push 'cs' and 'eip' to host stack. At the start of 'switch_to_guest' the 'es/ds/gs/fs/ebp' is pushed into host stack and the 'esp' is stored in 'lguest_pages' state->host_cr3. After this, the host state is stored. Then we will load the guest state.


![](/assets/img/lguestinternals/4.png)


First we change the stack to switcher's stack.


                movl	%eax, %edx
                addl	$LGUEST_PAGES_regs, %edx
                movl	%edx, %esp


Here 'eax' points the beginning of 'lguest_pages'. After these instruction, the 'esp' point to beginning of 'lguest_regs'.
Then the switcher loads the guest IDT/GDT/TSS, the most usage of TSS is used to specify the ss/esp when the guest exit to host.


                // The Guest's GDT we so carefully
                // Placed in the "struct lguest_pages" before
                lgdt	LGUEST_PAGES_guest_gdt_desc(%eax)

                // The Guest's IDT we did partially
                // Copy to "struct lguest_pages" as well.
                lidt	LGUEST_PAGES_guest_idt_desc(%eax)

                // The TSS entry which controls traps
                // Must be loaded up with "ltr" now:
                // The GDT entry that TSS uses 
                // Changes type when we load it: damn Intel!
                // For after we switch over our page tables
                // That entry will be read-only: we'd crash.
                movl	$(GDT_ENTRY_TSS*8), %edx
                ltr	%dx

                // Look back now, before we take this last step!
                // The Host's TSS entry was also marked used;
                // Let's clear it again for our return.
                // The GDT descriptor of the Host
                // Points to the table after two "size" bytes
                movl	(LGUEST_PAGES_host_gdt_desc+2)(%eax), %edx
                // Clear "used" from type field (byte 5, bit 2)
                andb	$0xFD, (GDT_ENTRY_TSS*8 + 5)(%edx)


Before switch to guest, we need to set the guest' cr3.


                // Once our page table's switched, the Guest is live!
                // The Host fades as we run this final step.
                // Our "struct lguest_pages" is now read-only.
                movl	%ebx, %cr3


Then we restore the guest state. Notice we have changed the cr3, so following code is actully executed in guest space address. This is why we need to map the switcher to the same address in both host and guest kernel.


                // The page table change did one tricky thing:
                // The Guest's register page has been mapped
                // Writable under our %esp (stack) --
                // We can simply pop off all Guest regs.
                popl	%eax
                popl	%ebx
                popl	%ecx
                popl	%edx
                popl	%esi
                popl	%edi
                popl	%ebp
                popl	%gs
                popl	%fs
                popl	%ds
                popl	%es

                // Near the base of the stack lurk two strange fields
                // Which we fill as we exit the Guest
                // These are the trap number and its error
                // We can simply step past them on our way.
                addl	$8, %esp

                // The last five stack slots hold return address
                // And everything needed to switch privilege
                // From Switcher's level 0 to Guest's 1,
                // And the stack where the Guest had last left it.
                // Interrupts are turned back on: we are Guest.
                iret


After the 'addl' instruction, The 'esp' points to 'errorcode' field in the stack page, and the last five just fake a iret frame. At the first time, the register is initialized to following value. 


                void lguest_arch_setup_regs(struct lg_cpu *cpu, unsigned long start)
                {
                ...
                regs->ds = regs->es = regs->ss = __KERNEL_DS|GUEST_PL;
                        regs->cs = __KERNEL_CS|GUEST_PL;
                ...
                        regs->eflags = X86_EFLAGS_IF | X86_EFLAGS_FIXED;
                ...
                        regs->eip = start;
                ...
                }


The 'eip' is set from userspace, it is the vmlinx ELF 'e_entry' which is 'statup_32' in 'arch/x86/kernel/head_32.S' file. The 'esp' is not set as the stack is set by the guest OS.


<h3> VM exit </h3>


Now the guest is running in ring 1. When the guest need to trap to host, it trigger an interrupt by executing 'int' instruction. The guest idt is defined as following:


                .text
                        // The first two traps go straight back to the Host
                        IRQ_STUBS 0 1 return_to_host
                        // We'll say nothing, yet, about NMI
                        IRQ_STUB 2 handle_nmi
                        // Other traps also return to the Host
                        IRQ_STUBS 3 31 return_to_host
                        // All interrupts go via their handlers
                        IRQ_STUBS 32 127 deliver_to_host
                        // 'Cept system calls coming from userspace
                        // Are to go to the Guest, never the Host.
                        IRQ_STUB 128 return_to_host
                        IRQ_STUBS 129 255 deliver_to_host



                .macro IRQ_STUB N TARGET
                        .data; .long 1f; .text; 1:
                // Trap eight, ten through fourteen and seventeen
                // Supply an error number.  Else zero.
                .if (\N <> 8) && (\N < 10 || \N > 14) && (\N <> 17)
                        pushl	$0
                .endif
                        pushl	$\N
                        jmp	\TARGET
                        ALIGN
                .endm

                // This macro creates numerous entries
                // Using GAS macros which out-power C's.
                .macro IRQ_STUBS FIRST LAST TARGET
                irq=\FIRST
                .rept \LAST-\FIRST+1
                        IRQ_STUB irq \TARGET
                irq=irq+1
                .endr
                .endm


Some interrupts/exceptions(8, 10-14, 17) has an errorcode, this errorcode will be pushed into the stack by the hardware. In this other case, we need to push 0 to the stack.


![](/assets/img/lguestinternals/5.png)


Also in order to know the interrupt number we also need push the trap number to stack.


Let's take a 0x80(128) as an example. 

                return_to_host:
                        SWITCH_TO_HOST
                        iret


The core is 'SWITCH_TO_HOST'. First we push the guest general register into the stack. Notice the stack is now point to 'lguest_pages' and the 'esp' points to 'trapnum'. 


                #define SWITCH_TO_HOST							\
                        /* We save the Guest state: all registers first			\
                        * Laid out just as "struct lguest_regs" defines */		\
                        pushl	%es;							\
                        pushl	%ds;							\
                        pushl	%fs;							\
                        pushl	%gs;							\
                        pushl	%ebp;							\
                        pushl	%edi;							\
                        pushl	%esi;							\
                        pushl	%edx;							\
                        pushl	%ecx;							\
                        pushl	%ebx;							\
                        pushl	%eax;							\


Load the guest ds

                movl	$(LGUEST_DS), %eax;					\
                movl	%eax, %ds;						\


Get the lguest_pages start address. And then load host cr3. Load host gdt and idt. Chnage esp to host esp. Load tss.


                movl	%esp, %eax;						\
                andl	$(~(1 << PAGE_SHIFT - 1)), %eax;			\
                /* Save our trap number: the switch will obscure it		\
                * (In the Host the Guest regs are not mapped here)		\
                * %ebx holds it safe for deliver_to_host */			\
                movl	LGUEST_PAGES_regs_trapnum(%eax), %ebx;			\
                /* The Host GDT, IDT and stack!					\
                * All these lie safely hidden from the Guest:			\
                * We must return to the Host page tables			\
                * (Hence that was saved in struct lguest_pages) */		\
                movl	LGUEST_PAGES_host_cr3(%eax), %edx;			\
                movl	%edx, %cr3;						\
                /* As before, when we looked back at the Host			\
                * As we left and marked TSS unused				\
                * So must we now for the Guest left behind. */			\
                andb	$0xFD, (LGUEST_PAGES_guest_gdt+GDT_ENTRY_TSS*8+5)(%eax); \
                /* Switch to Host's GDT, IDT. */				\
                lgdt	LGUEST_PAGES_host_gdt_desc(%eax);			\
                lidt	LGUEST_PAGES_host_idt_desc(%eax);			\
                /* Restore the Host's stack where its saved regs lie */		\
                movl	LGUEST_PAGES_host_sp(%eax), %esp;			\
                /* Last the TSS: our Host is returned */			\
                movl	$(GDT_ENTRY_TSS*8), %edx;				\
                ltr	%dx;							\


Finally pop the register when 'switch_to_guest' pushes.


                /* Restore now the regs saved right at the first. */		\
                popl	%ebp;							\
                popl	%fs;							\
                popl	%gs;							\
                popl	%ds;							\
                popl	%es


After 'SWITCH_TO_HOST', 'return_to_host' executes an iret instruction. Finally the switcher will return to the next instruction after 'lcall' in 'run_guest_once' function. Thus we has done the VM entry and VM exit world switch.


<h2> Hypercall </h2>


Before we continue, let's just see how guest communicate with the host using hyper call.
Paravirt virtualization relies hypercall to do the sensetive operation. lguest defines following hypercall:

                #define LHCALL_FLUSH_ASYNC	0
                #define LHCALL_LGUEST_INIT	1
                #define LHCALL_SHUTDOWN		2
                #define LHCALL_NEW_PGTABLE	4
                #define LHCALL_FLUSH_TLB	5
                #define LHCALL_LOAD_IDT_ENTRY	6
                #define LHCALL_SET_STACK	7
                #define LHCALL_TS		8
                #define LHCALL_SET_CLOCKEVENT	9
                #define LHCALL_HALT		10
                #define LHCALL_SET_PMD		13
                #define LHCALL_SET_PTE		14
                #define LHCALL_SET_PGD		15
                #define LHCALL_LOAD_TLS		16
                #define LHCALL_LOAD_GDT_ENTRY	18
                #define LHCALL_SEND_INTERRUPTS	19

The guest makes hypercall by calling 'hcall'.

                static inline unsigned long
                hcall(unsigned long call,
                unsigned long arg1, unsigned long arg2, unsigned long arg3,
                unsigned long arg4)
                {
                        /* "int" is the Intel instruction to trigger a trap. */
                        asm volatile("int $" __stringify(LGUEST_TRAP_ENTRY)
                                /* The call in %eax (aka "a") might be overwritten */
                                : "=a"(call)
                                /* The arguments are in %eax, %ebx, %ecx, %edx & %esi */
                                : "a"(call), "b"(arg1), "c"(arg2), "d"(arg3), "S"(arg4)
                                /* "memory" means this might write somewhere in memory.
                                        * This isn't true for all calls, but it's safe to tell
                                        * gcc that it might happen so it doesn't get clever. */
                                : "memory");
                        return call;
                }


The %eax is the hypercall number, the %ebx、%ecx...is the argument. The int instruction is used to trap to host. After this interrupt, we return to host. Later in 'lguest_arch_handle_trap' we get the argument 

                case LGUEST_TRAP_ENTRY:
                        /*
                        * Our 'struct hcall_args' maps directly over our regs: we set
                        * up the pointer now to indicate a hypercall is pending.
                        */
                        cpu->hcall = (struct hcall_args *)cpu->regs;


hcall_args defined as following:

                struct hcall_args {
                        /* These map directly onto eax/ebx/ecx/edx/esi in struct lguest_regs */
                        unsigned long arg0, arg1, arg2, arg3, arg4;
                };


In the next round to 'run_guest',  'do_hypercalls' is called, the 'do_hcall' is called.

                int run_guest(struct lg_cpu *cpu, unsigned long __user *user)
                {
                ...
                        /* We stop running once the Guest is dead. */
                        while (!cpu->lg->dead) {
                                unsigned int irq;
                                bool more;

                                /* First we run any hypercalls the Guest wants done. */
                                if (cpu->hcall)
                                        do_hypercalls(cpu);

                ...
                }
                ...
                }

'do_call' is a big switch-case to handle the LHCALL_XXX.


<h2> Memory virtualization </h2>

lguest uses shadow page tables to do the memory virtualization.
Shadow paging is used in MMU virtualization, following show the idea.


![](/assets/img/lguestinternals/6.png)



The key point is that the value loaded to CPU CR3 register is the host physical address(HPA) of shadow page table. When the guest update guest page table, it will traps to lguest to update the shadow page table.


<h3> Initialization </h3>

The initial shadow page table is initialized in 'init_guest_pagetable'.

                int init_guest_pagetable(struct lguest *lg)
                {
                        struct lg_cpu *cpu = &lg->cpus[0];
                        int allocated = 0;

                        /* lg (and lg->cpus[]) starts zeroed: this allocates a new pgdir */
                        cpu->cpu_pgd = new_pgdir(cpu, 0, &allocated);
                        if (!allocated)
                                return -ENOMEM;

                        /* We start with a linear mapping until the initialize. */
                        cpu->linear_pages = true;

                        /* Allocate the page tables for the Switcher. */
                        if (!allocate_switcher_mapping(cpu)) {
                                release_all_pagetables(lg);
                                return -ENOMEM;
                        }

                        return 0;
                }


'new_pgdir' is used to create a new page directory which means a new shadow page table. 
'cpu->linear_pages' is set to true here. This is the guest first created case. Unlike the physical machine which start at real mode and the memory access is in real mode. Here the cpu is in protected mode and the memory access is also translated.  So we need create a shadow page table even the guest now has no guest page table.

Let's dive into some details. When the guest start to execute the guest kernel code it starts at 0x1000000(which is the guest kernel start address in build). As the CR3 is set to the new page directory in 'init_guest_pagetable' so the first instruction will cause a page fault. 

![](/assets/img/lguestinternals/7.png)


'demand_page' will handle this page fault.  The initial case(which guest doesn't create page tables) is quite easy. 'demand_page' just need to set up shadow page table.
 
First find the pte table and the PTE entry in shadow page table. Then set the page in PTE entry.

                gpte = __pte((vaddr & PAGE_MASK) | _PAGE_RW | _PAGE_PRESENT);
                ...
                spte = find_spte(cpu, vaddr, true, pgd_flags(gpgd), pmd_flags(gpmd));
                ...
                set_pte(spte, gpte_to_spte(cpu, pte_wrprotect(gpte), 0));

The core function is 'gpte_to_spte' which translate gpte to spte. Here the 'gpte' is just from 'vaddr'.


                static pte_t gpte_to_spte(struct lg_cpu *cpu, pte_t gpte, int write)
                {
                        unsigned long pfn, base, flags;

                ...
                base = (unsigned long)cpu->lg->mem_base / PAGE_SIZE;

                        ...
                        pfn = get_pfn(base + pte_pfn(gpte), write);
                        ...
                        return pfn_pte(pfn, __pgprot(flags));
                }

The guest's physicall address is the virtual address of lguest, so here 'base+pte_pfn(gpte)' is the frame number of virtual address. 'get_pfn'  first get the page of this virtpfn and then return the host physical address.

                static unsigned long get_pfn(unsigned long virtpfn, int write)
                {
                        struct page *page;

                        /* gup me one page at this address please! */
                        if (get_user_pages_fast(virtpfn << PAGE_SHIFT, 1, write, &page) == 1)
                                return page_to_pfn(page);

                        /* This value indicates failure. */
                        return -1UL;
                }


Finally 'set_pte' set the physicall address in shadow PTE entry.

Let's add a 'printk' in 'demand_page'

![](/assets/img/lguestinternals/8.png)

We can see when the guest begins to execute the startup_32 code, it will first make a page fault as the shadow page table is not setup.


![](/assets/img/lguestinternals/9.png)


The dmesg will end after the guest create his own page table. Then 'cpu->linear_pages' will set to false.  Then the shadow page really shadow the guest page table.


![](/assets/img/lguestinternals/10.png)


<h3> Guest create pagetables </h3>

The guest is started  at 'startup_32'. Begin jump to lguest_entry, it will create an 'initial_page_table'.

                page_pde_offset = (__PAGE_OFFSET >> 20);

                        movl $pa(__brk_base), %edi
                        movl $pa(initial_page_table), %edx
                        movl $PTE_IDENT_ATTR, %eax
                10:
                        leal PDE_IDENT_ATTR(%edi),%ecx		/* Create PDE entry */
                        movl %ecx,(%edx)			/* Store identity PDE entry */
                        movl %ecx,page_pde_offset(%edx)		/* Store kernel PDE entry */
                        addl $4,%edx
                        movl $1024, %ecx
                11:
                        stosl
                        addl $0x1000,%eax
                        loop 11b
                        /*
                        * End condition: we must map up to the end + MAPPING_BEYOND_END.
                        */
                        movl $pa(_end) + MAPPING_BEYOND_END + PTE_IDENT_ATTR, %ebp
                        cmpl %ebp,%eax
                        jb 10b
                        addl $__PAGE_OFFSET, %edi
                        movl %edi, pa(_brk_end)
                        shrl $12, %eax
                        movl %eax, pa(max_pfn_mapped)

                        /* Do early initialization of the fixmap area */
                        movl $pa(initial_pg_fixmap)+PDE_IDENT_ATTR,%eax
                        movl %eax,pa(initial_page_table+0xffc)


Following show the initial_page_table. The kernel code has been mapped to the low address which the pa is identity with the va, this means identity mapping. Also the kernel is mapped to the high kernel address(above 0xc0000000).

![](/assets/img/lguestinternals/11.png)


Then the following code will jump to lguest_entry.


                #ifdef CONFIG_PARAVIRT
                        /* This is can only trip for a broken bootloader... */
                        cmpw $0x207, pa(boot_params + BP_version)
                        jb default_entry

                        /* Paravirt-compatible boot parameters.  Look to see what architecture
                                we're booting under. */
                        movl pa(boot_params + BP_hardware_subarch), %eax
                        cmpl $num_subarch_entries, %eax
                        jae bad_subarch

                        movl pa(subarch_entries)(,%eax,4), %eax
                        subl $__PAGE_OFFSET, %eax
                        jmp *%eax


In lguest_entry, it first make a LHCALL_LGUEST_INIT hypercall which do some initialization work, in this function the initiazation shadow page table is clear. This is why return to following code it will also trigger a page fault.


                ENTRY(lguest_entry)
                        /*
                        * We make the "initialization" hypercall now to tell the Host where
                        * our lguest_data struct is.
                        */
                        movl $LHCALL_LGUEST_INIT, %eax
                        movl $lguest_data - __PAGE_OFFSET, %ebx
                        int $LGUEST_TRAP_ENTRY

                        /* Now turn our pagetables on; setup by arch/x86/kernel/head_32.S. */
                        movl $LHCALL_NEW_PGTABLE, %eax
                        movl $(initial_page_table - __PAGE_OFFSET), %ebx
                        int $LGUEST_TRAP_ENTRY

                        /* Set up the initial stack so we can run C code. */
                        movl $(init_thread_union+THREAD_SIZE),%esp

                        /* Jumps are relative: we're running __PAGE_OFFSET too low. */
                        jmp lguest_init+__PAGE_OFFSET

This hypercall instructs the host to make a shadow page table which shadows the 'initial_page_table' created by the guest. Also the guest's page table will be changed to this new one. 
The final jmp will go to the lguest_init which in high virtual address(above 0xc0000000).

Later while the guest creates a new page table and load it to cr3(load_cr3) it will trap to host and create a new shadow page table. When the guest updates the guest page table, it will call the pv_mmu_ops almostly implemented in lguest. These hooks will make a hypercall to update the corresponding shadow page table.


                /* Pagetable management */
                pv_mmu_ops.write_cr3 = lguest_write_cr3;
                pv_mmu_ops.flush_tlb_user = lguest_flush_tlb_user;
                pv_mmu_ops.flush_tlb_single = lguest_flush_tlb_single;
                pv_mmu_ops.flush_tlb_kernel = lguest_flush_tlb_kernel;
                pv_mmu_ops.set_pte = lguest_set_pte;
                pv_mmu_ops.set_pte_at = lguest_set_pte_at;
                pv_mmu_ops.set_pmd = lguest_set_pmd;
                #ifdef CONFIG_X86_PAE
                pv_mmu_ops.set_pte_atomic = lguest_set_pte_atomic;
                pv_mmu_ops.pte_clear = lguest_pte_clear;
                pv_mmu_ops.pmd_clear = lguest_pmd_clear;
                pv_mmu_ops.set_pud = lguest_set_pud;
                #endif
                pv_mmu_ops.read_cr2 = lguest_read_cr2;
                pv_mmu_ops.read_cr3 = lguest_read_cr3;
                pv_mmu_ops.lazy_mode.enter = paravirt_enter_lazy_mmu;
                pv_mmu_ops.lazy_mode.leave = lguest_leave_lazy_mmu_mode;
                pv_mmu_ops.lazy_mode.flush = paravirt_flush_lazy_mmu;
                pv_mmu_ops.pte_update = lguest_pte_update;
                pv_mmu_ops.pte_update_defer = lguest_pte_update;


When the guest has triggered a shadow page fault. The 'demand_page' will be called to handle this, following shows the process. We need read the guest 'gpgd' and 'gpte', if either of both doesn't exist this means the guest hasn't setup the guest page table, so demand_page return false and the lguest will inject a page fault interrupt to guest thus the guest will first handle this page fault.  If the guest 'gpgd' and 'gpte' exist this means the fault is caused by the shadow pagetable and 'demand_page' find the 'spte' and set the 'spte' according the 'gpte'. 

                bool demand_page(struct lg_cpu *cpu, unsigned long vaddr, int errcode,
                                unsigned long *iomem)
                {
                        unsigned long gpte_ptr;
                        pte_t gpte;
                        pte_t *spte;
                        pmd_t gpmd;
                        pgd_t gpgd;

                        *iomem = 0;

                        
                        /* First step: get the top-level Guest page table entry. */
                        if (unlikely(cpu->linear_pages)) {
                                ...
                        } else {
                                gpgd = lgread(cpu, gpgd_addr(cpu, vaddr), pgd_t);
                                /* Toplevel not present?  We can't map it in. */
                                if (!(pgd_flags(gpgd) & _PAGE_PRESENT))
                                        return false;

                                /* 
                                * This kills the Guest if it has weird flags or tries to
                                * refer to a "physical" address outside the bounds.
                                */
                                if (!check_gpgd(cpu, gpgd))
                                        return false;
                        }

                        ...
                gpte_ptr = gpte_addr(cpu, gpgd, vaddr);
                
                        if (unlikely(cpu->linear_pages)) {
                                ...
                        } else {
                                /* Read the actual PTE value. */
                                gpte = lgread(cpu, gpte_ptr, pte_t);
                        }

                        /* If this page isn't in the Guest page tables, we can't page it in. */
                        if (!(pte_flags(gpte) & _PAGE_PRESENT))
                                return false;

                        ...

                        /* Add the _PAGE_ACCESSED and (for a write) _PAGE_DIRTY flag */
                        gpte = pte_mkyoung(gpte);
                        if (errcode & 2)
                                gpte = pte_mkdirty(gpte);

                        /* Get the pointer to the shadow PTE entry we're going to set. */
                        spte = find_spte(cpu, vaddr, true, pgd_flags(gpgd), pmd_flags(gpmd));
                        if (!spte)
                                return false;

                        ...
                        if (pte_dirty(gpte))
                                *spte = gpte_to_spte(cpu, gpte, 1);
                        else
                                /*
                                * If this is a read, don't set the "writable" bit in the page
                                * table entry, even if the Guest says it's writable.  That way
                                * we will come back here when a write does actually occur, so
                                * we can update the Guest's _PAGE_DIRTY flag.
                                */
                                set_pte(spte, gpte_to_spte(cpu, pte_wrprotect(gpte), 0));

                        /*
                        * Finally, we write the Guest PTE entry back: we've set the
                        * _PAGE_ACCESSED and maybe the _PAGE_DIRTY flags.
                        */
                        if (likely(!cpu->linear_pages))
                                lgwrite(cpu, gpte_ptr, pte_t, gpte);

                        /*
                        * The fault is fixed, the page table is populated, the mapping
                        * manipulated, the result returned and the code complete.  A small
                        * delay and a trace of alliteration are the only indications the Guest
                        * has that a page fault occurred at all.
                        */
                        return true;
                }


If the 'demand_page' handles the page fault correctly it will return true. If not, 'lguest_arch_handle_trap' will set 'lg->lguest_data->cr2' to the pagefault address and call 'deliver_trap' and this function will push an interrupt frame in guest stack so when guest got run in next round it will first handle this page fault.


                void lguest_arch_handle_trap(struct lg_cpu *cpu)
                {
                        unsigned long iomem_addr;

                        switch (cpu->regs->trapnum) {
                        case 13: /* We've intercepted a General Protection Fault. */
                                ...
                                break;
                        case 14: /* We've intercepted a Page Fault. */
                                ...
                                if (demand_page(cpu, cpu->arch.last_pagefault,
                                                cpu->regs->errcode, &iomem_addr))
                                        return;
                ...
                                if (cpu->lg->lguest_data &&
                                put_user(cpu->arch.last_pagefault,
                                        &cpu->lg->lguest_data->cr2))
                                        kill_guest(cpu, "Writing cr2");
                                break;
                        case 7: /* We've intercepted a Device Not Available fault. */
                                ...
                }

                        /* We didn't handle the trap, so it needs to go to the Guest. */
                        if (!deliver_trap(cpu, cpu->regs->trapnum))
                                /*
                                * If the Guest doesn't have a handler (either it hasn't
                                * registered any yet, or it's one of the faults we don't let
                                * it handle), it dies with this cryptic error message.
                                */
                                kill_guest(cpu, "unhandled trap %li at %#lx (%#lx)",
                                        cpu->regs->trapnum, cpu->regs->eip,
                                        cpu->regs->trapnum == 14 ? cpu->arch.last_pagefault
                                        : cpu->regs->errcode);
                }


The interrupt handle will be explored in next section.

<h2> Interrupt virtualization </h2>

<h3> Overview </h3>

There are three kinds of interrupts related with the guest. The first is the real hardware interrupts which occur while the guest is running. The second is the interrups generated by the guest's virtual devices. And the third kinds of interrupts is the traps and faults from the guest.

When the lguest module got installed the 'init' funciton will call 'lguest_arch_host_init' which will initialization 'guest_idt_desc' which in 'lguest_pages'.
‘default_idt_entries' is defined in the end of switcher page 


                .data
                .global default_idt_entries
                default_idt_entries:
                .text
                        // The first two traps go straight back to the Host
                        IRQ_STUBS 0 1 return_to_host
                        // We'll say nothing, yet, about NMI
                        IRQ_STUB 2 handle_nmi
                        // Other traps also return to the Host
                        IRQ_STUBS 3 31 return_to_host
                        // All interrupts go via their handlers
                        IRQ_STUBS 32 127 deliver_to_host
                        // 'Cept system calls coming from userspace
                        // Are to go to the Guest, never the Host.
                        IRQ_STUB 128 return_to_host
                        IRQ_STUBS 129 255 deliver_to_host

                // The NMI, what a fabulous beast
                // Which swoops in and stops us no matter that
                // We're suspended between heaven and hell,
                // (Or more likely between the Host and Guest)
                // When in it comes!  We are dazed and confused
                // So we do the simplest thing which one can.
                // Though we've pushed the trap number and zero
                // We discard them, return, and hope we live.
                handle_nmi:
                        addl	$8, %esp
                        iret

                // We are done; all that's left is Mastery
                // And "make Mastery" is a journey long
                // Designed to make your fingers itch to code.

                // Here ends the text, the file and poem.
                ENTRY(end_switcher_text)


First we set add the switcher_offset to every entry in 'default_idt_entries', this will get the load address of idt entries. Then 'setup_default_idt_entries' will set the guest's default idt entries.



                void __init lguest_arch_host_init(void)
                {
                        int i;

                        ...
                        for (i = 0; i < IDT_ENTRIES; i++)
                                default_idt_entries[i] += switcher_offset();

                        /*
                        * Set up the Switcher's per-cpu areas.
                        *
                        * Each CPU gets two pages of its own within the high-mapped region
                        * (aka. "struct lguest_pages").  Much of this can be initialized now,
                        * but some depends on what Guest we are running (which is set up in
                        * copy_in_guest_info()).
                        */
                        for_each_possible_cpu(i) {
                                /* lguest_pages() returns this CPU's two pages. */
                                struct lguest_pages *pages = lguest_pages(i);
                                /* This is a convenience pointer to make the code neater. */
                                struct lguest_ro_state *state = &pages->state;

                                ...
                                store_idt(&state->host_idt_desc);

                                /*
                                * The descriptors for the Guest's GDT and IDT can be filled
                                * out now, too.  We copy the GDT & IDT into ->guest_gdt and
                                * ->guest_idt before actually running the Guest.
                                */
                                state->guest_idt_desc.size = sizeof(state->guest_idt)-1;
                                state->guest_idt_desc.address = (long)&state->guest_idt;
                                state->guest_gdt_desc.size = sizeof(state->guest_gdt)-1;
                                state->guest_gdt_desc.address = (long)&state->guest_gdt;

                                ...
                                setup_default_gdt_entries(state);
                                /* Most IDT entries are the same for all Guests, too.*/
                                setup_default_idt_entries(state, default_idt_entries);

                                /*
                                * The Host needs to be able to use the LGUEST segments on this
                                * CPU, too, so put them in the Host GDT.
                                */
                                get_cpu_gdt_table(i)[GDT_ENTRY_LGUEST_CS] = FULL_EXEC_SEGMENT;
                                get_cpu_gdt_table(i)[GDT_ENTRY_LGUEST_DS] = FULL_SEGMENT;
                        }
                        ...
                }


The default idt entries is generated by 'IRQ_STUBS' and 'IRQ_SUTB' macro.
The 'return_to_host' means this is a trap and 'the 'deliver_to_host' means the interrupt is an external interrupt.


                IRQ_STUBS 0 1 return_to_host
                // We'll say nothing, yet, about NMI
                IRQ_STUB 2 handle_nmi
                // Other traps also return to the Host
                IRQ_STUBS 3 31 return_to_host
                // All interrupts go via their handlers
                IRQ_STUBS 32 127 deliver_to_host
                // 'Cept system calls coming from userspace
                // Are to go to the Guest, never the Host.
                IRQ_STUB 128 return_to_host
                IRQ_STUBS 129 255 deliver_to_host


When the guest kernel set interrupt table for example through 'set_intr_gate'. The pv ops 'lguest_write_idt_entry' will be called which will trigger a 'LHCALL_LOAD_IDT_ENTRY' after write idt to guest's. The lguest will call 'load_guest_idt_entry' to handle the hypercall.


                static void set_trap(struct lg_cpu *cpu, struct desc_struct *trap,
                                unsigned int num, u32 lo, u32 hi)
                {
                        u8 type = idt_type(lo, hi);

                        /* We zero-out a not-present entry */
                        if (!idt_present(lo, hi)) {
                                trap->a = trap->b = 0;
                                return;
                        }

                        /* We only support interrupt and trap gates. */
                        if (type != 0xE && type != 0xF)
                                kill_guest(cpu, "bad IDT type %i", type);

                        /*
                        * We only copy the handler address, present bit, privilege level and
                        * type.  The privilege level controls where the trap can be triggered
                        * manually with an "int" instruction.  This is usually GUEST_PL,
                        * except for system calls which userspace can use.
                        */
                        trap->a = ((__KERNEL_CS|GUEST_PL)<<16) | (lo&0x0000FFFF);
                        trap->b = (hi&0xFFFFEF00);
                }


                void load_guest_idt_entry(struct lg_cpu *cpu, unsigned int num, u32 lo, u32 hi)
                {
                        /*
                        * Guest never handles: NMI, doublefault, spurious interrupt or
                        * hypercall.  We ignore when it tries to set them.
                        */
                        if (num == 2 || num == 8 || num == 15 || num == LGUEST_TRAP_ENTRY)
                                return;

                        /*
                        * Mark the IDT as changed: next time the Guest runs we'll know we have
                        * to copy this again.
                        */
                        cpu->changed |= CHANGED_IDT;

                        /* Check that the Guest doesn't try to step outside the bounds. */
                        if (num >= ARRAY_SIZE(cpu->arch.idt))
                                kill_guest(cpu, "Setting idt entry %u", num);
                        else
                                set_trap(cpu, &cpu->arch.idt[num], num, lo, hi);
                }


The guest's setting of idt is stored in 'cpu->arch.idt'. 'load_guest_idt_entry' will set 'cpu->changed' with 'CHANGED_IDT' and then call 'set_trap'. The guest only allow set some interrupt and trap gates.
 
The 'run_guest_once' will call 'copy_in_guest_info' which will check 'cpu->changed' if it has CHANGED_IDT set it will call 'copy_traps'. This function will copy the 'direct trap' into the 'pages->state.guest_idt' from 'cpu->arch.idt[]'. 


                static void copy_in_guest_info 
                {
                ...
                if (cpu->changed & CHANGED_IDT)
                                copy_traps(cpu, pages->state.guest_idt, default_idt_entries);
                ...
                }

                void copy_traps(const struct lg_cpu *cpu, struct desc_struct *idt,
                                const unsigned long *def)
                {
                        unsigned int i;

                        /*
                        * We can simply copy the direct traps, otherwise we use the default
                        * ones in the Switcher: they will return to the Host.
                        */
                        for (i = 0; i < ARRAY_SIZE(cpu->arch.idt); i++) {
                                const struct desc_struct *gidt = &cpu->arch.idt[i];

                                /* If no Guest can ever override this trap, leave it alone. */
                                if (!direct_trap(i))
                                        continue;

                                /*
                                * Only trap gates (type 15) can go direct to the Guest.
                                * Interrupt gates (type 14) disable interrupts as they are
                                * entered, which we never let the Guest do.  Not present
                                * entries (type 0x0) also can't go direct, of course.
                                *
                                * If it can't go direct, we still need to copy the priv. level:
                                * they might want to give userspace access to a software
                                * interrupt.
                                */
                                if (idt_type(gidt->a, gidt->b) == 0xF)
                                        idt[i] = *gidt;
                                else
                                        default_idt_entry(&idt[i], i, def[i], gidt);
                        }
                }

                static bool direct_trap(unsigned int num)
                {
                        /*
                        * Hardware interrupts don't go to the Guest at all (except system
                        * call).
                        */
                        if (num >= FIRST_EXTERNAL_VECTOR && !could_be_syscall(num))
                                return false;

                        /*
                        * The Host needs to see page faults (for shadow paging and to save the
                        * fault address), general protection faults (in/out emulation) and
                        * device not available (TS handling) and of course, the hypercall trap.
                        */
                        return num != 14 && num != 13 && num != 7 && num != LGUEST_TRAP_ENTRY;
                }


After some debug, I find that only the 0x80 (syscall trap) can be set by guest. 

![](/assets/img/lguestinternals/12.png)

When host switch to guest(switch_to_guest), lidt will load the lguest_pages idt desc which point to the lguest_pages's state.guest_idt.

                lidt	LGUEST_PAGES_guest_idt_desc(%eax)


<h3> External interrupt </h3>

Then the physical CPU receive an interrupt, it will first trap to host and the following handler will be called, mostly 'deliver_to_host'. 

                IRQ_STUBS 32 127 deliver_to_host
                // 'Cept system calls coming from userspace
                // Are to go to the Guest, never the Host.
                IRQ_STUB 128 return_to_host
                IRQ_STUBS 129 255 deliver_to_host

                
The 'deliver_to_host' will first load the host context by calling 'SWITCH_TO_HOST'. Then find the interrupt handler and jump to there. The stack is ready by interrupt and 'SWITCH_TO_HOST' after the handler the iret will go to the right address which runs the host code.


                deliver_to_host:
                        SWITCH_TO_HOST
                        // But now we must go home via that place
                        // Where that interrupt was supposed to go
                        // Had we not been ensconced, running the Guest.
                        // Here we see the trickness of run_guest_once():
                        // The Host stack is formed like an interrupt
                        // With EIP, CS and EFLAGS layered.
                        // Interrupt handlers end with "iret"
                        // And that will take us home at long long last.

                        // But first we must find the handler to call!
                        // The IDT descriptor for the Host
                        // Has two bytes for size, and four for address:
                        // %edx will hold it for us for now.
                        movl	(LGUEST_PAGES_host_idt_desc+2)(%eax), %edx
                        // We now know the table address we need,
                        // And saved the trap's number inside %ebx.
                        // Yet the pointer to the handler is smeared
                        // Across the bits of the table entry.
                        // What oracle can tell us how to extract
                        // From such a convoluted encoding?
                        // I consulted gcc, and it gave
                        // These instructions, which I gladly credit:
                        leal	(%edx,%ebx,8), %eax
                        movzwl	(%eax),%edx
                        movl	4(%eax), %eax
                        xorw	%ax, %ax
                        orl	%eax, %edx
                        // Now the address of the handler's in %edx
                        // We call it now: its "iret" drops us home.
                        jmp	*%edx


<h3> Virtual device interrupt </h3>

When the lguest userspace tool wants to notify the guest for example receive of packets or console input, it will trigger an interrupt by calling 'trigger_irq'. This function writes the irq information to /dev/lguest.

                static void trigger_irq(struct virtqueue *vq)
                {
                        unsigned long buf[] = { LHREQ_IRQ, vq->dev->config.irq_line };

                        ...

                        /* Send the Guest an interrupt tell them we used something up. */
                        if (write(lguest_fd, buf, sizeof(buf)) != 0)
                                err(1, "Triggering irq %i", vq->dev->config.irq_line);
                }

The lg module calls 'user_send_irq' to handle this req. This function calls 'set_interrupt' to set bit in 'cpu->irqs_pending' and then wakeups the guest process cpu.

                static ssize_t write(struct file *file, const char __user *in,
                                size_t size, loff_t *off)
                {
                        ...

                        switch (req) {
                        case LHREQ_INITIALIZE:
                                return initialize(file, input);
                        case LHREQ_IRQ:
                                return user_send_irq(cpu, input);
                        case LHREQ_GETREG:
                                return getreg_setup(cpu, input);
                        case LHREQ_SETREG:
                                return setreg(cpu, input);
                        case LHREQ_TRAP:
                                return trap(cpu, input);
                        default:
                                return -EINVAL;
                        }
                }

                void set_interrupt(struct lg_cpu *cpu, unsigned int irq)
                {
                        /*
                        * Next time the Guest runs, the core code will see if it can deliver
                        * this interrupt.
                        */
                        set_bit(irq, cpu->irqs_pending);

                        /*
                        * Make sure it sees it; it might be asleep (eg. halted), or running
                        * the Guest right now, in which case kick_process() will knock it out.
                        */
                        if (!wake_up_process(cpu->tsk))
                                kick_process(cpu->tsk);
                }


The 'run_guest' will call 'interrupt_pending' to check whether there are pending interrupts and call 'try_deliver_interrupt' to handle the interrupts.

		irq = interrupt_pending(cpu, &more);
		if (irq < LGUEST_IRQS)
			try_deliver_interrupt(cpu, irq, more);


<h3> Guest trap </h3>

If the guest triggers a trap for example, the guest hasn't setup pagetables for memory access. This will first trap to the host and the 'return_to_host' will be called.

                IRQ_STUBS 0 1 return_to_host
                // We'll say nothing, yet, about NMI
                IRQ_STUB 2 handle_nmi
                // Other traps also return to the Host
                IRQ_STUBS 3 31 return_to_host


'return_to_host' is just 'SWITCH_TO_HOST' and 'iret' will return to the point which run guest code in 'run_guest_once'.

                return_to_host:
                        SWITCH_TO_HOST
                        iret


The SWITCH_TO_HOST will set the 'cpu->regs->trapnum'. After 'iret' we will call 'lguest_arch_handle_trap' to handle the guest trap. If the trap is about the guest. The 'deliver_trap' will be called to deliver the interrupt to guest. 


                int run_guest(struct lg_cpu *cpu, unsigned long __user *user)
                {
                        ...

                        /* We stop running once the Guest is dead. */
                        while (!cpu->lg->dead) {
                                unsigned int irq;
                                bool more;

                                /* First we run any hypercalls the Guest wants done. */
                                if (cpu->hcall)
                                        do_hypercalls(cpu);

                                ...

                                ...
                                irq = interrupt_pending(cpu, &more);
                                if (irq < LGUEST_IRQS)
                                        try_deliver_interrupt(cpu, irq, more);

                                ...
                                local_irq_disable();

                                /* Actually run the Guest until something happens. */
                                lguest_arch_run_guest(cpu);

                                /* Now we're ready to be interrupted or moved to other CPUs */
                                local_irq_enable();

                                /* Now we deal with whatever happened to the Guest. */
                                lguest_arch_handle_trap(cpu);
                        }
                        ...
                }


'push_guest_interrupt_stack' push the guest state to guest stack. 'guest_run_interrupt' will change the eip to the interrupt handler. When the guest code got run, it will first run the guest interrupt handler code.


                bool deliver_trap(struct lg_cpu *cpu, unsigned int num)
                {
                /*
                * Trap numbers are always 8 bit, but we set an impossible trap number
                * for traps inside the Switcher, so check that here.
                */
                if (num >= ARRAY_SIZE(cpu->arch.idt))
                        return false;

                /*
                * Early on the Guest hasn't set the IDT entries (or maybe it put a
                * bogus one in): if we fail here, the Guest will be killed.
                */
                if (!idt_present(cpu->arch.idt[num].a, cpu->arch.idt[num].b))
                        return false;
                push_guest_interrupt_stack(cpu, has_err(num));
                guest_run_interrupt(cpu, cpu->arch.idt[num].a,
                                cpu->arch.idt[num].b);
                return true;
                }

                static void guest_run_interrupt(struct lg_cpu *cpu, u32 lo, u32 hi)
                {
                        /* If we're already in the kernel, we don't change stacks. */
                        if ((cpu->regs->ss&0x3) != GUEST_PL)
                                cpu->regs->ss = cpu->esp1;

                        /*
                        * Set the code segment and the address to execute.
                        */
                        cpu->regs->cs = (__KERNEL_CS|GUEST_PL);
                        cpu->regs->eip = idt_address(lo, hi);

                        /*
                        * Trapping always clears these flags:
                        * TF: Trap flag
                        * VM: Virtual 8086 mode
                        * RF: Resume
                        * NT: Nested task.
                        */
                        cpu->regs->eflags &=
                                ~(X86_EFLAGS_TF|X86_EFLAGS_VM|X86_EFLAGS_RF|X86_EFLAGS_NT);

                        /*
                        * There are two kinds of interrupt handlers: 0xE is an "interrupt
                        * gate" which expects interrupts to be disabled on entry.
                        */
                        if (idt_type(lo, hi) == 0xE)
                                if (put_user(0, &cpu->lg->lguest_data->irq_enabled))
                                        kill_guest(cpu, "Disabling interrupts");
                }

<h3> Direct trap </h3>

Returning to the host every time a trap happens and then calling deliver_trap and re-entering the guest is slow. So we can set up the IDT to tell the CPU to execute the guest interrupt handler directly with no lguest involvement. When the guest set interrupt gate, the lguest will check whether this setting is allowed. Only a little interrupt is allowed to set such as the system call. When the interrupt is triggered, the guest kernel will just jump to the handler it sets(just like there is no hypervisor).


<h2> Device virtualization </h2>

lguest just supports the basic virtio devices including net/block/console/rng. The device memory space is just located after the guest normal memory. All devices is virtio device attached to the PCI host bridge. All devices is put in the global variable 'devices'.


                struct device_list {
                        /* Counter to assign interrupt numbers. */
                        unsigned int next_irq;

                        /* Counter to print out convenient device numbers. */
                        unsigned int device_num;

                        /* PCI devices. */
                        struct device *pci[MAX_PCI_DEVICES];
                };

                /* The list of Guest devices, based on command line arguments. */
                static struct device_list devices;


Let's take the console device as an example. 'new_pci_device' creates the pci device, 'add_pci_virtqueue' sets the input/output handler of virtio. 'add_pci_feature' adds the device feature. 


                static void setup_console(void)
                {
                        struct device *dev;
                        struct virtio_console_config conf;

                        /* If we can save the initial standard input settings... */
                        if (tcgetattr(STDIN_FILENO, &orig_term) == 0) {
                                struct termios term = orig_term;
                                /*
                                * Then we turn off echo, line buffering and ^C etc: We want a
                                * raw input stream to the Guest.
                                */
                                term.c_lflag &= ~(ISIG|ICANON|ECHO);
                                tcsetattr(STDIN_FILENO, TCSANOW, &term);
                        }

                        dev = new_pci_device("console", VIRTIO_ID_CONSOLE, 0x07, 0x00);

                        /* We store the console state in dev->priv, and initialize it. */
                        dev->priv = malloc(sizeof(struct console_abort));
                        ((struct console_abort *)dev->priv)->count = 0;

                        /*
                        * The console needs two virtqueues: the input then the output.  When
                        * they put something the input queue, we make sure we're listening to
                        * stdin.  When they put something in the output queue, we write it to
                        * stdout.
                        */
                        add_pci_virtqueue(dev, console_input, "input");
                        add_pci_virtqueue(dev, console_output, "output");

                        /* We need a configuration area for the emerg_wr early writes. */
                        add_pci_feature(dev, VIRTIO_CONSOLE_F_EMERG_WRITE);
                        set_device_config(dev, &conf, sizeof(conf));

                        verbose("device %u: console\n", devices.device_num);
                }


When the lguest receives data the 'console_input' will be called and when the guest kernel write data to console the 'console_output' will be called.

How guest kernel find and enumerate these PCI devices?
When the guest tries to enumerate the PCI devices it will access the PCI_CONFIG_ADDR (0xcf8) and PCI_CONFIG_DATA(0xcfc) ports.  These access will delivered to lguest userspace and 'emulate_insn' will try to emulate these access.

When the port is in PCI_CONFIG_ADDR or PCI_CONFIG_DATA, it will call the pci-related function.


                static void emulate_insn(const u8 insn[])
                {
                        unsigned long args[] = { LHREQ_TRAP, 13 };
                        unsigned int insnlen = 0, in = 0, small_operand = 0, byte_access;
                        unsigned int eax, port, mask;
                        ...
                        eax = getreg(eax);

                        if (in) {
                                /* This is the PS/2 keyboard status; 1 means ready for output */
                                if (port == 0x64)
                                        val = 1;
                                else if (is_pci_addr_port(port))
                                        pci_addr_ioread(port, mask, &val);
                                else if (is_pci_data_port(port))
                                        pci_data_ioread(port, mask, &val);

                                /* Clear the bits we're about to read */
                                eax &= ~mask;
                                /* Copy bits in from val. */
                                eax |= val & mask;
                                /* Now update the register. */
                                setreg(eax, eax);
                        } else {
                                if (is_pci_addr_port(port)) {
                                        if (!pci_addr_iowrite(port, mask, eax))
                                                goto bad_io;
                                } else if (is_pci_data_port(port)) {
                                        if (!pci_data_iowrite(port, mask, eax))
                                                goto bad_io;
                                }
                                /* There are many other ports, eg. CMOS clock, serial
                                * and parallel ports, so we ignore them all. */
                        }
                ...
                }


For example when the guest triggers a 'pci_data_ioread', we will find the pci device and return the data to guest.


                static void pci_data_ioread(u16 port, u32 mask, u32 *val)
                {
                        u32 reg;
                        struct device *d = dev_and_reg(&reg);

                        if (!d)
                                return;

                        /* Read through the PCI MMIO access window is special */
                        if (&d->config_words[reg] == &d->config.cfg_access.pci_cfg_data) {
                                u32 read_mask;

                                /*
                                * 4.1.4.7.1:
                                *
                                *  Upon detecting driver read access to pci_cfg_data, the
                                *  device MUST execute a read access of length cap.length at
                                *  offset cap.offset at BAR selected by cap.bar and store the
                                *  first cap.length bytes in pci_cfg_data.
                                */
                                /* Must be bar 0 */
                                if (!valid_bar_access(d, &d->config.cfg_access))
                                        bad_driver(d,
                                        "Invalid cfg_access to bar%u, offset %u len %u",
                                        d->config.cfg_access.cap.bar,
                                        d->config.cfg_access.cap.offset,
                                        d->config.cfg_access.cap.length);

                                /*
                                * Read into the window.  The mask we use is set by
                                * len, *not* this read!
                                */
                                read_mask = (1ULL<<(8*d->config.cfg_access.cap.length))-1;
                                d->config.cfg_access.pci_cfg_data
                                        = emulate_mmio_read(d,
                                                        d->config.cfg_access.cap.offset,
                                                        read_mask);
                                verbose("Window read %#x/%#x from bar %u, offset %u len %u\n",
                                        d->config.cfg_access.pci_cfg_data, read_mask,
                                        d->config.cfg_access.cap.bar,
                                        d->config.cfg_access.cap.offset,
                                        d->config.cfg_access.cap.length);
                        }
                        ioread(port - PCI_CONFIG_DATA, d->config_words[reg], mask, val);
                }

When the guest writes the devices' MMIO address, it will trigger a page fault trap and this will be delivered to userspace and the guest will emulate these access.


                static void __attribute__((noreturn)) run_guest(void)
                {
                        for (;;) {
                                struct lguest_pending notify;
                                int readval;

                                /* We read from the /dev/lguest device to run the Guest. */
                                readval = pread(lguest_fd, &notify, sizeof(notify), cpu_id);
                                if (readval == sizeof(notify)) {
                                        if (notify.trap == 13) {
                                                verbose("Emulating instruction at %#x\n",
                                                        getreg(eip));
                                                emulate_insn(notify.insn);
                                        } else if (notify.trap == 14) {
                                                verbose("Emulating MMIO at %#x\n",
                                                        getreg(eip));
                                                emulate_mmio(notify.addr, notify.insn);
                                        } else
                                                errx(1, "Unknown trap %i addr %#08x\n",
                                                notify.trap, notify.addr);
                                /* ENOENT means the Guest died.  Reading tells us why. */
                                } else if (errno == ENOENT) {
                                        char reason[1024] = { 0 };
                                        pread(lguest_fd, reason, sizeof(reason)-1, cpu_id);
                                        errx(1, "%s", reason);
                                /* ERESTART means that we need to reboot the guest */
                                } else if (errno == ERESTART) {
                                        restart_guest();
                                /* Anything else means a bug or incompatible change. */
                                } else
                                        err(1, "Running guest failed");
                        }
                }

<h2> Guest Time </h2>

Guest wall clock is got from 'cpu->lg->lguest_data->time'. When initialization and every interrupt injection 'write_timestamp' will be called to update the wall clock.


                void write_timestamp(struct lg_cpu *cpu)
                {
                        struct timespec now;
                        ktime_get_real_ts(&now);
                        if (copy_to_user(&cpu->lg->lguest_data->time,
                                        &now, sizeof(struct timespec)))
                                kill_guest(cpu, "Writing timestamp");
                }

lguest implements several timer-related callbacks. The first is 'x86_init.timers.timer_init'.
The most important function is the 'set_next_event' of 'lguest_clockevent'.


                x86_init.timers.timer_init = lguest_time_init;

                static void lguest_time_init(void)
                {
                        /* Set up the timer interrupt (0) to go to our simple timer routine */
                        if (lguest_setup_irq(0) != 0)
                                panic("Could not set up timer irq");
                        irq_set_handler(0, lguest_time_irq);

                        clocksource_register_hz(&lguest_clock, NSEC_PER_SEC);

                        /* We can't set cpumask in the initializer: damn C limitations!  Set it
                        * here and register our timer device. */
                        lguest_clockevent.cpumask = cpumask_of(0);
                        clockevents_register_device(&lguest_clockevent);

                        /* Finally, we unblock the timer interrupt. */
                        clear_bit(0, lguest_data.blocked_interrupts);
                }


                static struct clock_event_device lguest_clockevent = {
                        .name                   = "lguest",
                        .features               = CLOCK_EVT_FEAT_ONESHOT,
                        .set_next_event         = lguest_clockevent_set_next_event,
                        .set_state_shutdown	= lguest_clockevent_shutdown,
                        .rating                 = INT_MAX,
                        .mult                   = 1,
                        .shift                  = 0,
                        .min_delta_ns           = LG_CLOCK_MIN_DELTA,
                        .max_delta_ns           = LG_CLOCK_MAX_DELTA,
                };

                static int lguest_clockevent_set_next_event(unsigned long delta,
                                                        struct clock_event_device *evt)
                {
                        /* FIXME: I don't think this can ever happen, but James tells me he had
                        * to put this code in.  Maybe we should remove it now.  Anyone? */
                        if (delta < LG_CLOCK_MIN_DELTA) {
                                if (printk_ratelimit())
                                        printk(KERN_DEBUG "%s: small delta %lu ns\n",
                                        __func__, delta);
                                return -ETIME;
                        }

                        /* Please wake us this far in the future. */
                        hcall(LHCALL_SET_CLOCKEVENT, delta, 0, 0, 0);
                        return 0;
                }


Then this callback is called by the timer subsystem, a LHCALL_SET_CLOCKEVENT hypercall is issued. 'guest_set_clockevent' is called to handle this hypercall. This function just starts a timer and when the timer is alarmed an timer interrupt using irq(0) will be inject to the guest.



                void guest_set_clockevent(struct lg_cpu *cpu, unsigned long delta)
                {
                        ktime_t expires;

                        if (unlikely(delta == 0)) {
                                /* Clock event device is shutting down. */
                                hrtimer_cancel(&cpu->hrt);
                                return;
                        }

                        /*
                        * We use wallclock time here, so the Guest might not be running for
                        * all the time between now and the timer interrupt it asked for.  This
                        * is almost always the right thing to do.
                        */
                        expires = ktime_add_ns(ktime_get_real(), delta);
                        hrtimer_start(&cpu->hrt, expires, HRTIMER_MODE_ABS);
                }

                /* This is the function called when the Guest's timer expires. */
                static enum hrtimer_restart clockdev_fn(struct hrtimer *timer)
                {
                        struct lg_cpu *cpu = container_of(timer, struct lg_cpu, hrt);

                        /* Remember the first interrupt is the timer interrupt. */
                        set_interrupt(cpu, 0);
                        return HRTIMER_NORESTART;
                }

                /* This sets up the timer for this Guest. */
                void init_clockdev(struct lg_cpu *cpu)
                {
                        hrtimer_init(&cpu->hrt, CLOCK_REALTIME, HRTIMER_MODE_ABS);
                        cpu->hrt.function = clockdev_fn;
                }

<h2> Summary </h2> 

lguest is a paravirt virtualization solution which can run virtual machine without the hardware support. The guest kernel need to be modified to run in lguest. 

For CPU virtualization, the lguest maps switcher code to both guest and host (in the same virtual address). The switcher is used to switch between guest and host.

For memory virtualization, it uses shadow page table which does translation from gva to hpa. This is the most performance overhead.

For device virtualization, the lugest implements devices in lguest userspace tool and intercepts the PCI IO port access and manages the PCI devices. All support is virtio devices. 

There is no interrupt controller like APIC or IOAPI device. The devices' interrupt is injected by adjusting the eip of guest before run guest code. And the guest trap is intercepted by lguest.



