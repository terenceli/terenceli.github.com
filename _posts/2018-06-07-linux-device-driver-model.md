---
layout: post
title: "Anatomy of the Linux device driver model"
description: "Linux kernel"
category: 技术
tags: [Linux内核]
---
{% include JB/setup %}

Welcome back the anatomy series articles, this one we will talk about the Linux device driver model. 

##kobject and kset

kobject and kset is the basis of device driver model. Every kobject represent a kernel object. 

    struct kobject {
     const char  *name;
     struct list_head entry;
     struct kobject  *parent;
     struct kset  *kset;
     struct kobj_type *ktype;
     struct sysfs_dirent *sd;
     struct kref  kref;
    #ifdef CONFIG_DEBUG_KOBJECT_RELEASE
     struct delayed_work release;
    #endif
     unsigned int state_initialized:1;
     unsigned int state_in_sysfs:1;
     unsigned int state_add_uevent_sent:1;
     unsigned int state_remove_uevent_sent:1;
     unsigned int uevent_suppress:1;
    };

'name' indicates the object's name and will be show in a directory in sysfs file system.
'parent' indicates the object's parent, this makes  objects' hierarchical structure.
'kset' can be considered as a connection of the same kobject.
'ktype' represents the object's type, different objects has different type. kernel connects 'ktype' with the object's sysfs's file operations and attributes file.
'sd' indicates a directory entry instance in sysfs file syste. 
'uevent_suppress' indicates whether the 'kset' of this object belongs to should send an uevent to the userspace.

'kobject\_init' function is used to initialize a kobject.
'kobject_add' function create the object hierarchical and also create directory in sysfs, this directory will lies in 'parent' (while a parent is not NULL) or in the kset directory(parent is NULL) or in the root(if both NULL).

###kobject's attributes
There is a kobj\_type field in kobject。

      struct kobj_type {
       void (*release)(struct kobject *kobj);
       const struct sysfs_ops *sysfs_ops;
       struct attribute **default_attrs;
       const struct kobj_ns_type_operations *(*child_ns_type)(struct kobject *kobj);
       const void *(*namespace)(struct kobject *kobj);
      };
      
      
      
      struct sysfs_ops {
       ssize_t (*show)(struct kobject *, struct attribute *, char *);
       ssize_t (*store)(struct kobject *, struct attribute *, const char *, size_t);
      };
      
      struct attribute {
          const char      *name;
          umode_t         mode;
      #ifdef CONFIG_DEBUG_LOCK_ALLOC
          bool            ignore_lockdep:1;
          struct lock_class_key   *key;
          struct lock_class_key   skey;
      #endif
      };

'default\_attrs' defines some attributes and sysfs\_ops defines the operations that operates the attribute.

'sysfs\_create\_file' can be used for creating an attribute file in kobject.
When the userspace opena file in sysfs, 'sysfs\_open\_file' will be called, it allocates a struct 'struct sysfs\_open\_file ' of and call 'sysfs\_get\_open\_dirent', the later will set the 


        ((struct seq_file *)file->private_data)->private = data;

Later in writing:

        static ssize_t sysfs_write_file(struct file *file, const char __user *user_buf,
                        size_t count, loff_t *ppos)
        {
            struct sysfs_open_file *of = sysfs_of(file);
            ssize_t len = min_t(size_t, count, PAGE_SIZE);
            loff_t size = file_inode(file)->i_size;
            char *buf;
        
            if (sysfs_is_bin(of->sd) && size) {
                if (size <= *ppos)
                    return 0;
                len = min_t(ssize_t, len, size - *ppos);
            }
        
            if (!len)
                return 0;
        
            buf = kmalloc(len + 1, GFP_KERNEL);
            if (!buf)
                return -ENOMEM;
        
            if (copy_from_user(buf, user_buf, len)) {
                len = -EFAULT;
                goto out_free;
            }
            buf[len] = '\0';    /* guarantee string termination */
        
            len = flush_write_buffer(of, buf, *ppos, len);
            if (len > 0)
                *ppos += len;
        out_free:
            kfree(buf);
            return len;
        }
        
        static struct sysfs_open_file *sysfs_of(struct file *file)
        {
            return ((struct seq_file *)file->private_data)->private;
        }
        
        static int flush_write_buffer(struct sysfs_open_file *of, char *buf, loff_t off,
                        size_t count)
        {
            struct kobject *kobj = of->sd->s_parent->s_dir.kobj;
            int rc = 0;   
        
                const struct sysfs_ops *ops = sysfs_file_ops(of->sd);
        
                rc = ops->store(kobj, of->sd->s_attr.attr, buf, count);
            return rc;
        }



