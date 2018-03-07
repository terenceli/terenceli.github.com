---
layout: post
title: "Spectre Mitigation介绍"
description: "Spectre mitigation"
category: 技术
tags: [漏洞]
---
{% include JB/setup %}


<h3>背景</h3>

CPU使用indirect branch predictors来进行投机执行。攻击者能够通过训练这个predictor来控制CPU执行特定的指令，然后做一些侧信道分析。这也就是spectre变种2漏洞。

Intel在硬件层面提供了3个机制用来控制indirect branch，操作系统可以利用这三个机制防止入侵者控制indirect branch predictor。这个三个机制分别是IBRS, STIBP, IBPB。本文主要介绍这三个机制以及在Linux upstream中的状态，并且从个人角度会给出一些修复建议。

<h3>Indirect Branch Control 机制介绍 </h3>

CPUID.(EAX=7H,ECX=0):EDX[26]为1则表示支持IBRS和IBPB，OS可以写IA32_SPEC_CTRL[0] (IBRS) and IA32_PRED_CMD[0] (IBPB)来控制indirect branch predictor的行为。
CPUID.(EAX=7H,ECX=0):EDX[27]为1表示支持STIBP, OS可以写IA32_SPEC_CTRL[1] (STIBP)。

这里可以看到多了两个MSR，IA32_SPEC_CTRL和IA32_PRED_CMD，IBRS和STIBP通过前一个MSR控制，IBPB通过后一个MSR控制。从名字也可以看出，IBRS和STIBP是一种control，IBPB是一种command，具体来说，就是IBRS和STIBP会有状态信息，而IBPB是一种瞬时值。不恰当举例，IBRS类似于你每个月都会发工资，然后零花钱就会可以预见的增多，IBPB类似于地上捡了10块钱。

Indirect Branch Restricted Speculation (IBRS): 简单点来说，一般情况下，在高权限代码里面向IBRS的控制位写1，就能够保证indirect branch不被低权限时候train出来的predictor影响，也能够防止逻辑处理器的影响（超线程的时候）。这里权限转换就是host user-> host kernel, guest -> host等等。可以把IBRS理解成不同特权级之间的predictor隔离。
IBRS不能防止同一个级别的predictor共享，需要配合IBPB。

Single thread indirect branch predictors (STIBP)： 超线程中，一个core的逻辑处理器会共享一个indirect branch predictor，STIBP就是禁止这种共享，防止一个逻辑处理器的predictor被另一个污染。STIBP是IBRS的一个子集，所以一般开启了IBRS就不用开STIBP了。

Indirect Branch Predictor Barrier (IBPB): IBPB类似于一个barrier, 在这之前的indirect branch predictor不会影响这之后的。

综上，IBRS和IBPB可以结合起来一起作为spectre变种2的mitigation：
IBRS用于防止权限之间的predictor污染，IBPB用来阻止同一个权限下不同的实体之间的predictor污染(比如应用程序之间或者虚拟机之间)。

<h3> Linux状态及修复建议</h3>

IBRS由于性能问题最终还是没能进入内核，upstream最终选择了Google的retpoline方案，说句题外话，Google发现了漏洞，然后自己整的修复方案还进入了upstream，可以说是非常牛了，IBPB我看已经进入内核了（至少在vm切换的时候）。


个人修复建议：
从上面可以看到修复方案可以有两种选择。

    retpoline + IBPB， retpoline需要对内核修改比较大，并且需要编译器支持。

    IBRS + IBPB， 方案比较简单，稳定性能够保证，可以只在虚拟化这边部署，guest/host用IBRS, guest/guest用IBPB。
    
建议可以先测测第二种方案的性能，看看损失到底几何再做决定。

<h3> 参考 </h3>

[Speculative Execution Side Channel
Mitigations](http://kib.kiev.ua/x86docs/SDMs/336996-001.pdf)

[Meltdown and Spectre, explained](https://medium.com/@mattklein123/meltdown-spectre-explained-6bc8634cc0c2)