---
layout: post
title: "vsyscall and vDSO"
description: "vsyscall"
category: 技术
tags: [内核]
---
{% include JB/setup %}

<h3> Introduction </h3>

Though there is a very good article to introduce [vsyscalls and vDSO](https://0xax.gitbooks.io/linux-insides/content/SysCall/linux-syscall-3.html). I still write this to strengthen my understanding.

The application in user space triggers system call to kernel to do some privileged work. It is an expensive operation containing trapping to kernel and returning. If the application triggers a system call very often, there will be remarkable performance influence. The vsyscall and vDSO are designed to speed up some certain easy system calls.

<h3> vsyscalls </h3>

virtual system call(vsyscall) is the first mechanism in Linux kernel to try to accelerate the execution of some certain system calls. The idea behind vsyscall is simple. Some system call just return data to user space. If the kernel maps these system call implementation and the related-data into user space pages. Then the application can just trigger these system call like a trivial function call. There will be no context switch between user space and kernel space. We can found this vsyscall pages in kernel [documentation](https://github.com/torvalds/linux/blob/16f73eb02d7e1765ccab3d2018e0bd98eb93d973/Documentation/x86/x86_64/mm.txt).

        ffffffffff600000 - ffffffffffdfffff (=8 MB) vsyscalls

We can see this in process:

        test@ubuntu:~$ cat /proc/self/maps | grep vsyscall
        ffffffffff600000-ffffffffff601000 r-xp 00000000 00:00 0                  [vsyscall]
        test@ubuntu:~$ 

As we can see, this address is fixed in every process. Th fixed address is considered to violate the ASLR as this allow the attack to write exploit more easy. So the original vsyscall is discarded. But some very old program need this vsyscall page. In order to make them happy, the kernel doesn't get rid of vsyscall page instead implement a mechanism called emulated vsyscall. We will talk about this vsyscall.

Mapping vsyscall page occurs in Linux kernel initialization. In the call chain start\_kernel->setup\_arch->map\_vsyscall, the last call is to setup vsyscall page. The code of map\_vsyscall shows below:

        void __init map_vsyscall(void)
        {
            extern char __vsyscall_page;
            unsigned long physaddr_vsyscall = __pa_symbol(&__vsyscall_page);

            if (vsyscall_mode != NATIVE)
                vsyscall_pgprot = __PAGE_KERNEL_VVAR;
            if (vsyscall_mode != NONE)
                __set_fixmap(VSYSCALL_PAGE, physaddr_vsyscall,
                        __pgprot(vsyscall_pgprot));

            BUILD_BUG_ON((unsigned long)__fix_to_virt(VSYSCALL_PAGE) !=
                    (unsigned long)VSYSCALL_ADDR);
        }

First get the physical address of the vsyscall page. It is \_\_vsyscall\_page and the contents of this page is below:

        __vsyscall_page:

            mov $__NR_gettimeofday, %rax
            syscall
            ret

            .balign 1024, 0xcc
            mov $__NR_time, %rax
            syscall
            ret

            .balign 1024, 0xcc
            mov $__NR_getcpu, %rax
            syscall
            ret

            .balign 4096, 0xcc

            .size __vsyscall_page, 4096

The vsyscall contains three system call, gettimeofday, time and getcpu.

After we get the physical address of the '\_\_vsyscall\_page', we check vsyscall\_mode and set the fix-mapped address for vsyscall page with the \_\_set\_fixmap macro. If the 'vsyscall\_mode' is not native, we set 'vsyscall\_pgprot' to '\_\_PAGE\_KERNEL\_VVAR', this means the user space can only read this page. If it is native, it can execute.
Note both of the two prot allow the user space to access this page. 

        #define __PAGE_KERNEL_VSYSCALL		(__PAGE_KERNEL_RX | _PAGE_USER)
        #define __PAGE_KERNEL_VVAR		(__PAGE_KERNEL_RO | _PAGE_USER)

Here we don't dig into the '\_\_set\_fixmap' function and just know that it sets mapping in the vsyscall page virtual address to physical address.

Finally check that virtual address of the vsyscall page is equal to the value of the 'VSYSCALL\_ADDR'.

Now  the start address of the vsyscall page is the ffffffffff600000. glibc or application can call the three system call just in vsyscall page.

        #define VSYSCALL_ADDR_vgettimeofday   0xffffffffff600000
        #define VSYSCALL_ADDR_vtime           0xffffffffff600400
        #define VSYSCALL_ADDR_vgetcpu          0xffffffffff600800

In emulate mode, the access of vsyscall page will trigger page fault and 'emulate\_vsyscall' will be called. This function get the syscall number from address:

    	vsyscall_nr = addr_to_vsyscall_nr(address);

        static int addr_to_vsyscall_nr(unsigned long addr)
        {
            int nr;

            if ((addr & ~0xC00UL) != VSYSCALL_ADDR)
                return -EINVAL;

            nr = (addr & 0xC00UL) >> 10;
            if (nr >= 3)
                return -EINVAL;

            return nr;
        }


Here we can see only the three address is valid. This is also helpful to mitigate the ROP chain using this vsyscall page.

After the check, it calls the system call function.

        switch (vsyscall_nr) {
        case 0:
            ret = sys_gettimeofday(
                (struct timeval __user *)regs->di,
                (struct timezone __user *)regs->si);
            break;

        case 1:
            ret = sys_time((time_t __user *)regs->di);
            break;

        case 2:
            ret = sys_getcpu((unsigned __user *)regs->di,
                    (unsigned __user *)regs->si,
                    NULL);
            break;
        }

So as we can see here, the performance of this emulated vsyscall is even more than just do system call directly.

<h3> vDSO </h3>

As I have said, the vsyscall is discarded and replaced by virtual dynamic shared object(vDSO). The difference between the vsyscall and vDSO is that vDSO maps memory pages into each process as a shared object, but vsyscall is static in memory and has the same address every time in every process. All userspace application that dynamically link to glibc will use vDSO automatically. For example:

        root@ubuntu:~# ldd /bin/ls
            linux-vdso.so.1 (0x00007ffed38da000)
            libselinux.so.1 => /lib/x86_64-linux-gnu/libselinux.so.1 (0x00007fab27f0a000)
            libc.so.6 => /lib/x86_64-linux-gnu/libc.so.6 (0x00007fab27b19000)
            libpcre.so.3 => /lib/x86_64-linux-gnu/libpcre.so.3
            ...

We can see every time the vdso has a differenct load address.

        root@ubuntu:~# cat /proc/self/maps | grep vdso
        7ffd2307f000-7ffd23081000 r-xp 00000000 00:00 0                          [vdso]
        root@ubuntu:~# cat /proc/self/maps | grep vdso
        7ffce17c7000-7ffce17c9000 r-xp 00000000 00:00 0                          [vdso]
        root@ubuntu:~# cat /proc/self/maps | grep vdso
        7ffe581ca000-7ffe581cc000 r-xp 00000000 00:00 0                          [vdso]
        root@ubuntu:~# 

vdso is initialized in 'init\_vdso' function. 

        static int __init init_vdso(void)
        {
            init_vdso_image(&vdso_image_64);

        #ifdef CONFIG_X86_X32_ABI
            init_vdso_image(&vdso_image_x32);
        #endif

'vdso\_image\_64/x32' is in a generated source file arch/x86/entry/vdso/vdso-image-64.c. These source code files generated by the vdso2c program from the different source code files, represent different approaches to call a system call like int 0x80, sysenter and etc. The full set of the images depends on the kernel configuration.

For example for the x86_64 Linux kernel it will contain vdso_image_64:

        const struct vdso_image vdso_image_64 = {
            .data = raw_data,
            .size = 8192,
            .text_mapping = {
                .name = "[vdso]",
                .pages = pages,
            },
            .alt = 3673,
            .alt_len = 52,
            .sym_vvar_start = -12288,
            .sym_vvar_page = -12288,
            .sym_hpet_page = -8192,
            .sym_pvclock_page = -4096,
        };

vdso\_image contains the data of vDSO image. 

Where the raw_data contains raw binary code of the 64-bit vDSO system calls which are 2 page size:

        static struct page *pages[2];

'init\_vdso\_image' initialize some of the 'vdso_image'. 

        void __init init_vdso_image(const struct vdso_image *image)
        {
            int i;
            int npages = (image->size) / PAGE_SIZE;

            BUG_ON(image->size % PAGE_SIZE != 0);
            for (i = 0; i < npages; i++)
                image->text_mapping.pages[i] =
                    virt_to_page(image->data + i*PAGE_SIZE);

            apply_alternatives((struct alt_instr *)(image->data + image->alt),
                    (struct alt_instr *)(image->data + image->alt +
                                image->alt_len));
        }


When the kernel loads a binary to memory, it calls 'arch\_setup\_additional\_pages' and this function calls 'map\_vdso'.

Note the 'map\_vdso' need also map a vvar region. The vDSO implements four system calls

        __vdso_clock_gettime;
        __vdso_getcpu;
        __vdso_gettimeofday;
        __vdso_time.


        root@ubuntu:~# readelf -s vdso.so

        Symbol table '.dynsym' contains 10 entries:
        Num:    Value          Size Type    Bind   Vis      Ndx Name
            0: 0000000000000000     0 NOTYPE  LOCAL  DEFAULT  UND 
            1: 0000000000000a40   619 FUNC    WEAK   DEFAULT   12 clock_gettime@@LINUX_2.6
            2: 0000000000000cb0   352 FUNC    GLOBAL DEFAULT   12 __vdso_gettimeofday@@LINUX_2.6
            3: 0000000000000cb0   352 FUNC    WEAK   DEFAULT   12 gettimeofday@@LINUX_2.6
            4: 0000000000000e10    21 FUNC    GLOBAL DEFAULT   12 __vdso_time@@LINUX_2.6
            5: 0000000000000e10    21 FUNC    WEAK   DEFAULT   12 time@@LINUX_2.6
            6: 0000000000000a40   619 FUNC    GLOBAL DEFAULT   12 __vdso_clock_gettime@@LINUX_2.6
            7: 0000000000000000     0 OBJECT  GLOBAL DEFAULT  ABS LINUX_2.6
            8: 0000000000000e30    41 FUNC    GLOBAL DEFAULT   12 __vdso_getcpu@@LINUX_2.6
            9: 0000000000000e30    41 FUNC    WEAK   DEFAULT   12 getcpu@@LINUX_2.6


<h3> experienment </h3>

From above we know that the time consume of three mechanism to trigger system call.

        emulated vsyscall > native syscall > vDSO syscall 

I wrote the simple test program to test the time.

        #include <stdio.h>
        #include <stdlib.h>
        #include <time.h>
        #include <sys/syscall.h>

        time_t (*f)(time_t *tloc) = 0xffffffffff600400; 

        int main(int argc, char **argv)
        {
            unsigned long i = 0;
            if(!strcmp(argv[1], "1")) {
                for (i = 0; i < 1000000;++i)
                f(NULL);
            } else if (!strcmp(argv[1], "2")) { 
                for (i = 0; i < 1000000;++i)
                time(NULL);
            } else {
                for (i = 0; i < 1000000; ++i) 
                syscall(SYS_time, NULL);
            }
            return 0;

        }

Following is the result. The result show our conclusion.

        root@ubuntu:~# time ./test1 1

        real	0m0.539s
        user	0m0.195s
        sys	0m0.343s
        root@ubuntu:~# time ./test1 3

        real	0m0.172s
        user	0m0.080s
        sys	0m0.092s
        root@ubuntu:~# time ./test1 2

        real	0m0.002s
        user	0m0.000s
        sys	0m0.002s

