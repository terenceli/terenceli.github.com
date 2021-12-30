---
layout: post
title: "runc internals, part 2: create and run a container"
description: "runc"
category: 技术
tags: [container, runc]
---
{% include JB/setup %}


<h3> runc create analysis </h3>

We can create a container by run 'runc create', for not consider the tty/console, let's change the default 'config.json.

        "terminal": false,
        ...
        "args": [
                "sleep",
                "1000"
        ],

I list the important function call in the following. 

startContainer
    -->setupSpec
    -->createContainer
            -->specconv.CreateLibcontainerConfig
            -->loadFactory
            -->factory.Create
                    -->manager.New

    --runner.run
            -->newProcess
            -->setupIO
            -->r.container.Start
                    -->c.createExecFifo
                    -->c.start
                            -->c.newParentProcess
                                    -->c.commandTemplate
                                    -->c.newInitProcess

                            -->parent.start
                                    -->p.cmd.Start
                                    -->p.sendConfig

The create process contains three steps in general which I have split them with empty line.

The first is the prepare work, the code is mostly in 'utils_linux.go'. It contains following:
* load spec from config.json
* create a container object using factory pattern
* create a runner and call the runner.run


The second is the runner.run process, the code is mostly in 'container_linux.go'. It contains following:
* Call the container.Start, thus go to the libcontainer layer
* Call internal function c.start, this function create a newParentProcess 
* Call parent.start

The third is the parent.start(), the coe is in 'init.go' and 'nsenter.c'. It contains following:
* p.cmd.Start, this will create a child process which is 'runc init'. 
* The runc init process will do double clone and finally run the process defined in config.json, this is an interesting process, I will use a separate post to analysis it.

Ok, let's dig into more of the code.


<h3> prepare </h3>

Following pic show the prepare work.

![](/assets/img/runcinternals2/1.png)

'startContainer' calls setupSpec to get the spec from config.json. Then call 'createContainer' to get a new container object.

        func startContainer(context *cli.Context, action CtAct, criuOpts *libcontainer.CriuOpts) (int, error) {
                if err := revisePidFile(context); err != nil {
                        return -1, err
                }
                spec, err := setupSpec(context)
                ...
                container, err := createContainer(context, id, spec)
                ...
        }


Linux has no built-in container concept. libcontainer use a 'linuxContainer' to represent a container concept.

        type linuxContainer struct {
                id                   string
                root                 string
                config               *configs.Config
                cgroupManager        cgroups.Manager
                intelRdtManager      intelrdt.Manager
                initPath             string
                initArgs             []string
                initProcess          parentProcess
                initProcessStartTime uint64
                criuPath             string
                newuidmapPath        string
                newgidmapPath        string
                m                    sync.Mutex
                criuVersion          int
                state                containerState
                created              time.Time
                fifo                 *os.File
        }

As we can see, there are several container-related fields. The 'initPath' specify the init program for spawning a container. 'initProcess' is the process represent of the init program.

A linuxContainer is created by a 'LinuxFactory'.  The createContainer can be easily understood. It first create a libcontainer config and then create LinuxFactory(by calling loadFactory) and finally create a linuxContainer(by calling factory.Create).

        func createContainer(context *cli.Context, id string, spec *specs.Spec) (libcontainer.Container, error) {
                rootlessCg, err := shouldUseRootlessCgroupManager(context)
                if err != nil {
                        return nil, err
                }
                config, err := specconv.CreateLibcontainerConfig(&specconv.CreateOpts{
                        CgroupName:       id,
                        UseSystemdCgroup: context.GlobalBool("systemd-cgroup"),
                        NoPivotRoot:      context.Bool("no-pivot"),
                        NoNewKeyring:     context.Bool("no-new-keyring"),
                        Spec:             spec,
                        RootlessEUID:     os.Geteuid() != 0,
                        RootlessCgroups:  rootlessCg,
                })
                if err != nil {
                        return nil, err
                }

                factory, err := loadFactory(context)
                if err != nil {
                        return nil, err
                }
                return factory.Create(id, config)
        }


