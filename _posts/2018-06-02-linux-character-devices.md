---
layout: post
title: "Anatomy of the Linux character devices"
description: "Linux kernel"
category: 技术
tags: [Linux内核]
---
{% include JB/setup %}

Character device is one of the class of Linux devices. The coordinative devices contain block devices, network devices. Every class of devices has its own support infrastructure by kernel, often called device driver model. This article will disscuss the simple character devices model.

First we need prepare a simple character device driver and user program using it.

        root@debian986:~# cat demo_chr_dev.c
        #include <linux/module.h>
        #include <linux/kernel.h>
        #include <linux/fs.h>
        #include <linux/cdev.h>

        static struct cdev chr_dev;
        static dev_t ndev;

        static int chr_open(struct inode *nd, struct file *filp)
        {
            int major = MAJOR(nd->i_rdev);
            int minor = MINOR(nd->i_rdev);
            printk("chr_open, major = %d, minor = %d\n", major, minor);
            return 0;
        }

        static ssize_t chr_read(struct file *f, char __user *u, loff_t *off)
        {
            printk("In the chr_read() function\n");
            return 0;
        }

        struct file_operations chr_ops = 
        {
            .owner = THIS_MODULE,
            .open = chr_open,
            .read = chr_read,
        };

        static int demo_init(void)
        {
            int ret;
            cdev_init(&chr_dev, &chr_ops);
            ret = alloc_chrdev_region(&ndev, 0, 1, "chr_dev");
            if(ret < 0)
                return ret;
            printk("demo_init():major = %d, minor = %d\n",MAJOR(ndev), MINOR(ndev));
            ret = cdev_add(&chr_dev, ndev, 1);
            if(ret < 0)
                return ret;
            return 0;
        }

        static void demo_exit(void)
        {
            printk("Removing chr_dev module...\n");
            cdev_del(&chr_dev);
            unregister_chrdev(ndev, 1);
        }

        module_init(demo_init);
        module_exit(demo_exit);

        MODULE_LICENSE("GPL");

        root@debian986:~# cat Makefile 
        obj-m := demo_chr_dev.o
        KERNELDIR := /lib/modules/$(shell uname -r)/build
        PWD := $(shell pwd)

        default:
            $(MAKE) -C $(KERNELDIR) M=$(PWD) modules

        clean:
            rm -f *.o *.ko *.mod.c


The userspace program:

        root@debian986:~# cat main.c 
        #include <stdio.h>
        #include <fcntl.h>
        #include <unistd.h>

        #define CHR_DEV_NAME "/dev/chr_dev"

        int main()
        {
            int ret;
            char buf[32];
            int fd = open(CHR_DEV_NAME, O_RDONLY | O_NDELAY);
            if(fd < 0)
            {
            printf("open file %s failed\n", CHR_DEV_NAME);
                return -1;
            }
            read(fd, buf, 32);
            close(fd);
            return 0;
        }


First install the ko, using dmesg we can the major and minor number of the device.

        [  917.528480] demo_init():major = 249, minor = 0

Then we using maknod to create an entry in /dev directory:

        root@debian986:~# mknod /dev/chr_dev c 249 0

Now we have a chracter device, and run the main program, dmesg can show the open and read function has been executed.

        [  978.055050] chr_open, major = 249, minor = 0
        [  978.055055] In the chr_read() function

# character device abstract

Linux kernel uses struct 'cdev' to represent charater devices.

        //<include/linux/cdev.h>
        struct cdev {
            struct kobject kobj;
            struct module *owner;
            const struct file_operations *ops;
            struct list_head list;
            dev_t dev;
            unsigned int count;
        };

The most import field hereis 'struct file\_operations' which define the interface to virtual file system, when the user program trigger system call like open/read/write, it will finally go to the function which ops defines.

'dev' here represent the device number containing major and minor.

