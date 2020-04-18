---
layout: post
title: "Linux vsock internals"
description: "vsock internals"
category: 技术
tags: [内核, 虚拟化]
---
{% include JB/setup %}

<h3> Background </h3>

VM Sockets(vsock) is a fast and efficient communication mechanism between guest virtual machines and their host. It was added by VMware in commit [VSOCK: Introduce VM Sockets](https://github.com/torvalds/linux/commit/d021c344051af91f42c5ba9fdedc176740cbd238). The commit added a new socket address family named vsock and its vmci transport.

VM Sockets can be used in a lot of situation such as the VMware Tools inside the guest. As vsock is very useful the community has development vsock supporting other hypervisor such as qemu&&kvm and HyperV. 
Redhat added the virtio transport for vsock in [VSOCK: Introduce virtio_transport.ko](https://github.com/torvalds/linux/commit/0ea9e1d3a9e3ef7d2a1462d3de6b95131dc7d872), for vhost transport in host was added in comit [VSOCK: Introduce vhost_vsock.ko](https://github.com/torvalds/linux/commit/433fc58e6bf2c8bd97e57153ed28e64fd78207b8). Microsoft added the HyperV transport in commit [hv_sock: implements Hyper-V transport for Virtual Sockets (AF_VSOCK)](https://github.com/torvalds/linux/commit/ae0078fcf0a5eb3a8623bfb5f988262e0911fdb9), Of course this host transport is in Windows kernel and no open sourced.

This post will focus the virtio transport in guest and vhost transport in host.


<h3> Architecture </h3>


Following pics is from Stefano Garzarella's [slides](https://static.sched.com/hosted_files/devconfcz2020a/b1/DevConf.CZ_2020_vsock_v1.1.pdf)

![](/assets/img/vsock/1.png)


There are several layers here. 

* application, use <cid,port> as a socket address
* socket layer, support for socket API
* AF_VSOCK address family, implement the vsock core
* transport, trasnport the data between guest and host.

The transport layer is the mostly needed to talk as the other three just need to implement standand interfaces in kernel.

Transport as its name indicated, is used to transport the data between guest and host just like the networking card tranpost data between local and remote socket. There are two kinds of transports according to data's flow direction.

* G2H: guest->host transport, they run in the guest and the guest vsock networking protocol uses this to communication with the host.
* H2G: host->guest transport, they run in the host and the host vsock networing protocol uses this to communiction with the guest.

Usually H2G transport is implemented as a device emulation, and G2H transport is implemented as the emulated device's driver. For example, in VMware the H2G transport is a emulated vmci PCI device and the G2H is vmci device driver. In qemu the H2G transport is a emulated vhost-vsock device and the G2H transport is the vosck device's driver.

Following pic shows the virtio(in guest) and vhost(in host) transport. This pic also from Stefano Garzarella's slides.

![](/assets/img/vsock/2.png)

vsock socket address family and G2H transport is implemented in 'net/vmw_vsock' directory in linux tree.
H2G transport is implemented in 'drivers' directory, vhost vsock is in 'drivers/vhost/vsock.c' and vmci is in 'drivers/misc/vmw_vmci' directory.

Following pic shows the more detailed virtio<->vhost transport in qemu.

![](/assets/img/vsock/3.png)

Following is the steps how guest and host initialize their tranport channel.
1. When start qemu, we need add '-device vhost-vsock-pci,guest-cid=<CID>' in qemu cmdline.
2. load the vhost_vsock driver in host.
3. The guest kernel will probe the vhost-vsock pci device and load its driver. This virtio driver is registered in 'virtio_vsock_init' function.
4. The virtio_vsock driver initializes the emulated vhost-vsock device. This will communication with vhost_vsock driver.

Transport layer has a global variable named 'transport'. Both guest and host side need to register his vsock transport by calling 'vsock_core_init'. This function will set the 'transport' to an transport implementaion.

For example the guest kernel function 'virtio_vsock_init' calls 'vsock_core_init' to set the 'transport' to 'virtio_transport.transport' and the host kernel function 'vhost_vsock_init' calls 'vsock_core_init' to set the 'transport' to 'vhost_transport.transport'.

After initialization, the guest and host can use vsock to talk to each other.

<h3> send/recv data</h3>

vsock has two type just like udp and tcp for ipv4. Following shows the 'vsock_stream_ops'

        static const struct proto_ops vsock_stream_ops = {
                .family = PF_VSOCK,
                .owner = THIS_MODULE,
                .release = vsock_release,
                .bind = vsock_bind,
                .connect = vsock_stream_connect,
                .socketpair = sock_no_socketpair,
                .accept = vsock_accept,
                .getname = vsock_getname,
                .poll = vsock_poll,
                .ioctl = sock_no_ioctl,
                .listen = vsock_listen,
                .shutdown = vsock_shutdown,
                .setsockopt = vsock_stream_setsockopt,
                .getsockopt = vsock_stream_getsockopt,
                .sendmsg = vsock_stream_sendmsg,
                .recvmsg = vsock_stream_recvmsg,
                .mmap = sock_no_mmap,
                .sendpage = sock_no_sendpage,
        };


Most of the 'proto_ops' of vsock is easy to understand. Here I just use send/recv process to show how the transport layer 'transport' data between 'guest' and 'host'. 


<h4> guest send </h4>
'vsock_stream_sendmsg' is used to send data to host, it calls transport's 'stream_enqueue' callback, in guest this function is 'virtio_transport_stream_enqueue'. It creates a 'virtio_vsock_pkt_info' and called 'virtio_transport_send_pkt_info'.

        ssize_t
        virtio_transport_stream_enqueue(struct vsock_sock *vsk,
                                        struct msghdr *msg,
                                        size_t len)
        {
                struct virtio_vsock_pkt_info info = {
                        .op = VIRTIO_VSOCK_OP_RW,
                        .type = VIRTIO_VSOCK_TYPE_STREAM,
                        .msg = msg,
                        .pkt_len = len,
                        .vsk = vsk,
                };

                return virtio_transport_send_pkt_info(vsk, &info);
        }


        virtio_transport_send_pkt_info
                -->virtio_transport_alloc_pkt
                -->virtio_transport_get_ops()->send_pkt(pkt);(virtio_transport_send_pkt)

'virtio_transport_alloc_pkt' allocate a buffer('pkt->buf') to store the send data'.
'virtio_transport_send_pkt' insert the 'virtio_vsock_pkt' to a list and queue it to a queue_work.
The actully data send is in 'virtio_transport_send_pkt_work' function. 

In 'virtio_transport_send_pkt_work' it is the virtio driver's standard operation, prepare scatterlist using msg header and msg itself, call 'virtqueue_add_sgs' and call 'virtqueue_kick'.

        static void
        virtio_transport_send_pkt_work(struct work_struct *work)
        {
                struct virtio_vsock *vsock =
                        container_of(work, struct virtio_vsock, send_pkt_work);
                struct virtqueue *vq;
                bool added = false;
                bool restart_rx = false;

                mutex_lock(&vsock->tx_lock);
                ...
                vq = vsock->vqs[VSOCK_VQ_TX];

                for (;;) {
                        struct virtio_vsock_pkt *pkt;
                        struct scatterlist hdr, buf, *sgs[2];
                        int ret, in_sg = 0, out_sg = 0;
                        bool reply;

                        ...
                        pkt = list_first_entry(&vsock->send_pkt_list,
                                        struct virtio_vsock_pkt, list);
                        list_del_init(&pkt->list);
                        spin_unlock_bh(&vsock->send_pkt_list_lock);

                        virtio_transport_deliver_tap_pkt(pkt);

                        reply = pkt->reply;

                        sg_init_one(&hdr, &pkt->hdr, sizeof(pkt->hdr));
                        sgs[out_sg++] = &hdr;
                        if (pkt->buf) {
                                sg_init_one(&buf, pkt->buf, pkt->len);
                                sgs[out_sg++] = &buf;
                        }

                        ret = virtqueue_add_sgs(vq, sgs, out_sg, in_sg, pkt, GFP_KERNEL);
                        /* Usually this means that there is no more space available in
                        * the vq
                        */
                        ...

                        added = true;
                }

                if (added)
                        virtqueue_kick(vq);

        ...
        }

<h4> host recv </h4>

The host side's handle for the tx queue kick is 'vhost_vsock_handle_tx_kick', this is initialized in 'vhost_vsock_dev_open' function.

'vhost_vsock_handle_tx_kick' also perform the virtio backedn standard operation, pop the vring desc and calls 'vhost_vsock_alloc_pkt' to reconstruct a 'virtio_vsock_pkt', then calls 'virtio_transport_recv_pkt' to delivery the packet to destination.


        static void vhost_vsock_handle_tx_kick(struct vhost_work *work)
        {
                struct vhost_virtqueue *vq = container_of(work, struct vhost_virtqueue,
                                                        poll.work);
                struct vhost_vsock *vsock = container_of(vq->dev, struct vhost_vsock,
                                                        dev);
                struct virtio_vsock_pkt *pkt;
                int head, pkts = 0, total_len = 0;
                unsigned int out, in;
                bool added = false;

                mutex_lock(&vq->mutex);
                ...
                vhost_disable_notify(&vsock->dev, vq);
                do {
                        u32 len;
                        ...
                        head = vhost_get_vq_desc(vq, vq->iov, ARRAY_SIZE(vq->iov),
                                                &out, &in, NULL, NULL);
                        ...
                        pkt = vhost_vsock_alloc_pkt(vq, out, in);
                        ...

                        len = pkt->len;

                        /* Deliver to monitoring devices all received packets */
                        virtio_transport_deliver_tap_pkt(pkt);

                        /* Only accept correctly addressed packets */
                        if (le64_to_cpu(pkt->hdr.src_cid) == vsock->guest_cid)
                                virtio_transport_recv_pkt(pkt);
                        else
                                virtio_transport_free_pkt(pkt);

                        len += sizeof(pkt->hdr);
                        vhost_add_used(vq, head, len);
                        total_len += len;
                        added = true;
                } while(likely(!vhost_exceeds_weight(vq, ++pkts, total_len)));
                ...
        }


'virtio_transport_recv_pkt' is the actually function to delivery the msg data. It calls 'vsock_find_connected_socket' to find the destination remote socket then according to the dest socket state calls specific function. For 'TCP_ESTABLISHED' it calls 'virtio_transport_recv_connected'.


        void virtio_transport_recv_pkt(struct virtio_vsock_pkt *pkt)
        {
                struct sockaddr_vm src, dst;
                struct vsock_sock *vsk;
                struct sock *sk;
                bool space_available;

                vsock_addr_init(&src, le64_to_cpu(pkt->hdr.src_cid),
                                le32_to_cpu(pkt->hdr.src_port));
                vsock_addr_init(&dst, le64_to_cpu(pkt->hdr.dst_cid),
                                le32_to_cpu(pkt->hdr.dst_port));
                ...

                /* The socket must be in connected or bound table
                * otherwise send reset back
                */
                sk = vsock_find_connected_socket(&src, &dst);
                ...
                vsk = vsock_sk(sk);

                ...
                switch (sk->sk_state) {
                case TCP_LISTEN:
                        virtio_transport_recv_listen(sk, pkt);
                        virtio_transport_free_pkt(pkt);
                        break;
                case TCP_SYN_SENT:
                        virtio_transport_recv_connecting(sk, pkt);
                        virtio_transport_free_pkt(pkt);
                        break;
                case TCP_ESTABLISHED:
                        virtio_transport_recv_connected(sk, pkt);
                        break;
                case TCP_CLOSING:
                        virtio_transport_recv_disconnecting(sk, pkt);
                        virtio_transport_free_pkt(pkt);
                        break;
                default:
                        virtio_transport_free_pkt(pkt);
                        break;
                }
                release_sock(sk);

                /* Release refcnt obtained when we fetched this socket out of the
                * bound or connected list.
                */
                sock_put(sk);
                return;

        free_pkt:
                virtio_transport_free_pkt(pkt);
        }

For the send data the 'pkt->hdr.op' is 'VIRTIO_VSOCK_OP_RW' so 'virtio_transport_recv_enqueue' will be called. 'virtio_transport_recv_enqueue' adds the packet to the destination's socket's queue 'rx_queue'.

So when the host/othere VM calls recv, the 'vsock_stream_recvmsg' will be called and the transport layer's 'stream_dequeue' callback(virtio_transport_stream_do_dequeue) will be called. virtio_transport_stream_do_dequeue will pop the entry from 'rx_queue' and store it to msghdr and return to the userspace application. 

        static ssize_t
        virtio_transport_stream_do_dequeue(struct vsock_sock *vsk,
                                        struct msghdr *msg,
                                        size_t len)
        {
                struct virtio_vsock_sock *vvs = vsk->trans;
                struct virtio_vsock_pkt *pkt;
                size_t bytes, total = 0;
                u32 free_space;
                int err = -EFAULT;

                spin_lock_bh(&vvs->rx_lock);
                while (total < len && !list_empty(&vvs->rx_queue)) {
                        pkt = list_first_entry(&vvs->rx_queue,
                                        struct virtio_vsock_pkt, list);

                        bytes = len - total;
                        if (bytes > pkt->len - pkt->off)
                                bytes = pkt->len - pkt->off;

                        /* sk_lock is held by caller so no one else can dequeue.
                        * Unlock rx_lock since memcpy_to_msg() may sleep.
                        */
                        spin_unlock_bh(&vvs->rx_lock);

                        err = memcpy_to_msg(msg, pkt->buf + pkt->off, bytes);
                        if (err)
                                goto out;

                        spin_lock_bh(&vvs->rx_lock);

                        total += bytes;
                        pkt->off += bytes;
                        if (pkt->off == pkt->len) {
                                virtio_transport_dec_rx_pkt(vvs, pkt);
                                list_del(&pkt->list);
                                virtio_transport_free_pkt(pkt);
                        }
                }

                ...
                return total;

        ...
        }

<h3> multi-transport </h3>

From above as we can see one kernel(both host/guest) can only register one transport. This is problematic in nested virtualization environment. For example the host with L0 VMware VM and in it there is a L1 qemu/kvm VM. The L0 VM can only register one transport, if it register the 'vmci' transport it can just talk to the VMware vmci device. If it register the 'vhost_vsock' it can just talk to the L1 VM.
Fortunately Stefano Garzarella has addressed this issue in commit [vsock: add multi-transports support
](https://github.com/torvalds/linux/commit/c0cfa2d8a788fcf45df5bf4070ab2474c88d543a). Who interested this can learn more.


<h3> Reference </h3>

1. [virtio-vsock Zero-configuration host/guest communication](https://vmsplice.net/~stefan/stefanha-kvm-forum-2015.pdf), Stefan Hajnoczi, KVM froum 2015
2. [VSOCK: VM↔host socket with minimal configuration](https://static.sched.com/hosted_files/devconfcz2020a/b1/DevConf.CZ_2020_vsock_v1.1.pdf), Stefano Garzarella, DevConf.CZ 2020
3. [AF_VSOCK: nested VMs and loopback support available](https://stefano-garzarella.github.io/posts/2020-02-20-vsock-nested-vms-loopback/)







