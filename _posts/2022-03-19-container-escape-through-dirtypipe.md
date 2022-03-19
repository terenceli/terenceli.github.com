---
layout: post
title: "Container escape using dirtypipe"
description: "runc"
category: 技术
tags: [container, 漏洞分析, 容器逃逸]
---
{% include JB/setup %}


<h3> Background </h3>

The story begins with the pictures that Yuval Avrahami shows in [twitter](https://twitter.com/yuvalavra/status/1500978532494843912/photo/1). Here it is:

![](/assets/img/containerescapedirtypipe/1.jpg)

It means we can write the host files in /bin directory by using dirtypipe, though in fact the dirtypipe just modify the file's pagecache.

Then the moresec security researcher also write a [post](https://mp.weixin.qq.com/s/VMR_kLz1tAbHrequa2OnUA) to show the capability of using dirtypipe to do container escape.
Also some other researcher such as [drivertom](https://twitter.com/drivertomtt/status/1504504067975909376) successfully do this.

At the busy working day, I just have no time to do more experiment. I just discussed the point with some friends. Anyway at the first glance, it seems dirtypipe can't be used to 
do cantainer escape. It is not difficult to understand that the dirtypipe can change the file in other containers as the container may share some of layer files. But as there
is only a file '/proc/self/exe' as I know that can be interacted with the host filesystem. However after CVE-2019-5736, the runc binary is cloned by memfd_create in memory and
it seems we can just overwrite the cloned binary but not the actually runc binary in host filesystem.

So how these guys achieve the container escape by using dirtypipe? Bonan, another excellent cloud native security researcher, mentions that maybe the memfd_create file is copy-on-write.
Then the cloned and the host runc binary maybe share the same physical page, as the dirtypipe modify the cloned pagecache, it also affects the host runc binary. This is quite explainable.
I'm more sure 'cloned and host runc binary share the same physical page' is the reason after I dig into the internals of 'memfd_create' and 'sendfile' syscall. 


<h3> Experiment </h3>

If our guess is right, we can stop the escape by using the 'read' runc and 'write' to memfd_create file to let the memfd_create file and host runc file don't share the physical page.
Anyway, this is just a guess, we need to prove it. First let's try to escape and overrite the runc binary from container.

This is easy to achieve by combining the everywhere CVE-2019-5736 poc and dirtypipe PoC. After get the read only runc binary, we can use the dirtypipe to overwrite it.

Before the escape:

                root@ubuntu:/home/test/go/src/runc# mv runc /usr/sbin/runc
                root@ubuntu:/home/test/go/src/runc# md5sum /usr/sbin/runc
                70df137b272bd8fb1e3e63e90d77943a  /usr/sbin/runc

After the escape:

                root@ubuntu:/home/test/go/src/runc# md5sum /usr/sbin/runc
                687765833647de6091b82896fe90844a  /usr/sbin/runc
                root@ubuntu:/home/test/go/src/runc# head -c 20 /usr/sbin/runc
                ELdirtypipe>root@ubuntu:/home/test/go/src/runc# runc --version
                bash: /usr/sbin/runc: cannot execute binary file: Exec format error

As we can see the host binary is modified so we can do container escape by using dirtypipe.
So let't do the second experiment: don't use the sendfile but just use the read-and-write copy (deep copy). Fortunately the runc code just has the methods,
we can easily test it by comment out the sendfile. The patches is:


                --- a/libcontainer/nsenter/cloned_binary.c
                +++ b/libcontainer/nsenter/cloned_binary.c
                @@ -507,13 +507,14 @@ static int clone_binary(void)
                                goto error_binfd;
                
                        while (sent < statbuf.st_size) {
                -               int n = sendfile(execfd, binfd, NULL, statbuf.st_size - sent);
                -               if (n < 0) {
                +               //int n = sendfile(execfd, binfd, NULL, statbuf.st_size - sent);
                +               int n = 0;
                +               //if (n < 0) {
                                        /* sendfile can fail so we fallback to a dumb user-space copy. */
                                        n = fd_to_fd(execfd, binfd);
                                        if (n < 0)
                                                goto error_binfd;
                -               }
                +               //}
                                sent += n;


After compile the new runc, we the output shows as following:

                root@ubuntu:/home/test/go/src/runc# cp runc  /usr/sbin/runc
                root@ubuntu:/home/test/go/src/runc# runc --version
                runc version 1.1.0+dev
                commit: v1.1.0-92-g98b75bef-dirty
                spec: 1.0.2-dev
                go: go1.18
                libseccomp: 2.5.1
                root@ubuntu:/home/test/go/src/runc# md5sum /usr/sbin/runc
                8a5acd21ac5099abf40c15c815c97de1  /usr/sbin/runc
                root@ubuntu:/home/test/go/src/runc# md5sum /usr/sbin/runc
                ece16f4f8aa1518d95a19e9c5b2cb66b  /usr/sbin/runc
                root@ubuntu:/home/test/go/src/runc# runc --version
                bash: /usr/sbin/runc: cannot execute binary file: Exec format error

Emmm, interesting, the runc binary is still be modified. We need to go to the runc code to find the truth. After a moment, a suspices function
appears. In the clone_binary it calls 'try_bindfd' to get a execfd, it 'try_bindfd' success, the 'sendfile' and 'fd_to_fd' will never be executed.
The comment is quite clear, the copying will be executed only when 'try_bindfd' failed.

                static int clone_binary(void)
                {
                        int binfd, execfd;
                        struct stat statbuf = { };
                        size_t sent = 0;
                        int fdtype = EFD_NONE;

                        /*
                        * Before we resort to copying, let's try creating an ro-binfd in one shot
                        * by getting a handle for a read-only bind-mount of the execfd.
                        */
                        execfd = try_bindfd();
                        if (execfd >= 0)
                                return execfd;

                        ...
                }

Let's comment out the calling of 'try_bindfd'. Notice: this time we comment out the 'try_bindfd' and 'sendfile' and uses 'fd_to_fd'.

                root@ubuntu:/home/test/go/src/runc# cp runc  /usr/sbin/runc
                root@ubuntu:/home/test/go/src/runc# runc --version
                runc version 1.1.0+dev
                commit: v1.1.0-92-g98b75bef-dirty
                spec: 1.0.2-dev
                go: go1.18
                libseccomp: 2.5.1
                root@ubuntu:/home/test/go/src/runc# md5sum /usr/sbin/runc
                49f35f333efdfaf628bcd48aee611340  /usr/sbin/runc
                root@ubuntu:/home/test/go/src/runc# md5sum /usr/sbin/runc
                49f35f333efdfaf628bcd48aee611340  /usr/sbin/runc
                root@ubuntu:/home/test/go/src/runc# runc --version
                runc version 1.1.0+dev
                commit: v1.1.0-92-g98b75bef-dirty
                spec: 1.0.2-dev
                go: go1.18
                libseccomp: 2.5.1

OK, as we can see we can't modify the runc binary by the deep copy.

Let's do the final experiment. This test will comment out 'try_bindfd' only and the runc will uses 'sendfile'. As our guess, the runc will also be modified.

                root@ubuntu:/home/test/go/src/runc# cp runc  /usr/sbin/runc
                root@ubuntu:/home/test/go/src/runc# runc --version
                runc version 1.1.0+dev
                commit: v1.1.0-92-g98b75bef-dirty
                spec: 1.0.2-dev
                go: go1.18
                libseccomp: 2.5.1
                root@ubuntu:/home/test/go/src/runc# md5sum /usr/sbin/runc
                81dd1b92fe8a80a0682b8ac117821790  /usr/sbin/runc
                root@ubuntu:/home/test/go/src/runc# md5sum /usr/sbin/runc
                81dd1b92fe8a80a0682b8ac117821790  /usr/sbin/runc


Emmm, interesting again, the runc isn't been modified. Our guess is wrong.
Then I modify the dirtypipe PoC from splice syscall to sendfile syscall, as expected, it doesn't work. So the answer is:
The sendfile syscall doesn't share the physical page between src file and dst file.


<h3> Conclusion </h3> 

After look into the source code, I find the 'sendfile' syscall is actually not share the physical page between src file and dst file. It works as following:

* splice the src file to a internal created pipe, this will share the src file pagecache to the pipe. 
* Then splice the data in pipe to the dst file, this will do the actual copy but no share.

This behaviour also apply to the splice syscall. That is to say in splice file to pipe case the page is shared and in pipe to splice the data is not shared but actaully copied.

So the function who is responsible for container escape is 'try_bindfd' which is introduced in [this commit](https://github.com/opencontainers/runc/commit/16612d74de5f84977e50a9c8ead7f0e9e13b8628).
From the commit message, we know that after introduce the [fix](https://github.com/opencontainers/runc/commit/0a8e4117e7f715d5fbeef398405813ce8e88558b) for CVE-2019-5736, the runc community decide 
to use a more effective methods to avoid the vulnerability. It creats a read-only bind-mount of the runc binary and then get the runc bind handle and finally unmount it.
This way the runc binary can't be overwrite. In this methods, the /proc/self/exe is still point the runc binary in host filesystem. Combinie with the dirtypipe, we can write the actual runc binary in host.


After the CVE-2019-5736, most of the security researcher think that the fix is to use memfd_create to create a file in memory and copy the runc binary to this file, but this is wrong.
As we can do container escape using dirtypipe, so we think the sendfile shares the src file and dst file. But again this is wrong. 
This two wrong assumption makes the thing work and seems to be expainable. Just like negative plus negative equals positive.
There is an old chinese saying, "we can only get superficial knowledge from paper, but deep knowledge from practice"， 纸上得来终觉浅，绝知此事要躬行. 
The process of exploring the container escape using dirtypipe just remind of this old saying.

Return the Yuval pictures, it modifies the files in /bin directory. I'm not sure this is the case that Yuval escape. If he escapes from /proc/self/exe can then the shellcode modify the file in /bin directory it will be like what pictures show, if it isn't the case, there maybe another interesting things.

<h3> reference </h3>

[The Dirty Pipe Vulnerability](https://dirtypipe.cm4all.com/)

[从DirtyPipe到Docker逃逸](https://mp.weixin.qq.com/s/VMR_kLz1tAbHrequa2OnUA)