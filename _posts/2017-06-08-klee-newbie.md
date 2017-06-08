---
layout: post
title: "Ubuntu 16.04安装KLEE"
description: "klee"
category: 技术
tags: [符号执行]
---
{% include JB/setup %}

符号执行也算是阳春白雪了，不研究一下都不好意思说你是搞安全的。据说这也是大坑，到哪是哪。
本文主要记录Ubuntu 16.04下面安装KLEE的过程，使用的clang/llvm是3.9的。整体还是按照官网来的，一些容易出错的地方记录一下。

<h3>1. 安装依赖库</h3>

	$ sudo apt-get install build-essential curl libcap-dev git cmake libncurses5-dev python-minimal python-pip unzip

<h3>2. 安装LLVM 3.9</h3>

这一步直接用安装packages就行，[LLVM Package Repository](http://apt.llvm.org/)选
llvm3.9添加到/etc/apt/sources.list

	deb http://apt.llvm.org/xenial/ llvm-toolchain-xenial-3.9 main
	deb-src http://apt.llvm.org/xenial/ llvm-toolchain-xenial-3.9 main

添加repository key并下载llvm 3.9的packages

	$ wget -O - http://llvm.org/apt/llvm-snapshot.gpg.key|sudo apt-key add -  
	$ sudo apt-get update  
	$ sudo apt-get install clang-3.9 llvm-3.9 llvm-3.9-dev llvm-3.9-tools 

注意这个时候/usr/bin/clang-3.9是在PATH里面，为了使用clang以及其他不带3.9后缀的版本
，需要在~/.profile里面改一下PATH：

	export PATH="/usr/lib/llvm-3.9/bin:$PATH"

<h3>3. 安装constraint solver

KLEE支持几种约束求解器，这里我用的是[Z3](https://github.com/z3prover/z3)，这个
按照官网编译就好。

<h3>4. 编译uclibc and the POSIX environment model</h3>

	$ git clone https://github.com/klee/klee-uclibc.git  
	$ cd klee-uclibc  
	$ ./configure --make-llvm-lib  
	$ make -j2  

<h3>5. Get Google test sources</h3>

	$ curl -OL https://github.com/google/googletest/archive/release-1.7.0.zip
	$ unzip release-1.7.0.zip

<h3>6. Install lit</h3>

用sudo安装

	$ sudo pip install lit

<h3>7. Install tcmalloc</h3>

	$ sudo apt-get install libtcmalloc-minimal4 libgoogle-perftools-dev


<h3>8. 得到KLEE源码</h3>

由于我们用的是llvm 3.9，直接用官方的KLEE会出现下列问题：

	/home/test/klee/include/klee/Internal/Support/FloatEvaluation.h: In function ‘bool klee::floats::isNaN(uint64_t, unsigned int)’:
	/home/test/klee/include/klee/Internal/Support/FloatEvaluation.h:135:25: error: ‘IsNAN’ is not a member of ‘llvm’
	case FLT_BITS: return llvm::IsNAN( UInt64AsFloat(l) );
							^
	/home/test/klee/include/klee/Internal/Support/FloatEvaluation.h:136:25: error: ‘IsNAN’ is not a member of ‘llvm’
	case DBL_BITS: return llvm::IsNAN( UInt64AsDouble(l) );
							^
	/home/test/klee/lib/Core/Executor.cpp: In member function ‘void klee::Executor::executeCall(klee::ExecutionState&, klee::KInstruction*, llvm::Function*, std::vector<klee::ref<klee::Expr> >&)’:
	/home/test/klee/lib/Core/Executor.cpp:1403:21: error: ‘RoundUpToAlignment’ is not a member of ‘llvm’
				size = llvm::RoundUpToAlignment(size, 16);

好在有人提供了一个llvm 3.9的[pr](https://github.com/klee/klee/pull/605/commits/5c4d9bc67e43e4a97391105dfc6a286215897fdb)
我们直接clone这个人的repo。

	test@ubuntu:~$ git clone https://github.com/jirislaby/klee.git
	test@ubuntu:~$ cd klee
	test@ubuntu:~/klee$ git branch -a
	* master
	remotes/origin/HEAD -> origin/master
	remotes/origin/better-paths
	remotes/origin/errno
	remotes/origin/llvm40_WallTimer
	remotes/origin/llvm40_opt_end
	remotes/origin/llvm40_static_casts
	remotes/origin/llvm_37
	remotes/origin/llvm_39
	remotes/origin/master
	test@ubuntu:~/klee$ git checkout remotes/origin/llvm_39

<h3>9. 配置KLEE</h3>

	$ mkdir klee_build_dir
	$ cd klee_build_dir
	$ cmake -DENABLE_SOLVER_Z3=ON \
		-DENABLE_POSIX_RUNTIME=ON  \
		-DENABLE_KLEE_UCLIBC=ON \
		-DKLEE_UCLIBC_PATH=../klee-uclibc \
		-DGTEST_SRC_DIR=../googletest-release-1.7.0  \
		-DENABLE_SYSTEM_TESTS=ON  \
		-DENABLE_UNIT_TESTS=ON \
		../klee

如果这一步出现找不到Doxygen，需要安装

	$ sudo apt-get install doxygen

如果出现ZLIB\_LIBRARY (ADVANCED)，需要自己下载zlib安装。

<h3>10. 编译安装KLEE</h3>

	$ make
	$ sudo make install

这一步出现了一个错误：

	make[2]: *** No rule to make target '/usr/lib/llvm-3.9/lib/liblibLLVM-3.9.so.so', needed by 'bin/gen-random-bout'.  Stop.

找不到这个so,一看名字liblibLLVM-3.9.so.so，太怪异了，目测是脚本的问题。

	test@ubuntu:~/klee_build_dir$ cd /usr/lib/llvm-3.9/lib
	test@ubuntu:/usr/lib/llvm-3.9/lib$ ls

	libLLVM-3.9.1.so                                       libLLVMX86AsmParser.a
	libLLVM-3.9.1.so.1                                     libLLVMX86AsmPrinter.a
	libLLVM-3.9.so                                         libLLVMX86CodeGen.a
	libLLVM-3.9.so.1                                       libLLVMX86Desc.a

简单的解决办法：

	$ ln -l libLLVM-3.9.so liblibLLVM-3.9.so.so

这样就把KLEE的环境搞好了，可以安装Tutorial搞起来了。



