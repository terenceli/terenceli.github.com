---
layout: post
title: "How eBPF program connects with tracepoint"
description: "Linux tracing"
category: 技术
tags: [内核, trace]
---
{% include JB/setup %}

In the last post [Linux tracing - trace event framework](https://terenceli.github.io/%E6%8A%80%E6%9C%AF/2020/08/08/trace-event-framework) I have discussed the internal of trace event. Now it's time to look at how the trace event connects with eBPF program.


<h3> trace event under perf </h3>

When we define perf subsystem, the 'TRACE_EVENT' will be defined as following, also the 'even

                include/trace/perf.h
                #undef DECLARE_EVENT_CLASS
                #define DECLARE_EVENT_CLASS(call, proto, args, tstruct, assign, print)	\
                static notrace void							\
                perf_trace_##call(void *__data, proto)					\
                {									\
                        struct trace_event_call *event_call = __data;			\
                        struct trace_event_data_offsets_##call __maybe_unused __data_offsets;\
                        struct trace_event_raw_##call *entry;				\
                        struct pt_regs *__regs;						\
                        u64 __count = 1;						\
                        struct task_struct *__task = NULL;				\
                        struct hlist_head *head;					\
                        int __entry_size;						\
                        int __data_size;						\
                        int rctx;							\
                                                                                        \
                        __data_size = trace_event_get_offsets_##call(&__data_offsets, args); \
                                                                                        \
                        head = this_cpu_ptr(event_call->perf_events);			\
                        if (!bpf_prog_array_valid(event_call) &&			\
                        __builtin_constant_p(!__task) && !__task &&			\
                        hlist_empty(head))						\
                                return;							\
                                                                                        \
                        __entry_size = ALIGN(__data_size + sizeof(*entry) + sizeof(u32),\
                                        sizeof(u64));				\
                        __entry_size -= sizeof(u32);					\
                                                                                        \
                        entry = perf_trace_buf_alloc(__entry_size, &__regs, &rctx);	\
                        if (!entry)							\
                                return;							\
                                                                                        \
                        perf_fetch_caller_regs(__regs);					\
                                                                                        \
                        tstruct								\
                                                                                        \
                        { assign; }							\
                                                                                        \
                        perf_trace_run_bpf_submit(entry, __entry_size, rctx,		\
                                                event_call, __count, __regs,		\
                                                head, __task);			\
                }


As we know this is very like the 'probe' function of 'trace_event_class's probe function 'trace_event_raw_event_##call'. In fact, the 'trace_event_class' has a 'perf_probe' callback and it will be assigned with 'perf_trace_##call'. 

                include/trace/trace_events.h
                #ifdef CONFIG_PERF_EVENTS

                #define _TRACE_PERF_PROTO(call, proto)					\
                        static notrace void						\
                        perf_trace_##call(void *__data, proto);

                #define _TRACE_PERF_INIT(call)						\
                        .perf_probe		= perf_trace_##call,


                static struct trace_event_class __used __refdata event_class_##call = { \
                        .system			= TRACE_SYSTEM_STRING,			\
                        .define_fields		= trace_event_define_fields_##call,	\
                        .fields			= LIST_HEAD_INIT(event_class_##call.fields),\
                        .raw_init		= trace_event_raw_init,			\
                        .probe			= trace_event_raw_event_##call,		\
                        .reg			= trace_event_reg,			\
                        _TRACE_PERF_INIT(call)						\
                };


When the userspace calls 'perf_event_open' syscall and specify a tracepoint to monitor it will call 'tp_event->class->reg' callback with 'TRACE_REG_PERF_REGISTER'. This callback(trace_event_reg) will call 'tracepoint_probe_register' with the 'call->class->perf_probe' to add the 'perf_trace_##call' to the 'tracepoint's funcs member. 


                kernel/trace/trace_event_perf.c:perf_trace_event_reg
                tp_event->class->reg(tp_event, TRACE_REG_PERF_REGISTER, NULL);

                kernel/trace/trace_events.c
                int trace_event_reg(struct trace_event_call *call,
                                enum trace_reg type, void *data)
                {
                        struct trace_event_file *file = data;

                        WARN_ON(!(call->flags & TRACE_EVENT_FL_TRACEPOINT));
                        switch (type) {
                        case TRACE_REG_REGISTER:
                                return tracepoint_probe_register(call->tp,
                                                                call->class->probe,
                                                                file);
                        case TRACE_REG_UNREGISTER:
                                tracepoint_probe_unregister(call->tp,
                                                        call->class->probe,
                                                        file);
                                return 0;

                #ifdef CONFIG_PERF_EVENTS
                        case TRACE_REG_PERF_REGISTER:
                                return tracepoint_probe_register(call->tp,
                                                                call->class->perf_probe,
                                                                call);
                        case TRACE_REG_PERF_UNREGISTER:
                                tracepoint_probe_unregister(call->tp,
                                                        call->class->perf_probe,
                                                        call);
                                return 0;
                        case TRACE_REG_PERF_OPEN:
                        case TRACE_REG_PERF_CLOSE:
                        case TRACE_REG_PERF_ADD:
                        case TRACE_REG_PERF_DEL:
                                return 0;
                #endif
                        }
                        return 0;
                }

When the 'trace_xxx_xxx' is called, the 'tracepoint's funcs will be called, so 'perf_trace_##call' will be called. In 'perf_trace_##call' function, the perf subsys will allocate buffer and call 'perf_trace_run_bpf_submit' to commit the buffer. Here will call the 'trace_call_bpf' to run the eBPF program.

                void perf_trace_run_bpf_submit(void *raw_data, int size, int rctx,
                                        struct trace_event_call *call, u64 count,
                                        struct pt_regs *regs, struct hlist_head *head,
                                        struct task_struct *task)
                {
                        if (bpf_prog_array_valid(call)) {
                                *(struct pt_regs **)raw_data = regs;
                                if (!trace_call_bpf(call, raw_data) || hlist_empty(head)) {
                                        perf_swevent_put_recursion_context(rctx);
                                        return;
                                }
                        }
                        perf_tp_event(call->event.type, count, raw_data, size, regs, head,
                                rctx, task);
                }


<h3> Connect eBPF program with tracepoint </h3>

When the userspace calls 'ioctl(PERF_EVENT_IOC_SET_BPF)', 'perf_event_set_bpf_prog' will be used to handle this request. 'perf_event_attach_bpf_prog' then called. 


                int perf_event_attach_bpf_prog(struct perf_event *event,
                                        struct bpf_prog *prog)
                {
                        struct bpf_prog_array __rcu *old_array;
                        struct bpf_prog_array *new_array;
                        int ret = -EEXIST;

                        mutex_lock(&bpf_event_mutex);

                        if (event->prog)
                                goto unlock;

                        old_array = event->tp_event->prog_array;
                        if (old_array &&
                        bpf_prog_array_length(old_array) >= BPF_TRACE_MAX_PROGS) {
                                ret = -E2BIG;
                                goto unlock;
                        }

                        ret = bpf_prog_array_copy(old_array, NULL, prog, &new_array);
                        if (ret < 0)
                                goto unlock;

                        /* set the new array to event->tp_event and set event->prog */
                        event->prog = prog;
                        rcu_assign_pointer(event->tp_event->prog_array, new_array);
                        bpf_prog_array_free(old_array);

                unlock:
                        mutex_unlock(&bpf_event_mutex);
                        return ret;
                }

This is quite trivial as it just add the eBPF program to 'event->tp_event->prog_array'. Here 'tp_event' is 'struct trace_event_call'.

When 'perf_trace_run_bpf_submit' calls 'trace_call_bpf', this eBPF program will be called. The '*(struct pt_regs **)raw_data = regs;' is quite strange.
This commit [perf, bpf: allow bpf programs attach to tracepoints](https://github.com/torvalds/linux/commit/98b5c2c65c2951772a8fc661f50d675e450e8bce) explain what this is for. We should also notice if 'trace_call_bpf' return non-zero value, the origin 'perf_tp_event' will be called and the event data will be copy to the perf subsystem buffer. 

                kernel/events/core.c
                void perf_trace_run_bpf_submit(void *raw_data, int size, int rctx,
                                        struct trace_event_call *call, u64 count,
                                        struct pt_regs *regs, struct hlist_head *head,
                                        struct task_struct *task)
                {
                        if (bpf_prog_array_valid(call)) {
                                *(struct pt_regs **)raw_data = regs;
                                if (!trace_call_bpf(call, raw_data) || hlist_empty(head)) {
                                        perf_swevent_put_recursion_context(rctx);
                                        return;
                                }
                        }
                        perf_tp_event(call->event.type, count, raw_data, size, regs, head,
                                rctx, task);
                }

                kernel/trace/bpf_trace.c
                unsigned int trace_call_bpf(struct trace_event_call *call, void *ctx)
                {
                        unsigned int ret;

                        if (in_nmi()) /* not supported yet */
                                return 1;

                        preempt_disable();
                        ...
                        ret = BPF_PROG_RUN_ARRAY_CHECK(call->prog_array, ctx, BPF_PROG_RUN);

                out:
                        __this_cpu_dec(bpf_prog_active);
                        preempt_enable();

                        return ret;
                }


                include/linux/bpf.h
                #define __BPF_PROG_RUN_ARRAY(array, ctx, func, check_non_null)	\
                        ({						\
                                struct bpf_prog **_prog, *__prog;	\
                                struct bpf_prog_array *_array;		\
                                u32 _ret = 1;				\
                                rcu_read_lock();			\
                                _array = rcu_dereference(array);	\
                                if (unlikely(check_non_null && !_array))\
                                        goto _out;			\
                                _prog = _array->progs;			\
                                while ((__prog = READ_ONCE(*_prog))) {	\
                                        _ret &= func(__prog, ctx);	\
                                        _prog++;			\
                                }					\
                _out:							\
                                rcu_read_unlock();			\
                                _ret;					\
                        })

                #define BPF_PROG_RUN_ARRAY(array, ctx, func)		\
                        __BPF_PROG_RUN_ARRAY(array, ctx, func, false)

                #define BPF_PROG_RUN_ARRAY_CHECK(array, ctx, func)	\
                        __BPF_PROG_RUN_ARRAY(array, ctx, func, true)