'list' links all of the character devices in the system.
cdev's initialization:

        //<fs/char_dev.c>
        void cdev_init(struct cdev *cdev, const struct file_operations *fops)
        {
            memset(cdev, 0, sizeof *cdev);
            INIT_LIST_HEAD(&cdev->list);
            kobject_init(&cdev->kobj, &ktype_cdev_default);
            cdev->ops = fops;
        }

# device number

Every device has a device number which was combined of major and minor number. Major number is used to indicate device driver major for indicate which device of the same class device. 

'dev_t' is used to represent a device number, it is 32 unsigned bit.

        //<include/linux/types.h>
        typedef __u32 __kernel_dev_t;

        typedef __kernel_fd_set		fd_set;
        typedef __kernel_dev_t		dev_t;

Its' high 12 bits represents major number and low 20 bits represents minor number

        //<include/linux/kdev_t.h>
        #define MINORBITS	20

        #define MAJOR(dev)	((unsigned int) ((dev) >> MINORBITS))
        #define MINOR(dev)	((unsigned int) ((dev) & MINORMASK))

device number can be allocated by two function

        register_chrdev_region
        alloc_chrdev_region

The kernel uses 'chrdevs' global variable to manage device number's allocation

    static struct char_device_struct {
        struct char_device_struct *next;
        unsigned int major;
        unsigned int baseminor;
        int minorct;
        char name[64];
        struct cdev *cdev;		/* will die */
    } *chrdevs[CHRDEV_MAJOR_HASH_SIZE];


'register\_chrdev\_region' records the device number in the chrdevs array.

        int register_chrdev_region(dev_t from, unsigned count, const char *name)
        {
            struct char_device_struct *cd;
            dev_t to = from + count;
            dev_t n, next;

            for (n = from; n < to; n = next) {
                next = MKDEV(MAJOR(n)+1, 0);
                if (next > to)
                    next = to;
                cd = __register_chrdev_region(MAJOR(n), MINOR(n),
                        next - n, name);
                if (IS_ERR(cd))
                    goto fail;
            }
            return 0;
        fail:
            to = n;
            for (n = from; n < to; n = next) {
                next = MKDEV(MAJOR(n)+1, 0);
                kfree(__unregister_chrdev_region(MAJOR(n), MINOR(n), next - n));
            }
            return PTR_ERR(cd);
        }

The really work is done by '\_\_register\_chrdev\_region', which takes a major number and counts of the major. In this function, it insert the dev_t in the chrdevs's entry.
Of course we first need get the index:

        i = major_to_index(major);

Then '\_\_register\_chrdev\_region' check if the new added entry has conflicts with the already exists. If not added it in the chrdevs entry. After two 2 and 257 major number inserted:

            +------------------+
        0  |                  |
            +------------------+
        1  |                  |          struct char_device_struct
            +------------------+
        2  |                  +-------> +---------------+---> +---------------+
            +------------------+         |   next        |     |   next        |
            |                  |         +---------------+     +---------------+
            |                  |         |   major=2     |     |  major=257    |
            |                  |         +---------------+     +---------------+
            |                  |         | baseminor=0   |     | baseminor=0   |
            |                  |         +---------------+     +---------------+
            |                  |         |  minorct=1    |     |  minorct=4    |
            |                  |         +---------------+     +---------------+
            |                  |         |  "augdev"     |     |  "devmodev"   |
            |                  |         +---------------+     +---------------+
            +------------------+
        254  |                  |
            +------------------+



'alloc\_chrdev\_region' is different with 'register\_chrdev\_region' is that the former hints the kernel to allocate a usable major number instead of specifying one in the later. It iterates chrdevs from last and find and empty entry to return as the major number.

# character device registration

After initializing the char device and allocating the device number, we need register this char device to system. It is done by 'cdev\_add' function.

        int cdev_add(struct cdev *p, dev_t dev, unsigned count)
        {
            int error;

            p->dev = dev;
            p->count = count;

            error = kobj_map(cdev_map, dev, count, NULL,
                    exact_match, exact_lock, p);
            if (error)
                return error;

            kobject_get(p->kobj.parent);

            return 0;
        }

