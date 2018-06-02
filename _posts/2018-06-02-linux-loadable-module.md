---
layout: post
title: "Anatomy of the Linux loadable kernel module"
description: "Linux kernel"
category: 技术
tags: [Linux内核]
---
{% include JB/setup %}


Loadable module plays a very important role in modern applications and operating systems. Nearly all processes need loadable modules, .so and .dll file for Linux and Windows for example. The operating systems can also benefit from the loadable modules, for examle , the Linux can insert .ko driver file into the kernel when it is running, also the Windows operating has the corresponding mechanism. This article will dig into the anatomy the Linux loadable kernel module.  We will use the below very simple loadable kernel module to follow our discuss.

hello.c:

    #include <linux/kernel.h>
    #include <linux/module.h>


    int testexport(void)
    {
    printk("in testexport\n");
    }
    EXPORT_SYMBOL(testexport);

    int hello_init(void) {
      int i;
      printk(KERN_INFO "Hello World!\n");
      return 0;
    }
    void hello_exit(void) {
      printk(KERN_INFO "Bye World!\n");
    }

    module_init(hello_init);
    module_exit(hello_exit);

Below is the Makefile:

    obj-m += hello.o
    all:
    make -C /lib/modules/$(shell uname -r)/build M=$(PWD) modules
    clean:
    make -C /lib/modules/$(shell uname -r)/build M=$(PWD) clean

When we compile the kernel module, it generates a hello.ko file. Insert the .ko into the kernel using "insmod hello.ko", you will see the "Hello World" in dmesg, and remove it using "rmmod hello", you will see the "Bye World".

    [469345.236572] Hello World!
    [469356.544498] Bye World!

# File Format 

.ko is an ELF file, which stands for "Executable and Linking Format", the standand execute file format in Linux.

    # file hello.ko
    hello.ko: ELF 64-bit LSB relocatable, x86-64, version 1 (SYSV), BuildID[sha1]=28772d0d39be18e530b2b788dbf79acfabf189d6, not strippe

Below layout the tpyical .ko file format in disk.

    e_shoff  +------------------+
        +----+ ELF header       |
        |    +------------------+ <------+
        |    |                  |        |
        |    | section 1        |        |
        |    |                  |        |
        |    +------------------+        |
        |    | section 2        | <---+  |
        |    +------------------+     |  |
        |    | section 3        | <+  |  |
        +--> +------------------+  |  |  |
            | section header 1 +--------+
            +------------------+  |  |
            | section header 2 +-----+
            +------------------+  | sh_offset
            | section header 3 +--+
            +------------------+

In general, the ELF static file contains three portion, ELF header, several sections and the final several section header talbe. Notice here we omit the optional program header table as the .ko doesn't use it.

##ELF header

ELF header describes the overall infomation of the file, lies in the first portion of the ELF file. We can use readelf to read the header.

    # readelf -h hello.ko
    ELF Header:
      Magic:   7f 45 4c 46 02 01 01 00 00 00 00 00 00 00 00 00
      Class:                             ELF64
      Data:                              2's complement, little endian
      Version:                           1 (current)
      OS/ABI:                            UNIX - System V
      ABI Version:                       0
      Type:                              REL (Relocatable file)
      Machine:                           Advanced Micro Devices X86-64
      Version:                           0x1
      Entry point address:               0x0
      Start of program headers:          0 (bytes into file)
      Start of section headers:          285368 (bytes into file)
      Flags:                             0x0
      Size of this header:               64 (bytes)
      Size of program headers:           0 (bytes)
      Number of program headers:         0
      Size of section headers:           64 (bytes)
      Number of section headers:         33
      Section header string table index: 3

Use the hexdump  we can see the raw data.

    0000000 457f 464c 0102 0001 0000 0000 0000 0000
    0000010 0001 003e 0001 0000 0000 0000 0000 0000
    0000020 0000 0000 0000 0000 5ab8 0004 0000 0000
    0000030 0000 0000 0040 0000 0000 0040 0021 0020

