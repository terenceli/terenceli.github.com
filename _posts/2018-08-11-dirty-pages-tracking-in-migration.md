---
layout: post
title: "qemu/kvm dirty pages tracking in migration"
description: "dirty page tracking"
category: 技术
tags: [qemu]
---
{% include JB/setup %}

The live migration's most work is to migrate the RAM of guest from src host to dest host.
So the qemu need to track the dirty pages of guest to transfer them to the dest host.
This article discusses how qemu do the tracking work.

In a summary, the following steps show the overview of dirty tracking:

1. qemu allocs a bitmap and set its all bits to 1(mean dirty)
2. qemu calls kvm to set memory slots with 'KVM_MEM_LOG_DIRTY_PAGES' flags
3. qemu calls kvm to get the kvm dirty bitmap
4. qemu kvm wrapper: walk the dirty bitmap(from kvm) and fill the dirty bitmap(ram_list)
5. migration code: walk the ram\_list dirty bitmap and set the qemu dirty page bitmap




<h3> qemu and kvm create bitmap </h3>

In the ram migration setup function, it allocates the qemu bitmap in function 'ram\_save\_init\_globals'.

    {
        ...
        qemu_mutex_lock_iothread();

        qemu_mutex_lock_ramlist();
        rcu_read_lock();
        bytes_transferred = 0;
        reset_ram_globals();

        ram_bitmap_pages = last_ram_offset() >> TARGET_PAGE_BITS;
        migration_bitmap_rcu = g_new0(struct BitmapRcu, 1);
        migration_bitmap_rcu->bmap = bitmap_new(ram_bitmap_pages);
        bitmap_set(migration_bitmap_rcu->bmap, 0, ram_bitmap_pages);

        ...

        /*
        * Count the total number of pages used by ram blocks not including any
        * gaps due to alignment or unplugs.
        */
        migration_dirty_pages = ram_bytes_total() >> TARGET_PAGE_BITS;

        memory_global_dirty_log_start();
        migration_bitmap_sync();
        qemu_mutex_unlock_ramlist();
        qemu_mutex_unlock_iothread();
        rcu_read_unlock();

        return 0;
    }

As we can see 'migration\_bitmap\_rcu' is the bitmap for qemu maintains.

Then it calls 'memory\_global\_dirty\_log\_start':

    void memory_global_dirty_log_start(void)
    {
        global_dirty_log = true;

        MEMORY_LISTENER_CALL_GLOBAL(log_global_start, Forward);

        /* Refresh DIRTY_LOG_MIGRATION bit.  */
        memory_region_transaction_begin();
        memory_region_update_pending = true;
        memory_region_transaction_commit();
    }

This set 'global\_dirty\_log' to true and commit the memory change to kvm (for update).