call the sysfs\_ops store through sysfs\_open\_file struct of.

###kset
kset is a collection of kobjects, it self is a kobject so it has a kobject field.

    struct kset {
     struct list_head list;
     spinlock_t list_lock;
     struct kobject kobj;
     const struct kset_uevent_ops *uevent_ops;
    };

'list' links the kobjects belongs to this kset.
'uevent\_ops' defines some function pointers, when some of the kobjects' status has changed, it will call these function pointers.

    struct kset_uevent_ops {
     int (* const filter)(struct kset *kset, struct kobject *kobj);
     const char *(* const name)(struct kset *kset, struct kobject *kobj);
     int (* const uevent)(struct kset *kset, struct kobject *kobj,
            struct kobj_uevent_env *env);
    };

We can use 'kset\_register' to register and add a kset to the system.

    int kset_register(struct kset *k)
    {
     int err;
    
     if (!k)
      return -EINVAL;
    
     kset_init(k);
     err = kobject_add_internal(&k->kobj);
     if (err)
      return err;
     kobject_uevent(&k->kobj, KOBJ_ADD);
     return 0;
    }

The only interesting thing is 'kobject\_uevent', this is used to send an event to userspace that something about kobject has happened, KOBJ\_ADD for this example. So if one kobject doen't belong to no kset, he can't send such event to userspace.
Below show the relation between kset and kobject.

                       kset
                       +-----------+-----+
        uevent_ops<----+     |kobj |     |
                       |     |     |     |
                       +-----+--+--+-----+
                                ^
                                |parent
                       kset     |
                       +--------+--+-----+
        uevent_ops<----+     |kobj |     |
                + +----+     |     |     |
                |      +-----+-----+-----+
            list|     ^
                |     |kset
                v     |
                +-----+     +-----+        +-----+
                |kobj +---> |kobj +------> |kobj |
                |     |     |     |        |     |
                +-----+     +--+--+        +-----+
                               ^
                               |parent
                               |
                            +--+--+
                            |kobj |
                            |     |
                            +-----+

###uevent and call_usermodehelper
Hotplug mechanism can be considered as follows, when one device plug into the system , the kernel can notify the userspace program and the userspace program can load the device's driver, when it removes, it can remove the driver. There ares two methods to notify the userspace, one is udev and the other is /sbin/hotplug. Both need the kernel's support, kobject\_uevent'. This function is the base of udev or /sbin/hotplug, it can send uevent or call call\_usermodehelper function to create a user process. 

    int kobject_uevent(struct kobject *kobj, enum kobject_action action)
    {
     return kobject_uevent_env(kobj, action, NULL);
    }
    
    int kobject_uevent_env(struct kobject *kobj, enum kobject_action action,
             char *envp_ext[])
    {
     struct kobj_uevent_env *env;
     const char *action_string = kobject_actions[action];
     const char *devpath = NULL;
     const char *subsystem;
     struct kobject *top_kobj;
     struct kset *kset;
     const struct kset_uevent_ops *uevent_ops;
     int i = 0;
     int retval = 0;
    #ifdef CONFIG_NET
     struct uevent_sock *ue_sk;
    #endif
    
     pr_debug("kobject: '%s' (%p): %s\n",
      kobject_name(kobj), kobj, __func__);
    
     /* search the kset we belong to */
     top_kobj = kobj;
     while (!top_kobj->kset && top_kobj->parent)
      top_kobj = top_kobj->parent;
    
     if (!top_kobj->kset) {
      pr_debug("kobject: '%s' (%p): %s: attempted to send uevent "
       "without kset!\n", kobject_name(kobj), kobj,
       __func__);
      return -EINVAL;
     }
    
     kset = top_kobj->kset;
     uevent_ops = kset->uevent_ops;
    
     /* skip the event, if uevent_suppress is set*/
     if (kobj->uevent_suppress) {
      pr_debug("kobject: '%s' (%p): %s: uevent_suppress "
        "caused the event to drop!\n",
        kobject_name(kobj), kobj, __func__);
      return 0;
     }
     /* skip the event, if the filter returns zero. */
     if (uevent_ops && uevent_ops->filter)
      if (!uevent_ops->filter(kset, kobj)) {
       pr_debug("kobject: '%s' (%p): %s: filter function "
        "caused the event to drop!\n",
        kobject_name(kobj), kobj, __func__);
       return 0;
      }
     /* default keys */
     retval = add_uevent_var(env, "ACTION=%s", action_string);
     if (retval)
      goto exit;
     retval = add_uevent_var(env, "DEVPATH=%s", devpath);
     if (retval)
      goto exit;
     retval = add_uevent_var(env, "SUBSYSTEM=%s", subsystem);
     if (retval)
      goto exit;
    
     /* let the kset specific function add its stuff */
     if (uevent_ops && uevent_ops->uevent) {
      retval = uevent_ops->uevent(kset, kobj, env);
      if (retval) {
       pr_debug("kobject: '%s' (%p): %s: uevent() returned "
        "%d\n", kobject_name(kobj), kobj,
        __func__, retval);
       goto exit;
      }
     }
    
     /*
    #if defined(CONFIG_NET)
     /* send netlink message */
     list_for_each_entry(ue_sk, &uevent_sock_list, list) {
      struct sock *uevent_sock = ue_sk->sk;
      struct sk_buff *skb;
      size_t len;
    
      if (!netlink_has_listeners(uevent_sock, 1))
       continue;
    
      /* allocate message with the maximum possible size */
      len = strlen(action_string) + strlen(devpath) + 2;
      skb = alloc_skb(len + env->buflen, GFP_KERNEL);
      if (skb) {
       char *scratch;
    
       /* add header */
       scratch = skb_put(skb, len);
       sprintf(scratch, "%s@%s", action_string, devpath);
    
       /* copy keys to our continuous event payload buffer */
       for (i = 0; i < env->envp_idx; i++) {
        len = strlen(env->envp[i]) + 1;
        scratch = skb_put(skb, len);
        strcpy(scratch, env->envp[i]);
       }
    
       NETLINK_CB(skb).dst_group = 1;
       retval = netlink_broadcast_filtered(uevent_sock, skb,
               0, 1, GFP_KERNEL,
               kobj_bcast_filter,
               kobj);
       /* ENOBUFS should be handled in userspace */
       if (retval == -ENOBUFS || retval == -ESRCH)
        retval = 0;
      } else
       retval = -ENOMEM;
     }
    #endif
     mutex_unlock(&uevent_sock_mutex);
    
     /* call uevent_helper, usually only enabled during early boot */
     if (uevent_helper[0] && !kobj_usermode_filter(kobj)) {
      char *argv [3];
    
      argv [0] = uevent_helper;
      argv [1] = (char *)subsystem;
      argv [2] = NULL;
      retval = add_uevent_var(env, "HOME=/");
      if (retval)
       goto exit;
      retval = add_uevent_var(env,
         "PATH=/sbin:/bin:/usr/sbin:/usr/bin");
      if (retval)
       goto exit;
    
      retval = call_usermodehelper(argv[0], argv,
              env->envp, UMH_WAIT_EXEC);
     }
    
    exit:
     kfree(devpath);
     kfree(env);
     return retval;
    }
    

