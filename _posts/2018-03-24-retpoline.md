---
layout: post
title: "retpoline: 原理与部署"
description: "retpoline introduction"
category: 技术
tags: [漏洞]
---
{% include JB/setup %}


本文主要翻译自[Retpoline: A Branch Target Injection Mitigation](https://software.intel.com/sites/default/files/managed/1d/46/Retpoline-A-Branch-Target-Injection-Mitigation.pdf?source=techstories.org).

<h3> 原理 </h3>

retpoline是Google开发的针对Spectre变种2漏洞缓解利用技术。Spectre变种2利用CPU的间接分支预测(indirect
branch predictor)功能，攻击者通过事先训练分支，让分支预测器去影响受害者进程，然后通过侧信道的方式来获取
受害者进程的信息。其实这个变种2的漏洞利用是非常困难的，Jann Horn的利用其实也是在一个老版本的kvm上，按照
Linus的说法是利用Spectre是"fairly hard"。

目前有两种方案来缓解Spectre漏洞，即硬件方案和软件方案。硬件方案就是IBRS + IBPB， 直接在硬件层面阻止投机执行
(speculative execution)，当然，这会导致性能很低，所以IBRS没有进入内核。软件方案主要就是retpoline了, 因为
性能影响较低，最终得以进入内核主线。

每次CPU在快执行间接跳转的时候，比如jmp [xxx], call, 会去询问indirect branch predictor，然后投机选择一个最有
可能执行的路径。retpoline就是要绕过这个indirect branch predictor，使得CPU没有办法利用其它人故意训练出来的
分支路径。retpoline是 "return" 和 "trampoline"，也就是在间接跳转的时候用return指令添加了一个垫子。这个看了后文
就能够理解了。

ret指令的预测跟jmp和call不太一样，ret依赖于Return Stack Buffer(RSB)。跟indirect branch predictor不一样的是，RSB是一个
先进后出的stack。当执行call指令时，会push一项，执行ret时，会pop一项，这很容易由软件控制，比如下面的指令系列：


	__asm__ __volatile__("       call 1f; pause;"
			     "1:     call 2f; pause;"
			     "2:     call 3f; pause;"
			     "3:     call 4f; pause;"
			     "4:     call 5f; pause;"
			     "5:     call 6f; pause;"


![](/assets/img/retpoline/retpoline.png)


上图显示了retpoline的基本原理，即用一段指令代替之前的简介跳转指令，然后CPU如果投机执行会陷入一个死循环。

下面分析一下jmp间接跳转指令如何被替换成retpoline的指令。

![](/assets/img/retpoline/jmp.png)

在这个例子中，jmp通过rax的值进行间接跳转，如果没有retpoline，处理器会去询问indirect branch predictor,如果之前有攻击者去训练过这个分支，会导致CPU执行特定的一个gadget代码。下面看看retpoline是如何阻止CPU投机执行的。

1. "1: call load_label"这句话把"2: pause ; lfence"的地址压栈，当然也填充了RSB的一项，然后跳到load_label;

2. "4: mov %rax, (%rsp)"，这里把间接跳转的地址(*%rax)直接放到了栈顶，注意，这个时候内存中的栈顶地址和RSB里面地址不一样了;

3. 如果这个时候ret CPU投机执行了，会使用第一步填充在RSB的地址进行，也就是"2:
pause ; lfence",这里是一个死循环;

4. 最后，CPU发现了内存栈上的返回地址跟RSB自己投机的地址不一样，所以，投机执行会终止，然后跳到*%rax。



下面看看call指令被替换成retpoline的指令之后如何工作。

![](/assets/img/retpoline/call.png)

1. 首先从"1: jmp label2"跳到"7: call label0";
2. "7: call label0"将"8: … continue execution"的地址压入了内存栈以及RSB中，然后跳到label0;
3. "2: call label1"将"3: pause ; lfence"的地址压入了内存栈以及RSB中，然后跳到lable1;

这个时候内存栈和RSB如下:

![](/assets/img/retpoline/4.png)

4. "5: mov %rax, (%rsp)" 这里把间接跳转的地址(*%rax)直接放到了栈顶，注意，这个时候内存中的栈顶地址和RSB里面地址不一样了;

5. "6: ret".如果这个时候ret CPU投机执行了，会使用第3步填充在RSB的地址,"3: pause ; lfence". 这是一个死循环;

6. 最后，CPU发现了内存栈上的返回地址跟RSB自己投机的地址不一样，所以，投机执行会终止，然后跳到*%rax;

这个时候内存栈和RSB如下

![](/assets/img/retpoline/5.png)

7. 当间接地址调用(*%rax)返回的时候，通过RSB和内存中地址继续执行步骤2的压的地址，也就是8那里。

<h3> 部署 </h3>

由于大部分的间接跳转都是由编译器产生的，所以需要编译器的支持，目前最新的gcc已经支持了-mindirect-branch=thunk选项用于替换间接指令为retpoline系列。下面看看一个简单的例子:

	#include <stdio.h>
	#include <stdlib.h>

	typedef void (*fp)();

	void test()
	{
		printf("indirect test\n");
	}
	int main()
	{
		fp f = test;
		f();
	}


上面是一个典型的间接跳转。

	# gcc  -mindirect-branch=thunk  test.c  -o test
	# objdump -d test

	... 
	00000000004004d8 <main>:
	4004d8:	55                   	push   %rbp
	4004d9:	48 89 e5             	mov    %rsp,%rbp
	4004dc:	48 83 ec 10          	sub    $0x10,%rsp
	4004e0:	48 c7 45 f8 c7 04 40 	movq   $0x4004c7,-0x8(%rbp)
	4004e7:	00 
	4004e8:	48 8b 55 f8          	mov    -0x8(%rbp),%rdx
	4004ec:	b8 00 00 00 00       	mov    $0x0,%eax
	4004f1:	e8 07 00 00 00       	callq  4004fd <__x86_indirect_thunk_rdx>
	4004f6:	b8 00 00 00 00       	mov    $0x0,%eax
	4004fb:	c9                   	leaveq 
	4004fc:	c3                   	retq   

	00000000004004fd <__x86_indirect_thunk_rdx>:
	4004fd:	e8 07 00 00 00       	callq  400509 <__x86_indirect_thunk_rdx+0xc>
	400502:	f3 90                	pause  
	400504:	0f ae e8             	lfence 
	400507:	eb f9                	jmp    400502 <__x86_indirect_thunk_rdx+0x5>
	400509:	48 89 14 24          	mov    %rdx,(%rsp)
	40050d:	c3                   	retq   
	40050e:	66 90                	xchg   %ax,%ax
	...

我们可以看到间接跳转已经被retpoline的指令系列所替换。
当然，如果是一些内嵌汇编的间接跳转，则需要自己手动去增加retpoline序列。

在Linux内核中，是通过一个内核命令行参数来决定是否开启retpoline的，如果开启则内核在启动时动态替换指令。这样最大限度的减小了内核的性能损耗。

