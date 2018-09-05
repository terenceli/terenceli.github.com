---
layout: post
title: "QOM Property"
description: "QOM Property"
category: 技术
tags: [虚拟化, QEMU]
---
{% include JB/setup %}

Long time ago, I have discussed the class-based polymorphism in QOM. I have left one important aspect, that's property which implements a prototype-based polymorphism. Properties is the interface export to external. Devices can set/get the property staticlly or dynamically. In this blog I will discuss how property is stored in QOM and how it interacts with other parts of QEMU.

<h3> Data structure </h3>

Both struct 'ObjectClass' and 'Object' has a GHashTable 'properties' fields, the former represents the common class properties and the latter represents the object's properties.

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
	
	struct Object
	{
		/*< private >*/
		ObjectClass *class;
		ObjectFree *free;
		GHashTable *properties;
		uint32_t ref;
		Object *parent;
	};

	
A property is represented by struct 'ObjectProperty'. It contains the basic information and the getter and setter function pointer. 

    typedef struct ObjectProperty
    {
        gchar *name;
        gchar *type;
        gchar *description;
        ObjectPropertyAccessor *get;
        ObjectPropertyAccessor *set;
        ObjectPropertyResolve *resolve;
        ObjectPropertyRelease *release;
        void *opaque;
    } ObjectProperty;

'ObjectProperty' is insert in the 'properties' hashtable, including struct 'ObjectClass' and 'Object'.

For every kind of property, there is a concrete struct to describe it. For example.

    //link property
    typedef struct {
        Object **child;
        void (*check)(const Object *, const char *, Object *, Error **);
        ObjectPropertyLinkFlags flags;
    } LinkProperty;
    
    //string property
    typedef struct StringProperty
    {
        char *(*get)(Object *, Error **);
        void (*set)(Object *, const char *, Error **);
    } StringProperty;
    
    //bool property
    typedef struct BoolProperty
    {
        bool (*get)(Object *, Error **);
        void (*set)(Object *, bool, Error **);
    } BoolProperty;
    
This concrete property is stored in the 'ObjectProperty's opaque field.
Following picture the relation of these structures.

    Object
    +-----------+
    |           |
    |           |
    +-----------+
    | properties+----------+---------------------------------------------------->
    +-----------+          ^
    |           |          |
    |           |          |
    +-----------+      +---+----+
                       | name   |
                       +--------+
                       | type   |
                       +--------+
                       |  set   +-> property_set_bool
                       +--------+
                       |  get   +-> property_get_bool
                       +--------+
                       | opaque +----+ +---------+
                       +--------+      |  get    +--> memfd_backend_get_seal
                       ObjectProperty  +---------+
                                       |  set    +--> memfd_backend_set_seal
                                       +---------+
                                       BoolProperty


<h3> Interface </h3>

'object\_property\_add' is used to add a property to Object. 

    ObjectProperty *
    object_property_add(Object *obj, const char *name, const char *type,
                        ObjectPropertyAccessor *get,
                        ObjectPropertyAccessor *set,
                        ObjectPropertyRelease *release,
                        void *opaque, Error **errp)
    {
        ObjectProperty *prop;
        size_t name_len = strlen(name);
    
        if (name_len >= 3 && !memcmp(name + name_len - 3, "[*]", 4)) {
            int i;
            ObjectProperty *ret;
            char *name_no_array = g_strdup(name);
    
            name_no_array[name_len - 3] = '\0';
            for (i = 0; ; ++i) {
                char *full_name = g_strdup_printf("%s[%d]", name_no_array, i);
    
                ret = object_property_add(obj, full_name, type, get, set,
                                          release, opaque, NULL);
                g_free(full_name);
                if (ret) {
                    break;
                }
            }
            g_free(name_no_array);
            return ret;
        }
    
        if (object_property_find(obj, name, NULL) != NULL) {
            error_setg(errp, "attempt to add duplicate property '%s'"
                       " to object (type '%s')", name,
                       object_get_typename(obj));
            return NULL;
        }
    
        prop = g_malloc0(sizeof(*prop));
    
        prop->name = g_strdup(name);
        prop->type = g_strdup(type);
    
        prop->get = get;
        prop->set = set;
        prop->release = release;
        prop->opaque = opaque;
    
        g_hash_table_insert(obj->properties, prop->name, prop);
        return prop;
    }

First find if the 'property' name exists already, if not, just allocates a new ObjectProperty and insert it to the hashtable. The [*] case is not discussed here.

'object\_property\_find' is used to find if the Object has a property, this function will search all of the parent class' properties of the object. 

    ObjectProperty *object_property_find(Object *obj, const char *name,
                                         Error **errp)
    {
        ObjectProperty *prop;
        ObjectClass *klass = object_get_class(obj);
    
        prop = object_class_property_find(klass, name, NULL);
        if (prop) {
            return prop;
        }
    
        prop = g_hash_table_lookup(obj->properties, name);
        if (prop) {
            return prop;
        }
    
        error_setg(errp, "Property '.%s' not found", name);
        return NULL;
    }

<h3> Example </h3>

Let's take the 'TYPE\_DEVICE' as example. 

    static const TypeInfo device_type_info = {
        .name = TYPE_DEVICE,
        .parent = TYPE_OBJECT,
        .instance_size = sizeof(DeviceState),
        .instance_init = device_initfn,
        .instance_post_init = device_post_init,
        .instance_finalize = device_finalize,
        .class_base_init = device_class_base_init,
        .class_init = device_class_init,
        .abstract = true,
        .class_size = sizeof(DeviceClass),
    };

The instance init function is 'device\_initfn'. In this function we add some property such as 'realized', 'hotpluggable'.

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
                                 device_get_hotplugged, NULL,
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

The setter of 'realized' property function is 'device\_set\_realized'. 

For each device option in qemu command line, the main function calls 'device\_init\_func' which calls 'qdev\_device\_add'.

    static int device_init_func(void *opaque, QemuOpts *opts, Error **errp)
    {
        Error *err = NULL;
        DeviceState *dev;
    
        dev = qdev_device_add(opts, &err);
        if (!dev) {
            error_report_err(err);
            return -1;
        }
        object_unref(OBJECT(dev));
        return 0;
    }

In the it calls 'object\_property\_set\_bool' to set the 'realized' property to be true.

		object_property_set_bool(OBJECT(dev), true, "realized", &err);

The object\_property\_set\_bool' calls 'object\_property\_set' and the latter function first calls the ObjectProperty's set function('property\_set\_bool'), then in 'property\_set\_bool' it calls the BoolProperty's set function, this is 'device\_set\_realized'. So finally in 'device\_set\_realized' this function calls the DeviceClass's realize function and initialized the device.