Generally, there are three steps in kobject\_uevent\_env.
Firstly, find the top kset, then call the filter of kset->uevent\_ops.
Secondly, set the environment variable and call uevent_ops->uevent.
Finally, according the definition of CONFIG_NET it will send uevent message to userspace using netlink, or call the call\_usermodehelper function to launch a userprocess from kernel.

###Bus
Bus is one of the core concept in linux device driver. Devices and drivers is around of bus. Bus is a very low level infrastructure that device driver programmer have nearly chance to write a bus. A bus can be both backed by a physical bus such as PCI bus or just a virtual concept bus such as virtio bus.


    struct bus_type {
     const char  *name;
     const char  *dev_name;
     struct device  *dev_root;
     struct device_attribute *dev_attrs; /* use dev_groups instead */
     const struct attribute_group **bus_groups;
     const struct attribute_group **dev_groups;
     const struct attribute_group **drv_groups;
    
     int (*match)(struct device *dev, struct device_driver *drv);
     int (*uevent)(struct device *dev, struct kobj_uevent_env *env);
     int (*probe)(struct device *dev);
     int (*remove)(struct device *dev);
     void (*shutdown)(struct device *dev);
    
     int (*online)(struct device *dev);
     int (*offline)(struct device *dev);
    
     int (*suspend)(struct device *dev, pm_message_t state);
     int (*resume)(struct device *dev);
    
     const struct dev_pm_ops *pm;
    
     struct iommu_ops *iommu_ops;
    
     struct subsys_private *p;
     struct lock_class_key lock_key;
    };
    

'match' was called whenever a new device or driver is added for this bus.
the 'p', struct subsys\_private is used to manage the devices and drivers in this bus.

    struct subsys_private {
     struct kset subsys;
     struct kset *devices_kset;
     struct list_head interfaces;
     struct mutex mutex;
    
     struct kset *drivers_kset;
     struct klist klist_devices;
     struct klist klist_drivers;
     struct blocking_notifier_head bus_notifier;
     unsigned int drivers_autoprobe:1;
     struct bus_type *bus;
    
     struct kset glue_dirs;
     struct class *class;
    };