Quite simple, the 'p' is the device which need added, the 'dev' is the device number, and count is the number of devices.

The core is to call kobj\_map. 'kobj\_map' adds the char device to a global variable 'cdev\_map's hash table.  'cdev\_map' is defined:

        static struct kobj_map *cdev_map;

        struct kobj_map {
            struct probe {
                struct probe *next;
                dev_t dev;
                unsigned long range;
                struct module *owner;
                kobj_probe_t *get;
                int (*lock)(dev_t, void *);
                void *data;
            } *probes[255];
            struct mutex *lock;
        };

Here 'probes' field is liked the 'chrdevs' array, every entry represent a class of devices. The same value mod 255 is in the same entry.

        int kobj_map(struct kobj_map *domain, dev_t dev, unsigned long range,
                struct module *module, kobj_probe_t *probe,
                int (*lock)(dev_t, void *), void *data)
        {
            unsigned n = MAJOR(dev + range - 1) - MAJOR(dev) + 1;
            unsigned index = MAJOR(dev);
            unsigned i;
            struct probe *p;

            if (n > 255)
                n = 255;

            p = kmalloc(sizeof(struct probe) * n, GFP_KERNEL);

            if (p == NULL)
                return -ENOMEM;

            for (i = 0; i < n; i++, p++) {
                p->owner = module;
                p->get = probe;
                p->lock = lock;
                p->dev = dev;
                p->range = range;
                p->data = data;
            }
            mutex_lock(domain->lock);
            for (i = 0, p -= n; i < n; i++, p++, index++) {
                struct probe **s = &domain->probes[index % 255];
                while (*s && (*s)->range < range)
                    s = &(*s)->next;
                p->next = *s;
                *s = p;
            }
            mutex_unlock(domain->lock);
            return 0;
        }

'kobj\_map' first allocates a probe and then insert to one of the 'cdev\_map's probes entry.
Below show after calling 'cdev\_add' by two major satisfied major%255 = 2.


                    +------------------+
                0  |                  |
                    +------------------+
                1  |                  |          struct probe
                    +------------------+
                2  |                  +-------> +-------------------> +---------------+
                    +------------------+         |  next         |     |  next         |
                    |                  |         +---------------+     +---------------+
        probes[255]|                  |         |  dev          |     |               |
                    |                  |         +---------------+     +---------------+
                    |                  |         |               |     |               |
                    |                  |         +---------------+     +---------------+
                    |                  |         |    locak      |     |               |
                    |                  |         +---------------+     +---------------+
                    |                  |         |    data       +--+  |    data       |
                    |                  |         +---------------+  |  +---------------+
                    +------------------+                            |
            254  |                  |                            v
                    +------------------+                            +--------------+
                                                                    |              |
                                                                    +--------------+
                                                                    |              |
                                                                    +--------------+
                                                                    |              |
                                                                    +--------------+
                                                                    |              |
                                                                    +--------------+
                                                                    struct cdev


After calling 'cdev\_add', the char device has been added to the system. The system can find our char device if needed. Before our user program can call user char device driver's function, we need make a node in VFS so bridge the program and device driver.

# make device file node