Structure represented:

    typedef struct
    {
        unsigned char e_ident[16]; /* ELF identification */
        Elf64_Half e_type; /* Object file type */
        Elf64_Half e_machine; /* Machine type */
        Elf64_Word e_version; /* Object file version */
        Elf64_Addr e_entry; /* Entry point address */
        Elf64_Off e_phoff; /* Program header offset */
        Elf64_Off e_shoff; /* Section header offset */
        Elf64_Word e_flags; /* Processor-specific flags */
        Elf64_Half e_ehsize; /* ELF header size */
        Elf64_Half e_phentsize; /* Size of program header entry */
        Elf64_Half e_phnum; /* Number of program header entries */
        Elf64_Half e_shentsize; /* Size of section header entry */
        Elf64_Half e_shnum; /* Number of section header entries */
        Elf64_Half e_shstrndx; /* Section name string table index */
    } Elf64_Ehdr;
The comment describe every filed's meaning.

## Sections

Several sections lies after the ELF header. Sections occupies the most space of ELF file. Every section is the true data about the file. For example, the .text section contains the code the program will be executed, the .data contains the data the program will use. There maybe a lot of sections, our this very simple helloworld has 33 sections. When the operating system load the ELF file into the memory, some of the sections will be togethered into a segment, and some sections may be omited, means not load into memory.

## Section header tables

Section header tables lies in the tail of ELF file. It is the metadata of sections, contains the information about the corresponding section, section start in the ELF file and size for example.


# EXPORT_SYMBOL internals

