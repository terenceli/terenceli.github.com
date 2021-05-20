---
layout: post
title: "seccomp user notification"
description: "driver"
category: 技术
tags: [内核]
---
{% include JB/setup %}


seccomp user notification defers the seccomp decisions to userspace. This post [Seccomp Notify](https://brauner.github.io/2020/07/23/seccomp-notify.html) has a very detail description of this feature. The [page](https://man7.org/tlpi/code/online/dist/seccomp/seccomp_user_notification.c.html) has an example of seccomp. I change this example to following: seccomp BPF will forward the listen syscall's decision to userspace. And the tracer will print the listen port and can block the specified port to be listenend. Just a poc and the program doesn't exit normally.



        #define _GNU_SOURCE
        #include <sys/types.h>
        #include <sys/prctl.h>
        #include <fcntl.h>
        #include <limits.h>
        #include <signal.h>
        #include <sys/wait.h>
        #include <stddef.h>
        #include <stdbool.h>
        #include <linux/audit.h>
        #include <sys/syscall.h>
        #include <sys/stat.h>
        #include <linux/filter.h>
        #include <linux/seccomp.h>
        #include <sys/ioctl.h>
        #include <stdio.h>
        #include <stdlib.h>
        #include <unistd.h>
        #include <errno.h>
        #include <netinet/in.h>

        #include "scm_functions.h"

        #define errExit(msg)    do { perror(msg); exit(EXIT_FAILURE); \
                                } while (0)

        static int
        seccomp(unsigned int operation, unsigned int flags, void *args)
        {
            return syscall(__NR_seccomp, operation, flags, args);
        }

        static int
        pidfd_getfd(int pidfd, int targetfd, unsigned int flags)
        {
            return syscall(438, pidfd, targetfd, flags);
        }

        static int
        pidfd_open(pid_t pid, unsigned int flags)
        {
            return syscall(__NR_pidfd_open, pid, flags);
        }


        #define X32_SYSCALL_BIT         0x40000000

        #define X86_64_CHECK_ARCH_AND_LOAD_SYSCALL_NR \
                BPF_STMT(BPF_LD | BPF_W | BPF_ABS, \
                        (offsetof(struct seccomp_data, arch))), \
                BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, AUDIT_ARCH_X86_64, 0, 2), \
                BPF_STMT(BPF_LD | BPF_W | BPF_ABS, \
                        (offsetof(struct seccomp_data, nr))), \
                BPF_JUMP(BPF_JMP | BPF_JGE | BPF_K, X32_SYSCALL_BIT, 0, 1), \
                BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_KILL_PROCESS)


        static int
        installNotifyFilter(void)
        {
            struct sock_filter filter[] = {
                X86_64_CHECK_ARCH_AND_LOAD_SYSCALL_NR,

                /* mkdir() triggers notification to user-space tracer */

                BPF_JUMP(BPF_JMP | BPF_JEQ | BPF_K, __NR_listen, 0, 1),
                BPF_STMT(BPF_RET + BPF_K, SECCOMP_RET_USER_NOTIF),

                /* Every other system call is allowed */

                BPF_STMT(BPF_RET | BPF_K, SECCOMP_RET_ALLOW),
            };

            struct sock_fprog prog = {
                .len = (unsigned short) (sizeof(filter) / sizeof(filter[0])),
                .filter = filter,
            };

            int notifyFd = seccomp(SECCOMP_SET_MODE_FILTER,
                                SECCOMP_FILTER_FLAG_NEW_LISTENER, &prog);
            if (notifyFd == -1)
                errExit("seccomp-install-notify-filter");

            return notifyFd;
        }

        static void
        closeSocketPair(int sockPair[2])
        {
            if (close(sockPair[0]) == -1)
                errExit("closeSocketPair-close-0");
            if (close(sockPair[1]) == -1)
                errExit("closeSocketPair-close-1");
        }

        static pid_t
        targetProcess(int sockPair[2], char *argv[])
        {
            pid_t targetPid;
            int notifyFd;
            struct sigaction sa;
            int s;
            int sockfd;
            struct sockaddr_in sockaddr;

            targetPid = fork();
            if (targetPid == -1)
                errExit("fork");

            if (targetPid > 0)          /* In parent, return PID of child */
                return targetPid;


            printf("Target process: PID = %ld\n", (long) getpid());

            if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0))
                errExit("prctl");

            notifyFd = installNotifyFilter();


            if (sendfd(sockPair[0], notifyFd) == -1)
                errExit("sendfd");

            if (close(notifyFd) == -1)
                errExit("close-target-notify-fd");

            closeSocketPair(sockPair);

            sockfd = socket(AF_INET, SOCK_STREAM, 0);
            sockaddr.sin_family = AF_INET;
            sockaddr.sin_addr.s_addr = htonl(INADDR_ANY);
            sockaddr.sin_port = htons(80);
            if (bind(sockfd, (struct sockaddr*)&sockaddr, sizeof(sockaddr)))
                errExit("Target process: bind error");
            if (listen(sockfd, 1024))
                errExit("Target process: listen error");
            printf("listen success\n");
            

        }

        static void
        checkNotificationIdIsValid(int notifyFd, __u64 id, char *tag)
        {
            if (ioctl(notifyFd, SECCOMP_IOCTL_NOTIF_ID_VALID, &id) == -1) {
                fprintf(stderr, "Tracer: notification ID check (%s): "
                        "target has died!!!!!!!!!!!\n", tag);
            }
        }

        /* Handle notifications that arrive via SECCOMP_RET_USER_NOTIF file
        descriptor, 'notifyFd'. */

        static void
        watchForNotifications(int notifyFd)
        {
            struct seccomp_notif *req;
            struct seccomp_notif_resp *resp;
            struct seccomp_notif_sizes sizes;
            char path[PATH_MAX];
            int procMem;        /* FD for /proc/PID/mem of target process */

            int pidfd;
            int listennum;
            int listenfd;

            struct sockaddr_in sa;
            int salen = sizeof(sa);

            if (seccomp(SECCOMP_GET_NOTIF_SIZES, 0, &sizes) == -1)
                errExit("Tracer: seccomp-SECCOMP_GET_NOTIF_SIZES");

            req = malloc(sizes.seccomp_notif);
            if (req == NULL)
                errExit("Tracer: malloc");

            resp = malloc(sizes.seccomp_notif_resp);
            if (resp == NULL)
                errExit("Tracer: malloc");

            /* Loop handling notifications */

            for (;;) {

                /* Wait for next notification, returning info in '*req' */

                if (ioctl(notifyFd, SECCOMP_IOCTL_NOTIF_RECV, req) == -1)
                    errExit("Tracer: ioctlSECCOMP_IOCTL_NOTIF_RECV");

                printf("Tracer: got notification for PID %d; ID is %llx\n",
                        req->pid, req->id);


            pidfd = pidfd_open(req->pid, 0);
            listennum = req->data.args[0];
            listenfd = pidfd_getfd(pidfd, listennum, 0);
            getsockname(listenfd, &sa, &salen);
            printf("Tracer: listen %d port\n", ntohs(sa.sin_port));

                resp->id = req->id;
                resp->flags = SECCOMP_USER_NOTIF_FLAG_CONTINUE;        
                resp->error = 0;

                resp->val = 0;

                if (ioctl(notifyFd, SECCOMP_IOCTL_NOTIF_SEND, resp) == -1) {
                    if (errno == ENOENT)
                        printf("Tracer: response failed with ENOENT; perhaps target "
                                "process's syscall was interrupted by signal?\n");
                    else
                        perror("ioctl-SECCOMP_IOCTL_NOTIF_SEND");
                }
            }
        }

        static pid_t
        tracerProcess(int sockPair[2])
        {
            pid_t tracerPid;

            tracerPid = fork();
            if (tracerPid == -1)
                errExit("fork");

            if (tracerPid > 0)          /* In parent, return PID of child */
                return tracerPid;

            /* Child falls through to here */

            printf("Tracer: PID = %ld\n", (long) getpid());

            /* Receive the notification file descriptor from the target process */

            int notifyFd = recvfd(sockPair[1]);
            if (notifyFd == -1)
                errExit("recvfd");

            closeSocketPair(sockPair);  /* We no longer need the socket pair */

            /* Handle notifications */

            watchForNotifications(notifyFd);

            exit(EXIT_SUCCESS);         /* NOTREACHED */
        }

        int main(int argc, char *argv[])
        {
            pid_t targetPid, tracerPid;
            int sockPair[2];

            setbuf(stdout, NULL);

            if (socketpair(AF_UNIX, SOCK_STREAM, 0, sockPair) == -1)
                errExit("socketpair");

            targetPid = targetProcess(sockPair, &argv[optind]);

            tracerPid = tracerProcess(sockPair);

            closeSocketPair(sockPair);

            waitpid(targetPid, NULL, 0);
            printf("Parent: target process has terminated\n");

            waitpid(tracerPid, NULL, 0);

            exit(EXIT_SUCCESS);
        }