It then calls 'address\_space\_update\_topology\_pass' and will call the 'log\_start' for every MemoryRegionSection.

            if (adding) {
                MEMORY_LISTENER_UPDATE_REGION(frnew, as, Forward, region_nop);
                if (frnew->dirty_log_mask & ~frold->dirty_log_mask) {
                    MEMORY_LISTENER_UPDATE_REGION(frnew, as, Forward, log_start,
                                                  frold->dirty_log_mask,
                                                  frnew->dirty_log_mask);
                }

For kvm it is 'kvm\_log\_start'. We can see in 'kvm\_mem\_flags' it adds the 'KVM\_MEM\_LOG\_DIRTY\_PAGES' flags.

    static int kvm_mem_flags(MemoryRegion *mr)
    {
        bool readonly = mr->readonly || memory_region_is_romd(mr);
        int flags = 0;

        if (memory_region_get_dirty_log_mask(mr) != 0) {
            flags |= KVM_MEM_LOG_DIRTY_PAGES;
        }
        if (readonly && kvm_readonly_mem_allowed) {
            flags |= KVM_MEM_READONLY;
        }
        return flags;
    }


Following stack backtrack shows the callchains.

    (gdb) bt
    #0  kvm_set_user_memory_region (kml=0x55ab8fc502c0, slot=0x55ab8fc50500) at /home/liqiang02/qemu0711/qemu-2.8/kvm-all.c:236
    #1  0x000055ab8df10a92 in kvm_slot_update_flags (kml=0x55ab8fc502c0, mem=0x55ab8fc50500, mr=0x55ab8fd36f70)
        at /home/liqiang02/qemu0711/qemu-2.8/kvm-all.c:376
    #2  0x000055ab8df10b1f in kvm_section_update_flags (kml=0x55ab8fc502c0, section=0x7f0ab37fb4c0)
        at /home/liqiang02/qemu0711/qemu-2.8/kvm-all.c:389
    #3  0x000055ab8df10b65 in kvm_log_start (listener=0x55ab8fc502c0, section=0x7f0ab37fb4c0, old=0, new=4)
        at /home/liqiang02/qemu0711/qemu-2.8/kvm-all.c:404
    #4  0x000055ab8df18b33 in address_space_update_topology_pass (as=0x55ab8ea21880 <address_space_memory>, old_view=0x7f0cc4118ca0, 
        new_view=0x7f0aa804d380, adding=true) at /home/liqiang02/qemu0711/qemu-2.8/memory.c:854
    #5  0x000055ab8df18d9b in address_space_update_topology (as=0x55ab8ea21880 <address_space_memory>)
        at /home/liqiang02/qemu0711/qemu-2.8/memory.c:886
    #6  0x000055ab8df18ed6 in memory_region_transaction_commit () at /home/liqiang02/qemu0711/qemu-2.8/memory.c:926
    #7  0x000055ab8df1c9ef in memory_global_dirty_log_start () at /home/liqiang02/qemu0711/qemu-2.8/memory.c:2276
    #8  0x000055ab8df30ce6 in ram_save_init_globals () at /home/liqiang02/qemu0711/qemu-2.8/migration/ram.c:1939
    #9  0x000055ab8df30d36 in ram_save_setup (f=0x55ab90d874c0, opaque=0x0) at /home/liqiang02/qemu0711/qemu-2.8/migration/ram.c:1960
    #10 0x000055ab8df3609a in qemu_savevm_state_begin (f=0x55ab90d874c0, params=0x55ab8ea0178c <current_migration+204>)
        at /home/liqiang02/qemu0711/qemu-2.8/migration/savevm.c:956
    #11 0x000055ab8e25d9b8 in migration_thread (opaque=0x55ab8ea016c0 <current_migration>) at migration/migration.c:1829
    #12 0x00007f0cda1fd494 in start_thread () from /lib/x86_64-linux-gnu/libpthread.so.0
    #13 0x00007f0cd9f3facf in clone () from /lib/x86_64-linux-gnu/libc.so.6

Here we know the memory topology doesn't change but only adds the 'KVM\_MEM\_LOG\_DIRTY\_PAGES'.