Device file is used to make a bridge between userspace program and kernel driver. As we know in Linux everything is a file, so if we want to export the driver's service to user program, we must make an entry in VFS. We call mknod program in userspace will finally issues a 'mknod' system call.
The the kernel will allocate an inode in the filesystem. For now, we will just consider the how to connect the VFS and char device driver and emit the VFS connect to the specific filesystem. 
The 'vfs\_mknod' calls the specific filesystem's mknod function.


        int vfs_mknod(struct inode *dir, struct dentry *dentry, umode_t mode, dev_t dev)
        {
            int error = may_create(dir, dentry);

            if (error)
                return error;

            if ((S_ISCHR(mode) || S_ISBLK(mode)) && !capable(CAP_MKNOD))
                return -EPERM;

            if (!dir->i_op->mknod)
                return -EPERM;

            error = devcgroup_inode_mknod(mode, dev);
            if (error)
                return error;

            error = security_inode_mknod(dir, dentry, mode, dev);
            if (error)
                return error;

            error = dir->i_op->mknod(dir, dentry, mode, dev);
            if (!error)
                fsnotify_create(dir, dentry);
            return error;
        }

We will uses shmem filesystem as an example, the inode operationgs is 'shmem_dir_inode_operations'.
So it calls 'shmem\_mknod'.

        static int
        shmem_mknod(struct inode *dir, struct dentry *dentry, umode_t mode, dev_t dev)
        {
            struct inode *inode;
            int error = -ENOSPC;

            inode = shmem_get_inode(dir->i_sb, dir, mode, dev, VM_NORESERVE);
            if (inode) {
                error = simple_acl_create(dir, inode);
                if (error)
                    goto out_iput;
                error = security_inode_init_security(inode, dir,
                                    &dentry->d_name,
                                    shmem_initxattrs, NULL);
                if (error && error != -EOPNOTSUPP)
                    goto out_iput;

                error = 0;
                dir->i_size += BOGO_DIRENT_SIZE;
                dir->i_ctime = dir->i_mtime = CURRENT_TIME;
                d_instantiate(dentry, inode);
                dget(dentry); /* Extra count - pin the dentry in core */
            }
            return error;
        out_iput:
            iput(inode);
            return error;
        }

In 'shmem\_get\_inode', it allocates a new inode which represent our new create device, /dev/chr_dev for example. As our file is a char, it is special, so the 'init\_special\_inode' is called. 

        void init_special_inode(struct inode *inode, umode_t mode, dev_t rdev)
        {
            inode->i_mode = mode;
            if (S_ISCHR(mode)) {
                inode->i_fop = &def_chr_fops;
                inode->i_rdev = rdev;
            } else if (S_ISBLK(mode)) {
                inode->i_fop = &def_blk_fops;
                inode->i_rdev = rdev;
            } else if (S_ISFIFO(mode))
                inode->i_fop = &pipefifo_fops;
            else if (S_ISSOCK(mode))
                inode->i_fop = &bad_sock_fops;
            else
                printk(KERN_DEBUG "init_special_inode: bogus i_mode (%o) for"
                        " inode %s:%lu\n", mode, inode->i_sb->s_id,
                        inode->i_ino);
        }

This function's work is to set the inode's field 'i\_fop' and 'i\_rdev'. Char device's 'i\_fop' is set to 'def\_chr\_fops':

        const struct file_operations def_chr_fops = {
            .open = chrdev_open,
            .llseek = noop_llseek,
        };

The VFS and device driver is connected by 'inode->i\_rdev' now.

# Char device's operation

For now, the user program can open our device and issues system call like open/write/read.

do_sys_open
    -->do_filp_open
        -->path_openat
            -->do_last
                -->vfs_open
                    -->do_dentry_open


After a long call chain, we arrive 'do\_dentry\_open' function:

        static int do_dentry_open(struct file *f,
                    struct inode *inode,
                    int (*open)(struct inode *, struct file *),
                    const struct cred *cred)
        {
            static const struct file_operations empty_fops = {};
            int error;

            f->f_mode = OPEN_FMODE(f->f_flags) | FMODE_LSEEK |
                        FMODE_PREAD | FMODE_PWRITE;

            path_get(&f->f_path);
            f->f_inode = inode;
            f->f_mapping = inode->i_mapping;

            ...

            /* POSIX.1-2008/SUSv4 Section XSI 2.9.7 */
            if (S_ISREG(inode->i_mode))
                f->f_mode |= FMODE_ATOMIC_POS;

            f->f_op = fops_get(inode->i_fop);
            if (unlikely(WARN_ON(!f->f_op))) {
                error = -ENODEV;
                goto cleanup_all;
            }

            ...

            if (!open)
                open = f->f_op->open;
            if (open) {
                error = open(inode, f);
                if (error)
                    goto cleanup_all;
            }
            ...
        }


