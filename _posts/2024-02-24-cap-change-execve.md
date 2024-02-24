---
layout: post
title: "Linux process capability change through execve syscall"
description: "capability change through execve"
category: 技术
tags: [技术, 安全]
---
{% include JB/setup %}



<h3> The issue </h3>

I have encountered an interesting issue about capability change through execve syscall. Once we drop current process's capability, then execve another program, the new program get the dropped capability again. Following poc shows this.


                package main
                import (
                        "os"
                        "time"
                        goruntime "runtime"
                        "os/exec"
                        "syscall"
                        "github.com/syndtr/gocapability/capability"
                )
                func main() {
                        cap1, _ := capability.NewPid(os.Getpid())
                        goruntime.LockOSThread()
                        defer goruntime.UnlockOSThread()
                        cap1.Unset(capability.EFFECTIVE, 2)
                        cap1.Unset(capability.PERMITTED, 2)
                        cap1.Unset(capability.INHERITABLE, 2)
                        cap1.Unset(capability.BOUNDING, 2)
                        cap1.Unset(capability.AMBIENT, 2)
                        cap1.Apply(capability.CAPS)
                        time.Sleep(20 * time.Second)
                        binary, lookErr := exec.LookPath("bash")
                        if lookErr != nil {
                                panic(lookErr)
                        }
                        args := []string{"bash"}
                        env := os.Environ()
                        execErr := syscall.Exec(binary, args, env)
                        if execErr != nil {
                                panic(execErr)
                        }
                }


During the Sleep, we see the process has following cap:

![](/assets/img/capexecve/1.png)

After execve, we see the same process has following cap:

![](/assets/img/capexecve/2.png)

This means we don't drop capability in new program. 


<h3> The solution </h3>


It first shocks me. But after quick thought I found the reason: we don't fork. The child process will inherit the parent's capability, but if no fork the execve will have his own logic for capability in this case, it has full capability.
The quick solution is to use fork+execve, but our scenario here can't use fork for some reason. 
After some time thought, I suddenly remember that the Linux has a process attribute named 'no_new_privs'. The 'no_new_privs' [document](https://www.kernel.org/doc/Documentation/prctl/no_new_privs.txt) says:


> With no_new_privs set, execve promises not to grant the privilege to do anything that could not have been done without the execve call.


But amost all of the document is about suid, no capability.
Then I try following code, add Prctl(unix.PR_SET_NO_NEW_PRIVS) after drop capability then do execve syscall.

                package main
                import (
                        "fmt"
                        "os"
                        "time"
                        goruntime "runtime"
                        "os/exec"
                        "syscall"
                        "github.com/syndtr/gocapability/capability"
                        "golang.org/x/sys/unix"
                )
                func main() {
                        cap1, _ := capability.NewPid(os.Getpid())
                        goruntime.LockOSThread()
                        defer goruntime.UnlockOSThread()
                        cap1.Unset(capability.EFFECTIVE, 2)
                        cap1.Unset(capability.PERMITTED, 2)
                        cap1.Unset(capability.INHERITABLE, 2)
                        cap1.Unset(capability.BOUNDING, 2)
                        cap1.Unset(capability.AMBIENT, 2)
                        cap1.Apply(capability.CAPS)
                        if err := unix.Prctl(unix.PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0); err != nil {
                                fmt.Println("set new privs error")
                        }
                        time.Sleep(20 * time.Second)
                        binary, lookErr := exec.LookPath("bash")
                        if lookErr != nil {
                                panic(lookErr)
                        }
                        args := []string{"bash"}
                        env := os.Environ()
                        execErr := syscall.Exec(binary, args, env)
                        if execErr != nil {
                                panic(execErr)
                        }
                }


After execve, I see the following process capability, as we can see it works.

![](/assets/img/capexecve/3.png)


<h3> The internals </h3>


When execve detects that the current process has been set no_new_privs, it will add 'LSM_UNSAFE_NO_NEW_PRIVS' flag to 'bprm->unsafe' in 'check_unsafe_exec' function in fs/exec.c file.


                static void check_unsafe_exec(struct linux_binprm *bprm)
                {
                        struct task_struct *p = current, 
                t;
                        unsigned n_fs;
                ...
                        /
                        * This isn't strictly necessary, but it makes it harder for LSMs to
                        * mess up.
                        */
                        if (task_no_new_privs(current))
                                bprm->unsafe |= LSM_UNSAFE_NO_NEW_PRIVS;
                ...
                }

Later in 'cap_bprm_creds_from_file' function in security/commoncap.c it will check 'bprm->unsafe & ~LSM_UNSAFE_PTRACE'.


                int cap_bprm_creds_from_file(struct linux_binprm *bprm, struct file *file)
                {
                        ...
                        /* Don't let someone trace a set[ug]id/setpcap binary with the revised
                        * credentials unless they have the appropriate permit.
                        *
                        * In addition, if NO_NEW_PRIVS, then ensure we get no new privs.
                        */
                        is_setid = __is_setuid(new, old) || __is_setgid(new, old);
                        if ((is_setid || __cap_gained(permitted, new, old)) &&
                        ((bprm->unsafe & ~LSM_UNSAFE_PTRACE) ||
                        !ptracer_capable(current, new->user_ns))) {
                                /* downgrade; they get no more than they had, and maybe less */
                                if (!ns_capable(new->user_ns, CAP_SETUID) ||
                                (bprm->unsafe & LSM_UNSAFE_NO_NEW_PRIVS)) {
                                        new->euid = new->uid;
                                        new->egid = new->gid;
                                }
                                new->cap_permitted = cap_intersect(new->cap_permitted,
                                                                old->cap_permitted);
                        }
                        ...
                }


If this is true, it will caculate the new cap_permitted using 'cap_intersect'


                new->cap_permitted = cap_intersect(new->cap_permitted,
                                                                old->cap_permitted);



In this way the current process cap which has been dropped affects the new execve process. 