'loadFactory' will call 'libcontainer.New' to create a new Factory. As we can see the 'InitPath' is set to the runc program it self and the 'InitArgs' is set to 'init'. This means 'runc init'. 

        func New(root string, options ...func(*LinuxFactory) error) (Factory, error) {
                ...
                l := &LinuxFactory{
                        Root:      root,
                        InitPath:  "/proc/self/exe",
                        InitArgs:  []string{os.Args[0], "init"},
                        Validator: validate.New(),
                        CriuPath:  "criu",
                }
                ...
        }


After create the factory, 'createContainer' call 'factory.Create'. 

        func (l *LinuxFactory) Create(id string, config *configs.Config) (Container, error) {
                ...
                cm, err := manager.New(config.Cgroups)
                ...
                if err := os.MkdirAll(containerRoot, 0o711); err != nil {
                        return nil, err
                }
                if err := os.Chown(containerRoot, unix.Geteuid(), unix.Getegid()); err != nil {
                        return nil, err
                }
                c := &linuxContainer{
                        id:            id,
                        root:          containerRoot,
                        config:        config,
                        initPath:      l.InitPath,
                        initArgs:      l.InitArgs,
                        criuPath:      l.CriuPath,
                        newuidmapPath: l.NewuidmapPath,
                        newgidmapPath: l.NewgidmapPath,
                        cgroupManager: cm,
                }
                ...
                c.state = &stoppedState{c: c}
                return c, nil
        }


Notice, we can see 'initPath' and 'initArgs' of linuxContainer is assigned from the LinuxFactory. Also the 'factory.Create' create a directory as the container root. After creating the container, 'startContainer' create a 'runner' and calls 'r.run'.

        func startContainer(context *cli.Context, action CtAct, criuOpts *libcontainer.CriuOpts) (int, error) {
                ...
                r := &runner{
                        enableSubreaper: !context.Bool("no-subreaper"),
                        shouldDestroy:   !context.Bool("keep"),
                        container:       container,
                        listenFDs:       listenFDs,
                        notifySocket:    notifySocket,
                        consoleSocket:   context.String("console-socket"),
                        detach:          context.Bool("detach"),
                        pidFile:         context.String("pid-file"),
                        preserveFDs:     context.Int("preserve-fds"),
                        action:          action,
                        criuOpts:        criuOpts,
                        init:            true,
                }
                return r.run(spec.Process)
        }

The runner object is just as its name indicates, a runner. It allows the user to run a process in a container. The 'runner' contains the 'container' and also some other control options. And the 'action' can 'CT_ACT_CREATE' means just create and 'CT_ACT_RUN' means create and run. The 'init' decides whether we should do the initialization work. This can be false if we exec a new process in an exist container.
The 'r.run's parameter is 'spec.Process' which is the process we need to execute in config.json.

Let's go to the 'r.run', 'newProcess' create a new 'libcontainer.Process' object and 'setupIO' initialization the process's IO.

        func (r *runner) run(config *specs.Process) (int, error) {
                var err error
                ...
                process, err := newProcess(*config)
                ...
                // Populate the fields that come from runner.
                process.Init = r.init
                ...
                tty, err := setupIO(process, rootuid, rootgid, config.Terminal, detach, r.consoleSocket)
                if err != nil {
                        return -1, err
                }
                defer tty.Close()

                switch r.action {
                case CT_ACT_CREATE:
                        err = r.container.Start(process)
                case CT_ACT_RESTORE:
                        err = r.container.Restore(process, r.criuOpts)
                case CT_ACT_RUN:
                        err = r.container.Run(process)
                default:
                        panic("Unknown action")
                }
                ...
                return status, err
        }

Finally, according the 'r.action' we can corresponding  function, in the create case the 'r.container.Start' will be called.


<h3> container start </h3>

Following pic show the container start process.

![](/assets/img/runcinternals2/2.png)

        func (c *linuxContainer) Start(process *Process) error {
                c.m.Lock()
                defer c.m.Unlock()
                if c.config.Cgroups.Resources.SkipDevices {
                        return errors.New("can't start container with SkipDevices set")
                }
                if process.Init {
                        if err := c.createExecFifo(); err != nil {
                                return err
                        }
                }
                if err := c.start(process); err != nil {
                        if process.Init {
                                c.deleteExecFifo()
                        }
                        return err
                }
                return nil
        }


