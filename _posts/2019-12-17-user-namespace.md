---
layout: post
title: "user namespace internals"
description: "user ns"
category: 技术
tags: [内核]
---
{% include JB/setup %}


Namespace is another method to abstract resouces. A namespace make it appear to the process within the namespace that they 
have their own isolated instance of the global resouces. Compared to the virtual machine, namespace is more lightweight. In this post, I will dig into the user namespace from kernel part. I used kernel 4.4 in this post.

<h3> Basic structure </h3>

There are six different types of namespaces, they are uts, ipc, mount, pid, net and user. The former five namespaces is structured together in 'nsproxy' structure. 

    struct nsproxy {
        atomic_t count;
        struct uts_namespace *uts_ns;
        struct ipc_namespace *ipc_ns;
        struct mnt_namespace *mnt_ns;
        struct pid_namespace *pid_ns_for_children;
        struct net 	     *net_ns;
    };

'task_struct' has a 'nsproxy' member pointing to a 'struct nsproxy' to present the process's resource view. However the 'struct nsproxy' has no user namespace. User namespace is special as it is used for the process's crendential. A user namespace is represented by 'struct user_namespace'. 'struct task_struct's cred contains the process's credential information. 'struct cred' has a 'user_ns' member to point the process's namespace.  'struct user_namespace' has following definition:

        struct user_namespace {
            struct uid_gid_map	uid_map;
            struct uid_gid_map	gid_map;
            struct uid_gid_map	projid_map;
            atomic_t		count;
            struct user_namespace	*parent;
            int			level;
            kuid_t			owner;
            kgid_t			group;
            struct ns_common	ns;
            unsigned long		flags;

            /* Register of per-UID persistent keyrings for this namespace */
        #ifdef CONFIG_PERSISTENT_KEYRINGS
            struct key		*persistent_keyring_register;
            struct rw_semaphore	persistent_keyring_register_sem;
        #endif
        };

'struct uid_gid_map' defines the mapping of uid/gid between process user namespace and child namespace. 'parent' points to the parent user namespace. Just as other namespaces, user namespace has a hierarchy structure, the 'level' represent the level of hierarchy. 'owner'/'group' is the effective uid/gid of the process. 'ns' is the common structure of namespace.

'struct uid_gid_map' is defined as follows:

        struct uid_gid_map {	/* 64 bytes -- 1 cache line */
            u32 nr_extents;
            struct uid_gid_extent {
                u32 first;
                u32 lower_first;
                u32 count;
            } extent[UID_GID_MAP_MAX_EXTENTS];
        };


As we know, when we write to /proc/PID/uid_map, we define the process's user namespace and his parent user namespace mapping of uid. The uid/gid_map has following format:

        ID-inside-ns   ID-outside-ns   length

Here 'ID-inside-ns' is the 'uid_gid_extent's 'first' member, 'ID-outside-ns' is the 'uid_gid_extent's 'lower_first' member and 'length' is the 'count' member. The uid/gid_map can have UID_GID_MAP_MAX_EXTENTS(5) lines. The 'lower' in 'lower_first' represent parent user namespace. 


Following pic shows the data structure relation.

![](/assets/img/userns/1.png)


<h3> System call behavior of user namespace </h3> 

<h4> clone </h4>
The most common way to create new namespaces is using clone system call. The most work is done in 'copy_process' function. 'copy_creds' is used to copy the parent's cred and copy user namespace. The other namespaces is created in 'copy_namespaces' function.


        int copy_creds(struct task_struct *p, unsigned long clone_flags)
        {
            struct cred *new;
            int ret;

            ...
            new = prepare_creds();
            if (!new)
                return -ENOMEM;

            if (clone_flags & CLONE_NEWUSER) {
                ret = create_user_ns(new);
                if (ret < 0)
                    goto error_put;
            }

            ...
            atomic_inc(&new->user->processes);
            p->cred = p->real_cred = get_cred(new);
            alter_cred_subscribers(new, 2);
            validate_creds(new);
            return 0;
        }

