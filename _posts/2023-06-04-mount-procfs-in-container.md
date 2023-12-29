---
layout: post
title: "mount procfs in unprivileged container"
description: "mount procfs in contianer"
category: 技术
tags: [容器, gVisor]
---
{% include JB/setup %}



<h3> Background </h3>

gVisor is an application kernel that implements a substantial portion of the Linux system surface. gVisor is mostly used in cloud native as it implements an OCI runtime runsc. runsc uses the application kernel which is named Sentry to run the user's application. By this mean, the application doesn't share the same kernel with the host like what runc does which largely reduce the attack surface in container ecosystem.
gVisor is quite interesting that it rewrites the Linux syscall interface. The foundation of gVisor is system call interception. gVisor has three means of system call interception, ptrace, kvm and systrap. gVisor uses these interception means to intercept the user's application syscall and reimplements it in Sentry.
Though gVisor is used mostly in cloud native ecosystem, it is useful in process-level sandbox. I have designed a process-level sandbox based gVisor to sandbox the dangerous third party program.
Recently I encounter a problem that run gVisor in unprivileged container like docker or podman. When I run gVisor in docker it returns an EPERM error code. Following shows the error.


                # docker run -it --rm --security-opt apparmor=unconfined --security-opt seccomp=unconfined   ubuntu
                root@21adbdee0c6d:/# cd /tmp
                root@21adbdee0c6d:/tmp# ./runsc  -rootless --debug --debug-log=/tmp/log/ do ls
                *** Warning: sandbox network isn't supported with --rootless, switching to host ***
                creating container: cannot create sandbox: cannot read client sync file: waiting for sandbox to start: EOF
                root@21adbdee0c6d:/tmp# cd log/
                root@21adbdee0c6d:/tmp/log# ls
                ...
                W1227 04:54:24.366822       1 specutils.go:124] noNewPrivileges ignored. PR_SET_NO_NEW_PRIVS is assumed to always be set.
                W1227 04:54:24.366995       1 util.go:64] FATAL ERROR: error mounting proc: operation not permitted
                error mounting proc: operation not permitted
                root@21adbdee0c6d:/tmp/log#


After navigating the code, I found the error occurs in [mount procfs](https://github.com/google/gvisor/blob/master/runsc/cmd/gofer.go#L394C21-L394C21).
The error is that mount procfs in docker container return EPERM. 

<h3> Analysis </h3>

The mount syscall has several point to return EPERM. We need find which point it is that cause our gVisor failed.
I used following method. First patch the gVisor to add sleep code before the mount procfs error. Then we run runsc. The gofer process(which the mount failed occurs) will sleep.  We uses trace-cmd to trace the gofer process' kernel function call.


                trace-cmd record -P <goferpid> function_graph

After look at the trace output, I find the suspicious function. 



                |      security_sb_kern_mount();
                |      mount_too_revealing() {
                |        down_read() {
                |          __cond_resched();
                |        }
                |        _raw_spin_lock();
                |        _raw_spin_unlock();
                |        up_read();
                |      }
                |      fc_drop_locked() {


From the code we can found the 'mount_too_revealing' return true and should be responsible for our EPERM. 'mount_too_revealing' calls 'mnt_already_visible' to do the decision. As my [previous blog](https://terenceli.github.io/%E6%8A%80%E6%9C%AF/2022/03/06/cve-2022-0492) said:
‘mnt_already_visible’ will iterate the new mount namespace and check whether it has child mountpoint. If it has child mountpoint, it is not fully visible to this mount namespace so the procfs will not be mounted. This reason is as following. The procfs and sysfs contains some global data, so the container should not touch. So mouting procfs and sysfs in new user namespace should be restricted. Anyway, if we allow this, we can mount the whole procfs data in new user namespace. In docker and runc environment, it has ‘maskedPaths’ which means the path should be masked in container. 
Also I find there an old discuss in [runc issue](https://github.com/opencontainers/runc/issues/1658). The reason is just as I said. But Alban Crequy gives [two solutions](https://github.com/opencontainers/runc/issues/1658#issuecomment-375750981). 


1. by add '-v /proc:/newproc' in the docker command, thus the runsc can see the full procfs, so there will be no EPERM


                # docker run -it --rm --security-opt apparmor=unconfined --security-opt seccomp=unconfined -v /proc:/newproc ubuntu root@0723fa9d5c92:/# cd /tmp/
                root@0723fa9d5c92:/tmp# ls
                runsc
                root@0723fa9d5c92:/tmp# ./runsc  --rootless do ls
                *** Warning: sandbox network isn't supported with --rootless, switching to host ***
                runsc  runsc-do1613356723
                root@0723fa9d5c92:/tmp#


2. by first create a dead pidns, then mount this procfs to docker container


                # unshare -p -f mount -t proc proc /mnt/proc
                # docker run -it --rm --security-opt apparmor=unconfined --security-opt seccomp=unconfined -v /mnt/proc:/newproc ubuntu
                root@eda100eadf1f:/# cd /tmp
                root@eda100eadf1f:/tmp# ./runsc  --rootless do ls
                *** Warning: sandbox network isn't supported with --rootless, switching to host ***
                runsc  runsc-do1925241706
                root@eda100eadf1f:/tmp#


Both two solutions is not very elegant. Luckily runsc here doesn't need mount a whole procfs, it just need to open /proc/self/fd and read some generic files. Andrei Vagin has prepare a [patch](https://github.com/google/gvisor/commit/063ee51c57f6cd5c64aa0d115396941dce455b8b) to address this issue, without any tricks. It binds mount current /proc instead of mounting a new procfs instance.


<h3> Conclude  </h3> 

1. mount syscall needs CAP_SYS_ADMIN. unprivileged user can get CAP_SYS_ADMIN in new user ns. Some filesystem can be mounted in new user ns by specifying the 'FS_USERNS_MOUNT' flag.
2. procfs and sysfs can be mounted in new user ns. But if there are child mounts in procfs and sysfs the mount syscall will return EPERM.

Not all filesystem can be mounted in non-root user namespace. There is a permission check in mount syscall.



<h3> Ref </h3> 

1. gVisor issue: https://github.com/google/gvisor/issues/8205
2. runc issue: https://github.com/opencontainers/runc/issues/1658