'c.createExecFifo' create a fifo in container directory, the default path is '/run/runc/\<container id\>/exec.fifo'
Then we reach to the internal start fucntion. The most work of 'start' is create a new parentProcess. A parentProcess just as its name indicates, it's a process to lanuch child process which is the process defined in config.json. Why we need parentProcess, because we can't put the one process in a container environment (separete namespace, cgroup control and so on) in one step. It needs severals steps. 'parentProcess' is an interface in runc, it has two implementation 'setnsProcess' and 'initProcess'. These two again is used in the 'runc exec' and 'runc creat/run' two cases. 

        func (c *linuxContainer) start(process *Process) (retErr error) {
                parent, err := c.newParentProcess(process)
                ...
                if err := parent.start(); err != nil {
                        return fmt.Errorf("unable to start container process: %w", err)
                }
                ...
        }

The 'initProcess' is defined as following:

        type initProcess struct {
                cmd             *exec.Cmd
                messageSockPair filePair
                logFilePair     filePair
                config          *initConfig
                manager         cgroups.Manager
                intelRdtManager intelrdt.Manager
                container       *linuxContainer
                fds             []string
                process         *Process
                bootstrapData   io.Reader
                sharePidns      bool
        }

The 'cmd' is the parent process's program and args, the 'process' is the process info defined in config.json, the 'bootstrapData' contains the data that should be sent to the child process from parent.
Let's see how the parentProcess is created. 

        func (c *linuxContainer) newParentProcess(p *Process) (parentProcess, error) {
                parentInitPipe, childInitPipe, err := utils.NewSockPair("init")
                if err != nil {
                        return nil, fmt.Errorf("unable to create init pipe: %w", err)
                }
                messageSockPair := filePair{parentInitPipe, childInitPipe}

                parentLogPipe, childLogPipe, err := os.Pipe()
                if err != nil {
                        return nil, fmt.Errorf("unable to create log pipe: %w", err)
                }
                logFilePair := filePair{parentLogPipe, childLogPipe}

                cmd := c.commandTemplate(p, childInitPipe, childLogPipe)
                ...
                return c.newInitProcess(p, cmd, messageSockPair, logFilePair)
        }

'c.commandTemplate' prepare the parentProcess's command line. As we can see, the command is set to 'c.initPath' and 'c.initArgs'. This is the 'runc init'.It also add some environment variables to the parentProcess cmd. Two fd one for initpipe and one for logpipe is added through this way.

        func (c *linuxContainer) commandTemplate(p *Process, childInitPipe *os.File, childLogPipe *os.File) *exec.Cmd {
                cmd := exec.Command(c.initPath, c.initArgs[1:]...)
                cmd.Args[0] = c.initArgs[0]
                cmd.Stdin = p.Stdin
                cmd.Stdout = p.Stdout
                cmd.Stderr = p.Stderr
                cmd.Dir = c.config.Rootfs
                if cmd.SysProcAttr == nil {
                        cmd.SysProcAttr = &unix.SysProcAttr{}
                }
                cmd.Env = append(cmd.Env, "GOMAXPROCS="+os.Getenv("GOMAXPROCS"))
                cmd.ExtraFiles = append(cmd.ExtraFiles, p.ExtraFiles...)
                if p.ConsoleSocket != nil {
                        cmd.ExtraFiles = append(cmd.ExtraFiles, p.ConsoleSocket)
                        cmd.Env = append(cmd.Env,
                                "_LIBCONTAINER_CONSOLE="+strconv.Itoa(stdioFdCount+len(cmd.ExtraFiles)-1),
                        )
                }
                cmd.ExtraFiles = append(cmd.ExtraFiles, childInitPipe)
                cmd.Env = append(cmd.Env,
                        "_LIBCONTAINER_INITPIPE="+strconv.Itoa(stdioFdCount+len(cmd.ExtraFiles)-1),
                        "_LIBCONTAINER_STATEDIR="+c.root,
                )

                cmd.ExtraFiles = append(cmd.ExtraFiles, childLogPipe)
                cmd.Env = append(cmd.Env,
                        "_LIBCONTAINER_LOGPIPE="+strconv.Itoa(stdioFdCount+len(cmd.ExtraFiles)-1),
                        "_LIBCONTAINER_LOGLEVEL="+p.LogLevel,
                )

                // NOTE: when running a container with no PID namespace and the parent process spawning the container is
                // PID1 the pdeathsig is being delivered to the container's init process by the kernel for some reason
                // even with the parent still running.
                if c.config.ParentDeathSignal > 0 {
                        cmd.SysProcAttr.Pdeathsig = unix.Signal(c.config.ParentDeathSignal)
                }
                return cmd
        }

