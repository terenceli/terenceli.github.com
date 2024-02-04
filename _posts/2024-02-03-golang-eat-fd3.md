---
layout: post
title: "CVE-2021-3493 Ubuntu overlayfs privilege escalation vulnerability analysis"
description: "Ubuntu overlayfs vulnerability"
category: 技术
tags: [漏洞分析]
---
{% include JB/setup %}


Recently I analyzed the runc vulnerability CVE-2024-21626. The root cause of this vulnerability is that a cgroup fd is leaked to 'runc init' process. While digging into the root cause, I found something interesting of Golang's fd inheritance. This post describes the founding in detail.
First we need have a look at CVE-2024-21626.

<h3> CVE-2024-21626 analysis </h3>

<h4> runc double clone process </h4>

While creating the container environment, runc uses double clone method to do the complicated separated things. Following pic shows the process.

![](/assets/img/golangeatfd3/1.png)


runc first start runc[0:PARNET] process, the runc[0:PARENT] will clone a runc[1:CHILD] process, runc[1:CHILD] process will clone runc[2:INIT] process and finally the runc[2:INIT] process will execute the specified process in OCI configuration.

<h4> runc fd leak vulnerability </h4>

runc[2:INIT] will do the final work such as prepare the rootfs and change to rootfs, find the executable before executing the container process. In this process, the fd can be leaked to container process. As the fd is point to a file in the host filesystem if the container process can see this fd, it can break out container environment by leveraging  this fd. runc has several this kind of vulnreability in history, the most famous is CVE-2019-5736. The root cause of CVE-2019-5736 is that the container process can see /proc/self/exe which is point to the host runc binary. Following pic(from https://blog.wohin.me/posts/hack-runc-elf-inject/) show the root cause of CVE-2019-5736 and how to exploit it.


![](/assets/img/golangeatfd3/2.png)


<h4> CVE-2024-21626 </h4>

The root cause of this vulnerability is that a fd point /sys/fs/cgroup directory is leaked to runc init process. The leak happens here in file libcontainer/cgroups/file.go:


                func prepareOpenat2() error {
                        prepOnce.Do(func() {
                                fd, err := unix.Openat2(-1, cgroupfsDir, &unix.OpenHow{
                                        Flags: unix.O_DIRECTORY | unix.O_PATH, // no unix.O_CLOEXEC flag
                                })
                ...


The unix.Openat2 is used to open the cgroupfsDir(/sys/fs/cgroup) without unix.O_CLOEXEC flag set. After runc init execve the container process this fd will not be closed thus leaked to the container process.
When we add a Sleep code in runc init, we can see following:


![](/assets/img/golangeatfd3/3.png)


As we can see the fd 7 point to the /sys/fs/cgroup. We can set the 'cwd' in OCI config to '/proc/self/fd/7/../../../../', when the container process runs, our current working directory will point to the host rootfs.
Using following 'args' and 'cwd' to run a container


                "args": [
                        "cat", "hostfile"
                ],
                ...
                "cwd": "/proc/self/fd/7/../../../../",


We can see the container process read the file success.


![](/assets/img/golangeatfd3/4.png)


It seems not difficult to understand this vulnerability. But while reading the fix patches, I found something interesting. The first is after apply the backported commit [937ca107c3d22da77eb8e8030f2342253b980980](https://github.com/opencontainers/runc/pull/4004/commits/937ca107c3d22da77eb8e8030f2342253b980980) I can't see the fd leak. And also I see this words


        In practice, on runc 1.1 this does leak to "runc init" but on main the
        handle has a low enough file descriptor that it gets clobbered by the
        ForkExec of "runc init".


I want to know how it gets 'clobbered'.  And in cgroup v2 this issue is doesn't exist. runc exec doesn't trigger this issue.
In summary there are several issues that have been attracted my attention. 

1. Why the main branch doesn't affected by this CVE
2. Why cgroup v2 doesn't doesn't affected by this CVE
3. Why the first patch mitigates this CVE
4. Why 'run exec' doesn't trigger this CVE

I decided to dig into this issue. 

<h3> The fd inheritance in Golang cmd Run </h3>

First of all, I need to find out the fd inheritance about the os.Open and syscall.Openat2 as the first one related to commit [937ca107c3d22da77eb8e8030f2342253b980980](https://github.com/opencontainers/runc/pull/4004/commits/937ca107c3d22da77eb8e8030f2342253b980980) and the second related to the fd leak. I write two simple program, the first is 'wait', it is just used to be launched by another program 'test'. After the start wait, we can see the fd status of these two process.


                //wait
                package main
                import "time"
                func main() {
                time.Sleep(20 * time.Second)
                }

<h4> os.Open fd </h4>


Using following 'test':


        os.Open("/home/test")
        cmd := exec.Command("/home/test/go/src/test/wait")
        cmd.Run()


![](/assets/img/golangeatfd3/5.png)


cmd.Run uses ForkExecve to start a new process. As we can see, the child process (runc init) doesn't inherit the fd opend by os.Open. This is because that os.Open adds the O_CLOEXEC, so every file opened by os.Open will be closed after execve. The source code can be found [here](https://github.com/golang/go/blob/master/src/os/file_unix.go#L272):


                func openFileNolog(name string, flag int, perm FileMode) (*File, error) {
                        ...
                        var r int
                        var s poll.SysFile
                        for {
                                var e error
                                r, s, e = open(name, flag|syscall.O_CLOEXEC, syscallMode(perm))
                ...


<h4> syscall.Openat2 fd </h4>

Let's see the behaviour of syscall.Openat2. Use following 'test':


        unix.Openat2(-1, "/sys/fs/cgroup", &unix.OpenHow{
                                Flags: unix.O_DIRECTORY | unix.O_PATH})

        cmd := exec.Command("/home/test/go/src/test/wait")
        cmd.Run()


As we can see the "/sys/fs/cgroup" fd in the child process.


![](/assets/img/golangeatfd3/6.png)


So the fd opened by 'unix.Openat2' will not be closed after ForkExecve.


<h4> The magick </h4>

When I just apply the commit [937ca107c3d22da77eb8e8030f2342253b980980](https://github.com/opencontainers/runc/pull/4004/commits/937ca107c3d22da77eb8e8030f2342253b980980) the interesting things happen. Though the 'runc runc' has a fd point to '/sys/fs/cgroup' the 'runc init' has no this fd. The cgroupfd in ' tryDefaultCgroupRoot' function will be closed after apply the 937c commit. So the 'runc run' fd 3 is the fd in 'prepareOpenat2' function.


![](/assets/img/golangeatfd3/7.png)


But as we can see in our previous test, the fd opend by 'syscall.Openat2' will be inherited by child process. We don't see the fd in child process. What's wrong?
After I navigating  the runc code and do some experiment I found the most different between the 'runc' start a new process with my test is that in the runc case before it call cmd.Run it also set cmd.ExtraFiles. 
Let's do the following test.


        unix.Openat2(-1, "/sys/fs/cgroup", &unix.OpenHow{
                                Flags: unix.O_DIRECTORY | unix.O_PATH})

        cmd := exec.Command("/home/test/go/src/test/wait")
        cmd.SysProcAttr = &unix.SysProcAttr{}
        pipeRead, pipeWrite, _ := os.Pipe()
        defer pipeRead.Close()
        defer pipeWrite.Close()

        cmd.ExtraFiles = []*os.File{pipeWrite}
        cmd.Run()


Following is the fd of parent and child process.


![](/assets/img/golangeatfd3/8.png)


We have reproduced the issue, the fd 3 is eaten by Golang after cmd.Run if we add cmd.ExtraFiles. What if we open two fd by unix.Openat2?


        unix.Openat2(-1, "/sys/fs/cgroup", &unix.OpenHow{
                                Flags: unix.O_DIRECTORY | unix.O_PATH})
        unix.Openat2(-1, "/home/test", &unix.OpenHow{
                                Flags: unix.O_DIRECTORY | unix.O_PATH})
        cmd := exec.Command("/home/test/go/src/test/wait")
        cmd.SysProcAttr = &unix.SysProcAttr{}
        pipeRead, pipeWrite, _ := os.Pipe()
        defer pipeRead.Close()
        defer pipeWrite.Close()
        cmd.ExtraFiles = []*os.File{pipeWrite}
        cmd.Run()


As we can see only the fd 3 is eaten.


![](/assets/img/golangeatfd3/9.png)


After read the go source and document, I found following words in https://pkg.go.dev/os/exec.


![](/assets/img/golangeatfd3/10.png)


ExtraFiles is used to specify the open files to be inherited by the child process. and entry i becomes file descriptor 3+i as the first three is standard input/output/error. If we add two ExtraFiles we can see our fd 4 is also eaten.


![](/assets/img/golangeatfd3/11.png)


Now it's clear that the cmd.ExtraFiles will be guaranteed to be seen in child process. And it may overwrites the fds inherited from parent.


<h3> Conclusion </h3>

<h4> About the CVE-2024-21626 </h4>

After the investigation, we can now have the full picture of CVE-2024-21626.
The root cause of this CVE is that a cgroupfd is leaked to 'runc init'. This cgroupfd is opend in prepareOpenat2 using syscall.Openat2 without O_CLOEXEC flag set. So this fd is leaked to 'runc init'. 
The main branch is not affected because it has commit [937ca107c3d22da77eb8e8030f2342253b980980](https://github.com/opencontainers/runc/pull/4004/commits/937ca107c3d22da77eb8e8030f2342253b980980). This commit close another opened cgroupfd in time. So the prepareOpenat2 fd open will hold the fd 3. and it is low enough it will be clobbered by cmd.Run(forkExecve). 
The cgroup v2 is not affected is that tryDefaultCgroupRoot open cgroupfd only in cgroup v1, so even it has no commit 937c the prepareOpenat2 fd will be 3.
The 'run exec' doesn't trigger this CVE is because the tryDefaultCgroupRoot will only be called in 'runc init' process not in 'runc exec' so the prepareOpenat2 fd will be 3.


<h4> Golang fd inheritance after cmd Run </h4>


Three things get from this CVE.
1. os.Open fd will automatically closed as Golang adds O_CLOEXEC implicitly
2. syscall.Openat2 fd will not be closed automatically and will be inherited by child process even this is unwanted
3. Golang only guarantees that the cmd.ExtraFiles will be inherited by child process and it may destroy the unwanted inherited fd.


<h3> Ref </h3>

The runc internals(written by myself): https://terenceli.github.io/%E6%8A%80%E6%9C%AF/2021/12/28/runc-internals-3