For now the 'inode' is our create '/dev/chr_dev' file. We assign 'inode->i\_fop' to 'f->f\_op'. As we know:

        inode->i_fop = &def_chr_fops;

So 
        f->f_op = &def_chr_fops
    
Later, it will call f\_op->open, which is 'chrdev\_open':

        static int chrdev_open(struct inode *inode, struct file *filp)
        {
            const struct file_operations *fops;
            struct cdev *p;
            struct cdev *new = NULL;
            int ret = 0;

            spin_lock(&cdev_lock);
            p = inode->i_cdev;
            if (!p) {
                struct kobject *kobj;
                int idx;
                spin_unlock(&cdev_lock);
                kobj = kobj_lookup(cdev_map, inode->i_rdev, &idx);
                if (!kobj)
                    return -ENXIO;
                new = container_of(kobj, struct cdev, kobj);
                spin_lock(&cdev_lock);
                /* Check i_cdev again in case somebody beat us to it while
                we dropped the lock. */
                p = inode->i_cdev;
                if (!p) {
                    inode->i_cdev = p = new;
                    list_add(&inode->i_devices, &p->list);
                    new = NULL;
                } else if (!cdev_get(p))
                    ret = -ENXIO;
            } else if (!cdev_get(p))
                ret = -ENXIO;
            spin_unlock(&cdev_lock);
            cdev_put(new);
            if (ret)
                return ret;

            ret = -ENXIO;
            fops = fops_get(p->ops);
            if (!fops)
                goto out_cdev_put;

            replace_fops(filp, fops);
            if (filp->f_op->open) {
                ret = filp->f_op->open(inode, filp);
                if (ret)
                    goto out_cdev_put;
            }

            return 0;

        out_cdev_put:
            cdev_put(p);
            return ret;
        }

'kobj\_lookup' find the cdev in 'cdev\_map' according the 'i\_rdev'. After succeeding find the cdev, filp's 'f\_op' will be replaced by our cdev's ops which is the struct file\_operations implemented in our char device driver. 

Next it calls the open function in struct file\_operations implemented in driver.


                                 +--------------------------+
                                 |   open("/dev/chr_dev")   |
                                 +----------+----+----------+
                                            |    ^
                                          1 |    |
                                            v    |
                                  +---------+----+-----+
                                  |  do_sys_open       |
                                  +--------+-----+-----+
                     inode                 |     |
                       +-----------+       |     +----------------5-------------------+
                       |           |       |                                          |
                       +-----------+       |       filp    +-------------+            |
                       |  i_fop    | <-----+               |             |            |
                       +-----------+                       +-------------+       +----+---+
                  +----+  i_rdev   |                   +---+  f_op       +-------+  fd    |
                  |    +-----------+                   |   +-------------+       +--------+
                  |    |  i_cdev   +--------------+    |   |            ||
                2 |    +-----------+              |    |   +-------------|
                  |                               |    +-------4-----------+
                  +----------------------+        |                        |
                                         |        3                   +--->v+----------------+
         +-------+     +--------+   +----v----+   |                   |     |    read        |
         |       +---> |        +-> |         |   |                   |     +----------------+
         +-------+     +--------+   +----+----+   |                   |     |    write       |
      cdev_map                           |        v                   |     +----------------+
                                         +------->----------------+   |     |    ioctl       |
                                        data      |               |   |     +----------------+
                                                  +---------------+   |     |    ...         |
                                                  |  ops          +---+     +----------------+
                                                  +---------------+         |    release     |
                                                  |               |         |----------------+
                                                  +---------------+            file_operations
                                                   cdev


