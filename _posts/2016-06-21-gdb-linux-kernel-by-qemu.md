---
layout: post
title: "通过QEMU调试Linux内核"
description: "qemu调试Linux内核"
category: 技术
tags: [虚拟化,QEMU,内核]
---
{% include JB/setup %}


<h3>前言</h3>

相信从Windows内核转到Linux内核的人最开始都会对Windows的内核调试机制非常怀念，在Linux的远古时代调试内核是非常不方便的，或者需要打kgdb的补丁，或者多用用printk也能把问题解决了。当我刚开始接触虚拟化的时候就意识到这绝对是双机调试的绝佳场景，果然很快就在网上找到了通过QEMU调试Linux内核的文章。之前由于种种原因一直没有时间和机会尝试，最近终于下定决心搞定他，开始折腾了几天。鉴于网上的材料千篇一律，并且很多的坑都没有提到，写了这篇文章，希望能够帮助有需要的人。我对于QEMU和KVM还是区分得很开的，QEMU是虚拟化软件，KVM是内核模块用于QEMU的加速，代码的native执行。文中提到的QEMU虚拟机默认都是用了KVM加速的。

本文环境：

	VMWare中的一台CentOS 7 x64作为宿主机
	QEMU虚拟机是CentOS 6.7 x64
	虚拟机内核源码版本：3.18.35

文末提供了使用的内核模块源码，最简单的hello world Linux驱动版。

<h3>虚拟机创建</h3>

为了简单起见，使用libvirt的方式安装虚拟化环境

	yum install qemu-kvm qemu-img virt-manager libvirt libvirt-python libvirt-client virt-install virt-viewer

接着使用virt-manager创建虚拟机。

