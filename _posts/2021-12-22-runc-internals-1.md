---
layout: post
title: "runc internals, part 1: usage, build and source architecture"
description: "runc"
category: 技术
tags: [container, runc]
---
{% include JB/setup %}


[runc](https://github.com/opencontainers/runc) is the foundation of container technology. The idea of container is simple, put some process into a separate namespace and use cgroups to restrict these process' resource usage and use overlayfs as filesystem for container. So it seems that the runc's work is easy, just prepare the environment for container process and run it. In reality, it is not so easy. This serials will try to do a deep analysis of runc's internal. This is the first part, how to use and build runc and the runc's source code architecture.

<h3> install Go </h3>

Download Go binary from [here](https://go.dev/dl/), we uses 'go1.17.5.linux-amd64.tar.gz'. 

        wget https://go.dev/dl/go1.17.5.linux-amd64.tar.gz

Decompress it to /usr/local binary:

        tar -C /usr/local -xzf go1.17.5.linux-amd64.tar.gz

And go binary to $PATH and set the GOPATH and GOROOT directory, add following lines to ~/.profile

        export PATH=/usr/local/go/bin:$PATH
        export GOROOT=/usr/local/go
        export GOPATH=/home/test/go

Enable the setting:

        source  ~/.profile
        mkdir /home/test/go/bin
        mkdir /home/test/go/src
        mkdir /home/test/go/src


<h3> build runc </h3>

As the , first README.md of runc, install libseccomp-dev pkg:

        apt install libseccomp-dev

clone runc:

        mkdir /home/test/go/src/github.com/opencontainers
        cd /home/test/go/src/github.com/opencontainers
        git clone https://github.com/opencontainers/runc
        cd runc

Change the runc Makefile following two lines, add <b>-gcflags "-N -l"</b>:

        GO_BUILD := $(GO) build -trimpath $(GO_BUILDMODE) $(EXTRA_FLAGS) -tags "$(BUILDTAGS)" \
            -ldflags "-X main.gitCommit=$(COMMIT) -X main.version=$(VERSION) $(EXTRA_LDFLAGS)" -gcflags "-N -l"
        GO_BUILD_STATIC := CGO_ENABLED=1 $(GO) build -trimpath $(EXTRA_FLAGS) -tags "$(BUILDTAGS) netgo osusergo" \
            -ldflags "-extldflags -static -X main.gitCommit=$(COMMIT) -X main.version=$(VERSION) $(EXTRA_LDFLAGS)" -gcflags "-N -l"


build runc

        make
        make install


<h3> runc usage </h3>

        # create the top most bundle directory
        mkdir /mycontainer
        cd /mycontainer

        # create the rootfs directory
        mkdir rootfs

        # export busybox via Docker into the rootfs directory
        docker export $(docker create busybox) | tar -C rootfs -xvf -

        runc spec
        runc run test

Now we run a container.

Let's debug runc. In order to let the runc find the source directory 'github.com/opencontainers/runc/', I copy 'runc' binary to '/home/test/go/src'. 

        root@ubuntu:~/go/src# gdb --args ./runc  run --bundle /home/test/mycontainer/ test
        ...
        (gdb) b main.startContainer
        Breakpoint 1 at 0x60d100: file github.com/opencontainers/runc/utils_linux.go, line 374.
        (gdb) r
        Starting program: /home/test/go/src/runc run --bundle /home/test/mycontainer/ test
        ....

        Thread 1 "runc" hit Breakpoint 1, main.startContainer (context=0xc000144840, action=2 '\002', criuOpts=0x0, ~r3=824635577192, ~r4=...)
            at github.com/opencontainers/runc/utils_linux.go:374
        374	func startContainer(context *cli.Context, action CtAct, criuOpts *libcontainer.CriuOpts) (int, error) {
        (gdb) n
        375		if err := revisePidFile(context); err != nil {
        (gdb) n
        378		spec, err := setupSpec(context)
        (gdb) n
        379		if err != nil {
        (gdb) p spec
        $1 = (github.com/opencontainers/runtime-spec/specs-go.Spec *) 0xc000170380
        (gdb) p *spec
        $2 = {Version = 0xc0002067f0 "1.0.2-dev", Process = 0xc00020c000, Root = 0xc000127e90, Hostname = 0xc0002068b8 "runc", Mounts = {array = 0xc000184580, 
            len = 7, cap = 9}, Hooks = 0x0, Annotations = 0x0, Linux = 0xc00020c0f0, Solaris = 0x0, Windows = 0x0, VM = 0x0}
        (gdb) p *spec.Process 
        $3 = {Terminal = true, ConsoleSize = 0x0, User = {UID = 0, GID = 0, Umask = 0x0, AdditionalGids = {array = 0x0, len = 0, cap = 0}, Username = 0x0 ""}, 
        Args = {array = 0xc000149440, len = 1, cap = 4}, CommandLine = 0x0 "", Env = {array = 0xc000149480, len = 2, cap = 4}, Cwd = 0x5555561ba178 "/", 
        Capabilities = 0xc000170400, Rlimits = {array = 0xc000170480, len = 1, cap = 4}, NoNewPrivileges = true, ApparmorProfile = 0x0 "", OOMScoreAdj = 0x0, 
        SelinuxLabel = 0x0 ""}
        (gdb) 

<h3> runc source architecture </h3>

Following shows the source code architecture of runc

![](/assets/img/runcinternals1/1.png)


The runc binary has several subcommands, every handler is in the go file of root directory. The core code of runc is the libcontainer directory. In the next post I will analysis the runc create and start command.

<h3> reference </h3>

[探索 runC (上)](https://yacanliu.gitee.io/runc-1.html)