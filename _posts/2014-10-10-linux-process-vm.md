---
layout: post
title: "Linux进程地址空间简介"
description: "内核视角下的进程地址空间"
category: 技术
tags: [Linux内核]
---
{% include JB/setup %}


<h3>一. 进程的地址空间</h3>


32位系统下，每一个进程可以使用的虚拟地址空间为4G,这4G包括了进程独有的和内核,windows下进程占2G，内核占2G，Linux下默认是3G和1G。有4G的地址空间，当然不可能全部用到，所有实际上只有很少一部分是分配了实际内存的。进程的地址空间由允许进程使用的全部线性地址组成。

内核通过所谓线性区的资源来表示线性地址空间，线性区是由其实线性地址、长度和一些访问权限来描述的。为了效率起见，起始地址和线性区长度都必须是4096的倍数，以便每个线性区所识别的数据完全填满分配给它的页框。内核可以通过增加或删除某些线性地址区间来动态修改进程的地址空间。


<h3>二. 内存描述符</h3>

与进程地址空间有关的全部信息都包含在一个叫做内存描述符的数据结构中，这个结构的类型为mm\_struct，进程描述符的mm字段就指向这个结构。mm\_struct定义如下。

	struct mm_struct {
	    struct vm_area_struct * mmap;        /* list of VMAs */
	    struct rb_root mm_rb;
	    struct vm_area_struct * mmap_cache;    /* last find_vma result */
	    unsigned long free_area_cache;        /* first hole */
	    pgd_t * pgd;
	    atomic_t mm_users;            /* How many users with user space? */
	    atomic_t mm_count;            /* How many references to "struct mm_struct" (users count as 1) */
	    int map_count;                /* number of VMAs */
	    struct rw_semaphore mmap_sem;
	    spinlock_t page_table_lock;        /* Protects task page tables and mm->rss */
	
	    struct list_head mmlist;        /* List of all active mm's.  These are globally strung
	                         * together off init_mm.mmlist, and are protected
	                         * by mmlist_lock
	                         */
	
	    unsigned long start_code, end_code, start_data, end_data;
	    unsigned long start_brk, brk, start_stack;
	    unsigned long arg_start, arg_end, env_start, env_end;
	    unsigned long rss, total_vm, locked_vm;
	    unsigned long def_flags;
	
	    unsigned long saved_auxv[40]; /* for /proc/PID/auxv */
	
	    unsigned dumpable:1;
	    cpumask_t cpu_vm_mask;
	
	    /* Architecture-specific MM context */
	    mm_context_t context;
	
	    /* coredumping support */
	    int core_waiters;
	    struct completion *core_startup_done, core_done;
	
	    /* aio bits */
	    rwlock_t        ioctx_list_lock;
	    struct kioctx        *ioctx_list;
	
	    struct kioctx        default_kioctx;
	};

下面介绍一些比较重要的字段。

	* mmap 指向线性区对象的链表头，具体下一部分介绍。
	* mm_rb指向线性区对象的红-黑树的根。mmap 和 mm_rb 这两个不同数据结构体描述的对象是相同的：该地址空间中的所有内存区域。mmap 指向一个 vm_area_struct 结构的链表，利于简单、高效地遍历所有元素。 mm_rb 指向的是一个红-黑树结构节点，适合搜索指定元素。
	* pgd 指向第一级页表即页全局目录的基址，当内核运行这个进程时，它就将pgd存放在CR3寄存器内，根据它来进行地址转换工作。
	* mmlist 将所有的内存描述符存放在一个双向链表中，第一个元素是init_mm的mmlist字段。
	* mm_users 存放共享mm_struct数据结构的轻量级进程的个数。
	* mm_count mm_count字段是内存描述符的主使用计数器，在mm_users次使用计数器中的所有用户在mm_count中只作为一个单元。每当mm_count递减时，内核都要检查它是否变为0，如果是，就要解除这个内存描述符，因为不再有用户使用它。

mm\_count 代表了对 mm 本身的引用，而 mm\_users 代表对 mm 相关资源的引用，分了两个层次。mm\_count类似于 以进程为单位。  mm\_users类似于以线程为单位。内核线程在运行时会借用其他进程的mm\_struct,这样的线程叫"anonymous users", 因为他们不关心mm\_struct指向的用户空间,也不会去访问这个用户空间，他们只是临时借用，m_count记录这样的线程。 mm\_users是对mm\_struct所指向的用户空间进行共享的所有进程的计数，也就是说会有多个进程共享同一个用户空间。