在创建好虚拟机之后,在[内核官网](https://www.kernel.org/)下载内核源码，我用的版本是3.18.35，修改根目录下面的Makefile文件
将617行"-O3"改为"-O1"。当然，-O0是最好的，但是如[此文](http://www.ibm.com/developerworks/cn/linux/1508_zhangdw_gdb/index.html)中所说，-O0有一个bug，3.18.35版本也是编译会出问题。

	ifdef CONFIG_CC_OPTIMIZE_FOR_SIZE
	KBUILD_CFLAGS	+= -Os $(call cc-disable-warning,maybe-uninitialized,)
	else
	KBUILD_CFLAGS	+= -O1//修改此处

之后更换虚拟机中的内核,注意KGDB的配置，似乎是默认就有的。

	make menuconfig
	make 
	make modules_install
	make install

这样就替换了QEMU虚拟机中的内核了。

<h3>修改虚拟机配置文件</h3>

为了支持qemu虚拟机调试，需要通过libvirt传递命令行参数给qemu进程。
具体如下修改：
使用virsh list从第二列得到虚拟机名字，通过virsh edit <vm_name>即可修改虚拟机配置文件。
注意修改主要是两处：

	<domain type='kvm' xmlns:qemu='http://libvirt.org/schemas/domain/qemu/1.0'>

这是通过libvirt向qemu传递参数所必须的。

在最后一个节点devices之后添加qemu:commandline节点，注意一定要在最后。

	 <qemu:commandline>
	    <qemu:arg value='-S'/>
	    <qemu:arg value='-gdb'/>
	    <qemu:arg value='tcp::1234'/>
	  </qemu:commandline>

<h3>调试QEMU虚拟机模块</h3>

首先需要在宿主机的创建一个与虚拟机中目录一样的Linux内核代码树，为了方便，虚拟机中内核源码在/root/linux-3.18.35目录下，可以直接使用：
	
	scp -r linux-3.18.35 root@192.168.122.1:/root

这样，虚拟机就和宿主机中的访问路径一样了，对于内核模块同样如此。

在宿主机中启动gdb，监听端口，在virt-manager中开启虚拟机，可以看到虚拟机被断下来了，在这里先讨论模块的调试，因为内核的调试还有坑，后面再谈，直接c运行虚拟机。

	[root@localhost gdb]# ./gdb ~/linux-3.18.35/vmlinux
	GNU gdb (GDB) 7.9
	Copyright (C) 2015 Free Software Foundation, Inc.
	License GPLv3+: GNU GPL version 3 or later <http://gnu.org/licenses/gpl.html>
	This is free software: you are free to change and redistribute it.
	There is NO WARRANTY, to the extent permitted by law.  Type "show copying"
	and "show warranty" for details.
	This GDB was configured as "x86_64-unknown-linux-gnu".
	Type "show configuration" for configuration details.
	For bug reporting instructions, please see:
	<http://www.gnu.org/software/gdb/bugs/>.
	Find the GDB manual and other documentation resources online at:
	<http://www.gnu.org/software/gdb/documentation/>.
	For help, type "help".
	Type "apropos word" to search for commands related to "word"...
	Reading symbols from /root/linux-3.18.35/vmlinux...done.
	(gdb) target remote localhost:1234
	Remote debugging using localhost:1234
	0x0000000000000000 in irq_stack_union ()
	(gdb) 



当使用ctrl-c断下虚拟机时，可能会出现
	
	Remote 'g' packet reply is too long

可以在[这里](https://sourceware.org/bugzilla/show_bug.cgi?id=13984)找到一个patch，打上就好了。

在do\_init\_module下断点之后，在虚拟机中insmod poc.ko，可以看到虚拟机已经被断下来了，参数mod->sect_attrs->attrs放的是各个section的信息，在这个hello world的驱动中，只有.text信息，并没有.bss和.data，我们需要将这些信息提供给gdb。使用如下命令即可：

	add-symbol-file xxx.ko <text addr> -s .data <data addr> -s .bss <bss addr>

之后就可以在模块中进行单步调试了。整个过程如下：

	^C
	Program received signal SIGINT, Interrupt.
	default_idle () at arch/x86/kernel/process.c:316
	warning: Source file is more recent than executable.
	316		trace_cpu_idle_rcuidle(PWR_EVENT_EXIT, smp_processor_id());
	(gdb) b do_init_module
	Breakpoint 1 at 0xffffffff810c5c0e: file kernel/module.c, line 3043.
	(gdb) c
	Continuing.
	
	Breakpoint 1, do_init_module (mod=0xffffffffa02010e0) at kernel/module.c:3043
	warning: Source file is more recent than executable.
	3043		current->flags &= ~PF_USED_ASYNC;
	(gdb) p /x  mod->sect_attrs->attrs[1]->address 
	$1 = 0xffffffffa0201000
	(gdb) add-symbol-file ~/hello/poc.ko 0xffffffffa0201000
	add symbol table from file "/root/hello/poc.ko" at
		.text_addr = 0xffffffffa0201000
	(y or n) y
	Reading symbols from /root/hello/poc.ko...done.
	(gdb) b hello_init 
	Breakpoint 2 at 0xffffffffa020100d: file /root/hello/poc.c, line 7.
	(gdb) c
	Continuing.
	
	Breakpoint 2, hello_init () at /root/hello/poc.c:7
	7		struct task_struct *ts = current;
	(gdb) n
	p t8		printk("hello,world,%s\n",current->comm);
	(gdb) p ts
	$2 = (struct task_struct *) 0xffff88003c0b2190
	(gdb) p ts->pid
	$3 = 2629
	(gdb) p ts->comm
	$4 = "insmod\000erminal\000"
	(gdb) n
	9		ts = NULL;
	(gdb) n
	10		ts->pid=123;
	(gdb) p ts
	$5 = (struct task_struct *) 0x0 <irq_stack_union>
	(gdb) p ts->pid
	Cannot access memory at address 0x7f0
	(gdb) n

<h3>调试虚拟机内核</h3>

上面的过程是调试可加载模块的方法，很多文章都说直接在虚拟机连过来的时候b start_kernel就可以调试内核了，然而真实情况并不是，你会看到虚拟机根本不会在这个断点停留，也不会在内核代码中的其他断点停留。

找了好久终于在[这里](https://bugs.launchpad.net/ubuntu/+source/qemu-kvm/+bug/901944)找到了答案，一句话：需要下硬件断点才行。之后就可以下软断点了。

	(gdb) target remote localhost:1234
	Remote debugging using localhost:1234
	0x0000000000000000 in irq_stack_union ()
	(gdb) hb start_kernel//硬件断点
	Hardware assisted breakpoint 1 at 0xffffffff81b40044: file init/main.c, line 501.
	(gdb) c
	Continuing.
	
	Breakpoint 1, start_kernel () at init/main.c:501
	warning: Source file is more recent than executable.
	501	{
	(gdb) n
	510		set_task_stack_end_magic(&init_task);
	(gdb) n
	511		smp_setup_processor_id();
	(gdb) p init_task
	$1 = {state = 0, stack = 0xffffffff81a00000 <init_thread_union>, usage = {
	...
	(gdb) b security_init
	Breakpoint 2 at 0xffffffff81b6ff8a: file security/security.c, line 67.
	(gdb) c
	Continuing.
	
	Breakpoint 2, security_init () at security/security.c:67
	warning: Source file is more recent than executable.
	67		printk(KERN_INFO "Security Framework initialized\n");
	(gdb) 

使用的hello world Linux驱动源码
	
	#include <linux/init.h>
	#include <linux/module.h>
	#include <linux/sched.h>
	
	static int hello_init(void)
	{
		struct task_struct *ts = current;
		printk("hello,world,%s\n",current->comm);
		ts = NULL;
		ts->pid=123;
		return 0;
	}
	
	static void hello_exit(void)
	{
		printk("goodbye,world\n");
	}
	
	module_init(hello_init);
	module_exit(hello_exit);

Makefile文件,注意-O0不优化

	obj-m := poc.o
	KDIR :=/lib/modules/$(shell uname -r)/build
	PWD := $(shell pwd)
	ccflags-y = -O0
	default:
		$(MAKE) -C $(KDIR) M=$(PWD) modules

<h3>注意事项</h3>

1. 宿主机和虚拟机中的目录要一致，内核和自己添加的模块都需要
2. gdb记得打补丁
3. 调试内核代码的时候最开始记得用硬件断点

<h3>参考</h3>

1. [使用 GDB 和 KVM 调试 Linux 内核与模块](http://www.ibm.com/developerworks/cn/linux/1508_zhangdw_gdb/index.html)
2. [How to pass QEMU command-line options through libvirt](http://blog.vmsplice.net/2011/04/how-to-pass-qemu-command-line-options.html)
3. [gdbserver inside qemu does not stop on breakpoints](https://bugs.launchpad.net/ubuntu/+source/qemu-kvm/+bug/901944)
4. [Bug 13984 - gdb stops controlling a thread after "Remote 'g' packet reply is too long: ..." error message](https://sourceware.org/bugzilla/show_bug.cgi?id=13984)