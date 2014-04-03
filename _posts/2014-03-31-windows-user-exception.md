---
layout: post
title: "Windows用户态异常处理"
description: "Windows异常处理"
category: 技术
tags: [Windows原理, SEH]
---
{% include JB/setup %}


*	[Windows异常的分发](#第一节)
*	[OS提供的SEH机制](#第二节)
*	[编译器层面的SEH](#第三节)
*	[展开](#第四节)

已经有太多的文章对Windows异常处理进行了讨论，我这里也是在前人的基础上总结一下，自己做个记录。为了便于理解，我准备从异常发生的那一刻到执行我们自己定义的异常处理函数进行一个梳理。

<h3 id="第一节">一. Windows异常的分发</h3>

在保护模式下，当有中断或异常发生时，CPU是通过IDT进入内核来寻找处理函数的，比如我们在执行一个除0操作，就会使得CPU的执行转到IDT第一项所注册的地址(nt!KiTrap00)。或者我们试图访问一个不存在的内存页会使流程转到nt!KiTrap0E。使用windbg查看idt，如下：

	kd> !idt -a
	
	Dumping IDT: 8003f400
	
	9d120e4800000000:	804e0360 nt!KiTrap00
	9d120e4800000001:	804e04db nt!KiTrap01
	9d120e4800000002:	Task Selector = 0x0058
	9d120e4800000003:	804e08ad nt!KiTrap03
	9d120e4800000004:	804e0a30 nt!KiTrap04
	9d120e4800000005:	804e0b91 nt!KiTrap05
	9d120e4800000006:	804e0d12 nt!KiTrap06
	9d120e4800000007:	804e137a nt!KiTrap07
	9d120e4800000008:	Task Selector = 0x0050
	9d120e4800000009:	804e179f nt!KiTrap09
	9d120e480000000a:	804e18bc nt!KiTrap0A
	9d120e480000000b:	804e19f9 nt!KiTrap0B
	9d120e480000000c:	804e1c52 nt!KiTrap0C
	9d120e480000000d:	804e1f48 nt!KiTrap0D


KiTrap00函数通常只是对异常作简单的表征和描述，为了支持调试和软件自己定义的异常处理函数，系统需要将异常分发给调试器或应用程序的处理函数。对于软件异常，Windows系统采用的策略是以和CPU异常统一的方式来分发和处理的，处理的关键函数是nt!KiDispatchException。

![](/assets/img/exception/1.png)

KiDispatchException原型如下：

	VOID KiDispatchException(IN PEXCEPTION_RECORD 	ExceptionRecord,
							 IN PKEXCEPTION_FRAME 	ExceptionFrame,
							 IN PKTRAP_FRAME 	TrapFrame,
							 IN KPROCESSOR_MODE 	PreviousMode,
							 IN BOOLEAN 	FirstChance 
							)

ExceptionRecord用来描述异常，定义如下：
	
	 typedef struct _EXCEPTION_RECORD {
	            NTSTATUS ExceptionCode;
	            ULONG ExceptionFlags;
	            struct _EXCEPTION_RECORD *ExceptionRecord;
	            PVOID ExceptionAddress;
	            ULONG NumberParameters;
	            ULONG_PTR ExceptionInformatio[EXCEPTION_MAXIMUM_PARAMETERS];
	        } EXCEPTION_RECORD;

ExceptionFrame对于x86结构总是NULL，参数TrapFrame用来描述异常发生时的处理器状态，包括各种通用寄存器、调试寄存器、段寄存器等。定义如下：

	 typedef struct _KTRAP_FRAME {
	            ULONG   DbgEbp;         
	            ULONG   DbgEip;       
	            ULONG   DbgArgMark;    
	            ULONG   DbgArgPointer; 
	            ULONG   TempSegCs;
	            ULONG   TempEsp;
	            ULONG   Dr0;
	            ULONG   Dr1;
	            ULONG   Dr2;
	            ULONG   Dr3;
	            ULONG   Dr6;
	            ULONG   Dr7;
	            ULONG   SegGs;
	            ULONG   SegEs;
	            ULONG   SegDs;
	            ULONG   Edx;
	            ULONG   Ecx;
	            ULONG   Eax;
	            ULONG   PreviousPreviousMode;
	            PEXCEPTION_REGISTRATION_RECORD ExceptionList;
	            ULONG   SegFs;
	            ULONG   Edi;
	            ULONG   Esi;
	            ULONG   Ebx;
	            ULONG   Ebp;
	            ULONG   ErrCode;
	            ULONG   Eip;
	            ULONG   SegCs;
	            ULONG   EFlags;
	            ULONG   HardwareEsp;    
	            ULONG   HardwareSegSs; 
	            ULONG   V86Es;          
	            ULONG   V86Ds;  
	            ULONG   V86Fs;
	            ULONG   V86Gs;    
	    } KTRAP_FRAME;
 
PreviousMode是一个枚举类型，表示出发异常代码的执行模式是用户模式还是内核模式。FirstChance参数表示是否是第一轮分发这个异常。对于一个异常，Windows系统会最多分发两轮。图2画出了KiDispatchException分发异常的基本过程。


![](/assets/img/exception/2.png)

这里我们只关注用户态异常并且调试器没有处理该异常的的情况。KiDispatchException将CONTEXT和EXCEPTION_RECORD结构复制到用户态栈中，之后会将内核变量KeUserExceptionDispatcher赋予KTRAP_FRAME中的eip，这个值是KiUserExceptionDispatcher函数。之后执行iret指令返回用户空间。我们在windbg中看到：

	kd> dd KeUserExceptionDispatcher
	8055b310  7c92e47c 7c92e460 7c92e450 0002625a
	8055b320  00000000 00000000 00000000 00000000

可以看到KeUserExceptionDispatcher的值为0x7c92e47c，这与OD看到的吻合。

回到用户态后，KiUserException会通过调用RtlDispatchException来寻找异常处理器。

	 KiUserExceptionDispatcher( PEXCEPTION_RECORD pExcptRec, CONTEXT *pContext )
	 {
	     DWORD retValue;
	
	     // Note: If the exception is handled, RtlDispatchException() never returns
	     if ( RtlDispatchException( pExceptRec, pContext ) )
	         retValue = NtContinue( pContext, 0 );
	     else
	         retValue = NtRaiseException( pExceptRec, pContext, 0 );
	
	     EXCEPTION_RECORD excptRec2;
	
	     excptRec2.ExceptionCode = retValue;
	     excptRec2.ExceptionFlags = EXCEPTION_NONCONTINUABLE;
	     excptRec2.ExceptionRecord = pExcptRec;
	     excptRec2.NumberParameters = 0;
	
	     RtlRaiseException( &excptRec2 );
	 }
RtlDispatchException函数的工作就是找到注册在线程信息快(TIB)中异常处理器链表的头结点，然后依次访问每个节点，调用它的处理器函数，直到有人处理了异常，或者到了链表的末尾。这个时候SEH机制就上场了。

<h3 id="第二节">二. OS提供的SEH机制</h3>

RtlDispatchException调用用户层注册的异常处理函数，这个回调函数的原型如下：

	EXCEPTION_DISPOSITION
	__cdecl _except_handler(
	struct _EXCEPTION_RECORD *ExceptionRecord,
	void * EstablisherFrame,
	struct _CONTEXT *ContextRecord,
	void * DispatcherContext
	);
	
这些参数中ExceptionRecord和ContextRecord是从内核态复制到用户态栈中的，EstablisherFrame是建立（登记）异常处理函数的那个函数栈帧，DispatcherContext是个指针，仅用于嵌套异常的临时保护节点有效。

	typedef enum _EXCEPTION_DISPOSITION {
	    ExceptionContinueExecution,
	    ExceptionContinueSearch,
	    ExceptionNestedException,
	    ExceptionCollidedUnwind
	} EXCEPTION_DISPOSITION;
os会根据hander返回值来决定下一步操作。

这回快涉及到编译器的SEH支持了，我还是先来说说OS的机制，刚才说到RtlDispatchException通过TIB找到异常处理器的头节点，这是通过fs:[0]实现的，fs总是指向当前线程的TEB结构，TIB位于TEB起始处。我们先看看TIB结构：

	kd> dt ntdll!_NT_TIB
	   +0x000 ExceptionList    : Ptr32 _EXCEPTION_REGISTRATION_RECORD
	   +0x004 StackBase        : Ptr32 Void
	   +0x008 StackLimit       : Ptr32 Void
	   +0x00c SubSystemTib     : Ptr32 Void
	   +0x010 FiberData        : Ptr32 Void
	   +0x010 Version          : Uint4B
	   +0x014 ArbitraryUserPointer : Ptr32 Void
	   +0x018 Self             : Ptr32 _NT_TIB

我们看到第一个结构式_EXCEPTION_REGISTRATION_RECORD

	kd> dt ntdll!_EXCEPTION_REGISTRATION_RECORD
	   +0x000 Next             : Ptr32 _EXCEPTION_REGISTRATION_RECORD
	   +0x004 Handler          : Ptr32     _EXCEPTION_DISPOSITION 

第一部分是下一个_EXCEPTION_REGISTRATION_RECORD结构地址，第二部分是一个异常处理函数。

现在我们简单总结一下，在执行用户注册的异常处理函数的步骤是：当异常发生后，返回用户态RtlDispatchException查找用户态注册的异常处理器时，首先通过fs:[0]得到ExceptionList字段，遍历这个链表以便查找其中的一个EXCEPTION_REGISTRATION 结构，其例程回调（异常处理程序）同意处理该异常。在 MYSEH.CPP 的例子中，异常处理程序通过返回ExceptionContinueExecution 表示它同意处理这个异常。异常回调函数也可以拒绝处理这个异常。在这种情况下，系统移向链表的下一个EXCEPTION_REGISTRATION 结构并询问它的异常回调函数，看它是否愿意处理这个异常。图3显示了这个过程

![](/assets/img/exception/3.png)

我们给个例子手工编写代码来登记和注销异常处理函数。



	#include "stdafx.h"
	
	 //==================================================
	 // MYSEH - Matt Pietrek 1997
	 // Microsoft Systems Journal, January 1997
	 // FILE: MYSEH.CPP
	 // To compile: CL MYSEH.CPP
	 //==================================================
	#define WIN32_LEAN_AND_MEAN
	#include <windows.h>
	#include <stdio.h>
	
	DWORD  scratch;
	
	EXCEPTION_DISPOSITION
	__cdecl
	_except_handler(
	    struct _EXCEPTION_RECORD *ExceptionRecord,
	    void * EstablisherFrame,
	    struct _CONTEXT *ContextRecord,
	    void * DispatcherContext )
	{
	    unsigned i;
	
	    // Indicate that we made it to our exception handler
	    printf( "Hello from an exception handler/n" );
	
	    // Change EAX in the context record so that it points to someplace
	    // where we can successfully write
	    ContextRecord->Eax = (DWORD)&scratch;
	
	    // Tell the OS to restart the faulting instruction
	    return ExceptionContinueExecution;
	}
	
	int main()
	{
	    DWORD handler = (DWORD)_except_handler; 
	    __asm
	    { 
	        // 创建 EXCEPTION_REGISTRATION 结构：
	        push handler 	// handler函数的地址
	        push FS:[0] 	// 前一个handler函数的地址
	        mov FS:[0],ESP 	// 装入新的EXECEPTION_REGISTRATION结构
	    } 
	    __asm
	    {
	        mov eax,0     	// EAX清零
	        mov [eax], 1 	// 写EAX指向的内存从而故意引发一个错误
	    } 
	    printf( "After writing!/n" ); 
	    __asm
	    { 
	        // 移去我们的 EXECEPTION_REGISTRATION 结构记录
	        mov eax,[ESP]    	// 获取前一个结构
	        mov FS:[0], EAX 	// 装入前一个结构
	        add esp, 8       	// 将 EXECEPTION_REGISTRATION 弹出堆栈
	    } 
	    return 0; 
	}


代码不必赘言，就是我们手工压入一个处理函数，然后出发一个异常，流程进入我们的处理器，处理之后继续回到原来的流程。

刚刚我们看到的就是操作系统对SEH的支持，介绍这个事为了说明登记和注销SEH处理器的基本原理。很明显，我们自己写windows程序的时候如果这样写就比较麻烦了：第一，需要自己编写符合SehHandler函数原型的处理函数；第二，要直接操作栈指针。平时我们都是直接使用__try{} __excpet()就简单的完成了异常函数的注册。这就是编译器对SEH的支持了。

<h3 id="第三节">三. 编译器层面的SEH</h3>

我们使用一个例子来看看编译器层面的SEH，例子程序下载：[sehtes.cpp](/assets/file/exception/sehtes.cpp)

	1   119:  int main()
	2	120:  {
	3	00401280   push        ebp
	4	00401281   mov         ebp,esp
	5	00401283   push        0FFh
	6	00401285   push        offset string "Caught Exception in main\n"+24h (00422130)
	7	0040128A   push        offset __except_handler3 (00401430)
	8	0040128F   mov         eax,fs:[00000000]
	9	00401295   push        eax
	10	00401296   mov         dword ptr fs:[0],esp
	11	0040129D   add         esp,0B4h
	12	004012A0   push        ebx
	13	004012A1   push        esi
	14	004012A2   push        edi
	15	004012A3   mov         dword ptr [ebp-18h],esp
	16	004012A6   lea         edi,[ebp-5Ch]
	17	004012A9   mov         ecx,11h
	18	004012AE   mov         eax,0CCCCCCCCh
	19	004012B3   rep stos    dword ptr [edi]
	20	121:      int i;
	21	122:      // 使用两个__try块（并不嵌套），这导致为scopetable数组生成两个元素
	22	123:      __try
	23	004012B5   mov         dword ptr [ebp-4],0
	24	124:      {
	25	125:          i = 0x1234;
	26	004012BC   mov         dword ptr [ebp-1Ch],1234h
	27	126:
	28	127:      } __except( EXCEPTION_EXECUTE_HANDLER )
	29	004012C3   mov         dword ptr [ebp-4],0FFFFFFFFh
	30	004012CA   jmp         $L17074+17h (004012e9)
	31	$L17073:
	32	004012CC   mov         eax,1
	33	$L17075:
	34	004012D1   ret
	35	$L17074:
	36	004012D2   mov         esp,dword ptr [ebp-18h]
	37	128:      {
	38	129:          printf("div0 occur!\n");
	39	004012D5   push        offset string "div0 occur!\n" (004230c4)
	40	004012DA   call        printf (00401370)
	41	004012DF   add         esp,4
	42	130:      }
	43	004012E2   mov         dword ptr [ebp-4],0FFFFFFFFh
	44	131:      __try
	45	004012E9   mov         dword ptr [ebp-4],1
	46	132:      {
	47	133:          Function1(); // 调用一个设置更多异常帧的函数
	48	004012F0   call        @ILT+15(Function1) (00401014)
	49	134:      } __except( EXCEPTION_EXECUTE_HANDLER )
	50	004012F5   mov         dword ptr [ebp-4],0FFFFFFFFh
	51	004012FC   jmp         $L17078+17h (0040131b)
	52	$L17077:
	53	004012FE   mov         eax,1
	54	$L17079:
	55	00401303   ret
	56	$L17078:
	57	00401304   mov         esp,dword ptr [ebp-18h]
	58	135:      {
	59	136:          // 应该永远不会执行到这里，因为我们并没有打算产生任何异常
	60	137:          printf( "Caught Exception in main\n" );
	61	00401307   push        offset string "Caught Exception in main\n" (0042210c)
	62	0040130C   call        printf (00401370)
	63	00401311   add         esp,4
	64	138:      }
	65	00401314   mov         dword ptr [ebp-4],0FFFFFFFFh
	66	139:      return 0;
	67	0040131B   xor         eax,eax
	68	140:  }
	69	0040131D   mov         ecx,dword ptr [ebp-10h]
	70	00401320   mov         dword ptr fs:[0],ecx
	71	00401327   pop         edi
	72	00401328   pop         esi
	73	00401329   pop         ebx
	74	0040132A   add         esp,5Ch
	75	0040132D   cmp         ebp,esp
	76	0040132F   call        __chkesp (004013f0)
	77	00401334   mov         esp,ebp
	78	00401336   pop         ebp
	79	00401337   ret
	80	
	81	
	82	99:   void Function1( void )
	83	100:  {
	84	004011A0   push        ebp
	85	004011A1   mov         ebp,esp
	86	004011A3   push        0FFh
	87	004011A5   push        offset string "_except_handler3 is at address: "...+30h (004220e0)
	88	004011AA   push        offset __except_handler3 (00401430)
	89	004011AF   mov         eax,fs:[00000000]
	90	004011B5   push        eax
	91	004011B6   mov         dword ptr fs:[0],esp
	92	004011BD   add         esp,0B4h
	93	004011C0   push        ebx
	94	004011C1   push        esi
	95	004011C2   push        edi
	96	004011C3   mov         dword ptr [ebp-18h],esp
	97	004011C6   lea         edi,[ebp-5Ch]
	98	004011C9   mov         ecx,11h
	99	004011CE   mov         eax,0CCCCCCCCh
	100	004011D3   rep stos    dword ptr [edi]
	101	101:      int i;
	102	102:      // 嵌套3层__try块以便强制为scopetable数组产生3个元素
	103	103:      __try
	104	004011D5   mov         dword ptr [ebp-4],0
	105	104:      {
	106	105:          __try
	107	004011DC   mov         dword ptr [ebp-4],1
	108	106:          {
	109	107:              __try
	110	004011E3   mov         dword ptr [ebp-4],2
	111	108:              {
	112	109:                  i = i/0;
	113	004011EA   mov         eax,dword ptr [ebp-1Ch]
	114	004011ED   cdq
	115	0

第5~10行是在登记异常处理器，与我们手工编写有所不同。

第一，使用__except_handler3作为异常处理函数。编译器编译__try{}__except{}结构时总是使用统一的函数将其登记为异常处理函数，并不是为每段使用SEH的代码生成单独处理函数。不同编译器使用的异常处理函数可能不同，这里使用的VC6编译器的__except_handler3。异常处理函数是由系统异常分发函数来调用的，即RtlDispatchException>ExecuteHandler>ExecuteHandler2>__except_handler3，而且这些参数的个数是固定的。这意味着要增加新的参数是不可行的，解决办法只能扩展现有参数，通过类型转换将简单的类型转变为包含扩展字段的复杂类型，这正是VC所采用的方案。就是下面的第二点差异。

第二，在栈上准备EXCEPTION_REGISTRATION_RECORD前（7~9行），编译器产生的代码会先压入一个被称为trylevel的整数（第5行）和一个指向scopetable_entry结构的scopetable指针（第6行），这样在栈上世纪形成了如下的_EXCEPTION_REGISTRATION结构。

	struct _EXCEPTION_REGISTRATION{
		struct _EXCEPTION_REGISTRATION *prev;
		void (*handler)(PEXCEPTION_RECORD,PEXCEPTION_REGISTRATION,PCONTEXT,PEXCEPTION_RECORD);
		struct scopetable_entry *scopetable;
		int trylevel;
		int _ebp;
	}

下面分别介绍几个字段的作用。

1.scopetable

这个指针指向一个数组，数组的每个元素是一个scopetable_entry结构，用来描述一个__try{}__except结构。

	struct scopetable_entry
	{
		DWORD	previousTryLevel;
		FARPROC	lpfnFilter;
		FARPROC	lpfnHandler;
	}

其中lpfnFilter和lpfnHandler分别用来描述__try{}__except结构的过滤表达式和异常处理块的起始地址。还是以上面的例子看看 

	00422130  FF FF FF FF CC 12 40 00 D2 12 40 00 FF FF FF FF  ......@...@.....
	00422140  FE 12 40 00 04 13 40 00

一个函数注册一个_EXCEPTION_REGISTRATION，每个try except对应scopetable中的一个元素。
这个例子中，main函数中有2个try，所以有2个元素，第一个FFFFFFFF表示其不在任何__try结构中，004012CC是第一个__try的过滤函数，004012D2表示第一个__try的处理函数。

2.trylevel

trylevel表示的是scopetable对应的索引。在main最开始的时候是-1，表示不属于任何try结构，当进入第一个try结构中，设置这个变量为0（第23行），表示如果发生异常，就要去找scopetable中的第一个元素，离开第一个try之后，我们又将其设置为-1（第43行）。

为了对scopetable和trylevel，我们队Function1进行升入考察，其scopetable如下：

	004220E0  FF FF FF FF 2F 12 40 00 32 12 40 00 00 00 00 00  ..../.@.2.@.....
	004220F0  19 12 40 00 1C 12 40 00 01 00 00 00 03 12 40 00  ..@...@.......@.
	00422100  06 12 40 00 

这个scopetable共有3个元素，第一个的previousTrylevel为-1，说明其不再任何try块中，第二个元素的previousTrylevel为0，说明其在第0个scopetable元素的内部，第三个类似，我们从104~110行能够看到每次进入一个try块就会设置trylevel。

我们先看看__except_handler3的伪代码，然后再总结一下其运行过程：

	int __except_handler3(
	struct _EXCEPTION_RECORD * pExceptionRecord,
	struct EXCEPTION_REGISTRATION * pRegistrationFrame,
	struct _CONTEXT *pContextRecord,
	void * pDispatcherContext ) 
	{ 
		LONG filterFuncRet;
		LONG trylevel;
		EXCEPTION_POINTERS exceptPtrs;
		PSCOPETABLE pScopeTable; 
		CLD // 将方向标志复位（不测试任何条件！） 
			// 如果没有设置EXCEPTION_UNWINDING标志或EXCEPTION_EXIT_UNWIND标志
			// 表明这是第一次调用这个处理程序（也就是说，并非处于异常展开阶段）
			if ( ! (pExceptionRecord->ExceptionFlags
				& (EXCEPTION_UNWINDING | EXCEPTION_EXIT_UNWIND)) )
			{
				// 在堆栈上创建一个EXCEPTION_POINTERS结构
				exceptPtrs.ExceptionRecord = pExceptionRecord;
				exceptPtrs.ContextRecord = pContextRecord; 
				// 把前面定义的EXCEPTION_POINTERS结构的地址放在比
				// establisher栈帧低4个字节的位置上。参考前面我讲
				// 的编译器为GetExceptionInformation生成的汇编代
				// 码*(PDWORD)((PBYTE)pRegistrationFrame - 4) = &exceptPtrs; 
				// 获取初始的“trylevel”值
				trylevel = pRegistrationFrame->trylevel; 
				// 获取指向scopetable数组的指针 
				scopeTable = pRegistrationFrame->scopetable; 
	
		search_for_handler:
				if ( pRegistrationFrame->trylevel != TRYLEVEL_NONE )
				{
					if ( pRegistrationFrame->scopetable[trylevel].lpfnFilter )
					{
						PUSH EBP // 保存这个栈帧指针 
							// ！！！非常重要！！！切换回原来的EBP。正是这个操作才使得
							// 栈帧上的所有局部变量能够在异常发生后仍然保持它的值不变。
							EBP = &pRegistrationFrame->_ebp; 
						// 调用过滤器函数
						filterFuncRet = scopetable[trylevel].lpfnFilter(); 
						POP EBP // 恢复异常处理程序的栈帧指针 
							if ( filterFuncRet != EXCEPTION_CONTINUE_SEARCH )
							{
								if ( filterFuncRet < 0 ) // EXCEPTION_CONTINUE_EXECUTION
									return ExceptionContinueExecution; 
								// 如果能够执行到这里，说明返回值为EXCEPTION_EXECUTE_HANDLER
								scopetable = pRegistrationFrame->scopetable; 
								// 让操作系统清理已经注册的栈帧，这会使本函数被递归调用
								__global_unwind2( pRegistrationFrame ); 
								// 一旦执行到这里，除最后一个栈帧外，所有的栈帧已经
								// 被清理完毕，流程要从最后一个栈帧继续执行
								EBP = &pRegistrationFrame->_ebp; 
								__local_unwind2( pRegistrationFrame, trylevel ); 
								// NLG = "non-local-goto" (setjmp/longjmp stuff)
								__NLG_Notify( 1 ); // EAX = scopetable->lpfnHandler 
								// 把当前的trylevel设置成当找到一个异常处理程序时
								// SCOPETABLE中当前正在被使用的那一个元素的内容
								pRegistrationFrame->trylevel = scopetable->previousTryLevel; 
								// 调用__except {}块，这个调用并不会返回
								pRegistrationFrame->scopetable[trylevel].lpfnHandler();
							} 
					} 
					scopeTable = pRegistrationFrame->scopetable;
					trylevel = scopeTable->previousTryLevel;
					goto search_for_handler; 
				}
				else // trylevel == TRYLEVEL_NONE
				{
					return ExceptionContinueSearch;
				} 
			}
			else // 设置了EXCEPTION_UNWINDING标志或EXCEPTION_EXIT_UNWIND标志
			{
				PUSH EBP // 保存EBP
					EBP = &pRegistrationFrame->_ebp; // 为调用__local_unwind2设置EBP
				__local_unwind2( pRegistrationFrame, TRYLEVEL_NONE )
					POP EBP // 恢复EBP
					return ExceptionContinueSearch;
			} 
	}


__except_handler3函数执行的操作主要有：

1.将第二个参数pRegistrationRecord从系统默认的EXCEPTION_REGISTRATION_RECORD结构强制转化为包含扩展字段的_EXCEPTION_REGISTRATION结构。

2.先从pRegistrationRecord结构中取出trylevel字段的值并且赋给一个局部变量nTrylevel，然后根据nTrylevel的值从scopetable字段所指定的数组中找到一个scopetable_entry结构。

3.从scopetable_entry结构中取出lpfnFilter字段，如果不为空，则调用这个函数，即评估过滤表达式，如果为空，则跳到第五步。

4.如果lpfnFilter函数返回值不等于EXCEPTION_CONTINUE_SEARCH，则准备执行lpfnHandler字段做指定的函数，并且不再返回。如果过滤表达式返回的是EXCEPTION_CONTINUE_SEARCH，则自然进入（Fall Through)到第五步。

5.判断scopetable_entry结构的previousTrylevel字段值，如果它不等于-1，则将previousTrylevel赋给nTrylevel并返回到第二步继续循环。如果previousTrylevel等于-1，那么继续到第六步。

6.返回DISPOSITION_CONTINUE_SEARCH，让系统(RtlDispatchException)继续寻找其他异常处理器。


__except_handler3是如何做到既通过CALL指令调用__except块而又不让执行流程返回呢？由于CALL指令要向堆栈中压入了一个返回地址，你可以想象这有可能破坏堆栈。如果你检查一下编译器为__except块生成的代码，你会发现它做的第一件事就是将EXCEPTION_REGISTRATION结构下面8个字节处（即[EBP-18H]处）的一个DWORD值加载到ESP寄存器中（实际代码为MOV ESP,DWORD PTR [EBP-18H]）,这个值是在函数的 prolog 代码中被保存在这个位置的（实际代码为MOV DWORD PTR [EBP-18H],ESP）。


上述过程省略了全局展开和局部展开，我们在下一节专门讨论。

<h3 id="第四节">四. 展开</h3>

为了说明这个概念，需要先回顾下异常发生后的处理流程。

我们假设一系列使用 SEH 的函数调用流程： 
func1 -> func2 -> func3。在 func3 执行的过程中触发了异常。

看看分发异常流程 RtlRaiseException -> RtlDispatchException -> RtlpExecuteHandlerForException
RtlDispatchException 会遍历异常链表，对每个 EXCEPTION_REGISTRATION 都调用 RtlpExecuteHandlerForException。
RtlpExecuteHandlerForException 会调用 EXCEPTION_REGISTRATION::handler，也就是 ——__except_handler3。如咱们上面分析，该函数内部遍历 EXCEPTION_REGISTRATION::scopetable，如果遇到有 scopetable_entry::lpfnFilter 返回 EXCEPTION_EXECUTE_HANDLER，那么 scopetable_entry::lpfnHandler 就会被调用，来处理该异常。
因为 lpfnHandler 不会返回到__except_handler3，于是执行完 lpfnHandler 后，就会从 lpfnHandler 之后的代码继续执行下去。也就是说，假设 func3 中触发了一个异常，该异常被 func1 中的 __except 处理块处理了，那 __except 处理块执行完毕后，就从其后的指令继续执行下去，即异常处理完毕后，接着执行的就是 func1 的代码。不会再回到 func2 或者 func3，这样就有个问题，func2 和 func3 中占用的资源怎么办？这些资源比如申请的内存是不会自动释放的，岂不是会有资源泄漏问题？

这就需要用到“展开”了。
说白了，所谓“展开”就是进行清理。（注：这里的清理主要包含动态分配的资源的清理，栈空间是由 func1 的“mov esp,ebp” 这类操作顺手清理的。当时我被“谁来清理栈空间”这个问题困扰了很久……）
  
那这个展开工作由谁来完成呢？由 func1 来完成肯定不合适，毕竟 func2 和 func3 有没有申请资源、申请了哪些资源，func1 无从得知。于是这个展开工作还得要交给 func2 和 func3 自己来完成。

展开分为两种：“全局展开”和“局部展开”。
全局展开是指针对异常链表中的某一段，局部展开针对指定 EXCEPTION_REGISTRATION。用上面的例子来讲，局部展开就是针对 func3 或 func2 （某一个函数）内部进行清理，全局展开就是 func2 和 func3 的局部清理的总和。再归纳一下，局部展开是指具体某一函数内部的清理，而全局展开是指，从异常触发点（func3）到异常处理点（func1）之间所有函数（包含异常触发点 func3）的局部清理的总和。

使用RtlUnwind来进行展开。

	  void _RtlUnwind( PEXCEPTION_REGISTRATION pRegistrationFrame,
			  PVOID returnAddr, // 并未使用！（至少是在i386机器上）
			  PEXCEPTION_RECORD pExcptRec,
			  DWORD _eax_value) 
	  { 
		  DWORD stackUserBase;
		  DWORD stackUserTop;
		  PEXCEPTION_RECORD pExcptRec;
		  EXCEPTION_RECORD exceptRec;
		  CONTEXT context; 
		  // 从FS:[4]和FS:[8]处获取堆栈的界限
		  RtlpGetStackLimits( &stackUserBase, &stackUserTop ); 
		  if ( 0 == pExcptRec ) // 正常情况
		  {
			  pExcptRec = &excptRec;
			  pExcptRec->ExceptionFlags = 0;
			  pExcptRec->ExceptionCode = STATUS_UNWIND;
			  pExcptRec->ExceptionRecord = 0;
			  pExcptRec->ExceptionAddress = [ebp+4]; // RtlpGetReturnAddress()—获取返回地址
			  pExcptRec->ExceptionInformation[0] = 0;
		  } 
		  if ( pRegistrationFrame )
			  pExcptRec->ExceptionFlags |= EXCEPTION_UNWINDING;
		  else             // 这两个标志合起来被定义为EXCEPTION_UNWIND_CONTEXT
			  pExcptRec->ExceptionFlags|=(EXCEPTION_UNWINDING|EXCEPTION_EXIT_UNWIND); 
		  context.ContextFlags =( CONTEXT_i486 | CONTEXT_CONTROL |
			  CONTEXT_INTEGER | CONTEXT_SEGMENTS); 
		  RtlpCaptureContext( &context ); 
		  context.Esp += 0x10;
		  context.Eax = _eax_value; 
		  PEXCEPTION_REGISTRATION pExcptRegHead;
		  pExcptRegHead = RtlpGetRegistrationHead(); // 返回FS:[0]的值 
		  // 开始遍历EXCEPTION_REGISTRATION结构链表
		  while ( -1 != pExcptRegHead )
		  {
			  EXCEPTION_RECORD excptRec2; 
			  if ( pExcptRegHead == pRegistrationFrame )
			  {
				  NtContinue( &context, 0 );
			  }
			  else
			  {
				  // 如果存在某个异常帧在堆栈上的位置比异常链表的头部还低
				  // 说明一定出现了错误
				  if ( pRegistrationFrame && (pRegistrationFrame <= pExcptRegHead) )
				  {
					  // 生成一个异常
					  excptRec2.ExceptionRecord = pExcptRec;
					  excptRec2.NumberParameters = 0;
					  excptRec2.ExceptionCode = STATUS_INVALID_UNWIND_TARGET;
					  excptRec2.ExceptionFlags = EXCEPTION_NONCONTINUABLE;
					  RtlRaiseException( &exceptRec2 );
				  }
			  } 
			  PVOID pStack = pExcptRegHead + 8; // 8 = sizeof(EXCEPTION_REGISTRATION) 
			  // 确保pExcptRegHead在堆栈范围内，并且是4的倍数
			  if ( (stackUserBase <= pExcptRegHead )
				  && (stackUserTop >= pStack )
				  && (0 == (pExcptRegHead & 3)) )
			  {
				  DWORD pNewRegistHead;
				  DWORD retValue; 
				  retValue = RtlpExecutehandlerForUnwind(pExcptRec, pExcptRegHead, &context,
					  &pNewRegistHead, pExceptRegHead->handler ); 
				  if ( retValue != DISPOSITION_CONTINUE_SEARCH )
				  {
					  if ( retValue != DISPOSITION_COLLIDED_UNWIND )
					  {
						  excptRec2.ExceptionRecord = pExcptRec;
						  excptRec2.NumberParameters = 0;
						  excptRec2.ExceptionCode = STATUS_INVALID_DISPOSITION;
						  excptRec2.ExceptionFlags = EXCEPTION_NONCONTINUABLE;
						  RtlRaiseException( &excptRec2 );
					  }
					  else
						  pExcptRegHead = pNewRegistHead;
				  } 
				  PEXCEPTION_REGISTRATION pCurrExcptReg = pExcptRegHead;
				  pExcptRegHead = pExcptRegHead->prev;
				  RtlpUnlinkHandler( pCurrExcptReg ); 
			  }
			  else // 堆栈已经被破坏！生成一个异常
			  {
				  excptRec2.ExceptionRecord = pExcptRec;
				  excptRec2.NumberParameters = 0;
				  excptRec2.ExceptionCode = STATUS_BAD_STACK;
				  excptRec2.ExceptionFlags = EXCEPTION_NONCONTINUABLE;
				  RtlRaiseException( &excptRec2 );
			  } 
		  } 
		  // 如果执行到这里，说明已经到了EXCEPTION_REGISTRATION
		  // 结构链表的末尾，正常情况下不应该发生这种情况。
		  //（因为正常情况下异常应该被处理，这样就不会到链表末尾）
		  if ( -1 == pRegistrationFrame )
			  NtContinue( &context, 0 );
		  else
			  NtRaiseException( pExcptRec, &context, 0 ); 
	  } 
	
	  RtlUnwind函数的伪代码到这里就结束了，以下是它调用的几个函数的伪代码： 
		  PEXCEPTION_REGISTRATION RtlpGetRegistrationHead( void )
	  {
		  return FS:[0];
	  } 
	  RtlpUnlinkHandler( PEXCEPTION_REGISTRATION pRegistrationFrame )
	  {
		FS:[0] = pRegistrationFrame->prev;
	  } 
	  void RtlpCaptureContext( CONTEXT * pContext )
	  {
		  pContext->Eax = 0;
		  pContext->Ecx = 0;
		  pContext->Edx = 0;
		  pContext->Ebx = 0;
		  pContext->Esi = 0;
		  pContext->Edi = 0;
		  pContext->SegCs = CS;
		  pContext->SegDs = DS;
		  pContext->SegEs = ES;
		  pContext->SegFs = FS;
		  pContext->SegGs = GS;
		  pContext->SegSs = SS;
		  pContext->EFlags = flags; // 它对应的汇编代码为__asm{ PUSHFD / pop [xxxxxxxx] }
		  pContext->Eip = 此函数的调用者的调用者的返回地址    // 读者看一下这个函数的
			  pContext->Ebp = 此函数的调用者的调用者的EBP        // 汇编代码就会清楚这一点
			  pContext->Esp = pContext->Ebp + 8;
	  }

虽然 RtlUnwind 函数的规模看起来很大，但是如果你按一定方法把它分开，其实并不难理解。它首先从FS:[4]和FS:[8]处获取当前线程堆栈的界限。它们对于后面要进行的合法性检查非常重要，以确保所有将要被展开的异常帧都在堆栈范围内。 

RtlUnwind 接着在堆栈上创建了一个空的EXCEPTION_RECORD结构并把STATUS_UNWIND赋给它的ExceptionCode域，同时把 EXCEPTION_UNWINDING标志赋给它的 ExceptionFlags 域。指向这个结构的指针作为其中一个参数被传递给每个异常回调函数。然后，这个函数调用RtlCaptureContext函数来创建一个空的CONTEXT结构，这个结构也变成了在展开阶段调用每个异常回调函数时传递给它们的一个参数。 

RtlUnwind函数的其余部分遍历EXCEPTION_REGISTRATION结构链表。对于其中的每个帧，它都调用 RtlpExecuteHandlerForUnwind 函数，正是这个函数带 EXCEPTION_UNWINDING 标志调用了异常处理回调函数。RtlpExecuteHandlerForException的代码与RtlpExecuteHandlerForUnwind的代码极其相似。这两个“函数”都只是简单地给EDX寄存器加载一个不同的值然后就调用ExecuteHandler函数。也就是说，RtlpExecuteHandlerForException和RtlpExecuteHandlerForUnwind都是 ExecuteHanlder这个公共函数的前端。 

ExecuteHandler查找EXCEPTION_REGISTRATION结构的handler域的值并调用它。令人奇怪的是，对异常处理回调函数的调用本身也被一个结构化异常处理程序封装着。在SEH自身中使用SEH看起来有点奇怪，但你思索一会儿就会理解其中的含义。如果在异常回调过程中引发了另外一个异常，操作系统需要知道这个情况。根据异常发生在最初的回调阶段还是展开回调阶段，ExecuteHandler或者返回DISPOSITION_NESTED_EXCEPTION，或者返回DISPOSITION_COLLIDED_UNWIND。这两者都是“红色警报！现在把一切都关掉！”类型的代码。
每次回调之后，它调用RtlpUnlinkHandler 移除相应的异常帧。 

RtlUnwind 函数的第一个参数是一个帧的地址，当它遍历到这个帧时就停止展开异常帧。上面所说的这些代码之间还有一些安全性检查代码，它们用来确保不出问题。如果出现任何问题，RtlUnwind 就引发一个异常，指示出了什么问题，并且这个异常带有EXCEPTION_NONCONTINUABLE 标志。当一个进程被设置了这个标志时，它就不允许再运行，必须终止。

参考：

1. A Crash Course on the Depths of Win32™ Structured Exception Handling

2. SEH分析笔记（X86篇）

3. 《软件调试》张银奎 

4. ReactOS源码

5. wrk源码