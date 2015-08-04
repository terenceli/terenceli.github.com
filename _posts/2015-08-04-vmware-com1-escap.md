---
layout: post
title: "VMware COM1虚拟机逃逸漏洞分析"
description: "Escaping VMware Workstation through COM1"
category: 技术
tags: [exploit]
---
{% include JB/setup %}



本文是对谷歌的文章[Escaping VMware Workstation through COM1](https://docs.google.com/document/d/1sIYgqrytPK-CFWfqDntraA_Fwi2Ov-YBgMtl5hdrYd4/preview?sle=true)中提及的漏洞利用的分析。

##1. 背景简介

VMware为了方便，提供在虚拟机中打印文件并保存在宿主机中，默认将Microsoft XPS Document Writer作为打印机。COM1端口用于和Host的vprintproxy.exe进行交互。当Guest打印文件时，会将EMFSPOOL和EMF文件交给vprintproxy.exe进行处理，由于vprintproxy.exe的TPView.dll存在一个缓冲区漏洞，畸形构造的打印文件会导致vprintproxy.exe被控制，进而造成宿主机任意代码执行。

##2. 漏洞复现

环境：host win8.1, guest win7，VMWare 11.1.0 build-2496824，python版本为3.4.3。根据文档和分析，基本上只要TPView.dll为8.8.856.1版和iconv.dll为1.9.0.1版即可复现该漏洞。

工具：ida 6.5，x64dbg(这次用的是其32位版本x32dbg)

首先，看看正常的功能是怎么样的，在虚拟机中打开一个正常文件，选择下图所示的打印机，即可将虚拟机中的文档打印到宿主机中。


![](/assets/img/vmwarecom1/1.PNG)

在虚拟机中执行python.exe poc（[poc](/assets/file/vmwarecom1/poc)为谷歌文末给的代码），看到vprintproxy.exe成功创建了计算器进程，下图所示。

![](/assets/img/vmwarecom1/2.PNG)



##3. 总体分析

总体流程图如下图所示。

![](/assets/img/vmwarecom1/arch.PNG)

谷歌给的exp中与漏洞利用有关的主要是overflow部分和SHELLCODE部分。overflow负责淹没缓冲区以及布置各个gadget，大致分为2个部分，按照运行的流程分别叫做第一段和第二段。SHELLCODE则完成实际功能，可以是任何能够在win 8.1运行的shellcode。

第一段的首先4个字节（图中first eip）是覆盖ret控制eip的第一步，第一段的主要工作就是在0x1010ff00放置好VirtualAlloc - edi的差值,为0x00078c48，方便以后动态得到VirtualAlloc的地址，这里在漏洞触发点曝出的edi的值可以说是非常重要的。第一段还有一个作用就是将栈顶抬高到overflow前四个字节，然后去执行第二段。这里分两段的原因是第一段中由于触发漏洞需要有几个特殊的点布置特殊的数据，这些会跟first eip及之后的几个gadget的布局冲突。

第二段的主要工作就是动态得到VirtualAlloc的地址，分配0x10000个字节的可执行的内存区域，然后在0x40000000的前0xC个字节处布置特殊的指令，然后跳到0x40000000处执行。

0x40000000处将已经读入内存的SHELLCODE以及其他数据拷贝到0x40000010处开始的地址处，然后跳到0x40000200处执行，0x40000200经过一段nop指令后顺利滑到了SHELLCODE的地方。

由于整个进程地址空间实际只有1个iconv.dll为被随机化加载，如图4所示，可以利用的gadget非常不丰富，ROP的构造展现出了特别精妙的艺术。

![](/assets/img/vmwarecom1/3.PNG)

##4. 详细分析

###4.1 覆盖返回地址

在谷歌的文档中，我们知道溢出的位置是在距离TPView.dll加载基址0x48788处，根据实际加载的基址，我们找到溢出的位置在0x03208788处，x32dbg中下图所示。

![](/assets/img/vmwarecom1/4.PNG)


经过分析，在0x03208797的处的call会每次拷贝2个字节到esp+48（eip在0x0320879时）的位置，图6显示了已经拷贝了8个字节的情况（由于栈随机化，实际情况以dbg里面的为准）。

![](/assets/img/vmwarecom1/5.PNG)

对应的是exp中的overflow的开始部分，拷贝次数在ebx中，为0xAC，也就是理论上可以拷贝的字节为0xAC*2=0x158个字节，而拷贝0x4C以上的字节的时候会导致缓冲区溢出，淹没返回地址。直接运行到之后的0x032087ba，此时栈的已经被全部被exp中的overflow覆盖了。继续往下走，在0x03208882处有一个从esp+118读数据到edx，后面会将该数与其加1之后的结果比较作为分支方向（即0x032088a5处），这里必须保证能够跳转成功，所以布局overflow的时候需要在esp+118这个位置放上0x7fffffff。接着往下走，到0x032089f8处，需要从eps+110处读四个字节到edx,在0x03208a01处有向这个edx内存写数据的指令，所以这个地址需要是可写的，这就是exp中的WRITABLE为1010ff00的原因，这是iconv.dll的.idata空间,注意这里edx=0x1010ff00，之后一直没有变过。由于有这两个原因以及之后的控制eip之后的操作，布局无法向常规一样，像流水线一样一直往下走。文章中使用了比较巧妙的办法，先布局shellcode的一部分，然后将栈抬高，接着执行shellcode的第二部分。

###4.2 overflow第二段代码执行

从0x03208adf处ret之后，就到了我们第一个eip处0x1001cae4，这是跳向InterlockedExchange的指令，注意这个点的edi，edi的值与保存VirtualAlloc函数地址的值紧密相关。该exp大量使用InterlockedExchange来布置数据，技巧性相当高。现在控制流程到了0x74ec2520，很容易看出这是在交换[ecx]和eax的数据，eax和ecx分别取自esp+C和esp+8。ecx为0x1010ff00，eax为0xf4，这个0xf4就是从overflow开始到结束的距离，待会会利用这个数据直接将流程控制点到overflow的顶部。紧接着ret，到了0x1001c595，只是将之前的0x1010ff00弹出，接着ret还是0x1001c595，弹出之前的数据。现在eip又到了0x1001cae4，这次交换的数据是eax=0x00078c48和地址ecx=0x1010ff00处的数据，这也是特别巧妙的，可谓是一举两得，eax变成了0xf4作为之后调用_alloca_probe的参数，而0x1010ff00处的值0x00078c48与edi相加之后正好为存有VirtualAlloc函数地址的地址。在这个0x1001cae4返回之后到达0x1001c1e0，这就是_alloca_probe函数的地址，该函数将栈抬高eax字节，此时esp-f4即可到达overflow的前4个字节，由于在0x1001c1fb处，eax和esp交换，所以这时eax的值为老的esp,之后eax的值esp处的值，即overflow的最底部的值0x1001cae4，然后赋给栈顶，此时的栈顶已经在overflow第一段的前四个字节了。到0x1001c201返回ret直接到了0x1001cae4。这时开始执行overflow的第一部分shellcode代码。


###4.3 overflow第一段代码执行

最开始执行由4.2末尾设置在0x1001cae4的代码，也就是InterlockedExchange的指令，这次是将0x10110284的值设为0x1001c594，0x10110284为_io_func的函数地址，这个作用后面叙述。从这个gadget返回之后到了0x1001c94c，将edx的值放入eax之后返回（注意,edx自从被置为1010ff00之后没有变过，所以此时eax为1010ff00）。这个时候到了0x100010b1，在0x100010b4会调用call [100110284]，0x100110284地址处的值已经被替换成了0x1001c594，这个gadget什么也没做，接着到了0x1001c594，也只是到达下一个gadget。现在到了0x1000cb5c,这是dec eax，紧接着到达0x10003d43，这个指令add dword ptr ds:[eax+1],edi，正好将0x1010ff00的值设为0x00078c48+edi = 0x032812d8,这个值就是存放的就是存放VirtualAlloc地址的地址，注意这里由于0x10003d94的指令还将栈抬高了0x10个字节，所以现在又ret到了0x1001c594。这里弹出几个之前的布局，到了0x10001116将0x1010fef8弹到了ebp中，0x1001c120将ebp+8即1010ff00处的值放到eax中。之后到了0x10010b1处的gadget，这里调call [10110284],也是弹出之前需要的布局数据。然后到了0x1001c1fc，这个gadget将VirtualAlloc的地址（在eax中）放入[esp]，然后ret，根据在stack布置好的参数，就在0x40000000处分配了0x10000大小的空间，并且可执行。接下来又是3次跳到0x1001cae4，这个gadget已经很熟了，这里就是将新开辟的0x40000000的开始0xC个字节放入0x8b24438b和0x0xa4f21470,0x01f3e9。然后跳到0x40000000开始执行。

###4.4 执行SHELLCODE

这0xC个字节是组成4条指令，将内存中的[esi]处的数据复制到0x40000010处，[esi]之中就包括了SHELLCODE部分，之后jmp 0x40000200，进入一段nop滑板之后就执行了SHELLCODE。

##5. 总结

该漏洞有两个地方我认为是难点，第一是EMFSPOOL、EMF和JPEG2000的文件格式，需要构造触发漏洞的poc并不容易。第二是漏洞的利用，由于该漏洞可以使用的gadget来源仅有icov.dll，所以ROP链的构造非常不容易，从第四部分的分析也看出了，overflow被迫分为两段，然后栈的忽而抬升，忽而下降，布局溢出数据需要考虑栈提升的前后两个方面的情况，技巧性特别高。总之我认为这是一个基本完美的利用。
从VENOM和这个漏洞可以看出，虚拟化漏洞（特别是虚拟机逃逸）这种一般都是在跟主机打交道的时候发生的。KVM中，vm exit进入kvm内核处理的过程，以及kvm分发io给qemu的时候应该是发生漏洞的主要场景。由于docker依靠的是linux内核提供的隔离机制，内核出现漏洞，出事的概率特别大。
