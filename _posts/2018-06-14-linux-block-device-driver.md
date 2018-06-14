---
layout: post
title: "Anatomy of the Linux block device driver"
description: "Linux kernel"
category: 技术
tags: [Linux内核]
---
{% include JB/setup %}

In linux device driver, the block device is different from the char device which one we have discussed before. In this article we will discuss the block device driver. 

### block subsystem initialization

Block subsystem is initialized in 'genhd\_device\_init' function.


    static int __init genhd_device_init(void)
    {
      int error;

      block_class.dev_kobj = sysfs_dev_block_kobj;
      error = class_register(&block_class);
      if (unlikely(error))
        return error;
      bdev_map = kobj_map_init(base_probe, &block_class_lock);
      blk_dev_init();

      register_blkdev(BLOCK_EXT_MAJOR, "blkext");

      /* create top-level block dir */
      if (!sysfs_deprecated)
        block_depr = kobject_create_and_add("block", NULL);
      return 0;
    }

'block\_class' will indicate the '/dev/block' directory.
'bdev\_map' is a 'struct kobj_map' which we has discussed in the char device driver. 
Initialization work seems quite simple.


### register block device's number

    int register_blkdev(unsigned int major, const char *name)
    {
      struct blk_major_name **n, *p;
      int index, ret = 0;

      mutex_lock(&block_class_lock);

      /* temporary */
      if (major == 0) {
        for (index = ARRAY_SIZE(major_names)-1; index > 0; index--) {
        if (major_names[index] == NULL)
          break;
        }

        if (index == 0) {
        printk("register_blkdev: failed to get major for %s\n",
                name);
        ret = -EBUSY;
        goto out;
        }
        major = index;
        ret = major;
      }

      p = kmalloc(sizeof(struct blk_major_name), GFP_KERNEL);
      if (p == NULL) {
        ret = -ENOMEM;
        goto out;
      }

      p->major = major;
      strlcpy(p->name, name, sizeof(p->name));
      p->next = NULL;
      index = major_to_index(major);

      for (n = &major_names[index]; *n; n = &(*n)->next) {
        if ((*n)->major == major)
        break;
      }
      if (!*n)
        *n = p;
      else
        ret = -EBUSY;

      if (ret < 0) {
        printk("register_blkdev: cannot get major %d for %s\n",
              major, name);
        kfree(p);
      }
      out:
      mutex_unlock(&block_class_lock);
      return ret;
      }

      static struct blk_major_name {
      struct blk_major_name *next;
      int major;
      char name[16];
    } *major_names[BLKDEV_MAJOR_HASH_SIZE];


'register\_blkdev' is very like 'register\_chrdev\_region' just except the former uses 'major\_names'. 'register\_blkdev' is used to manage the block device major number.

### block_device

'block\_device ' represent a logic block device. 

    struct block_device {
      dev_t   bd_dev;  /* not a kdev_t - it's a search key */
      int   bd_openers;
      struct inode *  bd_inode; /* will die */
      struct super_block * bd_super;
      struct mutex  bd_mutex; /* open/close mutex */
      struct list_head bd_inodes;
      void *   bd_claiming;
      void *   bd_holder;
      int   bd_holders;
      bool   bd_write_holder;
      #ifdef CONFIG_SYSFS
      struct list_head bd_holder_disks;
      #endif
      struct block_device * bd_contains;
      unsigned  bd_block_size;
      struct hd_struct * bd_part;
      /* number of times partitions within this device have been opened. */
      unsigned  bd_part_count;
      int   bd_invalidated;
      struct gendisk * bd_disk;
      struct request_queue *  bd_queue;
      struct list_head bd_list;
      /*
      * Private data.  You must have bd_claim'ed the block_device
      * to use this.  NOTE:  bd_claim allows an owner to claim
      * the same device multiple times, the owner must take special
      * care to not mess up bd_private for that case.
      */
      unsigned long  bd_private;

      /* The counter of freeze processes */
      int   bd_fsfreeze_count;
      /* Mutex for freeze */
      struct mutex  bd_fsfreeze_mutex;
    };

This struct not only can represent a complete logical device, and also can represent a partition in a logical block device.If it is for a complete block device, the 'bd\_part' represents this device's partition info. if it is for a partition, the 'bd\_contains' indicates the block device which belongs to. When a block device or its partition has been open, the kernel will create a 'block\_device', we will discuss later. 'block\_device' is used for connecting the virtual file system and block device driver, so the block device driver has little chance to control it. 'block\_device' is often used with the 'bdev' file system. 

### struct gendisk

struct gendisk represents a real disk. It is allocated and controled by the block device driver.

    struct gendisk {
      /* major, first_minor and minors are input parameters only,
      * don't use directly.  Use disk_devt() and disk_max_parts().
      */
      int major;   /* major number of driver */
      int first_minor;
      int minors;                     /* maximum number of minors, =1 for
                                              * disks that can't be partitioned. */

      char disk_name[DISK_NAME_LEN]; /* name of major driver */
      char *(*devnode)(struct gendisk *gd, umode_t *mode);

      unsigned int events;  /* supported events */
      unsigned int async_events; /* async events, subset of all */

      /* Array of pointers to partitions indexed by partno.
      * Protected with matching bdev lock but stat and other
      * non-critical accesses use RCU.  Always access through
      * helpers.
      */
      struct disk_part_tbl __rcu *part_tbl;
      struct hd_struct part0;

      const struct block_device_operations *fops;
      struct request_queue *queue;
      void *private_data;

      int flags;
      struct device *driverfs_dev;  // FIXME: remove
      struct kobject *slave_dir;

      struct timer_rand_state *random;
      atomic_t sync_io;  /* RAID */
      struct disk_events *ev;
      #ifdef  CONFIG_BLK_DEV_INTEGRITY
      struct blk_integrity *integrity;
      #endif
      int node_id;
    };

'minors' indicates the max minor device, if it is one, we can't make partition for this block device.

'disk\_part\_tbl' represents the disk's partition table info, in his field, the 'part' represents the partitions.

'queue' represents the I/O request in this block device.

'part0' indicates the first partition, if no partition it represent the whole device.

The block device driver has to allocate gendisk and initialize the field in it. gendisk can represent a partitioned disk or no partition disk, when the driver calls' 'add\_disk' to add it to system, the kernel will decide whether scan this partition info.

### struct hd_struct

'hd\_struct' represents a partition info in a block device.

    struct hd_struct {
      sector_t start_sect;
      /*
      * nr_sects is protected by sequence counter. One might extend a
      * partition while IO is happening to it and update of nr_sects
      * can be non-atomic on 32bit machines with 64bit sector_t.
      */
      sector_t nr_sects;
      seqcount_t nr_sects_seq;
      sector_t alignment_offset;
      unsigned int discard_alignment;
      struct device __dev;
      struct kobject *holder_dir;
      int policy, partno;
      struct partition_meta_info *info;
      #ifdef CONFIG_FAIL_MAKE_REQUEST
      int make_it_fail;
      #endif
      unsigned long stamp;
      atomic_t in_flight[2];
      #ifdef CONFIG_SMP
      struct disk_stats __percpu *dkstats;
      #else
      struct disk_stats dkstats;
      #endif
      atomic_t ref;
      struct rcu_head rcu_head;
    };

'start\_sect', 'nr\_sects' and 'parto' represen this partition's start sector, number of sectors and partition number. The '\_\_dev' means a partition will be considered as a device.