' subsys' represents the subsystem of the bus lies, every bus in system through bus_register will be has the same bus\_kset, so bus\_kset is the container of all buses in the system.
'devices\_kset' represents all the devices' kset, and 'drivers\_kset' represents all the drivers's kset. 
'klist\_devices' and 'klist\_drivers' links the devices and drivers in this bus.


         bus_type
        +--------+
        | name   |                           bus_kset
        +--------+                           +--------------+
        |        |                           |    |kobj|    |
        +--------+                           +--------------+
        |        |                           ^
        +--------+                           |     dri^ers_kset
        |  p     |     subsys_pri^ate        |     +--------------+
        +--+-----+---> +---------------+     |     |    |kobj|    |
           ^           |   subsys      +-----+     +--------------+
           |           +---------------+          ^
           |           | drivers_kset  +----------+
           |           +---------------+                de^ices_kset
           |           | devices_kset  +--------------> +--------------+
           |           +---------------+                |    |kobj|    |
           |           | klist_devices +-------+ de^    +--------------+
           |           +---------------+       <----+      +----+      +----+
           |           | klist_drivers +--+    |    +----> |    +----> |    |
           |           +---------------+  |    +----+      +----+      +----+
           |           |               |  |    drv
           |           +---------------+  +--> +----+      +----+      +----+
           +-----------+  bus          |       |    +----> |    +----> |    |
                       +---------------+       +----+      +----+      +----+


'bus\_register' is used to register a bus to the system.


    int bus_register(struct bus_type *bus)
    {
     int retval;
     struct subsys_private *priv;
     struct lock_class_key *key = &bus->lock_key;
    
     priv = kzalloc(sizeof(struct subsys_private), GFP_KERNEL);
     if (!priv)
      return -ENOMEM;
    
     priv->bus = bus;
     bus->p = priv;
    
     BLOCKING_INIT_NOTIFIER_HEAD(&priv->bus_notifier);
    
     retval = kobject_set_name(&priv->subsys.kobj, "%s", bus->name);
     if (retval)
      goto out;
    
     priv->subsys.kobj.kset = bus_kset;
     priv->subsys.kobj.ktype = &bus_ktype;
     priv->drivers_autoprobe = 1;
    
     retval = kset_register(&priv->subsys);
     if (retval)
      goto out;
    
     retval = bus_create_file(bus, &bus_attr_uevent);
     if (retval)
      goto bus_uevent_fail;
    
     priv->devices_kset = kset_create_and_add("devices", NULL,
          &priv->subsys.kobj);
     if (!priv->devices_kset) {
      retval = -ENOMEM;
      goto bus_devices_fail;
     }
    
     priv->drivers_kset = kset_create_and_add("drivers", NULL,
          &priv->subsys.kobj);
     if (!priv->drivers_kset) {
      retval = -ENOMEM;
      goto bus_drivers_fail;
     }
    
     INIT_LIST_HEAD(&priv->interfaces);
     __mutex_init(&priv->mutex, "subsys mutex", key);
     klist_init(&priv->klist_devices, klist_devices_get, klist_devices_put);
     klist_init(&priv->klist_drivers, NULL, NULL);
    
     retval = add_probe_files(bus);
     if (retval)
      goto bus_probe_files_fail;
    
     retval = bus_add_groups(bus, bus->bus_groups);
     if (retval)
      goto bus_groups_fail;
    
     pr_debug("bus: '%s': registered\n", bus->name);
     return 0;
     ...
     return retval;
    }


First, 'kset\_register' create a directory in /sys/bus, for example, /sys/bus/pci.
Then create two directory ----devices and drivers----in /sys/bus/$bus using 'kset\_create\_and\_add'. For example /sys/bus/pci/devices and /sys/bus/pci/drivers.

Bus' attributes represnet the information and configuration about the bus. 

        bus_create_file(bus, &bus_attr_uevent);

BUS\_ATTR is used to create bus attributes:

    static BUS_ATTR(uevent, S_IWUSR, NULL, bus_uevent_store);
    
    #define BUS_ATTR(_name, _mode, _show, _store) \
     struct bus_attribute bus_attr_##_name = __ATTR(_name, _mode, _show, _store)
    #define BUS_ATTR_RW(_name) \
     struct bus_attribute bus_attr_##_name = __ATTR_RW(_name)
    #define BUS_ATTR_RO(_name) \
     struct bus_attribute bus_attr_##_name = __ATTR_RO(_name)
     
User space can read/write these attributes to control bus's behavior.