Now let's go to the kvm part, as we can see the qemu sends 'KVM\_SET\_USER\_MEMORY\_REGION' ioctl
and the kernel will go to '\_\_kvm\_set\_memory\_region'

    int __kvm_set_memory_region(struct kvm *kvm,
                    const struct kvm_userspace_memory_region *mem)
    {

        if (npages) {
            if (!old.npages)
                change = KVM_MR_CREATE;
            else { /* Modify an existing slot. */
                if ((mem->userspace_addr != old.userspace_addr) ||
                    (npages != old.npages) ||
                    ((new.flags ^ old.flags) & KVM_MEM_READONLY))
                    goto out;

                if (base_gfn != old.base_gfn)
                    change = KVM_MR_MOVE;
                else if (new.flags != old.flags)
                    change = KVM_MR_FLAGS_ONLY;
                else { /* Nothing to change. */
                    r = 0;
                    goto out;
                }
            }
    ...

        /* Allocate page dirty bitmap if needed */
        if ((new.flags & KVM_MEM_LOG_DIRTY_PAGES) && !new.dirty_bitmap) {
            if (kvm_create_dirty_bitmap(&new) < 0)
                goto out_free;
        }
    ...
    }

The most important work here is to call 'kvm\_create\_dirty\_bitmap' to allocate a bitmap.
for every memslot it will allocate memslot->dirty\_bitmap in this function.
    /*
    * Allocation size is twice as large as the actual dirty bitmap size.
    * See x86's kvm_vm_ioctl_get_dirty_log() why this is needed.
    */
    static int kvm_create_dirty_bitmap(struct kvm_memory_slot *memslot)
    {
        unsigned long dirty_bytes = 2 * kvm_dirty_bitmap_bytes(memslot);

        memslot->dirty_bitmap = kvm_kvzalloc(dirty_bytes);
        if (!memslot->dirty_bitmap)
            return -ENOMEM;

        return 0;
    }

Then goes to 'kvm\_arch\_commit\_memory\_region' and 'kvm\_mmu\_slot\_remove\_write\_access'.
Notice, this is not the newest implementation but an old kernel (3.13).

    void kvm_mmu_slot_remove_write_access(struct kvm *kvm, int slot)
    {
        struct kvm_memory_slot *memslot;
        gfn_t last_gfn;
        int i;

        memslot = id_to_memslot(kvm->memslots, slot);
        last_gfn = memslot->base_gfn + memslot->npages - 1;

        spin_lock(&kvm->mmu_lock);

        for (i = PT_PAGE_TABLE_LEVEL;
            i < PT_PAGE_TABLE_LEVEL + KVM_NR_PAGE_SIZES; ++i) {
            unsigned long *rmapp;
            unsigned long last_index, index;

            rmapp = memslot->arch.rmap[i - PT_PAGE_TABLE_LEVEL];
            last_index = gfn_to_index(last_gfn, memslot->base_gfn, i);

            for (index = 0; index <= last_index; ++index, ++rmapp) {
                if (*rmapp)
                    __rmap_write_protect(kvm, rmapp, false);

                if (need_resched() || spin_needbreak(&kvm->mmu_lock)) {
                    kvm_flush_remote_tlbs(kvm);
                    cond_resched_lock(&kvm->mmu_lock);
                }
            }
        }

        kvm_flush_remote_tlbs(kvm);
        spin_unlock(&kvm->mmu_lock);
    }

As the function name implies, it remove write access of this memory slot.

Here we just focus the normal 4k page, not 2M and 1G page. The 'memslot->arch.rmp' is a gfn->spte map, say given a gfn we can find the correspoding spte. 

    static bool __rmap_write_protect(struct kvm *kvm, unsigned long *rmapp,
                    bool pt_protect)
    {
        u64 *sptep;
        struct rmap_iterator iter;
        bool flush = false;

        for (sptep = rmap_get_first(*rmapp, &iter); sptep;) {
            BUG_ON(!(*sptep & PT_PRESENT_MASK));
            if (spte_write_protect(kvm, sptep, &flush, pt_protect)) {
                sptep = rmap_get_first(*rmapp, &iter);
                continue;
            }

            sptep = rmap_get_next(&iter);
        }

        return flush;
    }

    static bool
    spte_write_protect(struct kvm *kvm, u64 *sptep, bool *flush, bool pt_protect)
    {
        u64 spte = *sptep;

        if (!is_writable_pte(spte) &&
            !(pt_protect && spte_is_locklessly_modifiable(spte)))
            return false;

        rmap_printk("rmap_write_protect: spte %p %llx\n", sptep, *sptep);

        if (__drop_large_spte(kvm, sptep)) {
            *flush |= true;
            return true;
        }

        if (pt_protect)
            spte &= ~SPTE_MMU_WRITEABLE;
        spte = spte & ~PT_WRITABLE_MASK;

        *flush |= mmu_spte_update(sptep, spte);
        return false;
    }

So here for every gfn, we remove the write access. After return from this ioctl, the guest's RAM
has been marked no write access, every write to this will exit to KVM make the page dirty. This means 'start the dirty log'.

When the guest write the memory, it will trigger the ept violation vmexit. Then calls 'tdp\_page\_fault'.
Because this is caused by write protection, the CPU will set the error code to 'PFERR\_WRITE\_MASK' so the 'fast\_page\_fault'
and 'fast\_pf\_fix\_direct\_spte' will be called. 


    static bool
    fast_pf_fix_direct_spte(struct kvm_vcpu *vcpu, u64 *sptep, u64 spte)
    {
        struct kvm_mmu_page *sp = page_header(__pa(sptep));
        gfn_t gfn;

        WARN_ON(!sp->role.direct);

        /*
        * The gfn of direct spte is stable since it is calculated
        * by sp->gfn.
        */
        gfn = kvm_mmu_page_get_gfn(sp, sptep - sp->spt);

        if (cmpxchg64(sptep, spte, spte | PT_WRITABLE_MASK) == spte)
            mark_page_dirty(vcpu->kvm, gfn);

        return true;
    }

    void mark_page_dirty(struct kvm *kvm, gfn_t gfn)
    {
        struct kvm_memory_slot *memslot;

        memslot = gfn_to_memslot(kvm, gfn);
        mark_page_dirty_in_slot(kvm, memslot, gfn);
    }

    void mark_page_dirty_in_slot(struct kvm *kvm, struct kvm_memory_slot *memslot,
                    gfn_t gfn)
    {
        if (memslot && memslot->dirty_bitmap) {
            unsigned long rel_gfn = gfn - memslot->base_gfn;

            set_bit_le(rel_gfn, memslot->dirty_bitmap);
        }
    }

Here we can see, it will set the spte writeable again and set the dirty bitmap.



<h3> qemu sync dirty log with kvm </h3>

Let's go back to 'ram_\save\_init\_globals' after telling the kvm to begin start dirty log, it calls 'migration\_bitmap\_sync'.
This function calls 'memory\_global\_dirty\_log\_sync' to get the dirty map from kvm. 'kvm\_log\_sync' is used to do this.

    static void kvm_log_sync(MemoryListener *listener,
                            MemoryRegionSection *section)
    {
        KVMMemoryListener *kml = container_of(listener, KVMMemoryListener, listener);
        int r;

        r = kvm_physical_sync_dirty_bitmap(kml, section);
        if (r < 0) {
            abort();
        }
    }

    static int kvm_physical_sync_dirty_bitmap(KVMMemoryListener *kml,
                                            MemoryRegionSection *section)
    {
        KVMState *s = kvm_state;
        unsigned long size, allocated_size = 0;
        struct kvm_dirty_log d = {};
        KVMSlot *mem;
        int ret = 0;
        hwaddr start_addr = section->offset_within_address_space;
        hwaddr end_addr = start_addr + int128_get64(section->size);

        d.dirty_bitmap = NULL;
        while (start_addr < end_addr) {
            mem = kvm_lookup_overlapping_slot(kml, start_addr, end_addr);
            if (mem == NULL) {
                break;
            }

            ...
            size = ALIGN(((mem->memory_size) >> TARGET_PAGE_BITS),
                        /*HOST_LONG_BITS*/ 64) / 8;
            if (!d.dirty_bitmap) {
                d.dirty_bitmap = g_malloc(size);
            } else if (size > allocated_size) {
                d.dirty_bitmap = g_realloc(d.dirty_bitmap, size);
            }
            allocated_size = size;
            memset(d.dirty_bitmap, 0, allocated_size);

            d.slot = mem->slot | (kml->as_id << 16);
            if (kvm_vm_ioctl(s, KVM_GET_DIRTY_LOG, &d) == -1) {
                DPRINTF("ioctl failed %d\n", errno);
                ret = -1;
                break;
            }

            kvm_get_dirty_pages_log_range(section, d.dirty_bitmap);
            start_addr = mem->start_addr + mem->memory_size;
        }
        g_free(d.dirty_bitmap);

        return ret;
    }

Here we can see the qemu sends out a 'KVM\_GET\_DIRTY\_LOG' ioctl. In kvm 

    int kvm_vm_ioctl_get_dirty_log(struct kvm *kvm, struct kvm_dirty_log *log)
    {
        int r;
        struct kvm_memory_slot *memslot;
        unsigned long n, i;
        unsigned long *dirty_bitmap;
        unsigned long *dirty_bitmap_buffer;
        bool is_dirty = false;

        mutex_lock(&kvm->slots_lock);

        r = -EINVAL;
        if (log->slot >= KVM_USER_MEM_SLOTS)
            goto out;

        memslot = id_to_memslot(kvm->memslots, log->slot);

        dirty_bitmap = memslot->dirty_bitmap;
        r = -ENOENT;
        if (!dirty_bitmap)
            goto out;

        n = kvm_dirty_bitmap_bytes(memslot);

        dirty_bitmap_buffer = dirty_bitmap + n / sizeof(long);
        memset(dirty_bitmap_buffer, 0, n);

        spin_lock(&kvm->mmu_lock);

        for (i = 0; i < n / sizeof(long); i++) {
            unsigned long mask;
            gfn_t offset;

            if (!dirty_bitmap[i])
                continue;

            is_dirty = true;

            mask = xchg(&dirty_bitmap[i], 0);
            dirty_bitmap_buffer[i] = mask;

            offset = i * BITS_PER_LONG;
            kvm_mmu_write_protect_pt_masked(kvm, memslot, offset, mask);
        }
        if (is_dirty)
            kvm_flush_remote_tlbs(kvm);

        spin_unlock(&kvm->mmu_lock);

        r = -EFAULT;
        if (copy_to_user(log->dirty_bitmap, dirty_bitmap_buffer, n))
            goto out;

        r = 0;
    out:
        mutex_unlock(&kvm->slots_lock);
        return r;
    }

It copys the dirty bitmap to userspace and also set the spte to write protection using 'kvm\_mmu\_write\_protect\_pt\_masked'.

    void kvm_mmu_write_protect_pt_masked(struct kvm *kvm,
                        struct kvm_memory_slot *slot,
                        gfn_t gfn_offset, unsigned long mask)
    {
        unsigned long *rmapp;

        while (mask) {
            rmapp = __gfn_to_rmap(slot->base_gfn + gfn_offset + __ffs(mask),
                        PT_PAGE_TABLE_LEVEL, slot);
            __rmap_write_protect(kvm, rmapp, false);

            /* clear the first set bit */
            mask &= mask - 1;
        }
    }

So next time, the guest write to this pfn page, it will mark as a dirty page again.

kvm\_get\_dirty\_pages\_log\_range-->cpu\_physical\_memory\_set\_dirty\_lebitmap.

In the later function, it sets 'ram\_list.dirty\_memory[i])->blocks' dirty bitmap.
This dirty bitmap lays in 'ram\_list', not with the migration.

<h3> qemu copy dirty bitmap to migration bitmap </h3>

In 'migration\_bitmap\_sync' after the call of 'memory\_global\_dirty\_log\_sync', 
'migration\_bitmap\_sync\_range' will be called for every block. This calls copy 'ram\_list's
dirty bitmap to 'migration\_bitmap\_rcu->bmap'.


    static void migration_bitmap_sync_range(ram_addr_t start, ram_addr_t length)
    {
        unsigned long *bitmap;
        bitmap = atomic_rcu_read(&migration_bitmap_rcu)->bmap;
        migration_dirty_pages +=
            cpu_physical_memory_sync_dirty_bitmap(bitmap, start, length);
    }


    static inline
    uint64_t cpu_physical_memory_sync_dirty_bitmap(unsigned long *dest,
                                                ram_addr_t start,
                                                ram_addr_t length)
    {
        ram_addr_t addr;
        unsigned long page = BIT_WORD(start >> TARGET_PAGE_BITS);
        uint64_t num_dirty = 0;

        /* start address is aligned at the start of a word? */
        if (((page * BITS_PER_LONG) << TARGET_PAGE_BITS) == start) {
           ...
            src = atomic_rcu_read(
                    &ram_list.dirty_memory[DIRTY_MEMORY_MIGRATION])->blocks;

            for (k = page; k < page + nr; k++) {
                if (src[idx][offset]) {
                    unsigned long bits = atomic_xchg(&src[idx][offset], 0);
                    unsigned long new_dirty;
                    new_dirty = ~dest[k];
                    dest[k] |= bits;
                    new_dirty &= bits;
                    num_dirty += ctpopl(new_dirty);
                }
       ...

        return num_dirty;
    }


Now, the 'migration\_bitmap\_rcu->bmap' know all the dirty pages. Of course it is not very useful for
the setup process, as qemu already set all of 'migration\_bitmap\_rcu->bmap' to 1.

<h3> find the dirty pages and send out </h3>

After the setup, we go to the most important process, iterate send pages to the dest and after a water mark 
reached, stop the machine and send the other all dirty pages to dest. The overview can short as following.

    while (s->state == MIGRATION_STATUS_ACTIVE ||
            s->state == MIGRATION_STATUS_POSTCOPY_ACTIVE) {
            ...

            if (!qemu_file_rate_limit(s->to_dst_file)) {
                uint64_t pend_post, pend_nonpost;

                qemu_savevm_state_pending(s->to_dst_file, max_size, &pend_nonpost,
                                        &pend_post);
                ...
                if (pending_size && pending_size >= max_size) {
                    /* Still a significant amount to transfer */

                    if (migrate_postcopy_ram() &&
                        s->state != MIGRATION_STATUS_POSTCOPY_ACTIVE &&
                        pend_nonpost <= max_size &&
                        atomic_read(&s->start_postcopy)) {

                        if (!postcopy_start(s, &old_vm_running)) {
                            current_active_state = MIGRATION_STATUS_POSTCOPY_ACTIVE;
                            entered_postcopy = true;
                        }

                        continue;
                    }
                    /* Just another iteration step */
                    qemu_savevm_state_iterate(s->to_dst_file, entered_postcopy);
                } else {
                    trace_migration_thread_low_pending(pending_size);
                    migration_completion(s, current_active_state,
                                        &old_vm_running, &start_time);
                    break;
                }
            }
        }

Here show the three most important function. 'qemu\_savevm\_state\_pending', 'qemu\_savevm\_state\_iterate' and
'migration\_completion'. For ram, the save pending function is 'ram\_save\_pending'.

    static void ram_save_pending(QEMUFile *f, void *opaque, uint64_t max_size,
                                uint64_t *non_postcopiable_pending,
                                uint64_t *postcopiable_pending)
    {
        uint64_t remaining_size;

        remaining_size = ram_save_remaining() * TARGET_PAGE_SIZE;

        if (!migration_in_postcopy(migrate_get_current()) &&
            remaining_size < max_size) {
            qemu_mutex_lock_iothread();
            rcu_read_lock();
            migration_bitmap_sync();
            rcu_read_unlock();
            qemu_mutex_unlock_iothread();
            remaining_size = ram_save_remaining() * TARGET_PAGE_SIZE;
        }

        /* We can do postcopy, and all the data is postcopiable */
        *postcopiable_pending += remaining_size;
    }


This function calls 'migration\_bitmap\_sync' to get the dirty page bitmap in 'migration\_bitmap\_rcu->bmap'.
In the iterate function 'ram\_save\_iterate' it calls 'ram\_find\_and\_save\_block' to find the dirty page and
then send out to the dest host.

    static int ram_save_iterate(QEMUFile *f, void *opaque)
    {
        int ret;
        int i;
        int64_t t0;
        int done = 0;

        rcu_read_lock();
        if (ram_list.version != last_version) {
            reset_ram_globals();
        }

        /* Read version before ram_list.blocks */
        smp_rmb();

        ram_control_before_iterate(f, RAM_CONTROL_ROUND);

        t0 = qemu_clock_get_ns(QEMU_CLOCK_REALTIME);
        i = 0;
        while ((ret = qemu_file_rate_limit(f)) == 0) {
            int pages;

            pages = ram_find_and_save_block(f, false, &bytes_transferred);
            /* no more pages to sent */
            if (pages == 0) {
                done = 1;
                break;
            }
            acct_info.iterations++;

            /* we want to check in the 1st loop, just in case it was the 1st time
            and we had to sync the dirty bitmap.
            qemu_get_clock_ns() is a bit expensive, so we only check each some
            iterations
            */
            if ((i & 63) == 0) {
                uint64_t t1 = (qemu_clock_get_ns(QEMU_CLOCK_REALTIME) - t0) / 1000000;
                if (t1 > MAX_WAIT) {
                    DPRINTF("big wait: %" PRIu64 " milliseconds, %d iterations\n",
                            t1, i);
                    break;
                }
            }
            i++;
        }
       ...

        return done;
    }

'ram\_find\_and\_save\_block-->get\_queued\_page':

    static bool get_queued_page(MigrationState *ms, PageSearchStatus *pss,
                                ram_addr_t *ram_addr_abs)
    {
        RAMBlock  *block;
        ram_addr_t offset;
        bool dirty;

        do {
            block = unqueue_page(ms, &offset, ram_addr_abs);
            /*
            * We're sending this page, and since it's postcopy nothing else
            * will dirty it, and we must make sure it doesn't get sent again
            * even if this queue request was received after the background
            * search already sent it.
            */
            if (block) {
                unsigned long *bitmap;
                bitmap = atomic_rcu_read(&migration_bitmap_rcu)->bmap;
                dirty = test_bit(*ram_addr_abs >> TARGET_PAGE_BITS, bitmap);
                if (!dirty) {
                    trace_get_queued_page_not_dirty(
                        block->idstr, (uint64_t)offset,
                        (uint64_t)*ram_addr_abs,
                        test_bit(*ram_addr_abs >> TARGET_PAGE_BITS,
                            atomic_rcu_read(&migration_bitmap_rcu)->unsentmap));
                } else {
                    trace_get_queued_page(block->idstr,
                                        (uint64_t)offset,
                                        (uint64_t)*ram_addr_abs);
                }
            }

        } while (block && !dirty);

        if (block) {
            /*
            * As soon as we start servicing pages out of order, then we have
            * to kill the bulk stage, since the bulk stage assumes
            * in (migration_bitmap_find_and_reset_dirty) that every page is
            * dirty, that's no longer true.
            */
            ram_bulk_stage = false;

            /*
            * We want the background search to continue from the queued page
            * since the guest is likely to want other pages near to the page
            * it just requested.
            */
            pss->block = block;
            pss->offset = offset;
        }

        return !!block;
    }

In this function we find the dirty page in bitmap.


The following shows the process of dirty bitmap tracking. 

    +-------------+          +----------+       +--------------+          +---------------------+
    |             |          | ram_list +-----> | dirty_memory +--------> | migration_bitmap_rcu|
    |             |          +----------+       +------+-------+          +---------------------+
    | Guest       |                                    ^
    |             |                                    |
    |             |                                    |
    |             |                                    |
    |             +--------------------------------+   |
    |             |                                |   |
    |             |                                |   |
    |             |                                |   |
    |             |                                v   |
    |             |                                    |
    |             |          +---------+       +-------+--------+
    |             |          | memslot +-----> | dirty_bitmap   |
    +-------------+          +---------+       +----------------+