### alloc_disk

'alloc\_disk' can be used to allocate a gendisk struct and also do some initialization.

    struct gendisk *alloc_disk(int minors)
    {
      return alloc_disk_node(minors, NUMA_NO_NODE);
    }

    struct gendisk *alloc_disk_node(int minors, int node_id)
    {
        struct gendisk *disk;

        disk = kzalloc_node(sizeof(struct gendisk), GFP_KERNEL, node_id);
        if (disk) {
          if (!init_part_stats(&disk->part0)) {
          kfree(disk);
          return NULL;
          }
          disk->node_id = node_id;
          if (disk_expand_part_tbl(disk, 0)) {
          free_part_stats(&disk->part0);
          kfree(disk);
          return NULL;
          }
          disk->part_tbl->part[0] = &disk->part0;

          /*
          * set_capacity() and get_capacity() currently don't use
          * seqcounter to read/update the part0->nr_sects. Still init
          * the counter as we can read the sectors in IO submission
          * patch using seqence counters.
          *
          * TODO: Ideally set_capacity() and get_capacity() should be
          * converted to make use of bd_mutex and sequence counters.
          */
          seqcount_init(&disk->part0.nr_sects_seq);
          hd_ref_init(&disk->part0);

          disk->minors = minors;
          rand_initialize_disk(disk);
          disk_to_dev(disk)->class = &block_class;
          disk_to_dev(disk)->type = &disk_type;
          device_initialize(disk_to_dev(disk));
        }
        return disk;
    }

    int disk_expand_part_tbl(struct gendisk *disk, int partno)
    {
        struct disk_part_tbl *old_ptbl = disk->part_tbl;
        struct disk_part_tbl *new_ptbl;
        int len = old_ptbl ? old_ptbl->len : 0;
        int target = partno + 1;
        size_t size;
        int i;

        /* disk_max_parts() is zero during initialization, ignore if so */
        if (disk_max_parts(disk) && target > disk_max_parts(disk))
          return -EINVAL;

        if (target <= len)
          return 0;

        size = sizeof(*new_ptbl) + target * sizeof(new_ptbl->part[0]);
        new_ptbl = kzalloc_node(size, GFP_KERNEL, disk->node_id);
        if (!new_ptbl)
          return -ENOMEM;

        new_ptbl->len = target;

        for (i = 0; i < len; i++)
          rcu_assign_pointer(new_ptbl->part[i], old_ptbl->part[i]);

        disk_replace_part_tbl(disk, new_ptbl);
        return 0;
    }


The argument of 'alloc\_disk' minors indicates the max partition of this disk can have.
Tough work is done in 'alloc\_disk\_node'. 'disk\_expand\_part\_tbl' is to allocate the gendisk's part\_tbl field and then assigned the gendisk's part0 to disk->part_tbl->part[0]. part0 is a hd\_struct and also can represent a whole disk device. Finally 'alloc\_disk' will do the trivial work that the device driver model requires. 

### add_disk

After allocating the gendisk and do some initialization, we need add the gendisk to system.  This is done by 'add\_disk' function.

    void add_disk(struct gendisk *disk)
    {
        struct backing_dev_info *bdi;
        dev_t devt;
        int retval;

        /* minors == 0 indicates to use ext devt from part0 and should
        * be accompanied with EXT_DEVT flag.  Make sure all
        * parameters make sense.
        */
        WARN_ON(disk->minors && !(disk->major || disk->first_minor));
        WARN_ON(!disk->minors && !(disk->flags & GENHD_FL_EXT_DEVT));

        disk->flags |= GENHD_FL_UP;

        retval = blk_alloc_devt(&disk->part0, &devt);
        if (retval) {
          WARN_ON(1);
          return;
        }
        disk_to_dev(disk)->devt = devt;

        /* ->major and ->first_minor aren't supposed to be
        * dereferenced from here on, but set them just in case.
        */
        disk->major = MAJOR(devt);
        disk->first_minor = MINOR(devt);

        disk_alloc_events(disk);

        /* Register BDI before referencing it from bdev */
        bdi = &disk->queue->backing_dev_info;
        bdi_register_dev(bdi, disk_devt(disk));

        blk_register_region(disk_devt(disk), disk->minors, NULL,
              exact_match, exact_lock, disk);
        register_disk(disk);
        blk_register_queue(disk);

        /*
        * Take an extra ref on queue which will be put on disk_release()
        * so that it sticks around as long as @disk is there.
        */
        WARN_ON_ONCE(!blk_get_queue(disk->queue));

        retval = sysfs_create_link(&disk_to_dev(disk)->kobj, &bdi->dev->kobj,
              "bdi");
        WARN_ON(retval);

        disk_add_events(disk);
    }

In block device, the major number represent the device driver and the minor number represent a partition of the device driver manages. 'blk\_alloc\_devt' generates the block device device number. 
'blk\_register\_region' is a very important function as it adds the block device to the system just like the char does. Insert the devt to global variable 'bdev\_map'. 
Next is 'register\_disk':

    static void register_disk(struct gendisk *disk)
    {
        struct device *ddev = disk_to_dev(disk);
        struct block_device *bdev;
        struct disk_part_iter piter;
        struct hd_struct *part;
        int err;

        ddev->parent = disk->driverfs_dev;

        dev_set_name(ddev, "%s", disk->disk_name);

        /* delay uevents, until we scanned partition table */
        dev_set_uevent_suppress(ddev, 1);

        if (device_add(ddev))
          return;
        if (!sysfs_deprecated) {
          err = sysfs_create_link(block_depr, &ddev->kobj,
            kobject_name(&ddev->kobj));
          if (err) {
          device_del(ddev);
          return;
          }
    }

        /*
        * avoid probable deadlock caused by allocating memory with
        * GFP_KERNEL in runtime_resume callback of its all ancestor
        * devices
        */
        pm_runtime_set_memalloc_noio(ddev, true);

        disk->part0.holder_dir = kobject_create_and_add("holders", &ddev->kobj);
        disk->slave_dir = kobject_create_and_add("slaves", &ddev->kobj);

        /* No minors to use for partitions */
        if (!disk_part_scan_enabled(disk))
          goto exit;

        /* No such device (e.g., media were just removed) */
        if (!get_capacity(disk))
          goto exit;

        bdev = bdget_disk(disk, 0);
        if (!bdev)
          goto exit;

        bdev->bd_invalidated = 1;
        err = blkdev_get(bdev, FMODE_READ, NULL);
        if (err < 0)
          goto exit;
        blkdev_put(bdev, FMODE_READ);

        exit:
        /* announce disk after possible partitions are created */
        dev_set_uevent_suppress(ddev, 0);
        kobject_uevent(&ddev->kobj, KOBJ_ADD);

        /* announce possible partitions */
        disk_part_iter_init(&piter, disk, 0);
        while ((part = disk_part_iter_next(&piter)))
          kobject_uevent(&part_to_dev(part)->kobj, KOBJ_ADD);
        disk_part_iter_exit(&piter);
    }

