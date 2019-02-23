---
layout: post
title: "system call analysis: mount"
description: "mount syscall analysis"
category: 技术
tags: [内核]
---
{% include JB/setup %}

The data in disk is just raw bytes, the user need to access these data as file, so there shoud be a layer to abstract this. This is what file system does.

Linux supports a lot of file systems. There are kinds of file systems, for eaxmple ext2/3/4, xfs is for local storage, proc and sys are pseudo file systems and nfs is network file system.

Whenever we want to use a new storage, we need first make file system on it and then mount it in OS. After that, the user can access the data in the new storage.

This post is the onte for mount system call.
Following is the definition of mount system call:

        #include <sys/mount.h>

        int mount(const char *source, const char *target,
                const char *filesystemtype, unsigned long mountflags,
                const void *data);


The first argument 'source' often specifies a storage device's pathname.
The second argument 'target' sepcifies the location the 'source' will be attached.
The 'filesystemtype' specifies file system name such as 'ext4', 'xfs', 'iso9660' and so on.
The final argument 'data' is interpreted by different filesystems.

mount syscall is defined in fs/namespace.c.

        SYSCALL_DEFINE5(mount, char __user *, dev_name, char __user *, dir_name,
                char __user *, type, unsigned long, flags, void __user *, data)
        {
            int ret;
            char *kernel_type;
            char *kernel_dev;
            unsigned long data_page;

            kernel_type = copy_mount_string(type);
            ret = PTR_ERR(kernel_type);
            if (IS_ERR(kernel_type))
                goto out_type;

            kernel_dev = copy_mount_string(dev_name);
            ret = PTR_ERR(kernel_dev);
            if (IS_ERR(kernel_dev))
                goto out_dev;

            ret = copy_mount_options(data, &data_page);
            if (ret < 0)
                goto out_data;

            ret = do_mount(kernel_dev, dir_name, kernel_type, flags,
                (void *) data_page);

            free_page(data_page);
        out_data:
            kfree(kernel_dev);
        out_dev:
            kfree(kernel_type);
        out_type:
            return ret;
        }

Copy the userspace argument to kernel and then transfer the control to 'do\_mount'.

'do\_mount' first get the 'path' struct of userspace specified directory path. struct 'path' contains 'vfsmount' and 'dentry' and is used to present a directory patch's dentry.
Then 'do\_mount' according to 'flags' value and call corresponding function, such as 'do\_remount', 'do\_lookback', 'do\_change\_type' and so on. The default call is 'do\_new\_mount'. This add a new mount to a directory.


        static int do_new_mount(struct path *path, const char *fstype, int flags,
                    int mnt_flags, const char *name, void *data)
        {
            struct file_system_type *type;
            struct user_namespace *user_ns = current->nsproxy->mnt_ns->user_ns;
            struct vfsmount *mnt;
            int err;

            if (!fstype)
                return -EINVAL;

            type = get_fs_type(fstype);
            if (!type)
                return -ENODEV;

            if (user_ns != &init_user_ns) {
                if (!(type->fs_flags & FS_USERNS_MOUNT)) {
                    put_filesystem(type);
                    return -EPERM;
                }
                /* Only in special cases allow devices from mounts
                * created outside the initial user namespace.
                */
                if (!(type->fs_flags & FS_USERNS_DEV_MOUNT)) {
                    flags |= MS_NODEV;
                    mnt_flags |= MNT_NODEV | MNT_LOCK_NODEV;
                }
                if (type->fs_flags & FS_USERNS_VISIBLE) {
                    if (!fs_fully_visible(type, &mnt_flags)) {
                        put_filesystem(type);
                        return -EPERM;
                    }
                }
            }

            mnt = vfs_kern_mount(type, flags, name, data);
            if (!IS_ERR(mnt) && (type->fs_flags & FS_HAS_SUBTYPE) &&
                !mnt->mnt_sb->s_subtype)
                mnt = fs_set_subtype(mnt, fstype);

            put_filesystem(type);
            if (IS_ERR(mnt))
                return PTR_ERR(mnt);

            err = do_add_mount(real_mount(mnt), path, mnt_flags);
            if (err)
                mntput(mnt);
            return err;
        }


The mainly function called by 'do\_new\_mount' is 'vfs\_kern\_mount' and 'do\_add\_mount'.
'do\_new\_mount' create and initialize a new 'mount' to represent this new mount. 

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
                mnt_free_id(mnt);
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

It then calls 'mount\_fs', in this function it calls the system type registered 'mount' callback. The 'mount' callback read the device's super\_block and return the 'dentry' of the 'super\_block'. Then it initializes the struct 'mount'. 

After 'vfs\_kernel\_mount' finishes it calls 'do\_new\_mount', this function adds this new mount to the system.

        static int do_add_mount(struct mount *newmnt, struct path *path, int mnt_flags)
        {
            struct mountpoint *mp;
            struct mount *parent;
            int err;

            mnt_flags &= ~MNT_INTERNAL_FLAGS;

            mp = lock_mount(path);
            if (IS_ERR(mp))
                return PTR_ERR(mp);

            parent = real_mount(path->mnt);
            err = -EINVAL;
            if (unlikely(!check_mnt(parent))) {
                /* that's acceptable only for automounts done in private ns */
                if (!(mnt_flags & MNT_SHRINKABLE))
                    goto unlock;
                /* ... and for those we'd better have mountpoint still alive */
                if (!parent->mnt_ns)
                    goto unlock;
            }

            /* Refuse the same filesystem on the same mount point */
            err = -EBUSY;
            if (path->mnt->mnt_sb == newmnt->mnt.mnt_sb &&
                path->mnt->mnt_root == path->dentry)
                goto unlock;

            err = -EINVAL;
            if (d_is_symlink(newmnt->mnt.mnt_root))
                goto unlock;

            newmnt->mnt.mnt_flags = mnt_flags;
            err = graft_tree(newmnt, parent, mp);

        unlock:
            unlock_mount(mp);
            return err;
        }

Notice here the 'newmount' is the new created mount represents the new deivce.
And the 'path' is the directory that the device will be attached. This function does some check (for example, the same file system can't be attached to the directory twice) and then calls 'graft\_tree'. 'graft\_tree' calls 'attach_recursive_mnt' to add this new mount to system.

The most important is to set the relation of the new vfsmount and the parent vfsmount.

		mnt_set_mountpoint(dest_mnt, dest_mp, source_mnt);
		commit_tree(source_mnt);