###Binding the device and driver
Connect the device and his corresponding  driver is called binding. The bus does a lot of work to bind device and driver behind of the device driver progreammer. There are two events that will cause the bind. When one device is registered into a bus by device\_register, the kernel will try to bind this device with every drivers registered in this bus. When one driver is registered into a bus by driver\_registered, the kernel will try to bind this driver with every devices registered in this bus.

      int device_bind_driver(struct device *dev)
      {
       int ret;
      
       ret = driver_sysfs_add(dev);
       if (!ret)
        driver_bound(dev);
       return ret;
      }
      
      static void driver_bound(struct device *dev)
      {
       if (klist_node_attached(&dev->p->knode_driver)) {
        printk(KERN_WARNING "%s: device %s already bound\n",
         __func__, kobject_name(&dev->kobj));
        return;
       }
      
       pr_debug("driver: '%s': %s: bound to device '%s'\n", dev_name(dev),
        __func__, dev->driver->name);
      
       klist_add_tail(&dev->p->knode_driver, &dev->driver->p->klist_devices);
      
       /*
       * Make sure the device is no longer in one of the deferred lists and
       * kick off retrying all pending devices
       */
       driver_deferred_probe_del(dev);
       driver_deferred_probe_trigger();
      
       if (dev->bus)
        blocking_notifier_call_chain(&dev->bus->p->bus_notifier,
                BUS_NOTIFY_BOUND_DRIVER, dev);
      }
    
device\_register calls driver\_bound to bind the device and drivers.
Links device private's field knode\_driver with the driver private's klist\_devices.

###device
Linux uses struct device to represent a device. 


    struct device {
     struct device  *parent;
    
     struct device_private *p;
    
     struct kobject kobj;
     const char  *init_name; /* initial name of the device */
     const struct device_type *type;
    
     struct mutex  mutex; /* mutex to synchronize calls to
         * its driver.
         */
    
     struct bus_type *bus;  /* type of bus device is on */
     struct device_driver *driver; /* which driver has allocated this
            device */
     void  *platform_data; /* Platform specific data, device
            core doesn't touch it */
     struct dev_pm_info power;
     struct dev_pm_domain *pm_domain;
    
    #ifdef CONFIG_PINCTRL
     struct dev_pin_info *pins;
    #endif
    
    #ifdef CONFIG_NUMA
     int  numa_node; /* NUMA node this device is close to */
    #endif
     u64  *dma_mask; /* dma mask (if dma'able device) */
     u64  coherent_dma_mask;/* Like dma_mask, but for
              alloc_coherent mappings as
              not all hardware supports
              64 bit addresses for consistent
              allocations such descriptors. */
    
     struct device_dma_parameters *dma_parms;
    
     struct list_head dma_pools; /* dma pools (if dma'ble) */
    
     struct dma_coherent_mem *dma_mem; /* internal for coherent mem
              override */
    #ifdef CONFIG_DMA_CMA
     struct cma *cma_area;  /* contiguous memory area for dma
            allocations */
    #endif
     /* arch specific additions */
     struct dev_archdata archdata;
    
     struct device_node *of_node; /* associated device tree node */
     struct acpi_dev_node acpi_node; /* associated ACPI device node */
    
     dev_t   devt; /* dev_t, creates the sysfs "dev" */
     u32   id; /* device instance */
    
     spinlock_t  devres_lock;
     struct list_head devres_head;
    
     struct klist_node knode_class;
     struct class  *class;
     const struct attribute_group **groups; /* optional groups */
    
     void (*release)(struct device *dev);
     struct iommu_group *iommu_group;
    
     bool   offline_disabled:1;
     bool   offline:1;
    };


'parent' indicates the parent device.
'kobj' represent devices' kobject in kernel.
'driver' indicates whether this device has been bind with the driver. if this is NULL, it doesn't find his driver.

Every device in system is a object of struct device, so the kernel uses a kset---devices_kset as a container of devices. Kernel classify the devices as two class, one is block and the other is char. Each class has a kobject, sysfs\_dev\_block\_kobj and sysfs\_dev\_char\_kobj. It is initialized in "devices\_init":

    int __init devices_init(void)
    {
     devices_kset = kset_create_and_add("devices", &device_uevent_ops, NULL);
     if (!devices_kset)
      return -ENOMEM;
     dev_kobj = kobject_create_and_add("dev", NULL);
     if (!dev_kobj)
      goto dev_kobj_err;
     sysfs_dev_block_kobj = kobject_create_and_add("block", dev_kobj);
     if (!sysfs_dev_block_kobj)
      goto block_kobj_err;
     sysfs_dev_char_kobj = kobject_create_and_add("char", dev_kobj);
     if (!sysfs_dev_char_kobj)
      goto char_kobj_err;
    
     return 0;
    
     char_kobj_err:
     kobject_put(sysfs_dev_block_kobj);
     block_kobj_err:
     kobject_put(dev_kobj);
     dev_kobj_err:
     kset_unregister(devices_kset);
     return -ENOMEM;
    }