The first part is to do the device model operation. Most important is 'device\_add', after this function, there will be a /dev/xx, /dev/ramhda for example. 
'disk\_part\_scan\_enabled' will return false if this disk can't be partitioned and 'register\_disk' wil exit. If it can, go ahead. 
'bdget\_disk' will get a 'block\_device' this is a very important struct 

    struct block_device *bdget_disk(struct gendisk *disk, int partno)
    {
        struct hd_struct *part;
        struct block_device *bdev = NULL;

        part = disk_get_part(disk, partno);
        if (part)
          bdev = bdget(part_devt(part));
        disk_put_part(part);

        return bdev;
    }
    EXPORT_SYMBOL(bdget_disk);

    struct block_device *bdget(dev_t dev)
    {
        struct block_device *bdev;
        struct inode *inode;

        inode = iget5_locked(blockdev_superblock, hash(dev),
          bdev_test, bdev_set, &dev);

        if (!inode)
          return NULL;

        bdev = &BDEV_I(inode)->bdev;

        if (inode->i_state & I_NEW) {
          bdev->bd_contains = NULL;
          bdev->bd_super = NULL;
          bdev->bd_inode = inode;
          bdev->bd_block_size = (1 << inode->i_blkbits);
          bdev->bd_part_count = 0;
          bdev->bd_invalidated = 0;
          inode->i_mode = S_IFBLK;
          inode->i_rdev = dev;
          inode->i_bdev = bdev;
          inode->i_data.a_ops = &def_blk_aops;
          mapping_set_gfp_mask(&inode->i_data, GFP_USER);
          inode->i_data.backing_dev_info = &default_backing_dev_info;
          spin_lock(&bdev_lock);
          list_add(&bdev->bd_list, &all_bdevs);
          spin_unlock(&bdev_lock);
          unlock_new_inode(inode);
        }
        return bdev;
    }

    struct inode *iget5_locked(struct super_block *sb, unsigned long hashval,
      int (*test)(struct inode *, void *),
      int (*set)(struct inode *, void *), void *data)
    {
        struct hlist_head *head = inode_hashtable + hash(sb, hashval);
        struct inode *inode;

        spin_lock(&inode_hash_lock);
        inode = find_inode(sb, head, test, data);
        spin_unlock(&inode_hash_lock);

        if (inode) {
          wait_on_inode(inode);
          return inode;
        }

        inode = alloc_inode(sb);
        if (inode) {
          struct inode *old;

          spin_lock(&inode_hash_lock);
          /* We released the lock, so.. */
          old = find_inode(sb, head, test, data);
          if (!old) {
          if (set(inode, data))
            goto set_failed;

          spin_lock(&inode->i_lock);
          inode->i_state = I_NEW;
          hlist_add_head(&inode->i_hash, head);
          spin_unlock(&inode->i_lock);
          inode_sb_list_add(inode);
          spin_unlock(&inode_hash_lock);

          /* Return the locked inode with I_NEW set, the
          * caller is responsible for filling in the contents
          */
          return inode;
          }

          /*
          * Uhhuh, somebody else created the same inode under
          * us. Use the old inode instead of the one we just
          * allocated.
          */
          spin_unlock(&inode_hash_lock);
          destroy_inode(inode);
          inode = old;
          wait_on_inode(inode);
        }
        return inode;

        set_failed:
        spin_unlock(&inode_hash_lock);
        destroy_inode(inode);
        return NULL;
    }

Here 'iget5\_locked' uses the global variable 'blockdev\_superblock' as the superblock and will finally call blockdev\_superblock->s_op->alloc_inode, this actually is 'bdev\_alloc\_inode'.

    static struct inode *bdev_alloc_inode(struct super_block *sb)
    {
        struct bdev_inode *ei = kmem_cache_alloc(bdev_cachep, GFP_KERNEL);
        if (!ei)
          return NULL;
        return &ei->vfs_inode;
    }

    struct bdev_inode {
        struct block_device bdev;
        struct inode vfs_inode;
    };


From this we know, 'iget5\_locked' return a inode in a 'bdev\_inode' struct and from this inode, we can actually get the 'block\_device' field 'bdev'. 
In 'iget5\_locked', it calls 'bdev\_set', this set the 'bdev.bd\_dev' to the disk's device number. 

    static int bdev_set(struct inode *inode, void *data)
    {
        BDEV_I(inode)->bdev.bd_dev = *(dev_t *)data;
        return 0;
    }

