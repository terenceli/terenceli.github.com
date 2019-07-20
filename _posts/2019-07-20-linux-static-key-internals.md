---
layout: post
title: "Linux static_key internlas"
description: "static_key"
category: 技术
tags: [内核]
---
{% include JB/setup %}

<h3> static_key introduction </h3>

There are often a situation that we need to check some switch to determine which code flow to be executed. In some cases the switch is almost the same (true or false), so the check may influence the performance. static_key and jump label let us do code patch in the address which we need to check. Using static_key, there is no check but just flat code flow. There are a lot of static_key usage introduction, but little internals introduction. This post is try to explain the static_key misc under the surface. This post uses kernel 4.4 as I just have this code in my hand now.

There are three aspects for static_key:
1. We need to save the static_key information in the ELF file, these information is stored in the '__jump_table' section in ELF file
2. The kernel need to parse these '__jump_table' information 
3. When we change the switch, the kernel need to update the patched code

The idea of static_key is illustrated as following:

![](/assets/img/static_key/1.jpg)


Here in most situation the switch is the 'most state' so the red block is nop, this means the switch is in the 'mostly' state. When we change the state of the switch,the kernel will update the red block as a jump instruction so that the code can go to the '2' code flow. 


<h3> Store static_key information in ELF file </h3>

static_key is defined by a 'struct static_key'：

        struct static_key {
                atomic_t enabled;
        /* Set lsb bit to 1 if branch is default true, 0 ot */
                struct jump_entry *entries;
        #ifdef CONFIG_MODULES
                struct static_key_mod *next;
        #endif
        };


The 'enabled' indicates the state of static_key, 0 means false and 1 means true. 'entries' contains the patching information of jump label, it is defined as following:

        struct jump_entry {
                jump_label_t code;
                jump_label_t target;
                jump_label_t key;
        };


code is the address of 'patching', target is where we should jump, and key is the address of static_key.

The 'next' field in static_key is used for modules reference the kernel image or other modules' static_key.

Let's use the 'apic_sw_disabled' in arch/x86/kvm/lapic.c as an example. It is defined as following:

        struct static_key_deferred apic_sw_disabled __read_mostly;

Here the 'static_key_deferred' is just a wrapper of static_key, it just contains a 'timeout' and a 'delayed work' to do the update using a delayed work.

        struct static_key_deferred {
                struct static_key key;
                unsigned long timeout;
                struct delayed_work work;
        };


'apic_sw_disabled' is used to determine whether the system software enables the local apic, in most cases, the software will enable this. So the default of 'apic_sw_disabled' is false. Notice, the 'apic_sw_disabled' is used for all of the vcpu. If any of the vcpu in the host disable the local apic, the 'apic_sw_disabled' will be true. 

In 'kvm_apic_sw_enabled', it calls 'static_key_false' to determine 'apic_sw_disabled.key'. The 'static_key_false' just calls 'arch_static_branch' and latter is as following:

        static __always_inline bool arch_static_branch(struct static_key *key, bool branch)
        {
                asm_volatile_goto("1:"
                        ".byte " __stringify(STATIC_KEY_INIT_NOP) "\n\t"
                        ".pushsection __jump_table,  \"aw\" \n\t"
                        _ASM_ALIGN "\n\t"
                        _ASM_PTR "1b, %l[l_yes], %c0 + %c1 \n\t"
                        ".popsection \n\t"
                        : :  "i" (key), "i" (branch) : : l_yes);

                return false;
        l_yes:
                return true;
        }


The 'STATIC_KEY_INIT_NOP' is 'no-op instruction' , it is '0x0f,0x1f,0x44,0x00,0'. This is the red block in the first pic. The data between '.pushsection' and '.popsection' will be in '__jump_table' section. For every arch_static_branch call there are three unsigned long data in the '__jump_table'. The first unsigned long is the address of '1b', this is the 5 'no-op instruction's address. The second if the address of 'l_yes', and the third is the static_key's address ored with the branch value(false for the static_key_false, and true for the static_key_true).


'static_key_false' and 'arch_static_branch' is always inline, so 'kvm_apic_sw_enabled' will be compiled as following asm instruction. 

