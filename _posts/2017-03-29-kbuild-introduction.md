---
layout: post
title: "Linux内核编译系统kbuild简介"
description: "linux kernel"
category: 技术
tags: [Linux, 内核]
---
{% include JB/setup %}

* [前言](#第一节)
* [kbuild四个部分](#第二节)
* [实例](#第三节)

<h2 id="第一节"> 前言 </h2>

这篇文章并非原创，是偶然在linuxjournal上面看到的一篇[文章](http://www.linuxjournal.com/content/kbuild-linux-kernel-build-system?page=0,0)，感觉写得比较清晰，例子详尽，所以这里对文章进行简单整理，算是一个笔记。本文主要是关于kbuild的简单介绍，不会介绍linux内核的具体编译过程，以后机会单独写一篇。

Linux内核有一个神奇的地方，既可以用在大型集群上面，也可以用在小巧的嵌入式设备上。使用Linux的设备不论大小，都有一个共同的代码基，你看苹果就不行，OSX和iOS就是分开的。主要原因有两点，Linux有一个非常好的抽象层，以及构建系统允许有非常大的定制自由度。

Linux是一个mono类型的内核，所有的内核代码都位于内核空间。但是Linux也能够加载内核模块，在内核运行期间可以增加内核代码。所以在内核编译的时候就需要决定哪些东西需要编译进内核，哪些需要编译成模块。这就需要一个系统来管理了，这就是kbuild。



<h2 id="第二节"> kbuild的四个部分 </h2>

kbuild主要包括如下四个部分：

- <b>Config symbols</b>:编译选项，用来决定代码的条件编译以及决定哪些编译进内核，哪些编译成模块。
- <b>Kconfig files</b>:定义每一个config symbol的属性，比如其类型，描述和依赖等。程序需要使用Kconfig file生成一个菜单，比如make menuconfig生成的数据就是读取这个文件来生成的。
- <b>.config file</b>:存储每一个config symbol选择的值。可以手动修改或者使用make工具生成。
- <b>Makefiles</b>:这个就是普通的make工具了，用于指导源文件生成目标文件的过程，内核啊，内核模块啊。

下面对这四个部分进行详细介绍。

<h3><b> Configuration Symbols </b></h3>

Configuration Symbols用来决定哪些特性或者模块将会被编译进内核。最常见的是两种编译选项，boolean和tristate，其不同之处只是可以取的值不同。boolean symbols可以取两种值:true/false，就是开关。tristate可以取三种值，yes/no/module。

内核中的很多选项都需要一个开关，而不是module，比如对SMP或者preemption的支持，必须要在内核编译时候就决定好，这个时候就用boolean config symbol就行了。很多设备驱动可以在之后加入内核，这个时候使用tristate config symbol，决定是编译进内核呢，还是模块，还是压根就不编译。


其他config symbol包括strings和hex，但是这些不常用，此处从略。

<h3><b> Kconfig Files </b></h3>

Configuration symbols是定义在Kconfig file中的，每一个Kconfig file可以描述任意数量的symbols，也可以使用include包含其他Kconfig file。内核编译工具如，make menuconfig读取这些文件生成一个树形结构。内核中的每一个目录都有一个Kconfig，并且它们包含自己子目录的Kconfig file，内核根目录树下面有一个Kconfig。menuconfig/gconfig就从根目录下的Kconfig开始，递归读取。

下面是arc/x86下的Kconfig节选：

	# Select 32 or 64 bit
	config 64BIT
		bool "64-bit kernel" if ARCH = "x86"
		default ARCH != "i386"
		---help---
		  Say yes to build a 64-bit kernel - formerly known as x86_64
		  Say no to build a 32-bit kernel - formerly known as i386
	
	config X86_32
		def_bool y
		depends on !64BIT
		# Options that are inherently 32-bit kernel only:
		select ARCH_WANT_IPC_PARSE_VERSION
		select CLKSRC_I8253
		select CLONE_BACKWARDS
		select HAVE_AOUT
		select HAVE_GENERIC_DMA_COHERENT
		select MODULES_USE_ELF_REL
		select OLD_SIGACTION

<h3><b> .config File </b></h3>

所有的config symbol值都保存在.config文件中，每一次执行meuconfig都会讲变化写入该文件。.config是一个文本文件，所以可以直接手动修改。.config每一行都会表示一个config symbol的值，如果没有选就会注释掉。

	CONFIG_KVM_AMD=m
	# CONFIG_KVM_MMU_AUDIT is not set
	CONFIG_KVM_DEVICE_ASSIGNMENT=y
	CONFIG_VHOST_NET=m

<h3><b> Makefiles </b></h3>

Makefiles用来编译内核和模块，与Kconfig类似，每一个子目录都会有一个Makefile文件，
用来编译其下的文件。整个编译过程也是递归的，上一层的Makefile下降到子目录中，
然后编译。

<h2 id="第三节"> 实例 </h2>
本节中实现一个coin driver，把上面的东西实践一下。coin driver是一个char类型的driver，每次读随机返回正反面(tail/head)，并且有一个统计次数的可选项。

比如：

	test@ubuntu:~$ sudo cat /dev/coin
	tail
	test@ubuntu:~$ sudo cat /dev/coin
	head
	test@ubuntu:~$ sudo cat /dev/coin
	head
	test@ubuntu:~$ sudo cat /dev/coin
	head
	test@ubuntu:~$ sudo cat /dev/coin
	head
	test@ubuntu:~$ sudo cat /sys/kernel/debug/coin/stats
	head=14 tail=12
	test@ubuntu:~$ 


给内核增加一个模块，需要做三件事：

1. 把源文件放在相应的目录，比如对于wifi设备驱动就应该放在drivers/net/wireless
2. 更新文件所在目录的Kconfig
3. 更新文件所在的Makefile

在我们的例子中，coin是一个字符设备，所以coin.c可以放在drivers/char。

coin可以编译到内核中，也可以编译成模块，所以COIN这个config symbol应该是一个tristate(y/n/m)，COIN\_STAT这个config symbol用于决定是否显示统计信息，很明显，COIN\_STAT依赖于COIN，如果不定义COIN，定义COIN\_STAT并没有意义。

	$make menuconfig

我们选择将COIN为m，COIN\_STAT为y。之后在.config之中，会加上一个CONFIG_前缀。

	CONFIG_COIN=m
	CONFIG_COIN_STAT=y


	#define CONFIG_COIN_MODULE 1
	#define CONFIG_COIN_STAT 1

当编译的时候，会执行脚本读取Kconfig

	$ scripts/kconfig/conf Kconfig

生成一个头文件include/generated/autoconf.h，其中可以看到

	#define CONFIG_COIN_MODULE 1
	#define CONFIG_COIN_STAT 1

如果将COIN定义为y，则会有如下定义

	#define CONFIG_COIN 1

为了生成.ko，我们还需要再drivers/char/Makefile中添加如下：

	obj-$(CONFIG_COIN)    += coin.o

由于CONFIG\_COIN不是y就是m，所以coin.o会被添加到obj-y或者obj-m链表中。
这样例子就完成了。kbuild编译流程可以简单如下图所示。文末附上驱动代码，来自原文。

![](/assets/img/kbuild/1.jpg)

	#include <linux/kernel.h>
	#include <linux/module.h>
	#include <linux/fs.h>
	#include <linux/uaccess.h>
	#include <linux/device.h>
	#include <linux/random.h>
	#include <linux/debugfs.h>

	#define DEVNAME "coin"
	#define LEN  20
	enum values {HEAD, TAIL};

	struct dentry *dir, *file;
	int file_value;
	int stats[2] = {0, 0};
	char *msg[2] = {"head\n", "tail\n"};

	static int major;
	static struct class *class_coin;
	static struct device *dev_coin;

	static ssize_t r_coin(struct file *f, char __user *b,
						size_t cnt, loff_t *lf)
	{
			char *ret;
			u32 value = prandom_u32() % 2;
			ret = msg[value];
			stats[value]++;
			return simple_read_from_buffer(b, cnt,
										lf, ret,
										strlen(ret));
	}

	static struct file_operations fops = { .read = r_coin };

	#ifdef CONFIG_COIN_STAT
	static ssize_t r_stat(struct file *f, char __user *b,
							size_t cnt, loff_t *lf)
	{
			char buf[LEN];
			snprintf(buf, LEN, "head=%d tail=%d\n",
					stats[HEAD], stats[TAIL]);
			return simple_read_from_buffer(b, cnt,
										lf, buf,
										strlen(buf));
	}

	static struct file_operations fstat = { .read = r_stat };
	#endif

	int init_module(void)
	{
			void *ptr_err;
			major = register_chrdev(0, DEVNAME, &fops);
			if (major < 0)
					return major;

			class_coin = class_create(THIS_MODULE,
									DEVNAME);
			if (IS_ERR(class_coin)) {
					ptr_err = class_coin;
					goto err_class;
			}

			dev_coin = device_create(class_coin, NULL,
									MKDEV(major, 0),
									NULL, DEVNAME);
			if (IS_ERR(dev_coin))
					goto err_dev;

	#ifdef CONFIG_COIN_STAT
			dir = debugfs_create_dir("coin", NULL);
			file = debugfs_create_file("stats", 0644,
									dir, &file_value,
									&fstat);
	#endif

			return 0;
	err_dev:
			ptr_err = class_coin;
			class_destroy(class_coin);
	err_class:
			unregister_chrdev(major, DEVNAME);
			return PTR_ERR(ptr_err);
	}

	void cleanup_module(void)
	{
	#ifdef CONFIG_COIN_STAT
			debugfs_remove(file);
			debugfs_remove(dir);
	#endif

			device_destroy(class_coin, MKDEV(major, 0));
			class_destroy(class_coin);
			return unregister_chrdev(major, DEVNAME);
	}

	MODULE_LICENSE("GPL");