After get the 'block\_device', 'register\_disk' set 'bdev->bd\_invalidated' to 1, this give the kernel chance to scan this disk again.
Next is to call 'blkdev\_get', it actually calls '\_\_blkdev\_get'.

    int blkdev_get(struct block_device *bdev, fmode_t mode, void *holder)
    {
        struct block_device *whole = NULL;
        int res;

        WARN_ON_ONCE((mode & FMODE_EXCL) && !holder);

        if ((mode & FMODE_EXCL) && holder) {
          whole = bd_start_claiming(bdev, holder);
          if (IS_ERR(whole)) {
          bdput(bdev);
          return PTR_ERR(whole);
          }
        }

        res = __blkdev_get(bdev, mode, 0);

        if (whole) {
          struct gendisk *disk = whole->bd_disk;

          /* finish claiming */
          mutex_lock(&bdev->bd_mutex);
          spin_lock(&bdev_lock);

          if (!res) {
          BUG_ON(!bd_may_claim(bdev, whole, holder));
          /*
          * Note that for a whole device bd_holders
          * will be incremented twice, and bd_holder
          * will be set to bd_may_claim before being
          * set to holder
          */
          whole->bd_holders++;
          whole->bd_holder = bd_may_claim;
          bdev->bd_holders++;
          bdev->bd_holder = holder;
          }

          /* tell others that we're done */
          BUG_ON(whole->bd_claiming != holder);
          whole->bd_claiming = NULL;
          wake_up_bit(&whole->bd_claiming, 0);

          spin_unlock(&bdev_lock);

          /*
          * Block event polling for write claims if requested.  Any
          * write holder makes the write_holder state stick until
          * all are released.  This is good enough and tracking
          * individual writeable reference is too fragile given the
          * way @mode is used in blkdev_get/put().
          */
          if (!res && (mode & FMODE_WRITE) && !bdev->bd_write_holder &&
              (disk->flags & GENHD_FL_BLOCK_EVENTS_ON_EXCL_WRITE)) {
          bdev->bd_write_holder = true;
          disk_block_events(disk);
          }

          mutex_unlock(&bdev->bd_mutex);
          bdput(whole);
        }

        return res;
    }

 '\_\_blkdev\_get' is very long. Here we wil go to the first path, as it first calls :

    static int __blkdev_get(struct block_device *bdev, fmode_t mode, int for_part)
    {
        struct gendisk *disk;
        struct module *owner;
        int ret;
        int partno;
        int perm = 0;

        ...

        ret = -ENXIO;
        disk = get_gendisk(bdev->bd_dev, &partno);
        if (!disk)
          goto out;
        owner = disk->fops->owner;

        disk_block_events(disk);
        mutex_lock_nested(&bdev->bd_mutex, for_part);
        if (!bdev->bd_openers) {
          bdev->bd_disk = disk;
          bdev->bd_queue = disk->queue;
          bdev->bd_contains = bdev;
          if (!partno) {
          struct backing_dev_info *bdi;

          ret = -ENXIO;
          bdev->bd_part = disk_get_part(disk, partno);
          if (!bdev->bd_part)
            goto out_clear;

          ret = 0;
          if (disk->fops->open) {
            ret = disk->fops->open(bdev, mode);
            if (ret == -ERESTARTSYS) {
            /* Lost a race with 'disk' being
            * deleted, try again.
            * See md.c
            */
            disk_put_part(bdev->bd_part);
            bdev->bd_part = NULL;
            bdev->bd_disk = NULL;
            bdev->bd_queue = NULL;
            mutex_unlock(&bdev->bd_mutex);
            disk_unblock_events(disk);
            put_disk(disk);
            module_put(owner);
            goto restart;
            }
          }

          if (!ret) {
            bd_set_size(bdev,(loff_t)get_capacity(disk)<<9);
            bdi = blk_get_backing_dev_info(bdev);
            if (bdi == NULL)
            bdi = &default_backing_dev_info;
            bdev_inode_switch_bdi(bdev->bd_inode, bdi);
          }

          /*
          * If the device is invalidated, rescan partition
          * if open succeeded or failed with -ENOMEDIUM.
          * The latter is necessary to prevent ghost
          * partitions on a removed medium.
          */
          if (bdev->bd_invalidated) {
            if (!ret)
            rescan_partitions(disk, bdev);
            else if (ret == -ENOMEDIUM)
            invalidate_partitions(disk, bdev);
          }
          if (ret)
            goto out_clear;
          } 
          ...
        bdev->bd_openers++;
        if (for_part)
          bdev->bd_part_count++;
        mutex_unlock(&bdev->bd_mutex);
        disk_unblock_events(disk);
        return 0;

        out_clear:
        disk_put_part(bdev->bd_part);
        bdev->bd_disk = NULL;
        bdev->bd_part = NULL;
        bdev->bd_queue = NULL;
        bdev_inode_switch_bdi(bdev->bd_inode, &default_backing_dev_info);
        if (bdev != bdev->bd_contains)
          __blkdev_put(bdev->bd_contains, mode, 1);
        bdev->bd_contains = NULL;
        out_unlock_bdev:
        mutex_unlock(&bdev->bd_mutex);
        disk_unblock_events(disk);
        put_disk(disk);
        module_put(owner);
        out:
        bdput(bdev);

        return ret;
    }

First get the gendisk, here we see the device number bdev->bd_dev's usage.
Later, set some of the field of bdev, and 'bdev->bd\_part' points to 'disk->part0'. 
Then calls 'disk->fops->open(bdev, mode);'.
Later important function is 'rescan\_partitions':

    int rescan_partitions(struct gendisk *disk, struct block_device *bdev)
    {
      struct parsed_partitions *state = NULL;
      struct hd_struct *part;
      int p, highest, res;
      rescan:
      if (state && !IS_ERR(state)) {
        free_partitions(state);
        state = NULL;
      }

      res = drop_partitions(disk, bdev);
      if (res)
        return res;

      if (disk->fops->revalidate_disk)
        disk->fops->revalidate_disk(disk);
      check_disk_size_change(disk, bdev);
      bdev->bd_invalidated = 0;
      if (!get_capacity(disk) || !(state = check_partition(disk, bdev)))
        return 0;
      if (IS_ERR(state)) {
        /*
        * I/O error reading the partition table.  If any
        * partition code tried to read beyond EOD, retry
        * after unlocking native capacity.
        */
        if (PTR_ERR(state) == -ENOSPC) {
        printk(KERN_WARNING "%s: partition table beyond EOD, ",
                disk->disk_name);
        if (disk_unlock_native_capacity(disk))
          goto rescan;
        }
        return -EIO;
      }
      /*
      * If any partition code tried to read beyond EOD, try
      * unlocking native capacity even if partition table is
      * successfully read as we could be missing some partitions.
      */
      if (state->access_beyond_eod) {
        printk(KERN_WARNING
              "%s: partition table partially beyond EOD, ",
              disk->disk_name);
        if (disk_unlock_native_capacity(disk))
        goto rescan;
      }

      /* tell userspace that the media / partition table may have changed */
      kobject_uevent(&disk_to_dev(disk)->kobj, KOBJ_CHANGE);

      /* Detect the highest partition number and preallocate
      * disk->part_tbl.  This is an optimization and not strictly
      * necessary.
      */
      for (p = 1, highest = 0; p < state->limit; p++)
        if (state->parts[p].size)
        highest = p;

      disk_expand_part_tbl(disk, highest);

      /* add partitions */
      for (p = 1; p < state->limit; p++) {
        sector_t size, from;
        struct partition_meta_info *info = NULL;

        size = state->parts[p].size;
        if (!size)
        continue;

        from = state->parts[p].from;
        if (from >= get_capacity(disk)) {
        printk(KERN_WARNING
                "%s: p%d start %llu is beyond EOD, ",
                disk->disk_name, p, (unsigned long long) from);
        if (disk_unlock_native_capacity(disk))
          goto rescan;
        continue;
        }

        if (from + size > get_capacity(disk)) {
        printk(KERN_WARNING
                "%s: p%d size %llu extends beyond EOD, ",
                disk->disk_name, p, (unsigned long long) size);

        if (disk_unlock_native_capacity(disk)) {
          /* free state and restart */
          goto rescan;
        } else {
          /*
          * we can not ignore partitions of broken tables
          * created by for example camera firmware, but
          * we limit them to the end of the disk to avoid
          * creating invalid block devices
          */
          size = get_capacity(disk) - from;
        }
        }

        if (state->parts[p].has_info)
        info = &state->parts[p].info;
        part = add_partition(disk, p, from, size,
              state->parts[p].flags,
              &state->parts[p].info);
        if (IS_ERR(part)) {
        printk(KERN_ERR " %s: p%d could not be added: %ld\n",
                disk->disk_name, p, -PTR_ERR(part));
        continue;
        }
      #ifdef CONFIG_BLK_DEV_MD
        if (state->parts[p].flags & ADDPART_FLAG_RAID)
        md_autodetect_dev(part_to_dev(part)->devt);
      #endif
      }
      free_partitions(state);
      return 0;
    }

It calls 'check\_partition'. Every partition recognition function is in the globa variable 'check\_part', if there is no partition in disk, it will print 'unknown partition table'.
How about if there are partitions in this disk. It will call 'disk\_expand\_part\_tbl' to expand 'gendisk->part\_tbl'. Then call 'add\_partition' to add partition device to the system. 

    struct hd_struct *add_partition(struct gendisk *disk, int partno,
        sector_t start, sector_t len, int flags,
        struct partition_meta_info *info)
    {
        struct hd_struct *p;
        dev_t devt = MKDEV(0, 0);
        struct device *ddev = disk_to_dev(disk);
        struct device *pdev;
        struct disk_part_tbl *ptbl;
        const char *dname;
        int err;

        err = disk_expand_part_tbl(disk, partno);
        if (err)
          return ERR_PTR(err);
        ptbl = disk->part_tbl;

        if (ptbl->part[partno])
          return ERR_PTR(-EBUSY);

        p = kzalloc(sizeof(*p), GFP_KERNEL);
        if (!p)
          return ERR_PTR(-EBUSY);

        if (!init_part_stats(p)) {
          err = -ENOMEM;
          goto out_free;
        }

        seqcount_init(&p->nr_sects_seq);
        pdev = part_to_dev(p);

        p->start_sect = start;
        p->alignment_offset =
          queue_limit_alignment_offset(&disk->queue->limits, start);
        p->discard_alignment =
          queue_limit_discard_alignment(&disk->queue->limits, start);
        p->nr_sects = len;
        p->partno = partno;
        p->policy = get_disk_ro(disk);

        if (info) {
          struct partition_meta_info *pinfo = alloc_part_info(disk);
          if (!pinfo)
          goto out_free_stats;
          memcpy(pinfo, info, sizeof(*info));
          p->info = pinfo;
        }

        dname = dev_name(ddev);
        if (isdigit(dname[strlen(dname) - 1]))
          dev_set_name(pdev, "%sp%d", dname, partno);
        else
          dev_set_name(pdev, "%s%d", dname, partno);

        device_initialize(pdev);
        pdev->class = &block_class;
        pdev->type = &part_type;
        pdev->parent = ddev;

        err = blk_alloc_devt(p, &devt);
        if (err)
          goto out_free_info;
        pdev->devt = devt;

        /* delay uevent until 'holders' subdir is created */
        dev_set_uevent_suppress(pdev, 1);
        err = device_add(pdev);
        if (err)
          goto out_put;

        err = -ENOMEM;
        p->holder_dir = kobject_create_and_add("holders", &pdev->kobj);
        if (!p->holder_dir)
          goto out_del;

        dev_set_uevent_suppress(pdev, 0);
        if (flags & ADDPART_FLAG_WHOLEDISK) {
          err = device_create_file(pdev, &dev_attr_whole_disk);
          if (err)
          goto out_del;
        }

        /* everything is up and running, commence */
        rcu_assign_pointer(ptbl->part[partno], p);

        /* suppress uevent if the disk suppresses it */
        if (!dev_get_uevent_suppress(ddev))
          kobject_uevent(&pdev->kobj, KOBJ_ADD);

        hd_ref_init(p);
        return p;

        out_free_info:
        free_part_info(p);
        out_free_stats:
        free_part_stats(p);
        out_free:
        kfree(p);
        return ERR_PTR(err);
        out_del:
        kobject_put(p->holder_dir);
        device_del(pdev);
        out_put:
        put_device(pdev);
        blk_free_devt(devt);
        return ERR_PTR(err);
    }

First allocate a 'hd\_struct' to contain this partition infomation. Kernel take every partition as a seprate device, so for every 'add\_partition' will call 'device\_add' to add partition to system and generate a directory in /dev/, such as /dev/ramhda1, /dev/ramhda2. Notice tehre is no 'block\_device' for partition. 

After call 'register\_disk' in 'add\_disk', it calls 'blk\_register\_queue'. This function initialize the disk's request queue. 

    int blk_register_queue(struct gendisk *disk)
    {
        int ret;
        struct device *dev = disk_to_dev(disk);
        struct request_queue *q = disk->queue;

        if (WARN_ON(!q))
          return -ENXIO;

        /*
        * Initialization must be complete by now.  Finish the initial
        * bypass from queue allocation.
        */
        blk_queue_bypass_end(q);
        queue_flag_set_unlocked(QUEUE_FLAG_INIT_DONE, q);

        ret = blk_trace_init_sysfs(dev);
        if (ret)
          return ret;

        ret = kobject_add(&q->kobj, kobject_get(&dev->kobj), "%s", "queue");
        if (ret < 0) {
          blk_trace_remove_sysfs(dev);
          return ret;
        }

        kobject_uevent(&q->kobj, KOBJ_ADD);

        if (q->mq_ops)
          blk_mq_register_disk(disk);

        if (!q->request_fn)
          return 0;

        ret = elv_register_queue(q);
        if (ret) {
          kobject_uevent(&q->kobj, KOBJ_REMOVE);
          kobject_del(&q->kobj);
          blk_trace_remove_sysfs(dev);
          kobject_put(&dev->kobj);
          return ret;
        }

        return 0;
    }

Though it seems that this queue is related to the device requests, here we just see its initialization is doing something with the standard device model. 

So after 'add_disk' add the disk to system. The following struct has been created. 

                                          block_de^ice
                                          +---------------+ <--+
    +--------------------------------------+  bd_part      |    |
    |                                      +---------------+    |
    |            +-------------------------+  bd_disk      |    |
    |            |                         +---------------+    |
    |            |                         |  bd_contains  +----+
    |            |                         +---------------|
    |            |                         |bd_iinvalidated=0
    |            |                         +---------------+
    |            |                         |bd_openers=1   |
    |            |                         +---------------+
    |            |
    |            |
    |            |
    |            |
    |            v
    |               gendisk
    |            +-------------------+
    |            |                   |
    |            +-------------------+              disk_part_tbl
    |            |   *part_tbl       +------------> +---------------+
    |            +-------------------+              |               |
    |            |                   |              +---------------+
    |            |                   |              |    len        |
    |            |                   |              +---------------+
    |            |                   |              |               |
    |            |                   |              +---------------+
    +--------->  +-------------------+ <------------+    *part[0]   |
      part0      |   start_sect      |              +---------------+            hd_struct
                +-------------------+              |    *part[1]   +----------> +---------------+
                |   nr_sects        |              +---------------+            | start_sect    |
                +-------------------+                                           +---------------+
                |   __dev           |                                           | nr_sects      |
                +-------------------+                                           +---------------+
                |    partno=0       |                                           |  partno=1     |
                +-------------------+                                           +---------------+
                |                   |                                           |               |
                |                   |                                           +---------------+
                |                   |
                |                   |
                +-------------------+


### open block device

When we add devices to system, a node in /dev/ will be created, this is done in 'devtmpfs\_create\_node'. This node is created by the devtmpfs and when create the inode, 'init\_special\_inode' will be called.

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

So inode's i\_fop' will be 'def\_blk\_fops'. 

    const struct file_operations def_blk_fops = {
        .open  = blkdev_open,
        .release = blkdev_close,
        .llseek  = block_llseek,
        .read  = do_sync_read,
        .write  = do_sync_write,
        .aio_read = blkdev_aio_read,
        .aio_write = blkdev_aio_write,
        .mmap  = generic_file_mmap,
        .fsync  = blkdev_fsync,
        .unlocked_ioctl = block_ioctl,
        #ifdef CONFIG_COMPAT
        .compat_ioctl = compat_blkdev_ioctl,
        #endif
        .splice_read = generic_file_splice_read,
        .splice_write = generic_file_splice_write,
    };

When this block device such as /dev/ramhda is opened, 'blkdev\_open' will be called.

    static int blkdev_open(struct inode * inode, struct file * filp)
    {
        struct block_device *bdev;

        /*
        * Preserve backwards compatibility and allow large file access
        * even if userspace doesn't ask for it explicitly. Some mkfs
        * binary needs it. We might want to drop this workaround
        * during an unstable branch.
        */
        filp->f_flags |= O_LARGEFILE;

        if (filp->f_flags & O_NDELAY)
          filp->f_mode |= FMODE_NDELAY;
        if (filp->f_flags & O_EXCL)
          filp->f_mode |= FMODE_EXCL;
        if ((filp->f_flags & O_ACCMODE) == 3)
          filp->f_mode |= FMODE_WRITE_IOCTL;

        bdev = bd_acquire(inode);
        if (bdev == NULL)
          return -ENOMEM;

        filp->f_mapping = bdev->bd_inode->i_mapping;

        return blkdev_get(bdev, filp->f_mode, filp);
    }


This function does two thing, get the 'block\_device' bdev using 'bd\_acquire' and call 'blkdev\_get' function. 
'bd\_acquire' will return an exist 'block\_device' if open the whole disk, otherwise it will create a new 'block\_device' to return. Any way, after, 'bd\_acquire' return a 'block\_device'.
The next function is 'blkdev\_get'. This function was discussed before. It calls '\_\_blkdev\_get'. This time we will discuss the differenct path. We will use opening a partition of a disk as an example, this time the partno is 1.
First get the gendisk in '\_\_blkdev\_get'. 

    if (!bdev->bd_openers) {
          bdev->bd_disk = disk;
          bdev->bd_queue = disk->queue;
          bdev->bd_contains = bdev;
        ...
          struct block_device *whole;
          whole = bdget_disk(disk, 0);
          ret = -ENOMEM;
          if (!whole)
            goto out_clear;
          BUG_ON(for_part);
          ret = __blkdev_get(whole, mode, 1);
          if (ret)
            goto out_clear;
          bdev->bd_contains = whole;
          bdev_inode_switch_bdi(bdev->bd_inode,
            whole->bd_inode->i_data.backing_dev_info);
          bdev->bd_part = disk_get_part(disk, partno);
          if (!(disk->flags & GENHD_FL_UP) ||
              !bdev->bd_part || !bdev->bd_part->nr_sects) {
            ret = -ENXIO;
            goto out_clear;
          }
          bd_set_size(bdev, (loff_t)bdev->bd_part->nr_sects << 9);
      }

Then get the gendisk's block\_device and assign it to 'whole'. 'Whole' later assign to 'bdev->bd\_contains'. 
Then call '\_\_blkdev\_get(whole, mode, 1);' This goes to here:

    {
      if (bdev->bd_contains == bdev) {
      ret = 0;
      if (bdev->bd_disk->fops->open)
        ret = bdev->bd_disk->fops->open(bdev, mode);
      /* the same as first opener case, read comment there */
      if (bdev->bd_invalidated) {
        if (!ret)
        rescan_partitions(bdev->bd_disk, bdev);
        else if (ret == -ENOMEDIUM)
        invalidate_partitions(bdev->bd_disk, bdev);
      }
      if (ret)
        goto out_unlock_bdev;
      }

Mostly call the 'bd\_disk->fops->open'.
So here we can see, every disk has a 'block\_device' and it is created when the 'add\_disk' is called. For the partition, the kernel doesn't create 'block\_device' when detecting it and insert it to system, it is created when the partition is opened.
Following pic show the partition's 'device\_block' and the gendisk's 'device\_block'.

                                          block_de^ice
                                          +---------------+ <--+ <-----------------------------------+
    +--------------------------------------+  bd_part      |    |                                     |
    |                                      +---------------+    |                                     |
    |            +-------------------------+  bd_disk      |    |                                     |
    |            |                         +---------------+    |                                     |
    |            |                         |  bd_contains  +----+                                     |
    |            |                         +---------------+                                          |
    |            |                         |bd_iin^alidated=0                                         |
    |            |                         +---------------+                                          |
    |            |                         |bd_openers=1   |                 block_de^ice             |
    |            |                         +---------------+                 +---------------+        |
    |            |                                                      +----+  bd_part      |        |
    |            |                                                      |    +---------------+        |
    |            |                   +---------------------------------------+  bd_disk      |        |
    |            |                   |                                  |    +---------------+        |
    |            v                   v                                  |    |  bd_contains  +--------+
    |               gendisk                                             |    +---------------+
    |            +-------------------+                                  |    |bd_iin^alidated=
    |            |                   |                                  |    +---------------+
    |            +-------------------+              disk_part_tbl       |    |bd_openers=1   |
    |            |   *part_tbl       +------------> +---------------+   |    +---------------+
    |            +-------------------+              |               |   |
    |            |                   |              +---------------+   |
    |            |                   |              |    len        |   |
    |            |                   |              +---------------+   |
    |            |                   |              |               |   +-------+
    |            |                   |              +---------------+           |
    +--------->  +-------------------+ <------------+    *part[0]   |           v
      part0      |   start_sect      |              +---------------+            hd_struct
                +-------------------+              |    *part[1]   +----------> +---------------+
                |   nr_sects        |              +---------------+            | start_sect    |
                +-------------------+                                           +---------------+
                |   __de^           |                                           | nr_sects      |
                +-------------------+                                           +---------------+
                |    partno=0       |                                           |  partno=1     |
                +-------------------+                                           +---------------+
                |                   |                                           |               |
                |                   |                                           +---------------+
                |                   |
                |                   |
                +-------------------+


### blk_init_queue

The block device need a queue to contain the data request from the file system. And also a funtion to handle every request in the queue. There are two methods called 'request' and 'make request' to handle this. We first discuss the 'request' method.
When using 'request', the block device driver has to allocate a request queue by calling 'blk\_init\_queue'. The driver needs to implement a request handler function and pass this to 'blk\_init\_queue'.

      struct request_queue *blk_init_queue(request_fn_proc *rfn, spinlock_t *lock)
      {
        return blk_init_queue_node(rfn, lock, NUMA_NO_NODE);
      }

      struct request_queue *
      blk_init_queue_node(request_fn_proc *rfn, spinlock_t *lock, int node_id)
      {
        struct request_queue *uninit_q, *q;

        uninit_q = blk_alloc_queue_node(GFP_KERNEL, node_id);
        if (!uninit_q)
          return NULL;

        q = blk_init_allocated_queue(uninit_q, rfn, lock);
        if (!q)
          blk_cleanup_queue(uninit_q);

        return q;
      }

      typedef void (request_fn_proc) (struct request_queue *q);

      struct 'request\_queue' represents a request queue. It is a very complicated structure. 
      struct request_queue {
        /*
        * Together with queue_head for cacheline sharing
        */
        struct list_head queue_head;
        struct request  *last_merge;
        struct elevator_queue *elevator;
        int   nr_rqs[2]; /* # allocated [a]sync rqs */
        int   nr_rqs_elvpriv; /* # allocated rqs w/ elvpriv */

        /*
        * If blkcg is not used, @q->root_rl serves all requests.  If blkcg
        * is used, root blkg allocates from @q->root_rl and all other
        * blkgs from their own blkg->rl.  Which one to use should be
        * determined using bio_request_list().
        */
        struct request_list root_rl;

        request_fn_proc  *request_fn;
        make_request_fn  *make_request_fn;
        prep_rq_fn  *prep_rq_fn;
        unprep_rq_fn  *unprep_rq_fn;
        merge_bvec_fn  *merge_bvec_fn;
        softirq_done_fn  *softirq_done_fn;
        rq_timed_out_fn  *rq_timed_out_fn;
        dma_drain_needed_fn *dma_drain_needed;
        lld_busy_fn  *lld_busy_fn;

        struct blk_mq_ops *mq_ops;

        unsigned int  *mq_map;

        /* sw queues */
        struct blk_mq_ctx *queue_ctx;
        unsigned int  nr_queues;

        /* hw dispatch queues */
        struct blk_mq_hw_ctx **queue_hw_ctx;
        unsigned int  nr_hw_queues;

        /*
        * Dispatch queue sorting
        */
        sector_t  end_sector;
        struct request  *boundary_rq;

        /*
        * Delayed queue handling
        */
        struct delayed_work delay_work;

        struct backing_dev_info backing_dev_info;

        /*
        * The queue owner gets to use this for whatever they like.
        * ll_rw_blk doesn't touch it.
        */
        void   *queuedata;

        /*
        * various queue flags, see QUEUE_* below
        */
        unsigned long  queue_flags;

      ...};


'queue\_head' links all of the requests adding to this queue. The link's element is struct 'request' which represents a request. The kernel will reorder or merge requests for performance consideration.
'request\_fn' is the request handler function the driver implement. When other subsystems need to read or write data from the block device, kernel will this function if the device driver using the 'request' method.
'make\_request\_fn'. If device driver using 'blk\_init\_queue' to handle request('request' method), kernel will provide a standard function 'blk\_queue\_bio' for this field. If the device driver uses 'make\_request', it needs to call 'blk\_queue\_make\_request' to provide an implementation for this field.  'blk\_queue\_make\_request' doesn't allocate the request queue, so the device driver need call 'blk\_queue\_make\_request' to allocate a request queue when using the 'make\_request' method.
'queue\_flags' indicate the request queue's status, for example 'QUEUE\_FLAG\_STOPPED', 'QUEUE\_FLAG\_PLUGGED' and 'QUEUE\_FLAG\_QUEUED' and so on.

Every request is represented by an struct request.

    struct request {
      union {
        struct list_head queuelist;
        struct llist_node ll_list;
      };
      union {
        struct call_single_data csd;
        struct work_struct mq_flush_data;
      };

      struct request_queue *q;
      struct blk_mq_ctx *mq_ctx;

      u64 cmd_flags;
      enum rq_cmd_type_bits cmd_type;
      unsigned long atomic_flags;

      int cpu;

      /* the following two fields are internal, NEVER access directly */
      unsigned int __data_len; /* total data len */
      sector_t __sector;  /* sector cursor */

      struct bio *bio;
      struct bio *biotail;

      struct hlist_node hash; /* merge hash */
      /*
      * The rb_node is only used inside the io scheduler, requests
      * are pruned when moved to the dispatch queue. So let the
      * completion_data share space with the rb_node.
      */
      union {
        struct rb_node rb_node; /* sort/lookup */
        void *completion_data;
      };

      /*
      * Three pointers are available for the IO schedulers, if they need
      * more they have to dynamically allocate it.  Flush requests are
      * never put on the IO scheduler. So let the flush fields share
      * space with the elevator data.
      */
      union {
        struct {
        struct io_cq  *icq;
        void   *priv[2];
        } elv;

        struct {
        unsigned int  seq;
        struct list_head list;
        rq_end_io_fn  *saved_end_io;
        } flush;
      };

      struct gendisk *rq_disk;
      struct hd_struct *part;
      unsigned long start_time;
      #ifdef CONFIG_BLK_CGROUP
      struct request_list *rl;  /* rl this rq is alloced from */
      unsigned long long start_time_ns;
      unsigned long long io_start_time_ns;    /* when passed to hardware */
      #endif
      /* Number of scatter-gather DMA addr+len pairs after
      * physical address coalescing is performed.
      */
      unsigned short nr_phys_segments;
      #if defined(CONFIG_BLK_DEV_INTEGRITY)
      unsigned short nr_integrity_segments;
      #endif

      unsigned short ioprio;

      void *special;  /* opaque pointer available for LLD use */
      char *buffer;  /* kaddr of the current segment if available */

      int tag;
      int errors;

      /*
      * when request is used as a packet command carrier
      */
      unsigned char __cmd[BLK_MAX_CDB];
      unsigned char *cmd;
      unsigned short cmd_len;

      unsigned int extra_len; /* length of alignment and padding */
      unsigned int sense_len;
      unsigned int resid_len; /* residual count */
      void *sense;

      unsigned long deadline;
      struct list_head timeout_list;
      unsigned int timeout;
      int retries;

      /*
      * completion callback.
      */
      rq_end_io_fn *end_io;
      void *end_io_data;

      /* for bidi */
      struct request *next_rq;
    };

'queuelist' is used to links this request to struct blk\_plug. 
'q' represents the request queue of this request attached. 
'\_\_data\_len' represents the total bytes this requst requires. 
'\_\_sector' represents the start sector.
'bio' and 'biotail'.  When one bio is traslated or merged to a request, the request links these bio. If the device driver uses 'make_request', the device driver can access these bio in the request handler function. 

So let's look at 'blk\_init\_queue\_node' function.It calls two functions, as the name indicates alloc and init a queue. 'blk\_alloc\_queue\_node' allocates a queue and do some basic initialization. The more initialization work is done in 'blk\_init\_allocated\_queue'

    struct request_queue *
    blk_init_allocated_queue(struct request_queue *q, request_fn_proc *rfn,
      spinlock_t *lock)
    {
    if (!q)
      return NULL;

    if (blk_init_rl(&q->root_rl, q, GFP_KERNEL))
      return NULL;

    q->request_fn  = rfn;
    q->prep_rq_fn  = NULL;
    q->unprep_rq_fn  = NULL;
    q->queue_flags  |= QUEUE_FLAG_DEFAULT;

    /* Override internal queue lock with supplied lock pointer */
    if (lock)
      q->queue_lock  = lock;

    /*
    * This also sets hw/phys segments, boundary and size
    */
    blk_queue_make_request(q, blk_queue_bio);

    q->sg_reserved_size = INT_MAX;

    /* Protect q->elevator from elevator_change */
    mutex_lock(&q->sysfs_lock);

    /* init elevator */
    if (elevator_init(q, NULL)) {
      mutex_unlock(&q->sysfs_lock);
      return NULL;
    }

    mutex_unlock(&q->sysfs_lock);

    return q;
    }

We can see the assignment of 'q->request\_fn' and calls of 'blk\_queue\_make\_request'. 
'blk\_queue\_bio' will be used to generate the new requests and finally  calls the device driver implement's 'request\_fn'. 
Later is to call 'elevator\_init'. Kernel uses the 'elevator algorithm' to schedule the block requests. 'elevator\_init' chooses a elevator algorithm for queue 'q'. Here we will not care the detail of which algorithm the kernel uses. 
For now, we just need know the 'blk\_init\_queue' allocates and initializes a request queue for the block device, and chooses a schedule algorithm. 

For the 'make\_request' method, the device driver first call 'blk\_alloc\_queue'to allocates a request queue and then call 'blk\_queue\_make\_request' to assign the self-implementation make\_request function to 'q->make\_request\_fn'.

### submit requests to block devices

When the file system need to read or write data from disk, it need to send requests to the device's request queue, this is done by 'submit\_io'.
'bio' contains the request's detail.
When 'submit\_io' is called, the struct bio has been created. Here we don't care how to create a bio but just focus how the block device driver handle it.

    void submit_bio(int rw, struct bio *bio)
    {
      bio->bi_rw |= rw;

      /*
      * If it's a regular read/write or a barrier with data attached,
      * go through the normal accounting stuff before submission.
      */
      if (bio_has_data(bio)) {
        unsigned int count;

        if (unlikely(rw & REQ_WRITE_SAME))
        count = bdev_logical_block_size(bio->bi_bdev) >> 9;
        else
        count = bio_sectors(bio);

        if (rw & WRITE) {
        count_vm_events(PGPGOUT, count);
        } else {
        task_io_account_read(bio->bi_size);
        count_vm_events(PGPGIN, count);
        }

        if (unlikely(block_dump)) {
        char b[BDEVNAME_SIZE];
        printk(KERN_DEBUG "%s(%d): %s block %Lu on %s (%u sectors)\n",
        current->comm, task_pid_nr(current),
          (rw & WRITE) ? "WRITE" : "READ",
          (unsigned long long)bio->bi_sector,
          bdevname(bio->bi_bdev, b),
          count);
        }
      }

      generic_make_request(bio);
    }

    void generic_make_request(struct bio *bio)
    {
      struct bio_list bio_list_on_stack;

      if (!generic_make_request_checks(bio))
        return;

      /*
      * We only want one ->make_request_fn to be active at a time, else
      * stack usage with stacked devices could be a problem.  So use
      * current->bio_list to keep a list of requests submited by a
      * make_request_fn function.  current->bio_list is also used as a
      * flag to say if generic_make_request is currently active in this
      * task or not.  If it is NULL, then no make_request is active.  If
      * it is non-NULL, then a make_request is active, and new requests
      * should be added at the tail
      */
      if (current->bio_list) {
        bio_list_add(current->bio_list, bio);
        return;
      }

      /* following loop may be a bit non-obvious, and so deserves some
      * explanation.
      * Before entering the loop, bio->bi_next is NULL (as all callers
      * ensure that) so we have a list with a single bio.
      * We pretend that we have just taken it off a longer list, so
      * we assign bio_list to a pointer to the bio_list_on_stack,
      * thus initialising the bio_list of new bios to be
      * added.  ->make_request() may indeed add some more bios
      * through a recursive call to generic_make_request.  If it
      * did, we find a non-NULL value in bio_list and re-enter the loop
      * from the top.  In this case we really did just take the bio
      * of the top of the list (no pretending) and so remove it from
      * bio_list, and call into ->make_request() again.
      */
      BUG_ON(bio->bi_next);
      bio_list_init(&bio_list_on_stack);
      current->bio_list = &bio_list_on_stack;
      do {
        struct request_queue *q = bdev_get_queue(bio->bi_bdev);

        q->make_request_fn(q, bio);

        bio = bio_list_pop(current->bio_list);
      } while (bio);
      current->bio_list = NULL; /* deactivate */
    }

The most work is done by 'generic\_make\_request'. First check if the process has request to handle, if it is add this new bio to 'current->bio\_list'.

    if (current->bio_list) {
      bio_list_add(current->bio_list, bio);
      return;
    }

Then for every bio, it calls the 'make\_request\_fn'.

    do {
      struct request_queue *q = bdev_get_queue(bio->bi_bdev);

      q->make_request_fn(q, bio);

      bio = bio_list_pop(current->bio_list);
    } while (bio);

If the block device driver uses 'request', the 'make\_request\_fn' is 'blk\_queue\_bio.

    void blk_queue_bio(struct request_queue *q, struct bio *bio)
    {
      const bool sync = !!(bio->bi_rw & REQ_SYNC);
      struct blk_plug *plug;
      int el_ret, rw_flags, where = ELEVATOR_INSERT_SORT;
      struct request *req;
      unsigned int request_count = 0;

      /*
      * low level driver can indicate that it wants pages above a
      * certain limit bounced to low memory (ie for highmem, or even
      * ISA dma in theory)
      */
      blk_queue_bounce(q, &bio);

      if (bio_integrity_enabled(bio) && bio_integrity_prep(bio)) {
        bio_endio(bio, -EIO);
        return;
      }

      if (bio->bi_rw & (REQ_FLUSH | REQ_FUA)) {
        spin_lock_irq(q->queue_lock);
        where = ELEVATOR_INSERT_FLUSH;
        goto get_rq;
      }

      /*
      * Check if we can merge with the plugged list before grabbing
      * any locks.
      */
      if (blk_attempt_plug_merge(q, bio, &request_count))
        return;

      spin_lock_irq(q->queue_lock);

      el_ret = elv_merge(q, &req, bio);
      if (el_ret == ELEVATOR_BACK_MERGE) {
        if (bio_attempt_back_merge(q, req, bio)) {
        elv_bio_merged(q, req, bio);
        if (!attempt_back_merge(q, req))
          elv_merged_request(q, req, el_ret);
        goto out_unlock;
        }
      } else if (el_ret == ELEVATOR_FRONT_MERGE) {
        if (bio_attempt_front_merge(q, req, bio)) {
        elv_bio_merged(q, req, bio);
        if (!attempt_front_merge(q, req))
          elv_merged_request(q, req, el_ret);
        goto out_unlock;
        }
      }

      get_rq:
      /*
      * This sync check and mask will be re-done in init_request_from_bio(),
      * but we need to set it earlier to expose the sync flag to the
      * rq allocator and io schedulers.
      */
      rw_flags = bio_data_dir(bio);
      if (sync)
        rw_flags |= REQ_SYNC;

      /*
      * Grab a free request. This is might sleep but can not fail.
      * Returns with the queue unlocked.
      */
      req = get_request(q, rw_flags, bio, GFP_NOIO);
      if (unlikely(!req)) {
        bio_endio(bio, -ENODEV); /* @q is dead */
        goto out_unlock;
      }

      /*
      * After dropping the lock and possibly sleeping here, our request
      * may now be mergeable after it had proven unmergeable (above).
      * We don't worry about that case for efficiency. It won't happen
      * often, and the elevators are able to handle it.
      */
      init_request_from_bio(req, bio);

      if (test_bit(QUEUE_FLAG_SAME_COMP, &q->queue_flags))
        req->cpu = raw_smp_processor_id();

      plug = current->plug;
      if (plug) {
        /*
        * If this is the first request added after a plug, fire
        * of a plug trace.
        */
        if (!request_count)
        trace_block_plug(q);
        else {
        if (request_count >= BLK_MAX_REQUEST_COUNT) {
          blk_flush_plug_list(plug, false);
          trace_block_plug(q);
        }
        }
        list_add_tail(&req->queuelist, &plug->list);
        blk_account_io_start(req, true);
      } else {
        spin_lock_irq(q->queue_lock);
        add_acct_request(q, req, where);
        __blk_run_queue(q);
      out_unlock:
        spin_unlock_irq(q->queue_lock);
      }
    }

'blk\_queue\_bio' reorders or merges the bio with current requests if it can. If not, this function allocates a new request and uses the bio to initializes the request. The requests are processed in function '\_\_blk\_run\_queue'.

    void __blk_run_queue(struct request_queue *q)
    {
      if (unlikely(blk_queue_stopped(q)))
        return;

      __blk_run_queue_uncond(q);
      }
      inline void __blk_run_queue_uncond(struct request_queue *q)
      {
      if (unlikely(blk_queue_dead(q)))
        return;

      /*
      * Some request_fn implementations, e.g. scsi_request_fn(), unlock
      * the queue lock internally. As a result multiple threads may be
      * running such a request function concurrently. Keep track of the
      * number of active request_fn invocations such that blk_drain_queue()
      * can wait until all these request_fn calls have finished.
      */
      q->request_fn_active++;
      q->request_fn(q);
      q->request_fn_active--;
    }

In here we see it call the 'request\_fn' we implement in device driver. 
For now we can distinguish the difference 'request' and 'make\_request' method. When the block device driver uses 'request', the file system send the bio to block subsystem it is processed by the 'blk\_queue\_bio',  'blk\_queue\_bio' do a lot of work to optimize the bio and convert the bio to requests and call the driver's implementation of 'request\_fn' callback. As for 'make\_request' method, the driver actually implement his own 'blk\_queue\_bio', so these bio will not go to the IO scheduler and goes directly to the device driver's implementation of 'make\_request\_fn'. So the self-implementation of 'make\_request\_fn' need to process the bios directly, not the request. 
Most of the block device driver will use the 'request' method.
So end of the long article, hope you enjoy it. 