After prepare the cmd, 'newParentProcess' calls 'newInitProcess' to create a 'initProcess' object. 'newInitProcess' also create some bootstrap data, the data contains the clone flags in config.json and the nsmaps, this defines what namespaces will be used in the process of config.json.

        func (c *linuxContainer) newInitProcess(p *Process, cmd *exec.Cmd, messageSockPair, logFilePair filePair) (*initProcess, error) {
                cmd.Env = append(cmd.Env, "_LIBCONTAINER_INITTYPE="+string(initStandard))
                nsMaps := make(map[configs.NamespaceType]string)
                for _, ns := range c.config.Namespaces {
                        if ns.Path != "" {
                                nsMaps[ns.Type] = ns.Path
                        }
                }
                _, sharePidns := nsMaps[configs.NEWPID]
                data, err := c.bootstrapData(c.config.Namespaces.CloneFlags(), nsMaps, initStandard)
                ...
                init := &initProcess{
                        cmd:             cmd,
                        messageSockPair: messageSockPair,
                        logFilePair:     logFilePair,
                        manager:         c.cgroupManager,
                        intelRdtManager: c.intelRdtManager,
                        config:          c.newInitConfig(p),
                        container:       c,
                        process:         p,
                        bootstrapData:   data,
                        sharePidns:      sharePidns,
                }
                c.initProcess = init
                return init, nil
        }

'CloneFlags' return the clone flags which parsed from the config.json.

        func (n *Namespaces) CloneFlags() uintptr {
                var flag int
                for _, v := range *n {
                        if v.Path != "" {
                                continue
                        }
                        flag |= namespaceInfo[v.Type]
                }
                return uintptr(flag)
        }

The default created new namespaces contains following:

		"namespaces": [
			{
				"type": "pid"
			},
			{
				"type": "network"
			},
			{
				"type": "ipc"
			},
			{
				"type": "uts"
			},
			{
				"type": "mount"
			}
		],

After create a 'parentProcess', the 'parent.start()' is called to start the parent process in linuxContainer.start function. This function will create the initialization function by calling 'p.cmd.Start()'.

        func (p *initProcess) start() (retErr error) {
                defer p.messageSockPair.parent.Close() //nolint: errcheck
                err := p.cmd.Start()
                ...
        }

<h3> parent start </h3>


Following pic is the brief description of this phase.

![](/assets/img/runcinternals2/3.png)


'p.cmd.Start()' will start a new process, its parent process, which is 'runc init'. The handler of 'init' is in the 'init.go' file. The go is a high level language, but the namespace operations is so low level, so it should be handled not in the code. So init.go, it has import a nsenter pkg.

        _ "github.com/opencontainers/runc/libcontainer/nsenter"

nsenter pkg contains cgo code as following:

        package nsenter

        /*
        #cgo CFLAGS: -Wall
        extern void nsexec();
        void __attribute__((constructor)) init(void) {
                nsexec();
        }
        */
        import "C"

So the nsexec will be executed first. The code is in the 'libcontainer/nsenter/nsexec.c'.
'nsexec' is a long function that I will use another post to discuss it. Here is just a summary of this parent process.
In the 'runc init' parent process (which is runc:[0:PARENT]), it will clone a new process, which is named 'runc:[1:CHILD]', in the runc:[1:CHILD] process, it will set the namespace, but as the pid namespace only take effect in the children process the 'runc:[1:CHILD]' process will clone another process named 'runc:[2:INIT]'. The original runc create process will do some sync work with these process. 