![](/assets/img/static_key/2.jpg)


Notice we have set the 'kvm_apic_sw_enabled' as noinline by adding 'noline' in the function signature.

As the '13f70' line is no-op instruction, so this 'kvm_apic_sw_enabled' always return 1. This is right. 

Also after 'arch_static_branch' is compiled, there are three unsigned long data in the '__jump_table'.  It lays as following:

        |no-op address | target address | static_key's address ored with 0|

In this function it is:

        |13f79 | 13f85| kvm_apic_sw_enabled.key's address|

These three data is coressponding to the 'jump_entry', The kvm_apic_sw_enabled.key's address is a global address.

Notice here '13f79' is just the address of the kvm.ko file offset. In module loding, it will be reallocated.

<h3> Parses '__jump_table' when startup </h3>

In 'start_kerne' it calls 'jump_label_init' to parse the '__jump_table'. For modules, in 'jump_label_init_module' it register a module notifier named 'jump_label_module_nb', when a module loaded, it calls 'jump_label_add_module' to parse '__jump_table'. We will deep into the module case. 'jump_label_add_module's code is following:

        static int jump_label_add_module(struct module *mod)
        {
                struct jump_entry *iter_start = mod->jump_entries;
                struct jump_entry *iter_stop = iter_start + mod->num_jump_entries;
                struct jump_entry *iter;
                struct static_key *key = NULL;
                struct static_key_mod *jlm;

                /* if the module doesn't have jump label entries, just return */
                if (iter_start == iter_stop)
                        return 0;

                jump_label_sort_entries(iter_start, iter_stop);

                for (iter = iter_start; iter < iter_stop; iter++) {
                        struct static_key *iterk;

                        iterk = jump_entry_key(iter);
                        if (iterk == key)
                                continue;

                        key = iterk;
                        if (within_module(iter->key, mod)) {
                                /*
                                * Set key->entries to iter, but preserve JUMP_LABEL_TRUE_BRANCH.
                                */
                                *((unsigned long *)&key->entries) += (unsigned long)iter;
                                key->next = NULL;
                                continue;
                        }
                        ...
                }

                return 0;
        }


The 'iter_start' pointer the first of jump_entries and 'iter_sopt' pointer the end of jump_entries.
The jump entries is sorted by 'jump_label_sort_entries' function. We can get the function of one 'static_key' from 'jump_entry' entry by calling 'jump_entry_key' function. Notice the third of 'jump_entry' is the address of static_key ored with the 0 or 1. So 'jump_entry_key' clears the first bit.

        static inline struct static_key *jump_entry_key(struct jump_entry *entry)
        {
                return (struct static_key *)((unsigned long)entry->key & ~1UL);
        }

Later if the static_key is defined in this module, 'jump_label_add_module' sets this static_key's entries to the address of 'jump_entry'. If the static_key is defined in another, we need to uses the 'next' field in 'static_key' to record this.

After calling 'jump_label_add_module', the 'static_key' and 'jump_entry' has following relation.


![](/assets/img/static_key/3.jpg)


<h4> patch the function </h4>

Now the function 'kvm_apic_sw_enabled' return true, means the 'apic_sw_disabled.key' is false. However in some point we need to change the 'apic_sw_disabled.key' to true. For example in 'kvm_create_lapic', it has following statement: 

        static_key_slow_inc(&apic_sw_disabled.key); 

This means when creating lapic, we need to set 'apic_sw_disabled.key' to true.

'static_key_slow_inc' calls 'jump_label_update' to patch the code, and also set 'static_key's enabled to 1. 

        static void jump_label_update(struct static_key *key)
        {
                struct jump_entry *stop = __stop___jump_table;
                struct jump_entry *entry = static_key_entries(key);
        #ifdef CONFIG_MODULES
                struct module *mod;

                __jump_label_mod_update(key);

                preempt_disable();
                mod = __module_address((unsigned long)key);
                if (mod)
                        stop = mod->jump_entries + mod->num_jump_entries;
                preempt_enable();
        #endif
                /* if there are no users, entry can be NULL */
                if (entry)
                        __jump_label_update(key, entry, stop);
        }

