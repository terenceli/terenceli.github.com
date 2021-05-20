---
layout: post
title: "hello world driver"
description: "driver"
category: 技术
tags: [内核]
---
{% include JB/setup %}


After several years kernel development, I still can't remember the templeate of driver. So I write this post.

<h3> Ubuntu </h3>

Install kernel header.

        apt install linux-headers-`uname -r`

hello.c

        #include <linux/module.h>
        #include <linux/init.h>

        MODULE_LICENSE("GPL");

        static int hello_init(void)
        {
            printk("Hello word\n");
            return 0;
        }


        static void hello_exit(void)
        {
            printk("Goodbye,Hello word\n");
        }

        module_init(hello_init);
        module_exit(hello_exit);

Makefile

        obj-m+=hello.o
        all:
            make -C /lib/modules/$(shell uname -r)/build/ M=$(shell pwd) modules
        clean:
            make -C /lib/modules/$(shell uname -r)/build/ M=$(shell pwd) clean


<h3> redhat </h3>

yum install kernel-devel-`uname -r`