Now the 'runc:[2:INIT]' is totally in new namespaces, the 'init.go' will call factory.StartInitialization to do the final initialization work and exec the process defined in config.json. 'factory.StartInitialization' will create a new 'initer' object, the 'initer' is an interface. Not surprisingly, there are two implementation which is one for 'runc exec'(linuxSetnsInit) and one for 'runc create/run'(linuxStandardInit). 'StartInitialization' finally calls the 'i.Init()' do the really initialization work.

        // StartInitialization loads a container by opening the pipe fd from the parent to read the configuration and state
        // This is a low level implementation detail of the reexec and should not be consumed externally
        func (l *LinuxFactory) StartInitialization() (err error) {
                ...
                i, err := newContainerInit(it, pipe, consoleSocket, fifofd, logPipeFd, mountFds)
                if err != nil {
                        return err
                }

                // If Init succeeds, syscall.Exec will not return, hence none of the defers will be called.
                return i.Init()
        }


Following is main routine of Init(). The Init's work is mostly setting the configuration specified in the config.json. For example, setupNetwork, setupRoute, hostName, apply apparmor profile, sysctl, readonly path, seccomp and so on.
Notice near the end of this function, it opens the execfifo pipe file which is the '/run/runc/\<container id\>/exec.fifo'. It writes data to it. As there is no reader for this pipe, so this write will be blocked.

        func (l *linuxStandardInit) Init() error {
                ...
                if err := setupNetwork(l.config); err != nil {
                        return err
                }
                if err := setupRoute(l.config.Config); err != nil {
                        return err
                }

                // initialises the labeling system
                selinux.GetEnabled()

                // We don't need the mountFds after prepareRootfs() nor if it fails.
                err := prepareRootfs(l.pipe, l.config, l.mountFds)
                ...
                if hostname := l.config.Config.Hostname; hostname != "" {
                        if err := unix.Sethostname([]byte(hostname)); err != nil {
                                return &os.SyscallError{Syscall: "sethostname", Err: err}
                        }
                }
                if err := apparmor.ApplyProfile(l.config.AppArmorProfile); err != nil {
                        return fmt.Errorf("unable to apply apparmor profile: %w", err)
                }

                for key, value := range l.config.Config.Sysctl {
                        if err := writeSystemProperty(key, value); err != nil {
                                return err
                        }
                }
                for _, path := range l.config.Config.ReadonlyPaths {
                        if err := readonlyPath(path); err != nil {
                                return fmt.Errorf("can't make %q read-only: %w", path, err)
                        }
                }
                for _, path := range l.config.Config.MaskPaths {
                        if err := maskPath(path, l.config.Config.MountLabel); err != nil {
                                return fmt.Errorf("can't mask path %s: %w", path, err)
                        }
                }
                pdeath, err := system.GetParentDeathSignal()
                if err != nil {
                        return fmt.Errorf("can't get pdeath signal: %w", err)
                }
                if l.config.NoNewPrivileges {
                ...
                if l.config.Config.Seccomp != nil && !l.config.NoNewPrivileges {
                        seccompFd, err := seccomp.InitSeccomp(l.config.Config.Seccomp)
                        if err != nil {
                                return err
                        }

                        if err := syncParentSeccomp(l.pipe, seccompFd); err != nil {
                                return err
                        }
                }
                if err := finalizeNamespace(l.config); err != nil {
                        return err
                }
                ...
                // Close the pipe to signal that we have completed our init.
                logrus.Debugf("init: closing the pipe to signal completion")
                _ = l.pipe.Close()

                // Close the log pipe fd so the parent's ForwardLogs can exit.
                if err := unix.Close(l.logFd); err != nil {
                        return &os.PathError{Op: "close log pipe", Path: "fd " + strconv.Itoa(l.logFd), Err: err}
                }

                // Wait for the FIFO to be opened on the other side before exec-ing the
                // user process. We open it through /proc/self/fd/$fd, because the fd that
                // was given to us was an O_PATH fd to the fifo itself. Linux allows us to
                // re-open an O_PATH fd through /proc.
                fifoPath := "/proc/self/fd/" + strconv.Itoa(l.fifoFd)
                fd, err := unix.Open(fifoPath, unix.O_WRONLY|unix.O_CLOEXEC, 0)
                if err != nil {
                        return &os.PathError{Op: "open exec fifo", Path: fifoPath, Err: err}
                }
                if _, err := unix.Write(fd, []byte("0")); err != nil {
                        return &os.PathError{Op: "write exec fifo", Path: fifoPath, Err: err}
                }

                // Close the O_PATH fifofd fd before exec because the kernel resets
                // dumpable in the wrong order. This has been fixed in newer kernels, but
                // we keep this to ensure CVE-2016-9962 doesn't re-emerge on older kernels.
                // N.B. the core issue itself (passing dirfds to the host filesystem) has
                // since been resolved.
                // https://github.com/torvalds/linux/blob/v4.9/fs/exec.c#L1290-L1318
                _ = unix.Close(l.fifoFd)

                s := l.config.SpecState
                s.Pid = unix.Getpid()
                s.Status = specs.StateCreated
                if err := l.config.Config.Hooks[configs.StartContainer].RunHooks(s); err != nil {
                        return err
                }

                return system.Exec(name, l.config.Args[0:], os.Environ())
        }

For now, we can the runc process is ./runc init.

        root@ubuntu:~/go/src# ps aux | grep runc
        root       4239  0.0  0.2 1090192 10400 ?       Ssl  Dec26   0:00 ./runc init
        root      10667  0.0  0.0  14432  1084 pts/0    S+   05:19   0:00 grep --color=auto runc
        root@ubuntu:~/go/src# cat /proc/4239/comm 
        runc:[2:INIT]

        root@ubuntu:/run/runc/test# runc list
        ID          PID         STATUS      BUNDLE                   CREATED                          OWNER
        test        4239        created     /home/test/mycontainer   2021-12-25T05:17:30.596712553Z   root

Now let's execute 'runc start test'. We can see following:

        root@ubuntu:/run/runc/test# runc start test
        root@ubuntu:/run/runc/test# runc list
        ID          PID         STATUS      BUNDLE                   CREATED                          OWNER
        test        4239        running     /home/test/mycontainer   2021-12-25T05:17:30.596712553Z   root
        root@ubuntu:/run/runc/test# runc ps test
        UID         PID   PPID  C STIME TTY          TIME CMD
        root       4239   2709  0 Dec26 ?        00:00:00 sleep 1000
        root@ubuntu:/run/runc/test# ls
        state.json


The 'runc start' will call 'getContainer' to get a container object and call the 'Exec()' of container which calls exec(). 

        func (c *linuxContainer) exec() error {
                path := filepath.Join(c.root, execFifoFilename)
                pid := c.initProcess.pid()
                blockingFifoOpenCh := awaitFifoOpen(path)
                for {
                        select {
                        case result := <-blockingFifoOpenCh:
                                return handleFifoResult(result)

                        case <-time.After(time.Millisecond * 100):
                                stat, err := system.Stat(pid)
                                if err != nil || stat.State == system.Zombie {
                                        // could be because process started, ran, and completed between our 100ms timeout and our system.Stat() check.
                                        // see if the fifo exists and has data (with a non-blocking open, which will succeed if the writing process is complete).
                                        if err := handleFifoResult(fifoOpen(path, false)); err != nil {
                                                return errors.New("container process is already dead")
                                        }
                                        return nil
                                }
                        }
                }
        }


The 'handleFifoResult' read data from the execfife pipe thus unblock the 'runc:[2:INIT]' process and finally the 'runc:[2:INIT]' will execute the process defined in config.json.

        func handleFifoResult(result openResult) error {
                if result.err != nil {
                        return result.err
                }
                f := result.file
                defer f.Close()
                if err := readFromExecFifo(f); err != nil {
                        return err
                }
                return os.Remove(f.Name())
        }



