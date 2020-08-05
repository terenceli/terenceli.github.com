---
layout: post
title: "Linux tracing - kprobe, uprobe and tracepoint"
description: "Linux tracing"
category: 技术
tags: [内核, trace]
---
{% include JB/setup %}

<h3> Background </h3>

Linux tracing system is confused as there are many faces of tracing. There are lots of terminology around tracing such as ftrace, kprobe, uprobe, tracing event. 

Julia Evans has written a blog [Linux tracing systems & how they fit together](https://jvns.ca/blog/2017/07/05/linux-tracing-systems/#ftrace) to clarify these by splitting linux tracing systems into data sources (where the tracing data comes from), mechanisms for collecting data for those sources (like “ftrace”) and tracing frontends (the tool you actually interact with to collect/analyse data). 

In this post, I will summary the mechanism of data sources. From Steven Rostedt slides [Unified Tracing Platform](https://static.sched.com/hosted_files/osseu19/5f/unified-tracing-platform-oss-eu-2019.pdf) the event trace basics kprobes, uprobes, tracepoint.

In this post I will give one example of each data sources and summary the mechanism how these work in Linux kernel.


<h3> kprobe </h3>


<h4> kprobe usage </h4>

Following is a raw usage of kprobe, minor adjustment from kernel/sample/kprobes/kprobe_example.c

                #include <linux/kernel.h>
                #include <linux/module.h>
                #include <linux/kprobes.h>

                #define MAX_SYMBOL_LEN	64
                static char symbol[MAX_SYMBOL_LEN] = "_do_fork";
                module_param_string(symbol, symbol, sizeof(symbol), 0644);

                /* For each probe you need to allocate a kprobe structure */
                static struct kprobe kp = {
                        .symbol_name	= symbol,
                };

                /* kprobe pre_handler: called just before the probed instruction is executed */
                static int handler_pre(struct kprobe *p, struct pt_regs *regs)
                {
                        pr_info("<%s> pre_handler: name = %s, p->addr = 0x%p, ip = %lx, flags = 0x%lx\n",
                                p->symbol_name, current->comm,  p->addr, regs->ip, regs->flags);

                        return 0;
                }

                /* kprobe post_handler: called after the probed instruction is executed */
                static void handler_post(struct kprobe *p, struct pt_regs *regs,
                                                unsigned long flags)
                {
                        pr_info("<%s> post_handler: p->addr = 0x%p, flags = 0x%lx\n",
                                p->symbol_name, p->addr, regs->flags);
                }

                /*
                * fault_handler: this is called if an exception is generated for any
                * instruction within the pre- or post-handler, or when Kprobes
                * single-steps the probed instruction.
                */
                static int handler_fault(struct kprobe *p, struct pt_regs *regs, int trapnr)
                {
                        pr_info("fault_handler: p->addr = 0x%p, trap #%dn", p->addr, trapnr);
                        /* Return 0 because we don't handle the fault. */
                        return 0;
                }

                static int __init kprobe_init(void)
                {
                        int ret;
                        kp.pre_handler = handler_pre;
                        kp.post_handler = handler_post;
                        kp.fault_handler = handler_fault;

                        ret = register_kprobe(&kp);
                        if (ret < 0) {
                                pr_err("register_kprobe failed, returned %d\n", ret);
                                return ret;
                        }
                        pr_info("Planted kprobe at %p\n", kp.addr);
                        return 0;
                }

                static void __exit kprobe_exit(void)
                {
                        unregister_kprobe(&kp);
                        pr_info("kprobe at %p unregistered\n", kp.addr);
                }

                module_init(kprobe_init)
                module_exit(kprobe_exit)
                MODULE_LICENSE("GPL");

After building and insmod it, the dmesg will show the message.


<h4> kprobe anatomy </h4>

The work flow of kprobe is as following:
* register_kprobe() function register a probe address(mostly a function), prepare_kprobe()->arch_prepare_kprobe(), in x86 the later will copy the instruction of probe address and store it, arm_kprobe->arch_arm_kprobe(), in x86 the later function will modify the probe address's instruction to 'BREAKPOINT_INSTRUCTION'(int3 breakpoint). This kprobe is inserted in 'kprobe_table' hash list.

* When the probe address is executed, do_int3() will be called to handle the exception. This function will call kprobe_int3_handler(), kprobe_int3_handler() call get_probe() to find the kprobe from the 'kprobe_table' hash list. And then call pre_handler of the registered kprobe. The kprobe_int3_handler then call 'setup_singlestep' to setup single execute the stored probe address. Then return and after the int3 handler over, the original probe address instruction execution begion.

* After the original probe instruction complete, it triggers a single step exeception, this is handled by 'kprobe_debug_handler'. In this function, the post_handler of registered kprobe will be executed.

The kretprobe is almostly the same as kprobe, in register_kretprobe(), it calls register_kprobe() to register a kprobe with the pre_handle 'pre_handler_kretprobe', This function will modify the normal return address to 'kretprobe_trampoline' address.


<h3> uprobe </h3>

<h4> uprobe usage </h4>

Prepare a tiny C program:

                #include <stdio.h>
                #include <stdlib.h>

                void f()
                {
                printf("f() called\n");
                }
                int main()
                {
                f();
                return 0; 
                }

Using objedump -S find the f()'s offset in ELF, it's 0x64d here.
Do the uprobe as following:

        root@ubuntu:~/uprobe# echo 'p /home/test/uprobe/test:0x64d' >> /sys/kernel/debug/tracing/uprobe_events 
        root@ubuntu:~/uprobe# echo 1 > /sys/kernel/debug/tracing/events/uprobes/p_test_0x64d/enable 
        root@ubuntu:~/uprobe# echo 1 > /sys/kernel/debug/tracing/tracing_on 
        root@ubuntu:~/uprobe# ./test
        f() called
        root@ubuntu:~/uprobe# ./test
        f() called
        root@ubuntu:~/uprobe# echo 0 > /sys/kernel/debug/tracing/tracing_on 
        root@ubuntu:~/uprobe# cat /sys/kernel/debug/tracing/trace
        # tracer: nop
        #
        # entries-in-buffer/entries-written: 2/2   #P:8
        #
        #                              _-----=> irqs-off
        #                             / _----=> need-resched
        #                            | / _---=> hardirq/softirq
        #                            || / _--=> preempt-depth
        #                            ||| /     delay
        #           TASK-PID   CPU#  ||||    TIMESTAMP  FUNCTION
        #              | |       |   ||||       |         |
                test-17489 [005] d... 128037.287391: p_test_0x64d: (0x55f38badc64d)
                test-17490 [004] d... 128038.998229: p_test_0x64d: (0x55c76884e64d)



<h4> uprobe anatomy </h4>

The uprobe has no separately interface exported except the debugfs/tracefs. Following steps show how uprobe works.

* Write uprobe event to 'uprobe_events'. probes_write()->create_trace_uprobe(). The later function call kern_path() to open the ELF file and get the file's inode. Call alloc_trace_uprobe() to allocate a trace_uprobe struct, the inode and offset is stored in this struct. Call register_trace_uprobe() to register a trace_uprobe. register_trace_uprobe() calls 'regiseter_uprobe_event' and insert trace_uprobe to probe_list. regiseter_uprobe_event() initialize the 'trace_uprobe' struct's member 'trace_event_call' and call trace_add_event_call(). trace_add_event_call() calls __register_event() and __add_event_to_tracers(), the later will create a directory and some files(enalbe, id..) in '/sys/kernel/debug/tracing/events/uprobes'. Anyway when writing to 'uprobe_events' we just setup the structure in trace framwork.

* When writing '/sys/kernel/debug/tracing/events/uprobes/p_test_0x64d/enable', trace_uprobe_register()->probe_event_enable()->uprobe_register(). uprobe_register calls alloc_uprobe() to allocate a 'struct uprobe' and in this struct we store the inode and offset and calls insert_uprobe() to insert this 'uprobe' to 'uprobes_tree' rb-tree. Then register_for_each_vma() will be called to insert breakpoint(0xcc) in the current running process virtual memory. 

* When the ELF which has uprobe got executed, the ELF's text file will be mmapped into the process address spaces and uprobe_mmap() will be called. In this function, build_probe_list() will be called to find all of the uprobe point and modify the process' virtual memory address's instruction to 0xcc.

* When the program execution arrive the 0xcc, it trigger an int3 exception. In do_int3() it calls notify_die(DIE_INT3). This will call the callbacks registered in 'die_chain'. In uprobe initialization function init_uprobes(), it registers 'uprobe_exception_nb', so arch_uprobe_exception_notify() will be called. uprobe_pre_sstep_notifier() will be called and set the thread flags with TIF_UPROBE. Before return to userspace exit_to_usermode_loop()->uprobe_notify_resume()->handle_swbp(), handle_swbp() will call the handler(handler_chain) and put thread to singlestep(pre_ssout).

* After execute the original instruction, the program triggers a singlestep. In do_debug(), it calls notify_me(DIE_DEBUG) and handle_singlestep() will be called.


<h3> tracepoint </h3>

<h4> tracepoint anatomy </h3>

Low linux kernel version has a standalone example of pure tracepoint, for example v3.8 has a example in samples/tracepoints directory. Of course it can't work in currently high version because currently the tracepoint has a more connection with the
tracer(ftrace) and together called 'trace event' which I will talk about it in the next post. 

The 'DECLARE_TRACE' and 'DEFINE_TRACE' is the key MACRO in tracepoint.

'DECLARE_TRACE' is defined as following:

                #define DECLARE_TRACE(name, proto, args)				\
                        __DECLARE_TRACE(name, PARAMS(proto), PARAMS(args),		\
                                        cpu_online(raw_smp_processor_id()),		\
                                        PARAMS(void *__data, proto),			\
                                        PARAMS(__data, args))


                #define __DECLARE_TRACE(name, proto, args, cond, data_proto, data_args) \
                        extern struct tracepoint __tracepoint_##name;			\
                        static inline void trace_##name(proto)				\
                        {								\
                                if (static_key_false(&__tracepoint_##name.key))		\
                                        __DO_TRACE(&__tracepoint_##name,		\
                                                TP_PROTO(data_proto),			\
                                                TP_ARGS(data_args),			\
                                                TP_CONDITION(cond), 0);			\
                                if (IS_ENABLED(CONFIG_LOCKDEP) && (cond)) {		\
                                        rcu_read_lock_sched_notrace();			\
                                        rcu_dereference_sched(__tracepoint_##name.funcs);\
                                        rcu_read_unlock_sched_notrace();		\
                                }							\
                        }								\
                        __DECLARE_TRACE_RCU(name, PARAMS(proto), PARAMS(args),		\
                                PARAMS(cond), PARAMS(data_proto), PARAMS(data_args))	\
                        static inline int						\
                        register_trace_##name(void (*probe)(data_proto), void *data)	\
                        {								\
                                return tracepoint_probe_register(&__tracepoint_##name,	\
                                                                (void *)probe, data);	\
                        }								\
                        static inline int						\
                        register_trace_prio_##name(void (*probe)(data_proto), void *data,\
                                                int prio)				\
                        {								\
                                return tracepoint_probe_register_prio(&__tracepoint_##name, \
                                                        (void *)probe, data, prio); \
                        }								\
                        static inline int						\
                        unregister_trace_##name(void (*probe)(data_proto), void *data)	\
                        {								\
                                return tracepoint_probe_unregister(&__tracepoint_##name,\
                                                                (void *)probe, data);	\
                        }								\
                        static inline void						\
                        check_trace_callback_type_##name(void (*cb)(data_proto))	\
                        {								\
                        }								\
                        static inline bool						\
                        trace_##name##_enabled(void)					\
                        {								\
                                return static_key_false(&__tracepoint_##name.key);	\
                        }

A tracepoint is represent by a 'struct tracepoint', the 

                'extern struct tracepoint __tracepoint_##name'

means there will be a 'tracepoint' definition. In fact it is defined by 'DEFINE_TRACE' MACRO.

                struct tracepoint {
                        const char *name;		/* Tracepoint name */
                        struct static_key key;
                        int (*regfunc)(void);
                        void (*unregfunc)(void);
                        struct tracepoint_func __rcu *funcs;
                };

'key' is used to determine if the tracepoint is enabled. 'funcs' is the array of function in this tracepoint will call.
'regfunc' is the callback before we add function to tracepoint. 

Here we see the definition of 'trace_##name' function, this is what we used in our code.

'register_trace_##name' function will call 'tracepoint_probe_register' to register our 'tracepoint' to system. 'tracepoint_add_func' will be used to do the real work.

                static int tracepoint_add_func(struct tracepoint *tp,
                                        struct tracepoint_func *func, int prio)
                {
                        struct tracepoint_func *old, *tp_funcs;
                        int ret;

                        if (tp->regfunc && !static_key_enabled(&tp->key)) {
                                ret = tp->regfunc();
                                if (ret < 0)
                                        return ret;
                        }

                        tp_funcs = rcu_dereference_protected(tp->funcs,
                                        lockdep_is_held(&tracepoints_mutex));
                        old = func_add(&tp_funcs, func, prio);
                        if (IS_ERR(old)) {
                                WARN_ON_ONCE(1);
                                return PTR_ERR(old);
                        }

                        /*
                        * rcu_assign_pointer has a smp_wmb() which makes sure that the new
                        * probe callbacks array is consistent before setting a pointer to it.
                        * This array is referenced by __DO_TRACE from
                        * include/linux/tracepoints.h. A matching smp_read_barrier_depends()
                        * is used.
                        */
                        rcu_assign_pointer(tp->funcs, tp_funcs);
                        if (!static_key_enabled(&tp->key))
                                static_key_slow_inc(&tp->key);
                        release_probes(old);
                        return 0;
                }

As we can see it just add 'func' to 'tp->funcs', it will be ordered by the 'prio'(in func_add).


Now let's look at the 'DEFINE_TRACE' MACRO.


                #define DEFINE_TRACE_FN(name, reg, unreg)				 \
                        static const char __tpstrtab_##name[]				 \
                        __attribute__((section("__tracepoints_strings"))) = #name;	 \
                        struct tracepoint __tracepoint_##name				 \
                        __attribute__((section("__tracepoints"))) =			 \
                                { __tpstrtab_##name, STATIC_KEY_INIT_FALSE, reg, unreg, NULL };\
                        static struct tracepoint * const __tracepoint_ptr_##name __used	 \
                        __attribute__((section("__tracepoints_ptrs"))) =		 \
                                &__tracepoint_##name;

                #define DEFINE_TRACE(name)						\
                        DEFINE_TRACE_FN(name, NULL, NULL);


So here we can see the 'struct tracepoint' has been defined and is stored in '__tracepoints' section.

Now that we know the create of 'strcut tracepoint' let's see what happend when we call 'trace_##name'. It will 
call __DO_TRACE.

                        static inline void trace_##name(proto)				\
                        {								\
                                if (static_key_false(&__tracepoint_##name.key))		\
                                        __DO_TRACE(&__tracepoint_##name,		\
                                                TP_PROTO(data_proto),			\
                                                TP_ARGS(data_args),			\
                                                TP_CONDITION(cond), 0);			\
                                if (IS_ENABLED(CONFIG_LOCKDEP) && (cond)) {		\
                                        rcu_read_lock_sched_notrace();			\
                                        rcu_dereference_sched(__tracepoint_##name.funcs);\
                                        rcu_read_unlock_sched_notrace();		\
                                }							\
                        }


                #define __DO_TRACE(tp, proto, args, cond, rcucheck)			\
                        do {								\
                                struct tracepoint_func *it_func_ptr;			\
                                void *it_func;						\
                                void *__data;						\
                                                                                        \
                                if (!(cond))						\
                                        return;						\
                                if (rcucheck) {						\
                                        if (WARN_ON_ONCE(rcu_irq_enter_disabled()))	\
                                                return;					\
                                        rcu_irq_enter_irqson();				\
                                }							\
                                rcu_read_lock_sched_notrace();				\
                                it_func_ptr = rcu_dereference_sched((tp)->funcs);	\
                                if (it_func_ptr) {					\
                                        do {						\
                                                it_func = (it_func_ptr)->func;		\
                                                __data = (it_func_ptr)->data;		\
                                                ((void(*)(proto))(it_func))(args);	\
                                        } while ((++it_func_ptr)->func);		\
                                }							\
                                rcu_read_unlock_sched_notrace();			\
                                if (rcucheck)						\
                                        rcu_irq_exit_irqson();				\
                        } while (0)


It will call the functions in 'tp->funcs' array.

So here we have a tracepoint framework, the only is to add 'function' to 'tp->funcs', this is call 'probe' function. In the old days, we can use another kernel module to do this. However nowdays the tracepoint is tied with ftrace and called 'trace event'.

Next post will talk about how 'trace event' work.


