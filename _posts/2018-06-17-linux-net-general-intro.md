---
layout: post
title: "Linux kernel networking: a general introduction"
description: "Linux kernel"
category: 技术
tags: [Linux内核]
---
{% include JB/setup %}

Linux's networking is originated from the BSD's socket just like most of the Unix-like operating system, this is called TCP/IP  protocol. The TCP/IP protocol  stack contains four layer in concept. The top-most is application layer , then trasport layer , next IP layer and finally the data link layer. Linux networking protocol stack is very complicated, this article will just talk about the general architecture. The following articles will contain more details though I don't how much there will be.

As we know, there are lots of protocols in the kernel and also there are lots of physical network card in the world. The linux need to abstract the common code and also the special code for every protocol and device. So the function pointer is in everywhere of network subsystem, and actually in everywhere of Linux kernel.
Follwing pic shows the Linux core network architecture. 


      +--------------------------+
      |   system call interface  |
      +--------------------------+
    
    
    +------------------------------+
    | protocol agnostic interface  |
    +------------------------------+
    
    
    +------------------------------+
    |       network protocols      |
    +------+------+-------+--------+
    |      |      |       |        |
    | inet | dccp | sctp  | packet |
    |      |      |       |        |
    +------+------+-------+--------+
    
    
    +------------------------------+
    | device agnostic interface    |
    +------------------------------+
    
    
    +------------------------------+
    |       device drivers         |
    +------+------+-------+--------+
    |      |      |       |        |
    |e1000 | virtio vmxnet|  ...   |
    |      |      |       |        |
    +------+------+-------+--------+
    

### System call inteface

Easy to understand, all the Unix-like operating system have the same system call interface. The socket, bind, listen, accept, connect and some other system call are all available in all operating system. Also the socket is abstracted as a file descriptor and the usespace interact with the kernel with this fd. The 

### protocol agnostic interface

This is the struct 'sock', as the struct 'socket' connect with the VFS(fd) for the userspace, the  'sock' connects with the following protocols. 

### network protocols

Here defines a lot of network protocols, for example the IPV4 protocol stacks, the ipx, irda and the other directory in linux/net directory. And for every network protocol stack, there are a 'family' for example the ipv4 is 'inet\_family\_ops'. In the initialization, the kernel will add some protocols in the family, for example TCP/UDP.

### device agnostic interface

This layer connects the protocols to the various network devices. This contains the common interface for example the device driver can register the network card device using 'register\_netdevice', also it can send packet using 'dev\_queue\_xmit'. They are all not related with a specific protocol and specific network device.

### device driver

This layer is the physical networkcard device that does the finally send/receiver packet work. There are lots of network device driver in linux/drivers/net directory.

The next articles will discuss this general picture in more details. Stay hungry, stay foolish.

### reference

Anatomy of the Linux networking stack

    