If the userspace specify 'CLONE_NEWUSER', 'copy_creds' will call 'create_user_ns' to create a new user namespace. 


        int create_user_ns(struct cred *new)
        {
            struct user_namespace *ns, *parent_ns = new->user_ns;
            kuid_t owner = new->euid;
            kgid_t group = new->egid;
            int ret;

            if (parent_ns->level > 32)
                return -EUSERS;

            /*
            * Verify that we can not violate the policy of which files
            * may be accessed that is specified by the root directory,
            * by verifing that the root directory is at the root of the
            * mount namespace which allows all files to be accessed.
            */
            if (current_chrooted())
                return -EPERM;

            /* The creator needs a mapping in the parent user namespace
            * or else we won't be able to reasonably tell userspace who
            * created a user_namespace.
            */
            if (!kuid_has_mapping(parent_ns, owner) ||
                !kgid_has_mapping(parent_ns, group))
                return -EPERM;

            ns = kmem_cache_zalloc(user_ns_cachep, GFP_KERNEL);
            if (!ns)
                return -ENOMEM;

            ret = ns_alloc_inum(&ns->ns);
            if (ret) {
                kmem_cache_free(user_ns_cachep, ns);
                return ret;
            }
            ns->ns.ops = &userns_operations;

            atomic_set(&ns->count, 1);
            /* Leave the new->user_ns reference with the new user namespace. */
            ns->parent = parent_ns;
            ns->level = parent_ns->level + 1;
            ns->owner = owner;
            ns->group = group;

            /* Inherit USERNS_SETGROUPS_ALLOWED from our parent */
            mutex_lock(&userns_state_mutex);
            ns->flags = parent_ns->flags;
            mutex_unlock(&userns_state_mutex);

            set_cred_user_ns(new, ns);

        #ifdef CONFIG_PERSISTENT_KEYRINGS
            init_rwsem(&ns->persistent_keyring_register_sem);
        #endif
            return 0;
        }


First we need do some check. The namespace's level can has 32 maximum. The chrooted process can't create namespace. The creator also need to has a mapping in the parent user namespace so that we can track the namespace's parental relation. 'kuid_has_mapping' has following definition:

        static inline bool kuid_has_mapping(struct user_namespace *ns, kuid_t uid)
        {
            return from_kuid(ns, uid) != (uid_t) -1;
        }

        uid_t from_kuid(struct user_namespace *targ, kuid_t kuid)
        {
            /* Map the uid from a global kernel uid */
            return map_id_up(&targ->uid_map, __kuid_val(kuid));
        }

        static u32 map_id_up(struct uid_gid_map *map, u32 id)
        {
            unsigned idx, extents;
            u32 first, last;

            /* Find the matching extent */
            extents = map->nr_extents;
            smp_rmb();
            for (idx = 0; idx < extents; idx++) {
                first = map->extent[idx].lower_first;
                last = first + map->extent[idx].count - 1;
                if (id >= first && id <= last)
                    break;
            }
            /* Map the id or note failure */
            if (idx < extents)
                id = (id - first) + map->extent[idx].first;
            else
                id = (u32) -1;

            return id;
        }

