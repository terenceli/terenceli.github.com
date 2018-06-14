---
layout: post
title: "Anatomy of the Linux 'bdev' file system"
description: "Linux kernel"
category: 技术
tags: [Linux内核]
---
{% include JB/setup %}


'bdev' file system is used for block device's inode. 
This fs is initialized in function 'bdev\_cache\_init'

        void __init bdev_cache_init(void)
        {
            int err;
            static struct vfsmount *bd_mnt;

            bdev_cachep = kmem_cache_create("bdev_cache", sizeof(struct bdev_inode),
            0, (SLAB_HWCACHE_ALIGN|SLAB_RECLAIM_ACCOUNT|
                SLAB_MEM_SPREAD|SLAB_PANIC),
            init_once);
            err = register_filesystem(&bd_type);
            if (err)
                panic("Cannot register bdev pseudo-fs");
            bd_mnt = kern_mount(&bd_type);
            if (IS_ERR(bd_mnt))
                panic("Cannot create bdev pseudo-fs");
            blockdev_superblock = bd_mnt->mnt_sb;   /* For writeback */

            #define kern_mount(type) kern_mount_data(type, NULL)

            struct vfsmount *kern_mount_data(struct file_system_type *type, void *data)
            {
                struct vfsmount *mnt;
                mnt = vfs_kern_mount(type, MS_KERNMOUNT, type->name, data);
                if (!IS_ERR(mnt)) {
                /*
                * it is a longterm mount, don't release mnt until
                * we unmount before file sys is unregistered
                */
                real_mount(mnt)->mnt_ns = MNT_NS_INTERNAL;
                }
                return mnt;
            }

        struct vfsmount *
        vfs_kern_mount(struct file_system_type *type, int flags, const char *name, void *data)
        {
            struct mount *mnt;
            struct dentry *root;

            if (!type)
            return ERR_PTR(-ENODEV);

            mnt = alloc_vfsmnt(name);
            if (!mnt)
            return ERR_PTR(-ENOMEM);

            if (flags & MS_KERNMOUNT)
            mnt->mnt.mnt_flags = MNT_INTERNAL;

            root = mount_fs(type, flags, name, data);
            if (IS_ERR(root)) {
            free_vfsmnt(mnt);
            return ERR_CAST(root);
            }

            mnt->mnt.mnt_root = root;
            mnt->mnt.mnt_sb = root->d_sb;
            mnt->mnt_mountpoint = mnt->mnt.mnt_root;
            mnt->mnt_parent = mnt;
            lock_mount_hash();
            list_add_tail(&mnt->mnt_instance, &root->d_sb->s_mounts);
            unlock_mount_hash();
            return &mnt->mnt;
        }

After registering 'bdev' fs, the initialize function mounts it. 

        struct dentry *
        mount_fs(struct file_system_type *type, int flags, const char *name, void *data)
        {
            struct dentry *root;
            struct super_block *sb;
            char *secdata = NULL;
            int error = -ENOMEM;

            ...
            root = type->mount(type, flags, name, data);
            if (IS_ERR(root)) {
                error = PTR_ERR(root);
                goto out_free_secdata;
            }
            sb = root->d_sb;
            BUG_ON(!sb);
            WARN_ON(!sb->s_bdi);
            WARN_ON(sb->s_bdi == &default_backing_dev_info);
            sb->s_flags |= MS_BORN;
            ...
            /*
            * filesystems should never set s_maxbytes larger than MAX_LFS_FILESIZE
            * but s_maxbytes was an unsigned long long for many releases. Throw
            * this warning for a little while to try and catch filesystems that
            * violate this rule.
            */
            WARN((sb->s_maxbytes < 0), "%s set sb->s_maxbytes to "
            "negative value (%lld)\n", type->name, sb->s_maxbytes);

            up_write(&sb->s_umount);
            free_secdata(secdata);
            return root;
            out_sb:
            dput(root);
            deactivate_locked_super(sb);
            out_free_secdata:
            free_secdata(secdata);
            out:
            return ERR_PTR(error);
        }


'mount\_fs' first call 'type->mount' to get a root dentry. This type->mount is ''bd\_mount'.

        static struct dentry *bd_mount(struct file_system_type *fs_type,
        int flags, const char *dev_name, void *data)
        {
            return mount_pseudo(fs_type, "bdev:", &bdev_sops, NULL, BDEVFS_MAGIC);
        }

        struct dentry *mount_pseudo(struct file_system_type *fs_type, char *name,
            const struct super_operations *ops,
            const struct dentry_operations *dops, unsigned long magic)
        {
            struct super_block *s;
            struct dentry *dentry;
            struct inode *root;
            struct qstr d_name = QSTR_INIT(name, strlen(name));

            s = sget(fs_type, NULL, set_anon_super, MS_NOUSER, NULL);
            if (IS_ERR(s))
            return ERR_CAST(s);

            s->s_maxbytes = MAX_LFS_FILESIZE;
            s->s_blocksize = PAGE_SIZE;
            s->s_blocksize_bits = PAGE_SHIFT;
            s->s_magic = magic;
            s->s_op = ops ? ops : &simple_super_operations;
            s->s_time_gran = 1;
            root = new_inode(s);
            if (!root)
                goto Enomem;
                /*
                * since this is the first inode, make it number 1. New inodes created
                * after this must take care not to collide with it (by passing
                * max_reserved of 1 to iunique).
                */
                root->i_ino = 1;
                root->i_mode = S_IFDIR | S_IRUSR | S_IWUSR;
                root->i_atime = root->i_mtime = root->i_ctime = CURRENT_TIME;
                dentry = __d_alloc(s, &d_name);
                if (!dentry) {
                iput(root);
                goto Enomem;
            }
            d_instantiate(dentry, root);
            s->s_root = dentry;
            s->s_d_op = dops;
            s->s_flags |= MS_ACTIVE;
            return dget(s->s_root);

            Enomem:
            deactivate_locked_super(s);
            return ERR_PTR(-ENOMEM);
        }

In' mount\_pseudo', we first allocate a super\_block and then allocate the root inode and dentry and initialize these data. The super\_operations for this 'bdev' fs is 'bdev\_sops'.

    static const struct super_operations bdev_sops = {
        .statfs = simple_statfs,
        .alloc_inode = bdev_alloc_inode,
        .destroy_inode = bdev_destroy_inode,
        .drop_inode = generic_delete_inode,
        .evict_inode = bdev_evict_inode,
    };

Finally the super block in 'bd\_mnt->mnt\_sb' is assigned the global variable 'blockdev\_superblock'. After 'bdev' is registered, the structure has following shape.

                                   super_operations
                                  +--------------+
                                  |              |
                                  +--------------|
                                  |bdev_alloc_inode
    blockde^_superblock           +--------------+
           +----------+           |              |
           |          |           |              |
           |          |           |              |
           +----------+           |              |
           | s_op     +---------> +--------------+
           +----------+
           | s_root   +---------> +--------------+         inode
           +----------+           |              |         +---------+
                                  |              |         |         |
                                  |              |         |         |
                                  |              |         |         |
                                  +--------------+         |         |
                                  |  d_inode     +-------> +---------+
                                  +--------------+
                                 dentry
    