So this function genereates the following directory, /sys/devices, /sys/dev, /sys/dev/block and /sys/dev/char.

device\_register is used to register a device into the system. First call device\_initialize to initialize some field of the device and then calls device\_add. 

    int device_register(struct device *dev)
    {
     device_initialize(dev);
     return device_add(dev);
    }
    
    void device_initialize(struct device *dev)
    {
     dev->kobj.kset = devices_kset;
     kobject_init(&dev->kobj, &device_ktype);
     INIT_LIST_HEAD(&dev->dma_pools);
     mutex_init(&dev->mutex);
     lockdep_set_novalidate_class(&dev->mutex);
     spin_lock_init(&dev->devres_lock);
     INIT_LIST_HEAD(&dev->devres_head);
     device_pm_init(dev);
     set_dev_node(dev, -1);
    }
    
‘device\_add’ do a lot of work. 
First it creates the topology in sysfs. 
1) If both and 'dev->class' and 'dev->parent' is NULL and the device is attached to a buts, the parent is the bus's device

     if (!parent && dev->bus && dev->bus->dev_root)
      return &dev->bus->dev_root->kobj;
    
2) If 'dev->class' is NULL and 'dev->parent' is not NULL, easy case, dev's directory is in 'dev->parent->kobj'

3) if 'dev->class' is not NULL and 'dev->parent' is NULL, dev's directory is in /sys/devices/virtual

4) both 'dev->class' and 'dev->parent' is not NULL, most complicated case, omit here.

Second it creates some attribute files of this device. If its mjaor is not zero, it calls 'devtmpfs\_create\_node' to create a node in devtmpfs. 

Then bind the device with all of the driver's in the bus.


    void bus_probe_device(struct device *dev)
    {
     struct bus_type *bus = dev->bus;
     struct subsys_interface *sif;
     int ret;
    
     if (!bus)
      return;
    
     if (bus->p->drivers_autoprobe) {
      ret = device_attach(dev);
      WARN_ON(ret < 0);
     }
    
     mutex_lock(&bus->p->mutex);
     list_for_each_entry(sif, &bus->p->interfaces, node)
      if (sif->add_dev)
       sif->add_dev(dev, sif);
     mutex_unlock(&bus->p->mutex);
    }
    
    int device_attach(struct device *dev)
    {
     int ret = 0;
    
     device_lock(dev);
     if (dev->driver) {
      if (klist_node_attached(&dev->p->knode_driver)) {
       ret = 1;
       goto out_unlock;
      }
      ret = device_bind_driver(dev);
      if (ret == 0)
       ret = 1;
      else {
       dev->driver = NULL;
       ret = 0;
      }
     } else {
      ret = bus_for_each_drv(dev->bus, NULL, dev, __device_attach);
      pm_request_idle(dev);
     }
    out_unlock:
     device_unlock(dev);
     return ret;
    }
    
If this device has a driver, we just need to call 'device\_bind\_driver' to establish the relation of device and driver.
If this device has no driver, we need to iterate every drivers in 'dev->bus' and call \_\_device\_attach

    static int __device_attach(struct device_driver *drv, void *data)
    {
     struct device *dev = data;
    
     if (!driver_match_device(drv, dev))
      return 0;
    
     return driver_probe_device(drv, dev);
    }
    
    static inline int driver_match_device(struct device_driver *drv,
              struct device *dev)
    {
     return drv->bus->match ? drv->bus->match(dev, drv) : 1;
    }

If driver's bus define a match method, call it. If it return 1, matchs and if return 0, not match.
If the device and the driver matchs, call 'driver\_probe\_device' to bind the device and driver:

    int driver_probe_device(struct device_driver *drv, struct device *dev)
    {
     int ret = 0;
    
     if (!device_is_registered(dev))
      return -ENODEV;
    
     pr_debug("bus: '%s': %s: matched device %s with driver %s\n",
      drv->bus->name, __func__, dev_name(dev), drv->name);
    
     pm_runtime_barrier(dev);
     ret = really_probe(dev, drv);
     pm_request_idle(dev);
    
     return ret;
    }
    
    static int really_probe(struct device *dev, struct device_driver *drv)
    {
     int ret = 0;
    
     atomic_inc(&probe_count);
     pr_debug("bus: '%s': %s: probing driver %s with device %s\n",
      drv->bus->name, __func__, drv->name, dev_name(dev));
     WARN_ON(!list_empty(&dev->devres_head));
    
     dev->driver = drv;
    
     /* If using pinctrl, bind pins now before probing */
     ret = pinctrl_bind_pins(dev);
     if (ret)
      goto probe_failed;
    
     if (driver_sysfs_add(dev)) {
      printk(KERN_ERR "%s: driver_sysfs_add(%s) failed\n",
       __func__, dev_name(dev));
      goto probe_failed;
     }
    
     if (dev->bus->probe) {
      ret = dev->bus->probe(dev);
      if (ret)
       goto probe_failed;
     } else if (drv->probe) {
      ret = drv->probe(dev);
      if (ret)
       goto probe_failed;
     }
    
     driver_bound(dev);
     ret = 1;
     pr_debug("bus: '%s': %s: bound device %s to driver %s\n",
      drv->bus->name, __func__, dev_name(dev), drv->name);
     。。。
    }