'jump_label_update' get the 'jump_entry' from 'static_key's 'entries' field. The 'stop' is either '__stop___jump_table' or the 'static_key's module's end of jump entries. Then call '__jump_label_update'.

        static void __jump_label_update(struct static_key *key,
                                        struct jump_entry *entry,
                                        struct jump_entry *stop)
        {
                for (; (entry < stop) && (jump_entry_key(entry) == key); entry++) {
                        /*
                        * entry->code set to 0 invalidates module init text sections
                        * kernel_text_address() verifies we are not in core kernel
                        * init code, see jump_label_invalidate_module_init().
                        */
                        if (entry->code && kernel_text_address(entry->code))
                                arch_jump_label_transform(entry, jump_label_type(entry));
                }
        }

After the check, this function calls 'arch_jump_label_transform', with the return value of 'jump_label_type'. 'jump_label_type' function return the jump type, means we should use nop or jump.
There are two jump type in kernel 4.4, JUMP_LABEL_NOP with 0, and JUMP_LABEL_JMP with 1.

        enum jump_label_type {
                JUMP_LABEL_NOP = 0,
                JUMP_LABEL_JMP,
        };

'jump_label_type' 

        static enum jump_label_type jump_label_type(struct jump_entry *entry)
        {
                struct static_key *key = jump_entry_key(entry);
                bool enabled = static_key_enabled(key);
                bool branch = jump_entry_branch(entry);

                /* See the comment in linux/jump_label.h */
                return enabled ^ branch;
        }

Here the 'enabled' is -1(0xffffffff), this is set in 'static_key_slow_inc', the branch is the function used, here is 0(static_key_false), so 'jump_label_type' return 1. 


'arch_jump_label_transform' calls '__jump_label_transform' with the type(1, JUMP_LABEL_JMP), poker(NULL), and init(NULL). So the calling code will be:

        static void __jump_label_transform(struct jump_entry *entry,
                                        enum jump_label_type type,
                                        void *(*poker)(void *, const void *, size_t),
                                        int init)
        {
                union jump_code_union code;
                const unsigned char default_nop[] = { STATIC_KEY_INIT_NOP };
                const unsigned char *ideal_nop = ideal_nops[NOP_ATOMIC5];

                if (type == JUMP_LABEL_JMP) {
                        if (init) {
                            ...
                        } else {
                                /*
                                * ...otherwise expect an ideal_nop. Otherwise
                                * something went horribly wrong.
                                */
                                if (unlikely(memcmp((void *)entry->code, ideal_nop, 5)
                                        != 0))
                                        bug_at((void *)entry->code, __LINE__);
                        }

                        code.jump = 0xe9;
                        code.offset = entry->target -
                                        (entry->code + JUMP_LABEL_NOP_SIZE);
                } else {
                      ...
                }

                ...
                if (poker)
                        (*poker)((void *)entry->code, &code, JUMP_LABEL_NOP_SIZE);
                else
                        text_poke_bp((void *)entry->code, &code, JUMP_LABEL_NOP_SIZE,
                                (void *)entry->code + JUMP_LABEL_NOP_SIZE);
        }

The 'code' will contains the jump code, the first byte is '0xe9', and later four bytes is the offset to jump. Finally, the '__jump_label_transform' calls 'text_poke_bp' to write the 'jump_entry->code's 5 bytes as the jump to another branch. In 'kvm_apic_sw_enabled' function, it will return 'apic->sw_enabled'. In 'static_key_slow_inc' after 'jump_label_update', it will set the 'key->enabled' to 1. 

'apic_sw_disabled.key' is later reenabled by 'static_key_slow_dec_deferred' in 'apic_set_spiv'. When we 
The delayed work will call '__static_key_slow_dec' finally, and it will decrease the 'key->enabled' and later 'enabled ^ branch' will be 0, so in '__jump_label_transform' it will patch the code goto no-op instruction. 





<h3> Reference </h3>

[1] [kernel static_key doc](https://github.com/torvalds/linux/blob/master/Documentation/static-keys.txt)

[2] [int3-based instruction patching](https://github.com/linux-wmt/linux-vtwm/commit/fd4363fff3d96795d3feb1b3fb48ce590f186bdd)