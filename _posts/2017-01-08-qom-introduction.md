---
layout: post
title: "QOM介绍"
description: "qemu qom"
category: 技术
tags: [虚拟化,QEMU]
---
{% include JB/setup %}

* [一. 模块注册](#第一节)
* [二. Class的初始化](#第二节)
* [三. Class的层次结构](#第三节)
* [四. 对象的构造](#第四节)
* [五. 总结](#总结)
* [后记](#后记)

QOM全称qemu object model,顾名思义，这是对qemu中对象的一个抽象层。通过QOM可以对qemu中的各种资源进行抽象、管理。比如设备模拟中的设备创建，配置，销毁。QOM还用于各种backend的抽象，MemoryRegion，Machine等的抽象，毫不夸张的说，QOM遍布于qemu代码。本文以qemu的设备模拟为例，对QOM进行详细介绍。本文代码基于qemu-2.8。

<h2 id="第一节"> 一. 模块注册 </h2>

在hw文件目录下的设备模拟中，几乎所有.c文件都会有一个全局的

	type_init(xxxxxxxxx)

。这就是向QOM模块注册自己，比如

	type_init(serial_register_types)//注册serial
	type_init(vmxnet3_register_types)//注册vmxnet3

这类似于Linux驱动模块的注册，在这里type\_init是一个宏，在include/qemu/module.h中，我们看到

	#define module_init(function, type)                                         \
	static void __attribute__((constructor)) do_qemu_init_ ## function(void)    \
	{                                                                           \
	    register_module_init(function, type);                                   \
	}
	typedef enum {
	    MODULE_INIT_BLOCK,
	    MODULE_INIT_OPTS,
	    MODULE_INIT_QAPI,
	    MODULE_INIT_QOM,
	    MODULE_INIT_TRACE,
	    MODULE_INIT_MAX
	} module_init_type;
	
	#define block_init(function) module_init(function, MODULE_INIT_BLOCK)
	#define opts_init(function) module_init(function, MODULE_INIT_OPTS)
	#define qapi_init(function) module_init(function, MODULE_INIT_QAPI)
	#define type_init(function) module_init(function, MODULE_INIT_QOM)
	#define trace_init(function) module_init(function, MODULE_INIT_TRACE)


这里有多个module,对于xxx\_init，都是通过调用module\_init来进行注册的。

	void register_module_init(void (*fn)(void), module_init_type type)
	{
	    ModuleEntry *e;
	    ModuleTypeList *l;
	
	    e = g_malloc0(sizeof(*e));
	    e->init = fn;
	    e->type = type;
	
	    l = find_type(type);
	
	    QTAILQ_INSERT_TAIL(l, e, node);
	}

	static ModuleTypeList *find_type(module_init_type type)
	{
	    init_lists();
	
	    return &init_type_list[type];
	}

	static ModuleTypeList init_type_list[MODULE_INIT_MAX];

这样一看就比较清楚了，init\_type\_list作为全局的list数组，所有通过type\_init注册的对象就会被放连接在init\_type\_list[MODULE\_INIT\_QOM]这个list上。这个过程可以用如下图表示。


![](/assets/img/qom/1.png)

我们注意到module\_init的定义

	#define module_init(function, type)                                         \
	static void __attribute__((constructor)) do_qemu_init_ ## function(void)    \
	{                                                                           \
	    register_module_init(function, type);                                   \
	}


所以每一个type\_init都会是一个函数do\_qemu\_init\_xxxx，比如type\_init(serial\_register\_types)将会被展开成

	staic void __attribute__((constructor)) do_qemu_init_serial_register_types()
	{
		register_module_init(serial_register_types, MODULE_INIT_QOM)
	}

从constructor属性看，这将会使得该函数在main之前执行。

所以在qemu的main函数执行之前，图1中的各种链表已经准备好了。
在main函数中，我们可以看到，很快就调用了

	module_call_init(MODULE_INIT_QOM);

看module\_call\_init定义，

	void module_call_init(module_init_type type)
	{
	    ModuleTypeList *l;
	    ModuleEntry *e;
	
	    l = find_type(type);
	
	    QTAILQ_FOREACH(e, l, node) {
	        e->init();
	    }
	}

可以看到该函数就是简单调用了注册在其上面的init函数，以serial举例：

	static void serial_register_types(void)
	{
	    type_register_static(&serial_isa_info);
	}
	
	type_init(serial_register_types)


这里就是调用会调用serial\_register\_types，这个函数以serial\_isa\_info为参数调用了type\_register\_static。
函数调用链如下

	type_register_static->type_register->type_register_internal->type_new


这一过程的目的就是利用TypeInfo构造出一个TypeImpl结构，之后插入到一个hash表之中，这个hash表以ti->name，也就是info->name为key,value就是生根据TypeInfo生成的TypeImpl。这样在，module\_call\_init(MODULE\_INIT\_QOM)调用之后，就有了一个type的哈希表，这里面保存了所有的类型信息。




<h2 id="第二节">二. Class的初始化 </h2>

从第一部分我们已经知道，现在已经有了一个TypeImpl的哈希表。下一步就是初始化每个type了，这一步可以看成是class的初始化，可以理解成每一个type对应了一个class，接下来会初始化class。调用链

	main->select_machine->find_default_machine->object_class_get_list->object_class_foreach

这里实在选择机器类型的时候顺便把各个type给初始化了。

	void object_class_foreach(void (*fn)(ObjectClass *klass, void *opaque),
	                          const char *implements_type, bool include_abstract,
	                          void *opaque)
	{
	    OCFData data = { fn, implements_type, include_abstract, opaque };
	
	    enumerating_types = true;
	    g_hash_table_foreach(type_table_get(), object_class_foreach_tramp, &data);
	    enumerating_types = false;
	}

type_table_get就是之前创建的name为key,TypeImpl为value的哈希表。看看对这个表中的每一项调用的函数。

	static void object_class_foreach_tramp(gpointer key, gpointer value,
	                                       gpointer opaque)
	{
	    OCFData *data = opaque;
	    TypeImpl *type = value;
	    ObjectClass *k;
	
	    type_initialize(type);
	    k = type->class;
	
	    if (!data->include_abstract && type->abstract) {
	        return;
	    }
	
	    if (data->implements_type && 
	        !object_class_dynamic_cast(k, data->implements_type)) {
	        return;
	    }
	
	    data->fn(k, data->opaque);
	}

我们来看 type\_initialize函数

	static void type_initialize(TypeImpl *ti)
	{
	    TypeImpl *parent;
	
	    if (ti->class) {
	        return;
	    }
	
	    ti->class_size = type_class_get_size(ti);
	    ti->instance_size = type_object_get_size(ti);
	
	    ti->class = g_malloc0(ti->class_size);
	
	    parent = type_get_parent(ti);
	    if (parent) {
	        type_initialize(parent);
	        GSList *e;
	        int i;
	
	        g_assert_cmpint(parent->class_size, <=, ti->class_size);
	        memcpy(ti->class, parent->class, parent->class_size);
	        ti->class->interfaces = NULL;
	        ti->class->properties = g_hash_table_new_full(
	            g_str_hash, g_str_equal, g_free, object_property_free);
	
	        for (e = parent->class->interfaces; e; e = e->next) {
	            InterfaceClass *iface = e->data;
	            ObjectClass *klass = OBJECT_CLASS(iface);
	
	            type_initialize_interface(ti, iface->interface_type, klass->type);
	        }
	
	        for (i = 0; i < ti->num_interfaces; i++) {
	            TypeImpl *t = type_get_by_name(ti->interfaces[i].typename);
	            for (e = ti->class->interfaces; e; e = e->next) {
	                TypeImpl *target_type = OBJECT_CLASS(e->data)->type;
	
	                if (type_is_ancestor(target_type, t)) {
	                    break;
	                }
	            }
	
	            if (e) {
	                continue;
	            }
	
	            type_initialize_interface(ti, t, t);
	        }
	    } else {
	        ti->class->properties = g_hash_table_new_full(
	            g_str_hash, g_str_equal, g_free, object_property_free);
	    }
	
	    ti->class->type = ti;
	
	    while (parent) {
	        if (parent->class_base_init) {
	            parent->class_base_init(ti->class, ti->class_data);
	        }
	        parent = type_get_parent(parent);
	    }
	
	    if (ti->class_init) {
	        ti->class_init(ti->class, ti->class_data);
	    }
	}

开头我们可以看到，如果ti->class已经存在说明已经初始化了，直接返回，再看，如果有parent，会递归调用type\_initialize，即调用父对象的初始化函数。

这里我们看到type也有一个层次关系，即QOM 对象的层次结构。在serial_isa_info
结构的定义中，我们可以看到有一个.parent域，

	static const TypeInfo serial_isa_info = {
	    .name          = TYPE_ISA_SERIAL,
	    .parent        = TYPE_ISA_DEVICE,
	    .instance_size = sizeof(ISASerialState),
	    .class_init    = serial_isa_class_initfn,
	};

这说明TYPE\_ISA\_SERIAL的父type是TYPE\_ISA\_DEVICE，在hw/isa/isa-bus.c中可以看到isa\_device\_type\_info的父type是TYPE_DEVICE

	static const TypeInfo isa_device_type_info = {
	    .name = TYPE_ISA_DEVICE,
	    .parent = TYPE_DEVICE,
	    .instance_size = sizeof(ISADevice),
	    .instance_init = isa_device_init,
	    .abstract = true,
	    .class_size = sizeof(ISADeviceClass),
	    .class_init = isa_device_class_init,
	};


依次往上溯我们可以得到这样一条type的链，

	TYPE_ISA_SERIAL->TYPE_ISA_DEVICE->TYPE_DEVICE->TYPE_OBJECT

事实上，qemu中有两种根type，还有一种是TYPE_INTERFACE。

这样我们看到其实就跟各个type初始化的顺序没有关系了。不管哪个type最先初始化，最终都会初始化到object的type。对于object，只是简单的设置了一下分配了ti->class，设置了ti->class->type的值。如果type有interface，还需要初始化ti->class->interfaces的值，每一个interface也是一个type。如果父type有interfaces，还需要将父type的interface添加到ti->class->interfaces上去。

之后，最重要的就是调用parent->class\_base\_init以及ti->class\_init了，这相当于C++里面的构造基类的数据。我们以一个class\_init为例，

	static void serial_isa_class_initfn(ObjectClass *klass, void *data)
	{
	    DeviceClass *dc = DEVICE_CLASS(klass);
	
	    dc->realize = serial_isa_realizefn;
	    dc->vmsd = &vmstate_isa_serial;
	    dc->props = serial_isa_properties;
	    set_bit(DEVICE_CATEGORY_INPUT, dc->categories);
	}

我们可以看到这里从ObjectClass转换成了DeviceClass，然后做了一些簿记工作。这里为什么可以做转换呢。接下来看看Class的层次结构。


<h2 id="第三节">三. Class的层次结构 </h2>

vmxnnet3的层次多一些，我们以他为例，首先看vmxnet3\_info的定义。

	static const TypeInfo vmxnet3_info = {
	    .name          = TYPE_VMXNET3,
	    .parent        = TYPE_PCI_DEVICE,
	    .class_size    = sizeof(VMXNET3Class),
	    .instance_size = sizeof(VMXNET3State),
	    .class_init    = vmxnet3_class_init,
	    .instance_init = vmxnet3_instance_init,
	};

	typedef struct VMXNET3Class {
	    PCIDeviceClass parent_class;
	    DeviceRealize parent_dc_realize;
	} VMXNET3Class;
	
	typedef struct PCIDeviceClass {
	    DeviceClass parent_class;
	
	    void (*realize)(PCIDevice *dev, Error **errp);
	    int (*init)(PCIDevice *dev);/* TODO convert to realize() and remove */
	    PCIUnregisterFunc *exit;
	    PCIConfigReadFunc *config_read;
	    PCIConfigWriteFunc *config_write;
	
		...
	} PCIDeviceClass;


	typedef struct DeviceClass {
	    /*< private >*/
	    ObjectClass parent_class;
	    /*< public >*/
		...
	} DeviceClass;


	struct ObjectClass
	{
	    /*< private >*/
	    Type type;
	    GSList *interfaces;
	
	    const char *object_cast_cache[OBJECT_CLASS_CAST_CACHE];
	    const char *class_cast_cache[OBJECT_CLASS_CAST_CACHE];
	
	    ObjectUnparent *unparent;
	
	    GHashTable *properties;
	};


我们可以看到这样一种层次结构
	
	VMXNET3Class->PCIDeviceClass->DeviceClass->ObjectClass

这可以看成C++中的继承关系，即当然基类就是ObjectClass，越往下包含的数据越具象。

从type\_initialize中，我们可以看到，调用class\_init(ti->class,ti->class_data)
，这里的ti->class就是刚刚分配出来的，对应到vmxnet3，这里就是一个VMXNET3Class结构，
注意到
	
	memcpy(ti->class, parent->class, parent->class_size);

所以VMXNET3Class的各个父Class已经被初始化了。所以当进入vmxnet3\_class\_init之后，调用DEVICE\_CLASS和PCI\_DEVICE\_CLASS以及VMXNET3\_DEVICE\_CLASS可以分别得到其基Class，类似于C++里面的派生类转换到基类。以
	
	PCIDeviceClass *c = PCI_DEVICE_CLASS(class);

这句为例，我们知道这里class是vmxnet3对应的class，即class->type->name="vmxnet3"。

	#define PCI_DEVICE_CLASS(klass) \
	     OBJECT_CLASS_CHECK(PCIDeviceClass, (klass), TYPE_PCI_DEVICE)
	
	#define OBJECT_CLASS_CHECK(class_type, class, name) \
	    ((class_type *)object_class_dynamic_cast_assert(OBJECT_CLASS(class), (name), \
	                                               __FILE__, __LINE__, __func__))
	
	ObjectClass *object_class_dynamic_cast_assert(ObjectClass *class,
	                                              const char *typename,
	                                              const char *file, int line,
	                                              const char *func)
	{
	    ObjectClass *ret;
	
	  	...
	    ret = object_class_dynamic_cast(class, typename);
	    ...
	    return ret;
	}


	ObjectClass *object_class_dynamic_cast(ObjectClass *class,
	                                       const char *typename)
	{
	    ObjectClass *ret = NULL;
	    TypeImpl *target_type;
	    TypeImpl *type;
	
	    if (!class) {
	        return NULL;
	    }
	
	    /* A simple fast path that can trigger a lot for leaf classes.  */
	    type = class->type;
	    if (type->name == typename) {
	        return class;
	    }
	
	    target_type = type_get_by_name(typename);
	    if (!target_type) {
	        /* target class type unknown, so fail the cast */
	        return NULL;
	    }
	
	    if (type->class->interfaces &&
	           ...
	    } else if (type_is_ancestor(type, target_type)) {
	        ret = class;
	    }
	
	    return ret;
	}
	
	static bool type_is_ancestor(TypeImpl *type, TypeImpl *target_type)
	{
	    assert(target_type);
	
	    /* Check if target_type is a direct ancestor of type */
	    while (type) {
	        if (type == target_type) {
	            return true;
	        }
	
	        type = type_get_parent(type);
	    }
	
	    return false;
	}

最终会进入object\_class\_dynamic\_cast函数，在该函数中，根据class对应的type以及typename对应的type，判断是否能够转换，判断的主要依据就是type\_is\_ancestor，
这个判断target\_type是否是type的一个祖先，如果是当然可以进行转换，否则就不行。

好了，总结一下，现在我们得到了什么，从最开始得TypeImpl初始化了每一个type对应的class，并且构建好了各个Class的继承关系。如下图所示,注意下面的***Class都包含了上面的一部分。


![](/assets/img/qom/2.png)



<h2 id="第四节">四. 对象的构造</h2>

我们上面已经看到了type哈希表的构造以及class的初始化，接下来讨论具体设备的创建。

以vmxnet3为例，我们需要再命令行指定-device vmxnet3。在main中，有这么一句话

    if (qemu_opts_foreach(qemu_find_opts("device"),
                          device_init_func, NULL, NULL)) {
        exit(1);
    }

对参数中的device调用device\_init\_func函数，调用链

	device_init_func->qdev_device_add

在qdev\_device\_add中我们可以看到这么一句话 

	 dev = DEVICE(object_new(driver));

	DeviceState *qdev_device_add(QemuOpts *opts, Error **errp)
	{
	    DeviceClass *dc;
	    const char *driver, *path;
	    DeviceState *dev;
	    BusState *bus = NULL;
	    Error *err = NULL;
	
	    driver = qemu_opt_get(opts, "driver");
	    if (!driver) {
	        error_setg(errp, QERR_MISSING_PARAMETER, "driver");
	        return NULL;
	    }
	
	    /* find driver */
	    dc = qdev_get_device_class(&driver, errp);
	    if (!dc) {
	        return NULL;
	    }
	
	    /* find bus */
	    path = qemu_opt_get(opts, "bus");
	    if (path != NULL) {
	        bus = qbus_find(path, errp);
	        if (!bus) {
	            return NULL;
	        }
	        if (!object_dynamic_cast(OBJECT(bus), dc->bus_type)) {
	            error_setg(errp, "Device '%s' can't go on %s bus",
	                       driver, object_get_typename(OBJECT(bus)));
	            return NULL;
	        }
	    } else if (dc->bus_type != NULL) {
	        bus = qbus_find_recursive(sysbus_get_default(), NULL, dc->bus_type);
	        if (!bus || qbus_is_full(bus)) {
	            error_setg(errp, "No '%s' bus found for device '%s'",
	                       dc->bus_type, driver);
	            return NULL;
	        }
	    }
	    if (qdev_hotplug && bus && !qbus_is_hotpluggable(bus)) {
	        error_setg(errp, QERR_BUS_NO_HOTPLUG, bus->name);
	        return NULL;
	    }
	
	    /* create device */
	    dev = DEVICE(object_new(driver));
	
	    if (bus) {
	        qdev_set_parent_bus(dev, bus);
	    }
	
	    qdev_set_id(dev, qemu_opts_id(opts));
	
	    /* set properties */
	    if (qemu_opt_foreach(opts, set_property, dev, &err)) {
	        error_propagate(errp, err);
	        object_unparent(OBJECT(dev));
	        object_unref(OBJECT(dev));
	        return NULL;
	    }
	
	    dev->opts = opts;
	    object_property_set_bool(OBJECT(dev), true, "realized", &err);
	    if (err != NULL) {
	        error_propagate(errp, err);
	        dev->opts = NULL;
	        object_unparent(OBJECT(dev));
	        object_unref(OBJECT(dev));
	        return NULL;
	    }
	    return dev;
	}

对象的调用是通过object\_new(driver)实现的，这里的driver就是设备名，vmxnet3，

	object_new->object_new_with_type->object_initialize_with_type


	Object *object_new_with_type(Type type)
	{
	    Object *obj;
	
	    g_assert(type != NULL);
	    type_initialize(type);
	
	    obj = g_malloc(type->instance_size);
	    object_initialize_with_type(obj, type->instance_size, type);
	    obj->free = g_free;
	
	    return obj;
	}

	static void object_init_with_type(Object *obj, TypeImpl *ti)
	{
	    if (type_has_parent(ti)) {
	        object_init_with_type(obj, type_get_parent(ti));
	    }
	
	    if (ti->instance_init) {
	        ti->instance_init(obj);
	    }
	}

从上面函数看，也会递归初始化每一个object的父object，之后调用instance\_init函数。这里又涉及到了object的继承。

	typedef struct {
	        PCIDevice parent_obj;
	        ...
	} VMXNET3State;
	
	struct PCIDevice {
	    DeviceState qdev;
	
	   ...
	};
	
	struct DeviceState {
	    /*< private >*/
	    Object parent_obj;
	    /*< public >*/
	
	    
	};
	
	struct Object
	{
	    /*< private >*/
	    ObjectClass *class;
	    ObjectFree *free;
	    GHashTable *properties;
	    uint32_t ref;
	    Object *parent;
	};

这次的继承体系是

	VMXNET3State->PCIDevice->DeviceState->Object

这样就创建好了一个DeviceState，当然其实也是VMXNET3State，并且每一个父object的instance_init函数都已经调用好了，这里我们看看object、deviceobject、pcideviceobject的init函数都干了啥

	static void object_instance_init(Object *obj)
	{
	    object_property_add_str(obj, "type", qdev_get_type, NULL, NULL);
	}


	static void device_initfn(Object *obj)
	{
	    DeviceState *dev = DEVICE(obj);
	    ObjectClass *class;
	    Property *prop;
	
	    if (qdev_hotplug) {
	        dev->hotplugged = 1;
	        qdev_hot_added = true;
	    }
	
	    dev->instance_id_alias = -1;
	    dev->realized = false;
	
	    object_property_add_bool(obj, "realized",
	                             device_get_realized, device_set_realized, NULL);
	    object_property_add_bool(obj, "hotpluggable",
	                             device_get_hotpluggable, NULL, NULL);
	    object_property_add_bool(obj, "hotplugged",
	                             device_get_hotplugged, device_set_hotplugged,
	                             &error_abort);
	
	    class = object_get_class(OBJECT(dev));
	    do {
	        for (prop = DEVICE_CLASS(class)->props; prop && prop->name; prop++) {
	            qdev_property_add_legacy(dev, prop, &error_abort);
	            qdev_property_add_static(dev, prop, &error_abort);
	        }
	        class = object_class_get_parent(class);
	    } while (class != object_class_by_name(TYPE_DEVICE));
	
	    object_property_add_link(OBJECT(dev), "parent_bus", TYPE_BUS,
	                             (Object **)&dev->parent_bus, NULL, 0,
	                             &error_abort);
	    QLIST_INIT(&dev->gpios);
	}


可以看到主要就是给对象添加了一些属性，object的type属性啊，device里面的realized、hotpluggable属性等，值得注意的是device\_initfn还根据class->props添加的添加了属性，
在vmxnet3\_class\_init函数中，我们可以看到，在class被初始化的时候，其已经赋值vmxnet3\_properties，

	static Property vmxnet3_properties[] = {
	    DEFINE_NIC_PROPERTIES(VMXNET3State, conf),
	    DEFINE_PROP_BIT("x-old-msi-offsets", VMXNET3State, compat_flags,
	                    VMXNET3_COMPAT_FLAG_OLD_MSI_OFFSETS_BIT, false),
	    DEFINE_PROP_BIT("x-disable-pcie", VMXNET3State, compat_flags,
	                    VMXNET3_COMPAT_FLAG_DISABLE_PCIE_BIT, false),
	    DEFINE_PROP_END_OF_LIST(),
	};

这样，object_new之后，创建的object其实已经具有了很多属性了，这是从父object那里继承过来的。

接着看qdev_device_add函数，调用了object_property_set_bool

	object_property_set_bool->object_property_set_qobject->object_property_set->property_set_bool->device_set_realized->vmxnet3_realize

最终，我们的vmxnet3_realize函数被调用了，这也就完成了object的构造，不同于type和class的构造，object当然是根据需要创建的，只有在命令行指定了设备或者是热插一个设备之后才会有object的创建。Class和object之间是通过Object的class域联系在一起的。如下图所示。


![](/assets/img/qom/3.png)


<h2 id="第五节">五. 总结</h2>

从上文可以看出，我把QOM的对象构造分成三部分，第一部分是type的构造，这是通过TypeInfo构造一个TypeImpl的哈希表，这是在main之前完成的，第二部分是class的构造，这是在main中进行的，这两部分都是全局的，也就是只要编译进去了的QOM对象都会调用，第三部分是object的构造，这是构造具体的对象实例，在命令行指定了对应的设备时，才会创建object。从上上面也可以看出，正如Paolo Bonzini所说的，qemu在object方面的多态是一种class based的，而属性方面，是动态构造的，每个实例可能都有不同的属性，这是一种prototype based的多态。

本文主要是对整个对象的产生做了介绍，没有对interface和property做过多介绍，maybe以后又机会再详细说吧。

<h2 id="后记">后记</h2>

这篇文章很早很早以前就说写了，15年还在学校就应该写的，结果今年忙于挖洞，一直就拖啊拖的，一直到现在终于把这个坑填上，鄙视一下自己，自己已经准备了好多qemu内容，一直没有时间填坑，希望有时间都填上。