If the device's bus define a probe calls it others call athe driver's probe function.
Finally call 'driver\_bound' to establish the relations.

###driver
struct device\_driver represents  a device driver.


      struct device_driver {
       const char  *name;
       struct bus_type  *bus;
      
       struct module  *owner;
       const char  *mod_name; /* used for built-in modules */
      
       bool suppress_bind_attrs; /* disables bind/unbind via sysfs */
      
       const struct of_device_id *of_match_table;
       const struct acpi_device_id *acpi_match_table;
      
       int (*probe) (struct device *dev);
       int (*remove) (struct device *dev);
       void (*shutdown) (struct device *dev);
       int (*suspend) (struct device *dev, pm_message_t state);
       int (*resume) (struct device *dev);
       const struct attribute_group **groups;
      
       const struct dev_pm_ops *pm;
      
       struct driver_private *p;
      };

'driver\_find' is used to find a driver in bus.
'driver\_register' is used to register a driver to system.


    int driver_register(struct device_driver *drv)
    {
     int ret;
     struct device_driver *other;
    
     BUG_ON(!drv->bus->p);
    
     if ((drv->bus->probe && drv->probe) ||
         (drv->bus->remove && drv->remove) ||
         (drv->bus->shutdown && drv->shutdown))
      printk(KERN_WARNING "Driver '%s' needs updating - please use "
       "bus_type methods\n", drv->name);
    
     other = driver_find(drv->name, drv->bus);
     if (other) {
      printk(KERN_ERR "Error: Driver '%s' is already registered, "
       "aborting...\n", drv->name);
      return -EBUSY;
     }
    
     ret = bus_add_driver(drv);
     if (ret)
      return ret;
     ret = driver_add_groups(drv, drv->groups);
     if (ret) {
      bus_remove_driver(drv);
      return ret;
     }
     kobject_uevent(&drv->p->kobj, KOBJ_ADD);
    
     return ret;
    }
    
    int bus_add_driver(struct device_driver *drv)
    {
     struct bus_type *bus;
     struct driver_private *priv;
     int error = 0;
    
     bus = bus_get(drv->bus);
     if (!bus)
      return -EINVAL;
    
     pr_debug("bus: '%s': add driver %s\n", bus->name, drv->name);
    
     priv = kzalloc(sizeof(*priv), GFP_KERNEL);
     if (!priv) {
      error = -ENOMEM;
      goto out_put_bus;
     }
     klist_init(&priv->klist_devices, NULL, NULL);
     priv->driver = drv;
     drv->p = priv;
     priv->kobj.kset = bus->p->drivers_kset;
     error = kobject_init_and_add(&priv->kobj, &driver_ktype, NULL,
             "%s", drv->name);
     if (error)
      goto out_unregister;
    
     klist_add_tail(&priv->knode_bus, &bus->p->klist_drivers);
     if (drv->bus->p->drivers_autoprobe) {
      error = driver_attach(drv);
      if (error)
       goto out_unregister;
     }
     module_add_driver(drv->owner, drv);
    
     error = driver_create_file(drv, &driver_attr_uevent);
     if (error) {
      printk(KERN_ERR "%s: uevent attr (%s) failed\n",
       __func__, drv->name);
     }
     error = driver_add_groups(drv, bus->drv_groups);
     if (error) {
      /* How the hell do we get out of this pickle? Give up */
      printk(KERN_ERR "%s: driver_create_groups(%s) failed\n",
       __func__, drv->name);
     }
    
     if (!drv->suppress_bind_attrs) {
      error = add_bind_files(drv);
      if (error) {
       /* Ditto */
       printk(KERN_ERR "%s: add_bind_files(%s) failed\n",
        __func__, drv->name);
      }
     }
    
     return 0;
    
    out_unregister:
     kobject_put(&priv->kobj);
     kfree(drv->p);
     drv->p = NULL;
    out_put_bus:
     bus_put(bus);
     return error;
    }