<h3>三. 线性区</h3>

Linux通过类型为vm\_area\_struct的对象对线性区进行管理，其定义如下：

	struct vm_area_struct {
		struct mm_struct * vm_mm;	/* The address space we belong to. */
		unsigned long vm_start;		/* Our start address within vm_mm. */
		unsigned long vm_end;		/* The first byte after our end address within vm_mm. */
	
		/* linked list of VM areas per task, sorted by address */
		struct vm_area_struct *vm_next;
	
	 	pgprot_t vm_page_prot;		/* Access permissions of this VMA. */
		unsigned long vm_flags;		/* Flags, listed below. */
	
	 	struct rb_node vm_rb;
	
		union {
			 struct {
				struct list_head list;
				void *parent;	/* aligns with prio_tree_node parent */
				struct vm_area_struct *head;
			} vm_set;
	
			struct raw_prio_tree_node prio_tree_node;
	 	} shared;
	
		struct list_head anon_vma_node;	/* Serialized by anon_vma->lock */
		struct anon_vma *anon_vma;	/* Serialized by page_table_lock */
	
		/* Function pointers to deal with this struct. */
	 	struct vm_operations_struct * vm_ops;
	
		/* Information about our backing store: */
		unsigned long vm_pgoff;		/* Offset (within vm_file) in PAGE_SIZE
						   units, *not* PAGE_CACHE_SIZE */
		struct file * vm_file;		/* File we map to (can be NULL). */
		void * vm_private_data;		/* was vm_pte (shared mem) */
		unsigned long vm_truncate_count;/* truncate_count or restart_addr */
	};

每一个线性区描述符表示一个线性地址区间。vm\_start字段包含区间的第一个线性地址，vm\_end字段包含区间之外的第一个线性地址。vm\_end-vm\_start表示线性区的长度。vm\_mm字段指向拥有这个区间的进程的mm\_struct内存描述符。

进程所拥有的线性区从来不重叠，并且内核尽力把新分配的线性区与紧邻的现有线性区进行合并。如果两个相邻区的访问权限相匹配，就能把它们合并在一起。如下图所示，当一个新的线性地址加入到进程的地址空间时，内核检查一个已经存在的线性区是否可以扩大（情况a）。如果不能，就创建一个新的线性区（情况b）。类似地，如果从进程地址空间删除一个线性地址空间，内核就要调整受影响的线性区大小（情况c）。有些情况下，调整大小迫使一个线性区被分成两个更小的部分（情况d）。

![](/assets/img/process_vm/1.jpg)

进程所拥有的所有线性区是通过一个简单的链表链接在一起的。出现在链表中的线性区是按内存地址的升序排列的；不过，每个线性区可以由未使用的内存地址区隔开。每个vm\_area\_struct元素的vm\_next字段指向链表的下一个元素。内核通过检查描述符mmap字段来查找线性区，其中mmap字符指向链表中的第一个线性区描述符。下图显示了进程的地址空间、它的内存描述符以及线性区链表三者之间的关系。


![](/assets/img/process_vm/2.PNG)

为了提高访问线性区的性能，Linux也使用了红-黑树。这两种数据结构包含指向同一线性区描述符的指针，当插入或删除一个线性区描述符时，内核通过红-黑树搜索前后元素，并用搜索结果快速更新链表而不用扫描链表。一般来说，红-黑树用来确定含有指定地址的线性区，而链表通常在扫描整个线性区集合时来使用。

下面随便看看一个进程的线性区。

	struct task_struct *t = pid_task(find_get_pid(2576),PIDTYPE_PID);
	struct mm_struct * mm = t->mm;
	struct vm_area_struct* vma = mm->mmap;
	int i;
	for(i = 0;i < mm->map_count;++i)
	{
	    printk("0x%x-----0x%x\n",vma->vm_start,vma->vm_end);
	    vma = vma->vm_next;
	}

通过dmesg看结果如下图。


![](/assets/img/process_vm/4.PNG)


这与通过cat /proc/2576/maps命令看的是一致，只有栈部分有少许差别。



![](/assets/img/process_vm/3.PNG)