When we write application in user space, we often use the library functions such as 'printf', 'malloc' and so on. We don't need write these functions by ourself as they are provided by the glic library. Also, in kernel space, the kernel module often needs use the kernel's function to  complete his work. For example, the 'printk' to print something. For the static linking, the compiler can solve this reference problem, but for the dynamic module load, the kernel should do this by himself, this called resolve the  "unresolved reference". Essentially process "unresolved reference" is to determine the actual address of the kernel module uses. So there must somewhere to export these symbols. In linux kernel, it is done by EXPORT\_SYMBOL macro.  So let's look at how to export symbols through EXPORT\_SYMBOL.

    <include/linux/export.h>
    /* For every exported symbol, place a struct in the __ksymtab section */
    #define __EXPORT_SYMBOL(sym, sec)    \
    extern typeof(sym) sym;     \
    __CRC_SYMBOL(sym, sec)     \
    static const char __kstrtab_##sym[]   \
    __attribute__((section("__ksymtab_strings"), aligned(1))) \
    = VMLINUX_SYMBOL_STR(sym);    \
    extern const struct kernel_symbol __ksymtab_##sym; \
    __visible const struct kernel_symbol __ksymtab_##sym \
    __used       \
    __attribute__((section("___ksymtab" sec "+" #sym), unused)) \
    = { (unsigned long)&sym, __kstrtab_##sym }

    #define EXPORT_SYMBOL(sym)     \
    __EXPORT_SYMBOL(sym, "")

    #define EXPORT_SYMBOL_GPL(sym)     \
    __EXPORT_SYMBOL(sym, "_gpl")

    #define EXPORT_SYMBOL_GPL_FUTURE(sym)    \
    __EXPORT_SYMBOL(sym, "_gpl_future"

This shows the EXPORT\_SYMBOL definition. Though seems complicated, we will uses our example to instantiate it. Think our EXPORT\_SYMBOL(testexport). After expand this macro, we get this(the \_\_CRC\_SYMBOL(sym, sec)  is left later):

    static const char __kstrtab_testexport[] = "testexport";
    const struct kernel_symbol __ksymtab_testexport =
    {(unsigned long)&testexport, __kstrtab_testexport}
    The second structure represented:
    struct kernel_symbol
    {
    unsigned long value;
    const char *name;
    };

So here we can see, the EXPORT\_SYMBOL just define variables, the 'value' is the address of this symbol in memory and 'name' is the name of this symbol. Not  like ordinary defination, the export function's name is stored in section "\_\_ksymtab\_strings", and the kernel\_symbol variable is stored in section "\_\_\_ksymtab+testexport". If you look at the ELF file section, you will not find "\_\_\_ksymtab+testexport" section. It is converted in "\_\_ksymtab" in <scripts/module-common.lds>:

    SECTIONS {
    /DISCARD/ : { *(.discard) }

    __ksymtab  : { *(SORT(___ksymtab+*)) }
    __ksymtab_gpl  : { *(SORT(___ksymtab_gpl+*)) }
    __ksymtab_unused : { *(SORT(___ksymtab_unused+*)) }
    __ksymtab_unused_gpl : { *(SORT(___ksymtab_unused_gpl+*)) }
    __ksymtab_gpl_future : { *(SORT(___ksymtab_gpl_future+*)) }
    __kcrctab  : { *(SORT(___kcrctab+*)) }
    __kcrctab_gpl  : { *(SORT(___kcrctab_gpl+*)) }
    __kcrctab_unused : { *(SORT(___kcrctab_unused+*)) }
    __kcrctab_unused_gpl : { *(SORT(___kcrctab_unused_gpl+*)) }
    __kcrctab_gpl_future : { *(SORT(___kcrctab_gpl_future+*)) }
    }

As for EXPORT\_SYMBOL\_GPL and EXPORT\_SYMBOL\_GPL\_FUTURE, the only difference is the section added by "\_gpl" and "\_gpl\_future".
In order to let the kernel uses these sections to find the exported symbol, the linker must export the address of these section. See <include/asm-generic/vmlinux.lds.h>:

    /* Kernel symbol table: Normal symbols */   \
    __ksymtab         : AT(ADDR(__ksymtab) - LOAD_OFFSET) {  \
      VMLINUX_SYMBOL(__start___ksymtab) = .;   \
      *(SORT(___ksymtab+*))     \
      VMLINUX_SYMBOL(__stop___ksymtab) = .;   \
    }        \
            \
    /* Kernel symbol table: GPL-only symbols */   \
    __ksymtab_gpl     : AT(ADDR(__ksymtab_gpl) - LOAD_OFFSET) { \
      VMLINUX_SYMBOL(__start___ksymtab_gpl) = .;  \
      *(SORT(___ksymtab_gpl+*))    \
      VMLINUX_SYMBOL(__stop___ksymtab_gpl) = .;  \
    }        \
            \
    /* Kernel symbol table: Normal unused symbols */  \
    __ksymtab_unused  : AT(ADDR(__ksymtab_unused) - LOAD_OFFSET) { \
      VMLINUX_SYMBOL(__start___ksymtab_unused) = .;  \
      *(SORT(___ksymtab_unused+*))    \
      VMLINUX_SYMBOL(__stop___ksymtab_unused) = .;  \
    }        \
    ...

In <kernel/module.c> we can see the declaration:

    /* Provided by the linker */
    extern const struct kernel_symbol __start___ksymtab[];
    extern const struct kernel_symbol __stop___ksymtab[];
    extern const struct kernel_symbol __start___ksymtab_gpl[];
    extern const struct kernel_symbol __stop___ksymtab_gpl[];
    extern const struct kernel_symbol __start___ksymtab_gpl_future[];
    extern const struct kernel_symbol __stop___ksymtab_gpl_future[];

So after this, the kernel can use '\_\_start\_\_\_ksymtab' and other variables without any errorsNow let's talk more about the ELF file about section "\_\_ksymtab". Firstly dump this section:

    # readelf --hex-dump=_ksymtab hello.ko
    readelf: Warning: Section '_ksymtab' was not dumped because it does not exist!
    # readelf --hex-dump=__ksymtab hello.ko

    Hex dump of section '__ksymtab':
    NOTE: This section has relocations against it, but these have NOT been applied to this dump.
      0x00000000 00000000 00000000 00000000 00000000 ................


Interesting, they are all zeros! Where is our data.
If you look the section headers more carefully, you can see some sections begin with ".rela".
There is a '.rela\_\_ksymtab' section:

    # readelf -S hello.ko
    There are 33 section headers, starting at offset 0x45ab8:

    Section Headers:
      [Nr] Name              Type             Address           Offset
          Size              EntSize          Flags  Link  Info  Align
      [ 0]                   NULL             0000000000000000  00000000
          0000000000000000  0000000000000000           0     0     0
      [ 1] .note.gnu.build-i NOTE             0000000000000000  00000040
          0000000000000024  0000000000000000   A       0     0     4
      [ 2] .text             PROGBITS         0000000000000000  00000070
          0000000000000051  0000000000000000  AX       0     0     16
      [ 3] .rela.text        RELA             0000000000000000  00025be8
          00000000000000d8  0000000000000018   I      30     2     8
      [ 4] __ksymtab         PROGBITS         0000000000000000  000000d0
          0000000000000010  0000000000000000   A       0     0     16
      [ 5] .rela__ksymtab    RELA             0000000000000000  00025cc0
          0000000000000030  0000000000000018   I      30     4     8
      [ 6] __kcrctab         PROGBITS         0000000000000000  000000e0
          0000000000000008  0000000000000000   A       0     0     8
      [ 7] .rela__kcrctab    RELA             0000000000000000  00025cf0

'.rela\_\_ksymtab' section's type is RELA. This means this section contains relocation data which data will be and how to be modified when the final executable is loaded to kernel. section of '.rela\_\_ksymtab' contains the '\_\_ksymtab' relocation data.

    # readelf  -r hello.ko | head -20

    Relocation section '.rela.text' at offset 0x25be8 contains 9 entries:
      Offset          Info           Type           Sym. Value    Sym. Name + Addend
    000000000001  001f00000002 R_X86_64_PC32     0000000000000000 __fentry__ - 4
    000000000008  00050000000b R_X86_64_32S      0000000000000000 .rodata.str1.1 + 0
    00000000000d  002400000002 R_X86_64_PC32     0000000000000000 printk - 4
    000000000021  001f00000002 R_X86_64_PC32     0000000000000000 __fentry__ - 4
    000000000028  00050000000b R_X86_64_32S      0000000000000000 .rodata.str1.1 + f
    00000000002d  002400000002 R_X86_64_PC32     0000000000000000 printk - 4
    000000000041  001f00000002 R_X86_64_PC32     0000000000000000 __fentry__ - 4
    000000000048  00050000000b R_X86_64_32S      0000000000000000 .rodata.str1.1 + 1f
    00000000004d  002400000002 R_X86_64_PC32     0000000000000000 printk - 4

    Relocation section '.rela__ksymtab' at offset 0x25cc0 contains 2 entries:
      Offset          Info           Type           Sym. Value    Sym. Name + Addend
    000000000000  002300000001 R_X86_64_64       0000000000000000 testexport + 0
    000000000008  000600000001 R_X86_64_64       0000000000000000 __ksymtab_strings + 0

    Relocation section '.rela__kcrctab' at offset 0x25cf0 contains 1 entries:
      Offset          Info           Type           Sym. Value    Sym. Name + Addend


Here we can see in section '.rela\_\_ksymtab' there is 2 entries. I will not dig into the RELA section format, just notice the 0x23 and 0x06 is used to index the .symtab section. So when the .ko is loaded into the kernel, the first 8 bytes of section '\_\_ksymtab' will be replaced by the actual address of testexport, and the second 8 bytes of section '\_\_ksymtab' will be replaced by the actual address of the string at '\_\_ksymtab_strings+0' which is 'testexport'. So this is what the structure kernel\_symbol---through EXPORT\_SYMBOL---does.

# Module load process

init\_module system call is used to load the kernel module to kernel. User space application loads the .ko file into user space and then pass the address and size of .ko and the arguments of the kernel module will use to this system call. In init\_module, it just allocates the memory space and copys the user's data to kernel, then call the actual work function load\_module. In general we can split the load\_module function up to two logical part. The first part completes the load work such as reallocation the memory to hold kernel module, resolve the symbol, apply relocations and so on. The second part later do other work such as call the module's init function, cleanup the allocated resource and so on. Before we go to the first part, let's first look at a very important structure 'struct module':
<include/linux/module.h>

    struct module {
    enum module_state state;

    /* Member of list of modules */
    struct list_head list;

    /* Unique handle for this module */
    char name[MODULE_NAME_LEN];

    /* Sysfs stuff. */
    struct module_kobject mkobj;
    struct module_attribute *modinfo_attrs;
    const char *version;
    const char *srcversion;
    struct kobject *holders_dir;

    /* Exported symbols */
    const struct kernel_symbol *syms;
    const unsigned long *crcs;
    unsigned int num_syms;

    /* Kernel parameters. */
    struct kernel_param *kp;
    unsigned int num_kp;
    ...
    }

Here I just list some of the fields of 'struct module', it represents a module in kernel, contains the infomation of the kernel module. For example, 'state' indicates the status of the module, it will change with the load process, the 'list' links all of the modules in kernel and 'name' contains the module name.
Below lists some important function the load\_module calls.

    load_module
      -->layout_and_allocate
        -->setup_load_info
          -->rewrite_section_headers
        -->layout_sections
        -->layout_symtab
        -->move_module
      -->find_module_sections
      -->simplify_symbols
      -->apply_relocations
      -->parse_args
      -->do_init_module

The rewrite\_section\_headers function replace the sections header field 'sh\_addr' with the real address in the memory. Then in function setup\_load\_info, 'mod' is initialized with the ".gnu.linkonce.this\_module" section's real address. Actually, this contains the data compiler setup for us. In the source directory, we can see a hello.mod.c file:

    __visible struct module __this_module
    __attribute__((section(".gnu.linkonce.this_module"))) = {
        .name = KBUILD_MODNAME,
        .init = init_module,
    #ifdef CONFIG_MODULE_UNLOAD
        .exit = cleanup_module,
    #endif
        .arch = MODULE_ARCH_INIT,
    };

So here we can see the 'mod' will have some field. The interesting here is that we can see the init function is init\_module, not the same as our hello\_init. The magic is caused by module\_init
as follows(include/linux/init.h):

    /* Each module must use one module_init(). */
    #define module_init(initfn)     \
    static inline initcall_t __inittest(void)  \
    { return initfn; }     \
    int init_module(void) __attribute__((alias(#initfn)));

From here we can see the compiler will set the 'init\_module's alias to our init function name which is 'hello\_init' in our example.
Next in the function 'layout\_sections', it will caculate the 'core' size and 'init' size of the ELF file. Then according where define the CONFIG\_KALLSYMS, 'layout_symtab' will be called and the symbol info will be added to the core section.
After caculate the core and init section, it will allocate space for core and init section in function 'move\_module' and then copy the origin section data to the new space. So the sections's sh\_addr should also be updated. Then the 'mod's address should be updated.

mod = (void *)info->sechdrs[info->index.mod].sh\_addr;


                        core section
                        +------------+ <-----mod->module_core
                    +-> |            |
                    |   +------------+
    +------------+ +---> |            |
    | ELF header | | |   +------------+
    +------------+ | |   |            |
    | section 0  +---+   +------------+
    +------------+ |
    | section 1  +----+
    +------------+ |  |  init section
    | section 2  +----+  +------------+ <-----mod->module_init
    +------------+ | +-> |            |
    | section 3  +-+ |   +------------+
    +------------+   +-> |           ||
    |sec head table      +------------+
    +------------+       |            |
                        |            |
                        +------------+

So for now , we have this section.

Later 'load\_module' call 'find\_module\_sections' to get the export symbol.
Next, it calls 'simplify\_symbols' to fix up the symbols. The function call chain is
simplify\_symbols-->resolve\_symbol\_wait-->
-->resolve\_symbol-->find\_symbol-->each\_symbol\_section
In the last function, it will first iterate the kernel's export symbol and then iterate the loaded modules symbol.
If 'resolve\_symbol' successful, it will call 'ref\_module' to establish the dependency between current load module and the module of the symbol it uses. This is done in 'add\_module\_usage'

    static int add_module_usage(struct module *a, struct module *b)
    {
    struct module_use *use;

    pr_debug("Allocating new usage for %s.\n", a->name);
    use = kmalloc(sizeof(*use), GFP_ATOMIC);
    if (!use) {
      pr_warn("%s: out of memory loading\n", a->name);
      return -ENOMEM;
    }

    use->source = a;
    use->target = b;
    list_add(&use->source_list, &b->source_list);
    list_add(&use->target_list, &a->target_list);
    return 0;
    }


Here a is current loading module, and b is the module a uses its symbol.
module->source\_list links the modules depend on module, and module->target\_list links the modules it depends on.

After fix up the symbols, the 'load\_module' function will do relocation by calling function 'apply\_relocations'. If the section's type is 'SHT\_REL' or 'SHT\_RELA', function 'apply\_relocations' will call the arch-spec function. As the symbol table has been solved, this relocation is much simple. So now the module's export symbol address has been corrected the right value.

Next the 'load\_module' function will call 'parse\_args' to parse module parameters. Let's first look at how to define parameter in kernel module.

    static bool __read_mostly fasteoi = 1;
    module_param(fasteoi, bool, S_IRUGO);

    #define module_param(name, type, perm)    \
    module_param_named(name, name, type, perm)

    #define module_param_named(name, value, type, perm)      \
    param_check_##type(name, &(value));       \
    module_param_cb(name, &param_ops_##type, &value, perm);     \
    __MODULE_PARM_TYPE(name, #type)

    #define module_param_cb(name, ops, arg, perm)          \
    __module_param_call(MODULE_PARAM_PREFIX, name, ops, arg, perm, -1, 0)

    #define __module_param_call(prefix, name, ops, arg, perm, level, flags) \
    /* Default value instead of permissions? */   \
    static const char __param_str_##name[] = prefix #name; \
    static struct kernel_param __moduleparam_const __param_##name \
    __used        \
        __attribute__ ((unused,__section__ ("__param"),aligned(sizeof(void *)))) \
    = { __param_str_##name, ops, VERIFY_OCTAL_PERMISSIONS(perm), \
        level, flags, { arg } }

Let's try an example using the 'fasteoi'.

    param_check_bool(fasteoi, &(fasteoi));
    static const char __param_str_bool[] = "fasteoi";
    static struct kernel_param __moduleparam_const __param_fasteoi \
    __used
        __attribute__ ((unused,__section__ ("__param"),aligned(sizeof(void *)))) \
      = { __param_str_fasteoi, param_ops_bool, VERIFY_OCTAL_PERMISSIONS(perm), \
        -1, 0, { &fasteoi} }

So here we can see 'module\_param(fasteoi, bool, S\_IRUGO);' define a variable which is 'struct kernel\_param' and store it in section '\_\_param'.

    struct kernel_param {
    const char *name;
    const struct kernel_param_ops *ops;
    u16 perm;
    s8 level;
    u8 flags;
    union {
      void *arg;
      const struct kparam_string *str;
      const struct kparam_array *arr;
    };
    };

the union 'arg' will contain the kernel parameter's address.

The user space will pass the specific arguments to load\_module in the 'uargs' argument.
In 'parse\_args', it will pass one by one parameter, and compare it will the data in section '\_\_param' , and then write it will the user specific value.

    int param_set_bool(const char *val, const struct kernel_param *kp)
    {
    /* No equals means "set"... */
    if (!val) val = "1";

    /* One of =[yYnN01] */
    return strtobool(val, kp->arg);
    }
    int strtobool(const char *s, bool *res)
    {
    switch (s[0]) {
    case 'y':
    case 'Y':
    case '1':
      *res = true;
      break;
    case 'n':
    case 'N':
    case '0':
      *res = false;
      break;
    default:
      return -EINVAL;
    }
    return 0;
    }

## Version control

One thing we have lost is version control. Version control is used to keep consistency between kernel and module. We can't load modules compiled for 2.6 kernel into 3.2 kernel. That's why version control needed. Kernel and module uses CRC checksum to do this. The idea behind this is so easy, the build tools will generate CRC checksum for every exported function and for every function module reference. Then in 'load\_module' function, these two CRC will be checked if there are the same.  In order to support this mechism, the kernel config must contain 'CONFIG\_MODVERSIONS'. In EXPORT\_SYMBOL macro, there is a \_\_CRC\_SYMBOL definition.

    #ifdef CONFIG_MODVERSIONS
    /* Mark the CRC weak since genksyms apparently decides not to
    * generate a checksums for some symbols */
    #define __CRC_SYMBOL(sym, sec)     \
    extern __visible void *__crc_##sym __attribute__((weak));  \
    static const unsigned long __kcrctab_##sym  \
    __used       \
    __attribute__((section("___kcrctab" sec "+" #sym), unused)) \
    = (unsigned long) &__crc_##sym;
    #else
    #define __CRC_SYMBOL(sym, sec)
    #endif

Expand it.

    extern __visible void *__crc_textexport;
    static const unsigned long __kcrctab_testexport = (unsigned long) &__crc_textexport;

So for every export symbol, build tools will generate a CRC checksum and store it in section '\_kcrctab'.

The time for module load process. In hello.mod.c we can see the below:

    static const struct modversion_info ____versions[]
    __used
    __attribute__((section("__versions"))) = {
        { 0x21fac097, __VMLINUX_SYMBOL_STR(module_layout) },
        { 0x27e1a049, __VMLINUX_SYMBOL_STR(printk) },
        { 0xbdfb6dbb, __VMLINUX_SYMBOL_STR(__fentry__) },
    };

    struct modversion_info {
    unsigned long crc;
    char name[MODULE_NAME_LEN];
    };


The ELF will have an array of struct modversion stored in section '\_\_versions', and every element in this array have a crc and name to indicate the module references symbol.

In 'check\_version', when it finds the symbole it will call 'check\_version'. Function 'check\_version' iterates the '\_\_versions' and compare the finded symble's CRC checksum. If it is the same, it passes the check.

## Modinfo

.ko file will also contain a '.modinfo' section which stores some of the module information. modinfo program can show these info. In the source code, one can use 'MODULE\_INFO' to add this information.

    #define MODULE_INFO(tag, info) __MODULE_INFO(tag, tag, info)

    #ifdef MODULE
    #define __MODULE_INFO(tag, name, info)       \
    static const char __UNIQUE_ID(name)[]       \
      __used __attribute__((section(".modinfo"), unused, aligned(1)))   \
      = __stringify(tag) "=" info
    #else  /* !MODULE */
    /* This struct is here for syntactic coherency, it is not used */
    #define __MODULE_INFO(tag, name, info)       \
      struct __UNIQUE_ID(name) {}
    #endif

MODULE\_INFO just define a key-value data in '.modinfo' section once the MODULE is defined. MODULE\_INFO is used several places, such as license, vermagic:

    #define MODULE_LICENSE(_license) MODULE_INFO(license, _license)

    /*
    * Author(s), use "Name <email>" or just "Name", for multiple
    * authors use multiple MODULE_AUTHOR() statements/lines.
    */
    #define MODULE_AUTHOR(_author) MODULE_INFO(author, _author)

    /* What your module does. */
    #define MODULE_DESCRIPTION(_description) MODULE_INFO(description, _description)

    MODULE_INFO(vermagic, VERMAGIC_STRING);


## vermagic

vermagic is a string generated by kernel configuration information. 'load\_module' will check this in 'layout\_and\_allocate'->'check\_modinfo'->'same\_magic'. 'VERMAGIC\_STRING' is generated by the kernel configuration.

    #define VERMAGIC_STRING        \
    UTS_RELEASE " "       \
    MODULE_VERMAGIC_SMP MODULE_VERMAGIC_PREEMPT     \
    MODULE_VERMAGIC_MODULE_UNLOAD MODULE_VERMAGIC_MODVERSIONS \
    MODULE_ARCH_VERMAGI

After doing the tough work, 'load\_module' goes to the final work to call 'do\_init\_module'.
If the module has an init function, 'do\_init\_module' will call it in function 'do\_one\_initcall'.  Then change the module's state to 'MODULE\_STATE\_LIVE', and call the function registered in 'module\_notify\_list' list and finally free the INIT section of module.

# Unload module

Unload module is quite easy, it is done by syscall 'delete\_module', which takes only the module name argument. First find the module in modules list and then check whether it is depended by other modules then call module exit function and finally notify the modules who are interested module unload by iterates 'module\_notify\_list'.