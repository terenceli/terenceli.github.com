// sehtes.cpp : Defines the entry point for the console application.
//

#include "stdafx.h"
//ShowSEHFrames.CPP 
//=========================================================
// ShowSEHFrames - Matt Pietrek 1997
// Microsoft Systems Journal, February 1997
// FILE: ShowSEHFrames.CPP
// ʹ��������CL ShowSehFrames.CPP���б���
//========================================================= 
#define WIN32_LEAN_AND_MEAN 
#include <windows.h>
#include <stdio.h> 
#pragma hdrstop 
//-------------------------------------------------------------------
// �������������Visual C++����ʹ�õ����ݽṹ���ض���Visual C++��
//------------------------------------------------------------------- 
#ifndef _MSC_VER
#error Visual C++ Required (Visual C++ specific information is displayed)
#endif 
//-------------------------------------------------------------------
// �ṹ����
//------------------------------------------------------------------- 

// ����ϵͳ����Ļ����쳣֡
struct EXCEPTION_REGISTRATION
{
	EXCEPTION_REGISTRATION* prev;
	FARPROC handler;
}; 
// Visual C++��չ�쳣ָ֡������ݽṹ
struct scopetable_entry
{
	DWORD previousTryLevel;
	FARPROC lpfnFilter;
	FARPROC lpfnHandler;
}; 
// Visual C++ʹ�õ���չ�쳣֡
struct VC_EXCEPTION_REGISTRATION : EXCEPTION_REGISTRATION
{
	scopetable_entry * scopetable;
	int trylevel;
	int _ebp;
}; 
//----------------------------------------------------------------
// ԭ������
//---------------------------------------------------------------- 
// __except_handler3��Visual C++����ʱ�⺯�����������ӡ�����ĵ�ַ
// ��������ԭ�Ͳ�û�г������κ�ͷ�ļ��У�����������Ҫ�Լ���������
extern "C" int _except_handler3(PEXCEPTION_RECORD,
			EXCEPTION_REGISTRATION *,
			PCONTEXT,
			PEXCEPTION_RECORD); 
//-------------------------------------------------------------
// ����
//------------------------------------------------------------- 
//
// ��ʾһ���쳣֡������Ӧ��scopetable����Ϣ
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
// �����쳣֡��������˳����ʾ���ǵ���Ϣ
//
void WalkSEHFrames( void )
{
	VC_EXCEPTION_REGISTRATION * pVCExcRec; 
	// ��ӡ��__except_handler3������λ��
	printf( "_except_handler3 is at address: %08X\n", _except_handler3 );
	printf( "\n" ); 
	// ��FS:[0]����ȡָ������ͷ��ָ��
	__asm mov eax, FS:[0]
	__asm mov [pVCExcRec], EAX 
		// �����쳣֡������0xFFFFFFFF��־������Ľ�β
		while ( 0xFFFFFFFF != (unsigned)pVCExcRec )
		{
			ShowSEHFrame( pVCExcRec );
			pVCExcRec = (VC_EXCEPTION_REGISTRATION *)(pVCExcRec->prev);
		} 
} 

void Function1( void )
{
	int i;
	// Ƕ��3��__try���Ա�ǿ��Ϊscopetable�������3��Ԫ��
	__try
	{
		__try
		{
			__try
			{
				i = i/0;
				WalkSEHFrames(); // ������ʾ���е��쳣֡����Ϣ
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
	// ʹ������__try�飨����Ƕ�ף����⵼��Ϊscopetable������������Ԫ��
	__try
	{
		i = 0x1234;
		
	} __except( EXCEPTION_EXECUTE_HANDLER )
	{
		printf("div0 occur!\n");
	} 
	__try
	{
		Function1(); // ����һ�����ø����쳣֡�ĺ���
	} __except( EXCEPTION_EXECUTE_HANDLER )
	{
		// Ӧ����Զ����ִ�е������Ϊ���ǲ�û�д�������κ��쳣
		printf( "Caught Exception in main\n" );
	} 
	return 0; 
}