The 'bus\_add\_driver' does the really work, first allocate and initialize a 'driver\_private' struct. 
Later calls 'driver\_attach', for every device in bus, it calls '\_\_driver\_attach':

    static int __driver_attach(struct device *dev, void *data)
    {
     struct device_driver *drv = data;
    
     /*
     * Lock device and try to bind to it. We drop the error
     * here and always return 0, because we need to keep trying
     * to bind to devices and some drivers will return an error
     * simply if it didn't support the device.
     *
     * driver_probe_device() will spit a warning if there
     * is an error.
     */
    
     if (!driver_match_device(drv, dev))
      return 0;
    
     if (dev->parent) /* Needed for USB */
      device_lock(dev->parent);
     device_lock(dev);
     if (!dev->driver)
      driver_probe_device(drv, dev);
     device_unlock(dev);
     if (dev->parent)
      device_unlock(dev->parent);
    
     return 0;
    }

In  '\_\_driver\_attach', it calls both 'driver\_match\_device' and 'driver\_probe\_device', the same as '\_\_device\_attach'.

'bus\_add\_driver' will also create some attribute files.

###class
class is a highter abstract of devices, classify the devices according the devices' functionality.

    struct class {
     const char  *name;
     struct module  *owner;
    
     struct class_attribute  *class_attrs;
     const struct attribute_group **dev_groups;
     struct kobject   *dev_kobj;
    
     int (*dev_uevent)(struct device *dev, struct kobj_uevent_env *env);
     char *(*devnode)(struct device *dev, umode_t *mode);
    
     void (*class_release)(struct class *class);
     void (*dev_release)(struct device *dev);
    
     int (*suspend)(struct device *dev, pm_message_t state);
     int (*resume)(struct device *dev);
    
     const struct kobj_ns_type_operations *ns_type;
     const void *(*namespace)(struct device *dev);
    
     const struct dev_pm_ops *pm;
    
     struct subsys_private *p;
    };

'classes\_init' create a root directory in sysfs.

    int __init classes_init(void)
    {
     class_kset = kset_create_and_add("class", NULL, NULL);
     if (!class_kset)
      return -ENOMEM;
     return 0;
    }

class is created using 'class\_create'

    #define class_create(owner, name)  \
    ({      \
     static struct lock_class_key __key; \
     __class_create(owner, name, &__key); \
    })
    
    struct class *__class_create(struct module *owner, const char *name,
            struct lock_class_key *key)
    {
     struct class *cls;
     int retval;
    
     cls = kzalloc(sizeof(*cls), GFP_KERNEL);
     if (!cls) {
      retval = -ENOMEM;
      goto error;
     }
    
     cls->name = name;
     cls->owner = owner;
     cls->class_release = class_create_release;
    
     retval = __class_register(cls, key);
     if (retval)
      goto error;
    
     return cls;
    
    error:
     kfree(cls);
     return ERR_PTR(retval);
    }
    EXPORT_SYMBOL_GPL(__class_create);


Again, '\_\_class\_register' does the tough work. It's most important work is to create a directory in /sys/class.

Let's see how class impose effects on device create. 

    struct device *device_create(struct class *class, struct device *parent,
            dev_t devt, void *drvdata, const char *fmt, ...)
    {
     va_list vargs;
     struct device *dev;
    
     va_start(vargs, fmt);
     dev = device_create_vargs(class, parent, devt, drvdata, fmt, vargs);
     va_end(vargs);
     return dev;
    }
    
    static struct device *
    device_create_groups_vargs(struct class *class, struct device *parent,
          dev_t devt, void *drvdata,
          const struct attribute_group **groups,
          const char *fmt, va_list args)
    {
     struct device *dev = NULL;
     int retval = -ENODEV;
    
     if (class == NULL || IS_ERR(class))
      goto error;
    
     dev = kzalloc(sizeof(*dev), GFP_KERNEL);
     if (!dev) {
      retval = -ENOMEM;
      goto error;
     }
    
     dev->devt = devt;
     dev->class = class;
     dev->parent = parent;
     dev->groups = groups;
     dev->release = device_create_release;
     dev_set_drvdata(dev, drvdata);
    
     retval = kobject_set_name_vargs(&dev->kobj, fmt, args);
     if (retval)
      goto error;
    
     retval = device_register(dev);
     if (retval)
      goto error;
    
     return dev;
    
    error:
     put_device(dev);
     return ERR_PTR(retval);
    }

Here we see the 'dev->class' is set to the class. As we have discussed in 'device\_register' the class and parent both have an influence in the device's lying the directory.