The 'creator'(parent process' euid) must has a mapping in the parent namespace. If not, the child namespace will has no information who created a user namespace.

After all thess check, 'create_user_ns' allocates a 'user_namespace' struct and do some intialization. We need to set the new created user_namespace's parent to its parent user_namespace, and add its level. Finally in 'set_cred_user_ns' the 'cred's 'user_ns' member is set to the newly created 'user_namespace'.

<h4> unshare </h4>

The unshare system call is easy, as it just create a new user_namespace for the caller process.

        int unshare_userns(unsigned long unshare_flags, struct cred **new_cred)
        {
            struct cred *cred;
            int err = -ENOMEM;

            if (!(unshare_flags & CLONE_NEWUSER))
                return 0;

            cred = prepare_creds();
            if (cred) {
                err = create_user_ns(cred);
                if (err)
                    put_cred(cred);
                else
                    *new_cred = cred;
            }

            return err;
        }


<h4> setns </h4>

Another way we can change the process to a new user namespace is using setns system call. This system call need a fd reffering to a namespace, which is in /proc/PID/ns/xxx.
'create_new_namespaces' function does nothing for user namespace. The calling 'ns->ops->install' does the work. First get ths 'ns_common' struct from the 'file struct'. 

        SYSCALL_DEFINE2(setns, int, fd, int, nstype)
        {
            struct task_struct *tsk = current;
            struct nsproxy *new_nsproxy;
            struct file *file;
            struct ns_common *ns;
            int err;

            file = proc_ns_fget(fd);
           
            ns = get_proc_ns(file_inode(file));
            if (nstype && (ns->ops->type != nstype))
                goto out;

            new_nsproxy = create_new_namespaces(0, tsk, current_user_ns(), tsk->fs);

            err = ns->ops->install(new_nsproxy, ns);
            
            switch_task_namespaces(tsk, new_nsproxy);
        out:
            fput(file);
            return err;
        }

For user namespace, the 'ns->ops->install' callback is 'userns_install'.

        static int userns_install(struct nsproxy *nsproxy, struct ns_common *ns)
        {
            struct user_namespace *user_ns = to_user_ns(ns);
            struct cred *cred;

            /* Don't allow gaining capabilities by reentering
            * the same user namespace.
            */
            if (user_ns == current_user_ns())
                return -EINVAL;

            /* Tasks that share a thread group must share a user namespace */
            if (!thread_group_empty(current))
                return -EINVAL;

            if (current->fs->users != 1)
                return -EINVAL;

            if (!ns_capable(user_ns, CAP_SYS_ADMIN))
                return -EPERM;

            cred = prepare_creds();
            if (!cred)
                return -ENOMEM;

            put_user_ns(cred->user_ns);
            set_cred_user_ns(cred, get_user_ns(user_ns));

            return commit_creds(cred);
        }


First get a 'user_namespace' from a 'ns_common' struct. After doing some check, it 'set_cred_user_ns' to set the process' cred's 'user_ns' member to the fd referring to.

<h4> getuid </h4>

        SYSCALL_DEFINE0(getuid)
        {
            /* Only we change this so SMP safe */
            return from_kuid_munged(current_user_ns(), current_uid());
        }


        uid_t from_kuid_munged(struct user_namespace *targ, kuid_t kuid)
        {
            uid_t uid;
            uid = from_kuid(targ, kuid);

            if (uid == (uid_t) -1)
                uid = overflowuid;
            return uid;
        }

The 'current_uid' return the user's UID. 'from_kuid' return the mapping uid of 'kuid' in user namespace 'targ'. If there is no mapping. the 'overlowuid' is returned. This is 'DEFAULT_OVERFLOWUID'. This is why we get following result if we just create a user namespace and not set the /proc/PID/uid_map mapping file.

        test@ubuntu:~/nstest$ unshare -U
        nobody@ubuntu:~/nstest$ id
        uid=65534(nobody) gid=65534(nogroup) groups=65534(nogroup)


<h3> User namespace hierarchy </h3>

From the last part, every user namespace has a parent except the 'init_user_ns'. 'init_user_ns' is hard-coded in the kernel as following:


        struct user_namespace init_user_ns = {
            .uid_map = {
                .nr_extents = 1,
                .extent[0] = {
                    .first = 0,
                    .lower_first = 0,
                    .count = 4294967295U,
                },
            },
            .gid_map = {
                .nr_extents = 1,
                .extent[0] = {
                    .first = 0,
                    .lower_first = 0,
                    .count = 4294967295U,
                },
            },
            .projid_map = {
                .nr_extents = 1,
                .extent[0] = {
                    .first = 0,
                    .lower_first = 0,
                    .count = 4294967295U,
                },
            },
            .count = ATOMIC_INIT(3),
            .owner = GLOBAL_ROOT_UID,
            .group = GLOBAL_ROOT_GID,
            .ns.inum = PROC_USER_INIT_INO,
        #ifdef CONFIG_USER_NS
            .ns.ops = &userns_operations,
        #endif
            .flags = USERNS_INIT_FLAGS,
        #ifdef CONFIG_PERSISTENT_KEYRINGS
            .persistent_keyring_register_sem =
            __RWSEM_INITIALIZER(init_user_ns.persistent_keyring_register_sem),
        #endif
        };

As we can see, the uid/gid mapping is the identical mapping. So if the process not use user namespace there is no effective. Les't take an example. Say we have a user which uid is 1000. Its user namespace is the 'init_user_ns'. 

![](/assets/img/userns/2.png)

Then the user creates two user namespaces named 'us1' and 'us2'. The 'us1' has a '0 1000 20' uid_map and the 'us2' has a '200 1000 20' uid_map. When write to the /proc/PDI/uid_map file. 
The 'proc_uid_map_write' is called and finally 'map_write' is called. In this function we can see how the 'uid_gid_map' is constructed.


		extent->first = simple_strtoul(pos, &pos, 10);
		if (!isspace(*pos))
			goto out;

		pos = skip_spaces(pos);
		extent->lower_first = simple_strtoul(pos, &pos, 10);
		if (!isspace(*pos))
			goto out;

		pos = skip_spaces(pos);
		extent->count = simple_strtoul(pos, &pos, 10);
		if (*pos && !isspace(*pos))
			goto out;


When the userspace read /proc/PID/uid_map, it uses a seq_file method. When the file is opened, the kernel calls 'proc_id_map_open'.


        static int proc_id_map_open(struct inode *inode, struct file *file,
            const struct seq_operations *seq_ops)
        {
            struct user_namespace *ns = NULL;
            struct task_struct *task;
            struct seq_file *seq;
            int ret = -EINVAL;

            task = get_proc_task(inode);
            if (task) {
                rcu_read_lock();
                ns = get_user_ns(task_cred_xxx(task, user_ns));
                rcu_read_unlock();
                put_task_struct(task);
            }
            if (!ns)
                goto err;

            ret = seq_open(file, seq_ops);
            if (ret)
                goto err_put_ns;

            seq = file->private_data;
            seq->private = ns;

            return 0;
        err_put_ns:
            put_user_ns(ns);
        err:
            return ret;
        }

Here we should notice, the 'seq->private' stores the /proc/PID/uid_map's process's user namespace. And also 'seq_open' sets the 'seq_file->file' to the file's struct file.

Following is the show process of the /proc/PID/uid_map.

        static int uid_m_show(struct seq_file *seq, void *v)
        {
            struct user_namespace *ns = seq->private;
            struct uid_gid_extent *extent = v;
            struct user_namespace *lower_ns;
            uid_t lower;

            lower_ns = seq_user_ns(seq);
            if ((lower_ns == ns) && lower_ns->parent)
                lower_ns = lower_ns->parent;

            lower = from_kuid(lower_ns, KUIDT_INIT(extent->lower_first));

            seq_printf(seq, "%10u %10u %10u\n",
                extent->first,
                lower,
                extent->count);

            return 0;
        }


        static inline struct user_namespace *seq_user_ns(struct seq_file *seq)
        {
        #ifdef CONFIG_USER_NS
            return seq->file->f_cred->user_ns;
        #else
            extern struct user_namespace init_user_ns;
            return &init_user_ns;
        #endif
        }

The 'ns' is the process's user namespace, and the 'lower_ns' is the open process's user namespace. So here we can see different open process may have different value of /proc/PID/uid_map. We have talked about 'from_kuid' above, it returns the 'kuid's mapping in the 'targ' user_namespace. 


So let's say our example. us1 has '0 1000 1' uid_map, us2 has '200 1000 1' uid_map.

So When the process in us1 read the process in us2's /proc/US2/uid_map. The 'lower_ns' in 'uid_m_show' will be the us1 process, the 'extent' will be the us2 process. So it will show 
'200 0 1'. Conversely, when the process in us2 read the /proc/US1/uid_map. It will show '0 200 1'. 

Following pics show the case.

![](/assets/img/userns/3.png)

![](/assets/img/userns/4.png)


