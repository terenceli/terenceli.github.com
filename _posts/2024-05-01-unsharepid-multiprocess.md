---
layout: post
title: "Multi-thread process can't unshare pid namespace (in some old Linux version)"
description: "multi-thread can't unshare pid namespace in old Linux version"
category: 技术
tags: [技术]
---
{% include JB/setup %}



<h3> The issue </h3>

When we unshare CLONE_NEWPID in a go program, we got an EINVAL error. Following is the test code.


                package main
                import (
                        "fmt"
                        "os"
                        "os/exec"
                        "syscall"
                )
                func main() {
                        // Unshare the PID namespace
                        if err := syscall.Unshare(syscall.CLONE_NEWPID); err != nil {
                                fmt.Fprintf(os.Stderr, "Error unsharing PID namespace: %v\n", err)
                                os.Exit(1)
                        }
                        // 此时，当前进程是新 PID namespace 中的第一个进程
                        // 运行一个 shell
                        cmd := exec.Command("/bin/sh")
                        // 设置文件描述符
                        cmd.Stdin = os.Stdin
                        cmd.Stdout = os.Stdout
                        cmd.Stderr = os.Stderr
                        // Run the command
                        if err := cmd.Run(); err != nil {
                                fmt.Fprintf(os.Stderr, "Error running shell: %v\n", err)
                                os.Exit(1)
                        }
                        fmt.Println("Exited shell")
                }


As we can see 


                root@xxx:~# ./test
                Error unsharing PID namespace: invalid argument


This first surprises me as the Linux's has supported pid namespace very long ago. After some tests, I found this only occurs in Linux 3.10. 


<h3> The solution </h3>


Then I go to the unshare source.