The above pic show the process of open a device file in user process.

		1. The kernel call do_sys_open, get the file's inode and call i_fop, for char device i_fop is chrdev_open
		2. find the cdev in cdev_map according the inode->i_rdev
		3. assign the probe->data to inode->i_cdev, so that next no need to find in cdev_map
		4. assign the cdev->ops to filp->f_op, so the next file system sys call can directly call the driver's file_operations through fd->fip->f_op
		5. return the fd to user program

Let's look an example of how to use the fd returned by the open in close function.

		SYSCALL_DEFINE1(close, unsigned int, fd)
		{
			int retval = __close_fd(current->files, fd);

			/* can't restart close syscall because file table entry was cleared */
			if (unlikely(retval == -ERESTARTSYS ||
					retval == -ERESTARTNOINTR ||
					retval == -ERESTARTNOHAND ||
					retval == -ERESTART_RESTARTBLOCK))
				retval = -EINTR;

			return retval;
		}
		EXPORT_SYMBOL(sys_close);

		int __close_fd(struct files_struct *files, unsigned fd)
		{
			struct file *file;
			struct fdtable *fdt;

			spin_lock(&files->file_lock);
			fdt = files_fdtable(files);
			if (fd >= fdt->max_fds)
				goto out_unlock;
			file = fdt->fd[fd];
			if (!file)
				goto out_unlock;
			rcu_assign_pointer(fdt->fd[fd], NULL);
			__clear_close_on_exec(fd, fdt);
			__put_unused_fd(files, fd);
			spin_unlock(&files->file_lock);
			return filp_close(file, files);

		out_unlock:
			spin_unlock(&files->file_lock);
			return -EBADF;
		}

		int filp_close(struct file *filp, fl_owner_t id)
		{
			int retval = 0;

			if (!file_count(filp)) {
				printk(KERN_ERR "VFS: Close: file count is 0\n");
				return 0;
			}

			if (filp->f_op->flush)
				retval = filp->f_op->flush(filp, id);

			if (likely(!(filp->f_mode & FMODE_PATH))) {
				dnotify_flush(filp, id);
				locks_remove_posix(filp, id);
			}
			fput(filp);
			return retval;
		}

finnally go to \_\_fput

		static void __fput(struct file *file)
		{
			struct dentry *dentry = file->f_path.dentry;
			struct vfsmount *mnt = file->f_path.mnt;
			struct inode *inode = file->f_inode;

			might_sleep();

			fsnotify_close(file);
			/*
			* The function eventpoll_release() should be the first called
			* in the file cleanup chain.
			*/
			eventpoll_release(file);
			locks_remove_file(file);

			if (unlikely(file->f_flags & FASYNC)) {
				if (file->f_op->fasync)
					file->f_op->fasync(-1, file, 0);
			}
			ima_file_free(file);
			if (file->f_op->release)
				file->f_op->release(inode, file);
			security_file_free(file);
			if (unlikely(S_ISCHR(inode->i_mode) && inode->i_cdev != NULL &&
					!(file->f_mode & FMODE_PATH))) {
				cdev_put(inode->i_cdev);
			}
			fops_put(file->f_op);
			put_pid(file->f_owner.pid);
			if ((file->f_mode & (FMODE_READ | FMODE_WRITE)) == FMODE_READ)
				i_readcount_dec(inode);
			if (file->f_mode & FMODE_WRITER) {
				put_write_access(inode);
				__mnt_drop_write(mnt);
			}
			file->f_path.dentry = NULL;
			file->f_path.mnt = NULL;
			file->f_inode = NULL;
			file_free(file);
			dput(dentry);
			mntput(mnt);
		}


From above a can see, the kernel calls a lot of filp->f\_op function, which is defined in the struct file\_operations  in char device driver.