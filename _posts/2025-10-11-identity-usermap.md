---
layout: post
title: "Map non-root user in host to non-root user in container with the same uid"
description: "Map non-root user in host to non-root user in container"
category: 技术
tags: [技术, Container, gVisor]
---
{% include JB/setup %}


<h2> Introduction </h2>

Once when I use gVisor's rootless mode, I found that non-root user can only be mapped to root in container. Some software's behaviour is different between root user and non-root user. So I want to run gVisor mapped the non-root user to the same user in container. 

Following is what I wanted. The uid=1000 user is the same both in user ns and the outside user ns.

![](/assets/img/identityuserns/1.png)


My first attempt is to set the container's user to 1000 user.


```

"process": {
    "user": {
        "uid": 1000,
        "gid": 1000
    },


```

However this [doesn't work](https://github.com/google/gvisor/issues/9918). Then I tried following OCI config.json which has following configuration:

* Config process.user to 1000
* Config linux.uidMappings to map host 1000 to container 1000
* Config linux.ns with user


```

{
  "ociVersion": "1.0.0",
  "process": {
    "user": {
      "uid": 1000,
      "gid": 1000
    },
    "args": [
      "sh"
    ],
    "env": [
      "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
      "TERM=xterm"
    ],
    "cwd": "/",
    "capabilities": {
      "bounding": [
        "CAP_AUDIT_WRITE",
        "CAP_KILL",
        "CAP_NET_BIND_SERVICE",
        "CAP_NET_RAW"
      ],
      "effective": [
        "CAP_AUDIT_WRITE",
        "CAP_KILL",
        "CAP_NET_BIND_SERVICE",
        "CAP_NET_RAW"
      ],
      "inheritable": [
        "CAP_AUDIT_WRITE",
        "CAP_KILL",
        "CAP_NET_BIND_SERVICE",
        "CAP_NET_RAW"
      ],
      "permitted": [
        "CAP_AUDIT_WRITE",
        "CAP_KILL",
        "CAP_NET_BIND_SERVICE"
      ]
    },
    "rlimits": [
      {
        "type": "RLIMIT_NOFILE",
        "hard": 1024,
        "soft": 1024
      }
    ]
  },
  "root": {
    "path": "rootfs",
    "readonly": true
  },
  "hostname": "runsc",
  "mounts": [
    {
      "destination": "/proc",
      "type": "proc",
      "source": "proc"
    },
    {
      "destination": "/dev",
      "type": "tmpfs",
      "source": "tmpfs"
    },
    {
      "destination": "/sys",
      "type": "sysfs",
      "source": "sysfs",
      "options": [
        "nosuid",
        "noexec",
        "nodev",
        "ro"
      ]
    },
    {
      "destination": "/tmp",
      "type": "bind",
      "source": "/tmp",
      "options": [
        "rbind",
        "rw"
      ]
    }
  ],
  "linux": {
    "uidMappings": [
      {
        "containerID": 1000,
        "hostID": 1000,
        "size": 1
      }
    ],
    "gidMappings": [
      {
        "containerID": 1000,
        "hostID": 1000,
        "size": 1
      }
    ],
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
      },
      {
        "type": "user"
      }
    ]
  }
}

```

This configuration map the uid=1000 user in host to the uid=1000 user in container. Which I expected should work. However it doesn't work.

The error occurs in unix.RawSyscall(unix.SYS_SETUID, 0, 0, 0).


```

func syncUsernsForRootless(fd int) {
	if err := waitForFD(fd, "userns sync FD"); err != nil {
		util.Fatalf("failed to sync on userns FD: %v", err)
	}

	// SETUID changes UID on the current system thread, so we have
	// to re-execute current binary.
	runtime.LockOSThread()
	if _, _, errno := unix.RawSyscall(unix.SYS_SETUID, 0, 0, 0); errno != 0 {
		util.Fatalf("failed to set UID: %v", errno)
	}
	if _, _, errno := unix.RawSyscall(unix.SYS_SETGID, 0, 0, 0); errno != 0 {
		util.Fatalf("failed to set GID: %v", errno)
	}
}

```

This is reasonable as we are 1000 user in the current user ns so we can't call setuid to 0.
So how can we achieve our goal? Before our analysis, Let's just see how podman and crun does.

<h2> The podman userns=keep-id implementation </h2>

The 'podman run' command has a '--userns' option which can be set as '--userns=keep-id'. This will achive what I want, to run the container process with the uid as the user outside the container.

Following pic show it:

![](/assets/img/identityuserns/2.png)

podman starts a conmon(seems it uses systemd to start).  Then conmon starts the container first process.

![](/assets/img/identityuserns/3.png)


Let's see the OCI spec.

```

test@test-virtual-machine:~$ podman inspect 8de77c63d183 --format json | grep OCI
        "OCIConfigPath": "/home/test/xxxuserdata/config.json",

```

```

  "linux": {
    "uidMappings": [
      {
        "containerID": 0,
        "hostID": 1,
        "size": 1000
      },
      {
        "containerID": 1000,
        "hostID": 0,
        "size": 1
      },
      {
        "containerID": 1001,
        "hostID": 1001,
        "size": 64536
      }
    ],
    "gidMappings": [
      {
        "containerID": 0,
        "hostID": 1,
        "size": 1000
      },
      {
        "containerID": 1000,
        "hostID": 0,
        "size": 1
      },
      {
        "containerID": 1001,
        "hostID": 1001,
        "size": 64536
      }
    ],

```

As we can see, it sets the host uid=0 to container uid=1000. But where is our host uid=1000. What I need is to map host uid=1000 to container uid=1000. 

After dig into the code and explore the uid_map of conmon and container process I found the truth.

In the container the uid_map is as follows, just the same as OCI spec.

![](/assets/img/identityuserns/4.png)

The conmon's uid_map.


![](/assets/img/identityuserns/5.png)


The container's uid_map

![](/assets/img/identityuserns/6.png)



Now we have the conclude, the podman rootless container create two user ns. One for conmon which map the host uid=1000 to container uid=0, and then the conmon start the container process which map uid=0 to container uid=1000. Through this method, the container uid=1000 is the same user in host uid=1000.

Notice the container's uid_map is not the same from host view and from container view. This is because the uid_map's read handler will adjust according the reader's user ns.

Following pic shows the process.

![](/assets/img/identityuserns/7.png)


<h2> The crun method </h2>

So can crun works well with following OCI spec(the same with my second attempt).


```

{
  "ociVersion": "1.0.2-dev",
  "process": {
    "terminal": true,
    "user": {
      "uid": 1000,
      "gid": 1000
    },
    "args": [
      "sh"
    ],
    "env": [
      "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
      "TERM=xterm"
    ],
    "cwd": "/",
    "capabilities": {
      "bounding": [
        "CAP_AUDIT_WRITE",
        "CAP_KILL",
        "CAP_NET_BIND_SERVICE"
      ],
      "effective": [
        "CAP_AUDIT_WRITE",
        "CAP_KILL",
        "CAP_NET_BIND_SERVICE"
      ],
      "permitted": [
        "CAP_AUDIT_WRITE",
        "CAP_KILL",
        "CAP_NET_BIND_SERVICE"
      ],
      "ambient": [
        "CAP_AUDIT_WRITE",
        "CAP_KILL",
        "CAP_NET_BIND_SERVICE"
      ]
    },
    "rlimits": [
      {
        "type": "RLIMIT_NOFILE",
        "hard": 1024,
        "soft": 1024
      }
    ],
    "noNewPrivileges": true
  },
  "root": {
    "path": "rootfs",
    "readonly": true
  },
  "hostname": "runc",
  "mounts": [
    {
      "destination": "/proc",
      "type": "proc",
      "source": "proc"
    },
    {
      "destination": "/dev",
      "type": "tmpfs",
      "source": "tmpfs",
      "options": [
        "nosuid",
        "strictatime",
        "mode=755",
        "size=65536k"
      ]
    },
    {
      "destination": "/dev/pts",
      "type": "devpts",
      "source": "devpts",
      "options": [
        "nosuid",
        "noexec",
        "newinstance",
        "ptmxmode=0666",
        "mode=0620"
      ]
    },
    {
      "destination": "/dev/shm",
      "type": "tmpfs",
      "source": "shm",
      "options": [
        "nosuid",
        "noexec",
        "nodev",
        "mode=1777",
        "size=65536k"
      ]
    },
    {
      "destination": "/dev/mqueue",
      "type": "mqueue",
      "source": "mqueue",
      "options": [
        "nosuid",
        "noexec",
        "nodev"
      ]
    },
    {
      "destination": "/sys",
      "type": "none",
      "source": "/sys",
      "options": [
        "rbind",
        "nosuid",
        "noexec",
        "nodev",
        "ro"
      ]
    },
    {
      "destination": "/sys/fs/cgroup",
      "type": "cgroup",
      "source": "cgroup",
      "options": [
        "nosuid",
        "noexec",
        "nodev",
        "relatime",
        "ro"
      ]
    },
    {
      "destination": "/tmp",
      "type": "bind",
      "source": "/home/test/cruntest/mycontainer/rootfs/tmp",
      "options": [
        "rw",
        "rbind"
      ]
    }
  ],
  "linux": {
    "uidMappings": [
      {
        "containerID": 1000,
        "hostID": 1000,
        "size": 1
      }
    ],
    "gidMappings": [
      {
        "containerID": 1000,
        "hostID": 1000,
        "size": 1
      }
    ],
    "namespaces": [
      {
        "type": "pid"
      },
      {
        "type": "ipc"
      },
      {
        "type": "uts"
      },
      {
        "type": "mount"
      },
      {
        "type": "cgroup"
      },
      {
        "type": "user"
      }
    ],
    "maskedPaths": [
      "/proc/acpi",
      "/proc/asound",
      "/proc/kcore",
      "/proc/keys",
      "/proc/latency_stats",
      "/proc/timer_list",
      "/proc/timer_stats",
      "/proc/sched_debug",
      "/sys/firmware",
      "/proc/scsi"
    ],
    "readonlyPaths": [
      "/proc/bus",
      "/proc/fs",
      "/proc/irq",
      "/proc/sys",
      "/proc/sysrq-trigger"
    ]
  }
}

```

Yes it works.

![](/assets/img/identityuserns/8.png)


Let's see the uid_map

![](/assets/img/identityuserns/9.png)


The same as our expected.

crun also has a 'setresuid' process, however the uid's switch to not always 0(which gVisor does). If the root(uid=0) user is mapped into the container user ns, it will uses 0. If not, the 'def->process->user->uid' will be used.


```

/* Detect if root is available in the container.  */
static bool
root_mapped_in_container_p (runtime_spec_schema_defs_id_mapping **mappings, size_t len)
{
  size_t i;

  for (i = 0; i < len; i++)
    if (mappings[i]->container_id == 0)
      return true;

  return false;
}

static int
set_id_init (libcrun_container_t *container, libcrun_error_t *err)
{
  runtime_spec_schema_config_schema *def = container->container_def;
  uid_t uid = 0;
  gid_t gid = 0;
  int ret;

  if (def->process && def->process->user && def->linux)
    {
      /*
        If it is running in a user namespace and root is not mapped
        use the UID/GID specified for running the container.
      */
      bool root_mapped = false;

      if (def->linux->uid_mappings_len != 0)
        {
          root_mapped = root_mapped_in_container_p (def->linux->uid_mappings, def->linux->uid_mappings_len);
          if (! root_mapped)
            uid = def->process->user->uid;

          libcrun_debug ("Using mapped UID in container: `%d`", uid);
        }

      if (def->linux->gid_mappings_len != 0)
        {
          root_mapped = root_mapped_in_container_p (def->linux->gid_mappings, def->linux->gid_mappings_len);
          if (! root_mapped)
            gid = def->process->user->gid;

          libcrun_debug ("Using mapped GID in container: `%d`", gid);
        }
    }

  ret = setresuid (uid, uid, uid);
  if (UNLIKELY (ret < 0))
    return crun_make_error (err, errno, "setresuid to `%d`", uid);

  ret = setresgid (gid, gid, gid);
  if (UNLIKELY (ret < 0))
    return crun_make_error (err, errno, "setresgid to `%d`", gid);

  return 0;
}

```

<h2> The gVisor method </h2>

The [gVisor patch](https://github.com/google/gvisor/pull/12166/commits/0b6d43a255a78c12e797d954cc3a6ca894d15635) also follows the crun's method(which is suggested by avagin). If the root user is not maped to container user ns, we uses the 'Process.User.UID'.

```

func rootMappedInContainer(IDMap []specs.LinuxIDMapping) bool {
	for _, idMap := range IDMap {
		if idMap.ContainerID == 0 {
			return true
		}
	}
	return false
}

func SandboxUserGroupIDs(spec *specs.Spec) (uint32, uint32) {
	uid := uint32(0)
	gid := uint32(0)

	if !rootMappedInContainer(spec.Linux.UIDMappings) {
		uid = spec.Process.User.UID
	}

	if !rootMappedInContainer(spec.Linux.GIDMappings) {
		gid = spec.Process.User.GID
	}

	return uid, gid
}

```

After this, we can run gVisor in rootlessmode with non-root host user mapped to non-root container use with the same uid.

After the new patch, following works well. 

![](/assets/img/identityuserns/10.png)

<h2> Summary </h2>

The most important is that 'The child process in a new user namespace will have the full capability even it has a non-0 uid'. So that it can do setuid(0,0).

