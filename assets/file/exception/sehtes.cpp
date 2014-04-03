// sehtes.cpp : Defines the entry point for the console application.
//

#include "stdafx.h"
//ShowSEHFrames.CPP 
//=========================================================
// ShowSEHFrames - Matt Pietrek 1997
// Microsoft Systems Journal, February 1997
// FILE: ShowSEHFrames.CPP
// 使用命令行CL ShowSehFrames.CPP进行编译
//========================================================= 
#define WIN32_LEAN_AND_MEAN 
#include <windows.h>
#include <stdio.h> 
#pragma hdrstop 
//-------------------------------------------------------------------
// 本程序仅适用于Visual C++，它使用的数据结构是特定于Visual C++的
//------------------------------------------------------------------- 
#ifndef _MSC_VER
#error Visual C++ Required (Visual C++ specific information is displayed)
#endif 
//-------------------------------------------------------------------
// 结构定义
//------------------------------------------------------------------- 

// 操作系统定义的基本异常帧
struct EXCEPTION_REGISTRATION
{
	EXCEPTION_REGISTRATION* prev;
	FARPROC handler;
}; 
// Visual C++扩展异常帧指向的数据结构
struct scopetable_entry
{
	DWORD previousTryLevel;
	FARPROC lpfnFilter;
	FARPROC lpfnHandler;
}; 
// Visual C++使用的扩展异常帧
struct VC_EXCEPTION_REGISTRATION : EXCEPTION_REGISTRATION
{
	scopetable_entry * scopetable;
	int trylevel;
	int _ebp;
}; 
//----------------------------------------------------------------
// 原型声明
//---------------------------------------------------------------- 
// __except_handler3是Visual C++运行时库函数，我们想打印出它的地址
// 但是它的原型并没有出现在任何头文件中，所以我们需要自己声明它。
extern "C" int _except_handler3(PEXCEPTION_RECORD,
			EXCEPTION_REGISTRATION *,
			PCONTEXT,
			PEXCEPTION_RECORD); 
//-------------------------------------------------------------
// 代码
//------------------------------------------------------------- 
//
// 显示一个异常帧及其相应的scopetable的信息
//
void ShowSEHFrame( VC_EXCEPTION_REGISTRATION * pVCExcRec )
{
	printf( "Frame: %08X Handler: %08X Prev: %08X Scopetable: %08X\n",
		pVCExcRec, pVCExcRec->handler, pVCExcRec->prev,
		pVCExcRec->scopetable ); 
	scopetable_entry * pScopeTableEntry = pVCExcRec->scopetable; 
	for ( unsigned i = 0; i <= pVCExcRec->trylevel; i++ )
	{
		printf( " scopetable[%u] PrevTryLevel: %08X "
			"filter: %08X __except: %08X\n", i,
			pScopeTableEntry->previousTryLevel,
			pScopeTableEntry->lpfnFilter,
			pScopeTableEntry->lpfnHandler ); 
		pScopeTableEntry++;
	} 
	printf( "\n" ); 
} 

//
// 遍历异常帧的链表，按顺序显示它们的信息
//
void WalkSEHFrames( void )
{
	VC_EXCEPTION_REGISTRATION * pVCExcRec; 
	// 打印出__except_handler3函数的位置
	printf( "_except_handler3 is at address: %08X\n", _except_handler3 );
	printf( "\n" ); 
	// 从FS:[0]处获取指向链表头的指针
	__asm mov eax, FS:[0]
	__asm mov [pVCExcRec], EAX 
		// 遍历异常帧的链表。0xFFFFFFFF标志着链表的结尾
		while ( 0xFFFFFFFF != (unsigned)pVCExcRec )
		{
			ShowSEHFrame( pVCExcRec );
			pVCExcRec = (VC_EXCEPTION_REGISTRATION *)(pVCExcRec->prev);
		} 
} 

void Function1( void )
{
	int i;
	// 嵌套3层__try块以便强制为scopetable数组产生3个元素
	__try
	{
		__try
		{
			__try
			{
				i = i/0;
				WalkSEHFrames(); // 现在显示所有的异常帧的信息
			} __except( EXCEPTION_CONTINUE_SEARCH )
			{}
		} __except( EXCEPTION_CONTINUE_SEARCH )
		{}
	} __except( EXCEPTION_CONTINUE_SEARCH )
	{} 
} 

int main() 
{
	int i; 
	// 使用两个__try块（并不嵌套），这导致为scopetable数组生成两个元素
	__try
	{
		i = 0x1234;
		
	} __except( EXCEPTION_EXECUTE_HANDLER )
	{
		printf("div0 occur!\n");
	} 
	__try
	{
		Function1(); // 调用一个设置更多异常帧的函数
	} __except( EXCEPTION_EXECUTE_HANDLER )
	{
		// 应该永远不会执行到这里，因为我们并没有打算产生任何异常
		printf( "Caught Exception in main\n" );
	} 
	return 0; 
}