Following [code](https://github.com/torvalds/linux/blob/v3.10/kernel/fork.c#L1819-L1830) got my attention:

When the application specify CLONE_NEWPID, it also set the flags with CLONE_THREAD, CLONE_VM and CLONE_SIGHAND.


                SYSCALL_DEFINE1(unshare, unsigned long, unshare_flags)
                {
                ...
                        if (unshare_flags & CLONE_NEWPID)
                                unshare_flags |= CLONE_THREAD;
                        /*
                        * If unsharing a thread from a thread group, must also unshare vm.
                        
                /
                        if (unshare_flags & CLONE_THREAD)
                                unshare_flags |= CLONE_VM;
                        /
                        * If unsharing vm, must also unshare signal handlers.
                        */
                        if (unshare_flags & CLONE_VM)
                                unshare_flags |= CLONE_SIGHAND;
                ...
                }


Later in the [unshare](https://github.com/torvalds/linux/blob/v3.10/kernel/fork.c#L1734) function it will check if the one of the CLONE_THREAD, CLONE_SIGHAND , CLONE_VM is set and the process has more than one threads, it will returen EINVAL.


                static int check_unshare_flags(unsigned long unshare_flags)
                {
                ...
                if (unshare_flags & (CLONE_THREAD | CLONE_SIGHAND | CLONE_VM)) {
                                /* FIXME: get_task_mm() increments ->mm_users */
                                if (atomic_read(&current->mm->mm_users) > 1)
                                        return -EINVAL; // this is the case
                        }
                        return 0;
                }



This means the multi-thread process can't unshare PID namespace. This is introduced in the '[unshare pid namespace](https://github.com/torvalds/linux/commit/50804fe3737ca6a5942fdc2057a18a8141d00141)' commit. And later in [this commit](https://github.com/torvalds/linux/commit/6e556ce209b09528dbf1931cbfd5d323e1345926) this behaviour is changed to allow multi-thread to unshare PID namespace. This error only occurs in Linux 3.8 to Linux 3.12. 



<h3> The internals </h3>


When the unshare PID namespace is introduced(Linux 3.8), the multi-thread process is not allowed to unshare PID namespace. As the go program is multi-thread process so it will get an EINVAL when unshare PID namespace. Later in Linux 3.12 this restriction is lifted.
Finally let's test a complicated unshare PID namespace case. In this case:

1. we create two threads
2. the first thread unshare PID namespace and then create a new process
3. the second thread create a new process after the first thread unshare the PID namespace


Following is the code:



                #define _GNU_SOURCE
                #include <stdio.h>
                #include <stdlib.h>
                #include <pthread.h>
                #include <unistd.h>
                #include <sched.h>
                #include <sys/types.h>
                #include <sys/wait.h>
                #include <sys/syscall.h>
                // 用于同步的全局变量
                volatile int pid_namespace_unshared = 0;
                // 获取当前线程的线程ID
                pid_t gettid() {
                return syscall(SYS_gettid);
                }
                // 线程函数原型，unshare PID namespace
                void* thread_function_unshare(void* arg) {
                printf("Thread 1 (PID: %d, TID: %ld) is starting to unshare PID namespace...\n", getpid(), (long)gettid());

                // 尝试unshare PID namespace
                if (unshare(CLONE_NEWPID) == -1) {
                        perror("unshare");
                        exit(EXIT_FAILURE);
                }

                printf("Thread 1 (PID: %d, TID: %ld) has unshared PID namespace.\n", getpid(), (long)gettid());
                pid_namespace_unshared = 1; // 标记已完成unshare工作

                // 需要fork一个新进程来激活PID namespace
                pid_t pid = fork();
                if (pid == 0) {
                        // 子进程只需退出即可
                        printf("Child process of Thread 1 (PID: %d, TID: %ld) exiting to activate PID namespace.\n", getpid(), (long)gettid());
                        exit(EXIT_SUCCESS);
                } else if (pid > 0) {
                        // 父进程（线程1）等待新子进程退出
                        waitpid(pid, NULL, 0);
                } else {
                        perror("fork");
                        exit(EXIT_FAILURE);
                }

                return NULL;
                }
                // 线程函数原型，创建子进程并sleep
                void* thread_function_spawn_child(void* arg) {
                // 等待线程1完成unshare操作
                while (!pid_namespace_unshared) {
                        usleep(100); // 短暂休眠
                }

                printf("Thread 2 (PID: %d, TID: %ld) is spawning a child process...\n", getpid(), (long)gettid());

                pid_t pid = fork();
                if (pid == 0) {
                        // 子进程
                        printf("Child process of Thread 2 (PID: %d, TID: %ld) is starting to sleep for 20 seconds...\n", getpid(), (long)gettid());
                        sleep(20);
                        printf("Child process of Thread 2 (PID: %d, TID: %ld) has finished sleeping.\n", getpid(), (long)gettid());
                        exit(EXIT_SUCCESS);
                } else if (pid > 0) {
                        // 父进程（线程2）等待子进程退出
                        waitpid(pid, NULL, 0);
                } else {
                        perror("fork");
                        exit(EXIT_FAILURE);
                }

                return NULL;
                }
                int main() {
                printf("Main process (PID: %d, TID: %ld) is starting...\n", getpid(), (long)gettid());
                pthread_t thread1, thread2;
                // 创建线程1，用于unshare PID namespace
                if (pthread_create(&thread1, NULL, thread_function_unshare, NULL) != 0) {
                        perror("Failed to create thread 1");
                        return 1;
                }
                // 创建线程2，用于在线程1完成unshare后创建子进程
                if (pthread_create(&thread2, NULL, thread_function_spawn_child, NULL) != 0) {
                        perror("Failed to create thread 2");
                        return 1;
                }
                // 等待两个线程完成
                if (pthread_join(thread1, NULL) != 0) {
                        perror("Failed to join thread 1");
                        return 1;
                }
                if (pthread_join(thread2, NULL) != 0) {
                        perror("Failed to join thread 2");
                        return 1;
                }
                printf("Main process (PID: %d, TID: %ld) has finished executing.\n", getpid(), (long)gettid());
                return 0;
                }


Following show the output:



                root@xxx:~# ./test3
                Main process (PID: 1820, TID: 1820) is starting...
                Thread 1 (PID: 1820, TID: 1821) is starting to unshare PID namespace...
                Thread 1 (PID: 1820, TID: 1821) has unshared PID namespace.
                Thread 2 (PID: 1820, TID: 1822) is spawning a child process...
                Child process of Thread 1 (PID: 1, TID: 1) exiting to activate PID namespace.
                Child process of Thread 2 (PID: 1824, TID: 1824) is starting to sleep for 20 seconds...
                Child process of Thread 2 (PID: 1824, TID: 1824) has finished sleeping.
                Main process (PID: 1820, TID: 1820) has finished executing.



As we can see only the first thread's child in the new PID namespace. So we can unshare PID namespace in one thread and only this thread's child process will in the new PID namespace.