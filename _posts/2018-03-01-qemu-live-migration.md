---
layout: post
title: "qemu热迁移简介"
description: "qemu热迁移"
category: 技术
tags: [QEMU]
---
{% include JB/setup %}


<h3> 热迁移的用法 </h3>

虚拟化环境中热迁移的好处是很明显的，所以QEMU/KVM在很早就支持了热迁移。
首先我们来看一下热迁移是怎么用的。按照官网[指示](https://www.linux-kvm.org/page/Migration)，一般来说需要迁移的src和dst同时访问虚拟机镜像，这里为了简单起见，我们只是在两台host使用同一个虚拟机镜像。

在src启动一个虚拟机vm1：

    qemu-system-x86_64  -m 2048   -hda centos.img  -vnc :0 --enable-kvm

在dst启动另一个虚拟机vm2：

    qemu-system-x86_64  -m 2048   -hda centos.img  -vnc :0 --enable-kvm -incoming tcp:0:6666

在vm1的的monitor里面输入:

    migrate tcp:$ip:6666

隔了十几秒可以看到vm2已经成为了vm1的样子，vm1处于stop状态。

<h3> 热迁移的基本原理 </h3>

![](/assets/img/qemulm/1.png)

首先看看热迁移过程中qemu的哪些部分会包含进来。上图中间的灰色部分是虚拟机的内存，它对于qemu来说是完全的黑盒，qemu不会做任何假设，而只是一股脑儿的发送到dst。左边的区域是表示的设备状态，这部分是虚拟机可见的，qemu使用自己的协议来发送这部分。右边的是不会迁移的部分，但是还是将dst和src保持一致，所以一般来说，src和dst的虚拟机使用相同的qemu command line能够保证这部分一致。

需要满足很多条件才能进行热迁：

    1. 使用共享存储，如NFS
    2. host的时间要一致
    3. 网络配置要一致，不能说src能访问某个网络，dst不能
    4. host CPU类型要一致，毕竟host导出指令集给guest
    5. 虚拟机的机器类型，QEMU版本，rom版本等

热迁移主要包括三个步骤：

    1. 将虚拟机所有RAM设置成dirty，主要函数:ram_save_setup
    2. 持续迭代将虚拟机的dirty RAM page发送到dst，直到达到一定条件，不如dirty page数量比较少, 主要函数:ram_save_iterate
    3. 停止src上面的guest，把剩下的dirty RAM发送到dst，之后发送设备状态，主要函数: qemu_savevm_state_complete_precopy

其中步骤1和步骤2是上图中的灰色区域，步骤3是灰色和左边的区域。

之后就可以在dst上面继续运行qemu程序了。

<h3> 发送端源码分析 </h3>

在qemu的monitor输入migrate命令后，经过的一些函数：

    hmp_migrate
      ->qmp_migrate
          ->tcp_start_outgoing_migration
              ->socket_start_outgoing_migration
                  ->socket_outgoing_migration
                      ->migration_channel_connect
                          ->qemu_fopen_channel_output
                          ->migrate_fd_connect

最后这个函数就重要了，创建了一个迁移线程，线程函数为migration\_thread
        
    void migrate_fd_connect(MigrationState *s)
    {
        xxx 

        qemu_thread_create(&s->thread, "migration", migration_thread, s,
                        QEMU_THREAD_JOINABLE);
        s->migration_thread_running = true;
    }


    static void *migration_thread(void *opaque)
    {

        xxx
        qemu_savevm_state_begin(s->to_dst_file, &s->params);

        xxx
        while (s->state == MIGRATION_STATUS_ACTIVE ||
            s->state == MIGRATION_STATUS_POSTCOPY_ACTIVE) {
            xxx
            if (!qemu_file_rate_limit(s->to_dst_file)) {
                uint64_t pend_post, pend_nonpost;

                qemu_savevm_state_pending(s->to_dst_file, max_size, &pend_nonpost,
                                        &pend_post);
                xxx
                if (pending_size && pending_size >= max_size) {
                    xxx
                    /* Just another iteration step */
                    qemu_savevm_state_iterate(s->to_dst_file, entered_postcopy);
                } else {
                    migration_completion(s, current_active_state,
                                        &old_vm_running, &start_time);
                    break;
                }
            }

            xxx
    }


migration\_thread主要就是用来完成之前提到的热迁移三个步骤。
首先来看第一个步骤，qemu\_savevm\_state\_begin标记所有RAM为dirty:

    qemu_savevm_state_begin
    -->ram_save_setup
        -->ram_save_init_globals
                -->bitmap_new
                -->bitmap_set


接着看第二个步骤，由migration\_thread中的while循环中的两个函数完成:
qemu\_savevm\_state\_pending和qemu\_savevm\_state\_iterate。

第一个函数通过调用回调函数ram\_save\_pending确定还要传输的字节数，比较简单。
第二个函数通过调用回调函数ram\_save\_iterate用来把dirty传到dst上面。

ram_save_iterate
  -->ram_find_and_save_block
       -->find_dirty_block
       -->ram_save_host_page
            -->ram_save_target_page
                 -->migration_bitmap_clear_dirty
                 -->ram_save_page
                      -->qemu_put_buffer_async
                          -->...->qemu_fflush
                                  -->...->send


在while循环中反复调用ram\_save\_pending和ram\_save\_iterate不停向dst发送虚拟机脏页，直到达到一定的条件，然后进入第三个步骤。


第三个步骤就是在migration\_thread中调用migration\_completion，在这一步中会停止src虚拟机，然后把最后剩的一点脏页拷贝到dst去。


    migration_completion
    -->vm_stop_force_state
    -->bdrv_inactivate_all
    -->qemu_savevm_state_complete_precopy
        -->ram_save_complete
                -->ram_find_and_save_block

可以看到最后一个函数跟第二个阶段传输脏页一样了。


<h3>接收端源码分析</h3>

接收端的qemu运行参数跟发送端的一样，但是多了一个参数-incoming tcp:0:6666, qemu在解析到-incoming后，就会等待src迁移过来，我们来看看这个流程。

main
  -->qemu_start_incoming_migration
       -->tcp_start_incoming_migration
            -->socket_start_incoming_migration
                 -->socket_accept_incoming_migration
                      -->migration_channel_process_incoming
                           -->qemu_fopen_channel_input
                           -->migration_fd_process_incoming
                                -->process_incoming_migration_co
                                     -->qemu_loadvm_state
                                     ..->bdrv_invalidate_cache_all

process\_incoming\_migration\_co函数用来完成接收数据，恢复虚拟机的运行。最重要的是qemu\_loadvm\_state，用于接收数据，在dst重构虚拟机。

    int qemu_loadvm_state(QEMUFile *f)
    {
        xxx  检查版本

        ret = qemu_loadvm_state_main(f, mis);
        
        xxx
        cpu_synchronize_all_post_init();

        return ret;
    }


显然，qemu\_loadvm\_state\_main是构建虚拟机的主要函数。

    static int qemu_loadvm_state_main(QEMUFile *f, MigrationIncomingState *mis)
    {
        uint8_t section_type;
        int ret = 0;

        while ((section_type = qemu_get_byte(f)) != QEMU_VM_EOF) {
            ret = 0;
            trace_qemu_loadvm_state_section(section_type);
            switch (section_type) {
            case QEMU_VM_SECTION_START:
            case QEMU_VM_SECTION_FULL:
                ret = qemu_loadvm_section_start_full(f, mis);
                if (ret < 0) {
                    goto out;
                }
                break;
            case QEMU_VM_SECTION_PART:
            case QEMU_VM_SECTION_END:
                ret = qemu_loadvm_section_part_end(f, mis);
                if (ret < 0) {
                    goto out;
                }
                break;
            case QEMU_VM_COMMAND:
                ret = loadvm_process_command(f);
                trace_qemu_loadvm_state_section_command(ret);
                if ((ret < 0) || (ret & LOADVM_QUIT)) {
                    goto out;
                }
                break;
            default:
                error_report("Unknown savevm section type %d", section_type);
                ret = -EINVAL;
                goto out;
            }
        }

    out:
        if (ret < 0) {
            qemu_file_set_error(f, ret);
        }
        return ret;
    }

qemu\_loadvm\_state\_main在一个循环里面处理各个section, src会把QEMU\_VM\_SECTION\_START等标志放到流中。

    qemu_loadvm_section_start_full
      -->find_se
      -->vmstate_load
           -->ram_load
                -->qemu_get_buffer

最后一个函数负责把接收到的数据拷贝到dst这端虚拟机内存上。
本文就是对热迁移的简单分析，后面会对一些具体的问题进行分析。

<h3>参考</h3>

Amit Shah: [Live Migrating QEMU-KVM Virtual Machines](https://developers.redhat.com/blog/2015/03/24/live-migrating-qemu-kvm-virtual-machines/)