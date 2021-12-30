---
layout: post
title: "runc internals, part 3: runc double clone"
description: "runc"
category: 技术
tags: [container, runc]
---
{% include JB/setup %}


Now that we have analyzed the general process of 'runc create' and know that the 'runc create' will execute 'runc init' parent process, the parent process will clone child process, and the child process will clone a grandchild process, and this grandchild process will execute the user defined process.

Once I decide to draw a pic of these four process' relation. But I found a detail pic [here](https://mp.weixin.qq.com/s/mSlc2RMRDe6liXb-ejtRvA). I just reference it here.

![](/assets/img/runcinternals3/1.png)

So let's see these process' work.

<h3> parent </h3>

This is runc:[0:PARENT].

* Got the config from runc create process. This is done by 
        
        nl_parse(pipenum, &config); //corresponding runc create code :io.Copy(p.messageSockPair.parent, p.bootstrapData)

* Create two socketpair 'sync_child_pipe' and 'sync_grandchild_pipe' to sync with the child and grandchild.
* Clone child process
* Update the uid/gid mapping for child process
* Receive the pid of children and grand children, and send these two to runc create process. So runc create can send config data to the grandchild.
* Wait the grandchild to run

<h3> child </h3>

This is runc:[1:CHILD].

* Join the namespace specified in the config.json
* Ask the parent process to set the uid/gid mapping
* unshare the namespace specified in config.json
* Clone grandchild process
* Send the pid of grandchild to parent

<h3> grandchild </h3>

This is runc:[2:INIT].

* Now this process is in the new pid namespace. 
* Notify the parent process we are ready
* factory.StartInitialization()
* Config the environment specified in config.json and execute the process


<h3> summary </h3>

The first clone is to let the parent to set the uid/gid mapping. The second clone is to make the pid namespace take effect. After these double clone, the child process is totally in the desirable new environment.
 

<h3> reference </h3>

[runc源码分析](https://mp.weixin.qq.com/s/mSlc2RMRDe6liXb-ejtRvA)
[runc nsenter 源码阅读](https://zdyxry.github.io/2020/04/12/runc-nsenter-%E6%BA%90%E7%A0%81%E9%98%85%E8%AF%BB/)