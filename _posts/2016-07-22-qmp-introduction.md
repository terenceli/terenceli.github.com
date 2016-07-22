---
layout: post
title: "QMP简介"
description: "qemu调试Linux内核"
category: 技术
tags: [虚拟化,QEMU]
---
{% include JB/setup %}


QMP是一种基于JSON格式的传输协议，可以用于与虚拟机的交互，比如查询虚拟机的内部状态，进行设备的热插拔等。

有多种方法使用qmp，这里简要介绍通过tcp和unix socket使用qmp。


<h3>通过TCP使用QMP</h3>

使用-qmp添加qmp相关参数：

	./qemu-system-x86_64 -m 2048 -hda /root/centos6.img -enable-kvm -qmp tcp:localhost:1234,server,nowait

使用telnet连接localhost:1234

	telnet localhost 1234

之后就可以使用qmp的命令和虚拟机交互了

	[root@localhost ~]# telnet localhost 1234
	Trying ::1...
	Connected to localhost.
	Escape character is '^]'.
	{"QMP": {"version": {"qemu": {"micro": 0, "minor": 6, "major": 2}, "package": ""}, "capabilities": []}}
	{ "execute": "qmp_capabilities" }
	{"return": {}}
	{ "execute": "query-status" }
	{"return": {"status": "running", "singlestep": false, "running": true}}

<h3>通过unix socket使用QMP</h3>

使用unix socket创建qmp：

	./qemu-system-x86_64 -m 2048 -hda /root/centos6.img -enable-kvm -qmp unix:/tmp/qmp-test,server,nowait

使用nc连接该socket:

	nc -U /tmp/qmp-test

之后就一样了。

	[root@localhost qmp]# nc -U /tmp/qmp-test
	{"QMP": {"version": {"qemu": {"micro": 0, "minor": 6, "major": 2}, "package": ""}, "capabilities": []}}
	{ "execute": "qmp_capabilities" }
	{"return": {}}
	{ "execute": "query-status" }
	{"return": {"status": "running", "singlestep": false, "running": true}}


QMP的详细命令格式可以在qemu的代码树主目录下面的qmp-commands.hx中找到。

<h3>自动批量发送QMP命令</h3>

可以通过[这里](https://gist.github.com/sibiaoluo/9798832)的方法向虚拟机自动批量的发送QMP命令，这对于测试虚拟机的一些功能是很有用的。试了一下，对于unix socket的方法使能够使用的，对于tcp连接的方法没有使用成功。
为了防止连接失效，代码附在下面：

	# QEMU Monitor Protocol Python class
	#
	# Copyright (C) 2009 Red Hat Inc.
	#
	# This work is licensed under the terms of the GNU GPL, version 2.  See
	# the COPYING file in the top-level directory.
	
	import socket, json, time, commands
	from optparse import OptionParser
	
	class QMPError(Exception):
	    pass
	
	class QMPConnectError(QMPError):
	    pass
	
	class QEMUMonitorProtocol:
	    def connect(self):
	        print self.filename
	        self.sock.connect(self.filename)
	        data = self.__json_read()
	        if data == None:
	            raise QMPConnectError
	        if not data.has_key('QMP'):
	            raise QMPConnectError
	        return data['QMP']['capabilities']
	
	    def close(self):
	        self.sock.close()
	
	    def send_raw(self, line):
	        self.sock.send(str(line))
	        return self.__json_read()
	
	    def send(self, cmdline, timeout=30, convert=True):
	        end_time = time.time() + timeout
	        if convert:
	            cmd = self.__build_cmd(cmdline)
	        else:
	            cmd = cmdline
		    print("*cmdline = %s" % cmd)
	        print cmd
	        self.__json_send(cmd)
	        while time.time() < end_time:
	            resp = self.__json_read()
	            if resp == None:
	                return (False, None)
	            elif resp.has_key('error'):
	                return (False, resp['error'])
	            elif resp.has_key('return'):
	                return (True, resp['return'])
	
	
	    def read(self, timeout=30):
	        o = ""
	        end_time = time.time() + timeout
	        while time.time() < end_time:
	            try:
	                o += self.sock.recv(1024)
	                if len(o) > 0:
	                    break
	            except:
	                time.sleep(0.01)
	        if len(o) > 0:
	            return json.loads(o)
	        else:
	            return None
	
	    def __build_cmd(self, cmdline):
	        cmdargs = cmdline.split()
	        qmpcmd = { 'execute': cmdargs[0], 'arguments': {} }
	        for arg in cmdargs[1:]:
	            opt = arg.split('=')
	            try:
	                value = int(opt[1])
	            except ValueError:
	                value = opt[1]
	            qmpcmd['arguments'][opt[0]] = value
		print("*cmdline = %s" % cmdline)
	        return qmpcmd
	
	    def __json_send(self, cmd):
	        # XXX: We have to send any additional char, otherwise
	        # the Server won't read our input
	        self.sock.send(json.dumps(cmd) + ' ')
	
	    def __json_read(self):
	        try:
	            return json.loads(self.sock.recv(1024))
	        except ValueError:
	            return
	
	    def __init__(self, filename, protocol="tcp"):
	        if protocol == "tcp":
	            self.filename = ("localhost", int(filename))
	            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
	        elif protocol == "unix":
	            self.filename = filename
	            print self.filename
	            self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
	        #self.sock.setblocking(0)
	        self.sock.settimeout(5)
	
	if __name__ == "__main__":
	    parser = OptionParser()
	    parser.add_option('-n', '--num', dest='num', default='10', help='Times want to try')
	    parser.add_option('-f', '--file', dest='port', default='4444', help='QMP port/filename')
	    parser.add_option('-p', '--protocol', dest='protocol',default='tcp', help='QMP protocol')
	    def usage():
	        parser.print_help()
	        sys.exit(1)
	
	    options, args = parser.parse_args()
	
	    print options
	    if len(args) > 0:
	        usage()
	
	    num = int(options.num)
	    qmp_filename = options.port
	    qmp_protocol = options.protocol
	    qmp_socket = QEMUMonitorProtocol(qmp_filename,qmp_protocol)
	    qmp_socket.connect()
	    qmp_socket.send("qmp_capabilities")
	    qmp_socket.close()
	
	
	##########################################################
	#Usage
	#Options:
	#  -h, --help            show this help message and exit
	#  -n NUM, --num=NUM     Times want to try
	#  -f PORT, --file=PORT  QMP port/filename
	#  -p PROTOCOL, --protocol=PROTOCOL
	#                        QMP protocol
	# e.g: # python xxxxx.py -n $NUM -f $PORT
	##########################################################
	
	
