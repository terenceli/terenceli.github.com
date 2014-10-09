---
layout: post
title: "Linux文件扩展属性以及从内核中获得文件扩展属性"
description: "从内核中获取文件EA"
category: 技术
tags: [Linux内核]
---
{% include JB/setup %}

扩展属性(EA)就是以名称-值对形式将任意元数据与文件i节点关联起来的技术。EA可以用于实现访问列表和文件能力，还可以利用EA去记录文件的版本号、与文件的MIME类型/字符集有关的信息等，反正想干嘛就干嘛吧。

EA的命名格式为namespace.name。其中namespace用来把EA从功能上划分为截然不同的几大类，而name则用来在既定命名空间内唯一标示某个EA。

Linux定义了4中namespace：user、trusted、system和security。

* user EA:在文件权限检查的制约下由非特权级进程操控。
* trusted EA:也可由用户进程“驱使”，与user EA相似。区别在于，要操纵trusted EA，进程必须具有特权(CAP_SYS_ADMIN)。
* system EA:供内核使用，将系统对象与一文件关联。目前仅支持访问控制列表。
* security EA:作用有二：其一，用来存储服务于操作系统安全模块的文件安全标签；其二，将可执行文件与能力关联起来。

		kvm@ubuntu:~$ touch filetest
		kvm@ubuntu:~$ setfattr -n user.x -v "The past is not dead." filetest 
		kvm@ubuntu:~$ setfattr -n user.y -v "In fact,it's not even past." filetest 
		kvm@ubuntu:~$ getfattr -n user.x filetest 
		# file: filetest
		user.x="The past is not dead."
		
		kvm@ubuntu:~$ getfattr -d filetest 
		# file: filetest
		user.x="The past is not dead."
		user.y="In fact,it's not even past."
		
		kvm@ubuntu:~$ setfattr -n user.x filetest    //设置EA的值为一个空字符串
		kvm@ubuntu:~$ getfattr -d filetest 
		# file: filetest
		user.x
		user.y="In fact,it's not even past."
		
		kvm@ubuntu:~$ setfattr -x user.y filetest //删除一个EA
		kvm@ubuntu:~$ getfattr -d filetest 
		# file: filetest
		user.x
		
应用层的函数就不说了，下面简单介绍一下在内核层中获取文件的EA。一小段测试代码如下，主要是通过inode结构中操作getxattr来得到，当然之前需要得到dentry。

	static int hello_init()
	{
		struct file *f;
		struct inode *node;
		struct dentry *dent;
		int rc;
		char in[100];
		printk(KERN_ALERT "Hello, world\n");
		printk(KERN_ALERT "name:%s\n",current->comm);
		f = filp_open("/home/kvm/tfile",O_RDONLY,0);
		dent = f->f_path.dentry;
		node = dent->d_inode;
		if (node->i_op->getxattr == NULL)
		{
		    printk("inode's getxattr is null!\n");
		    return 0;
		}
		rc = node->i_op->getxattr(dent, "user.x", in, 100);
		if (rc < 0)
			return 0;
		printk("the user.x is:%s\n",in);
		return 0;
	}


输出为：

	the user.x is:The past is not dead.