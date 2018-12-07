---
layout: post
title: "make QEMU VM escape great again"
description: "qemu vulnerability"
category: 技术
tags: [QEMU]
---
{% include JB/setup %}



The QEMU 3.1 introduced a very serious security issue in 
SMBus implementation.

The corresponding commit is following:

[i2c: pm_smbus: Add block transfer capability](https://git.qemu.org/?p=qemu.git;a=commitdiff;h=38ad4fae43b9c57a4ef3111217b110b25dbd3c50;hp=00bdfeab1584e68bad76034e4ffc33595533fe7d)


And the fix is in [i2c: pm_smbus: check smb_index before block transfer write](https://git.qemu.org/?p=qemu.git;a=commit;h=f2609ffdf39bcd4f89b5f67b33347490023a7a84)

The issue is the processing of SMBHSTSTS command in smb_ioport_writeb() function.

Here we see the s->smb_index is increased without bounding check. 
The read is from 's->smb_addr' and can be controlled by SMBHSTADD command. So it is easy
to bypass the if (!read...). As the 's->smb_index' is a 'uint_32', this means we can add it 
to 0xffffffff theoretically. This 's->smb_index' is used to index the memory in 's->smb_data'.

    case SMBHSTSTS:
        s->smb_stat &= ~(val & ~STS_HOST_BUSY);
        if (!s->op_done && !(s->smb_auxctl & AUX_BLK)) {
            uint8_t read = s->smb_addr & 0x01;

            s->smb_index++;
            if (!read && s->smb_index == s->smb_data0) {
                uint8_t prot = (s->smb_ctl >> 2) & 0x07;
                uint8_t cmd = s->smb_cmd;
                uint8_t addr = s->smb_addr >> 1;
                int ret;

                if (prot == PROT_I2C_BLOCK_READ) {
                    s->smb_stat |= STS_DEV_ERR;
                    goto out;
                }

                ret = smbus_write_block(s->smbus, addr, cmd, s->smb_data,
                                        s->smb_data0, !s->i2c_enable);
                if (ret < 0) {
                    s->smb_stat |= STS_DEV_ERR;
                    goto out;
                }
                s->op_done = true;
                s->smb_stat |= STS_INTR;
                s->smb_stat &= ~STS_HOST_BUSY;
            } else if (!read) {
                s->smb_data[s->smb_index] = s->smb_blkdata;
                s->smb_stat |= STS_BYTE_DONE;
            } else if (s->smb_ctl & CTL_LAST_BYTE) {
                s->op_done = true;
                s->smb_blkdata = s->smb_data[s->smb_index];
                s->smb_index = 0;
                s->smb_stat |= STS_INTR;
                s->smb_stat &= ~STS_HOST_BUSY;
            } else {
                s->smb_blkdata = s->smb_data[s->smb_index];
                s->smb_stat |= STS_BYTE_DONE;
            }
        }
        break;

Look at this code snippet more, there are three 'else' after the 's->smb_index' increased. 
The next important data appears 's->smb_blkdata'. This data can be assign by write and write 
using 'SMBBLKDAT' command. In the first 'else' we can assign 's->smb_data[s->smb_index]' with 's->smb_blkdata', this means we can write arbitrary bytes out of 's->smb_data' array. 
In the second and last 'else', the 's->smb_data[s->smb_index]' is assigned to 's->smb_blkdata',
this means we can read bytes out of 's->smb_data' array.

So we can read/write a lot of (4G theoretically) memory after 's->smb_data' array. This gives us 
a lot of power and room to make exploit.

Following is the demo of VM escape.

![](/assets/img/qemues/1.jpg)