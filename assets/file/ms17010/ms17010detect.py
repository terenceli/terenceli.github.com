#!/usr/bin/env python
# coding:utf8
# cmd example: ms17-10.py 192.168.1.1/24
import sys,socket, Queue, ipaddress, re
from threading import Thread
from threading import Lock
import threadpool
import time
import argparse

g_mutex = Lock()
g_log = Lock()
timetag = time.strftime("%Y_%m_%d_%X", time.localtime())
timetag = timetag.replace(":","_")
global logname
global timeout
global thread
global g_logfd

def multiprint(str):
    g_mutex.acquire()
    print str
    g_mutex.release()

def write_log(string):
    global g_logfd
    g_log.acquire()
    g_logfd.write(string+"\n")
    g_logfd.flush()
    g_log.release()


def scan_ip(host2,port2=445):
    #multiprint("scan " + host2)
    connected = False
    try:
        client = socket.socket( socket.AF_INET, socket.SOCK_STREAM )
        #multiprint(client.fileno())
        client.settimeout(timeout)
        client.connect((host2,port2))
        connected = True
        msg = "00000054ff534d427200000000180128000000000000000000000000000087110000b372003100024c414e4d414e312e3000024c4d312e325830303200024e54204c414e4d414e20312e3000024e54204c4d20302e313200"
        msg = msg.decode('hex')
        client.send(msg)
        client.recv(2048)


        msg = "0000008fff534d427300000000180128000000000000000000000000000087110000b3720cff000000dfff0200010000000000310000000000d400008054004e544c4d5353500001000000050208a2010001002000000010001000210000002e4a5634615a4e674652584d614b57686c57696e646f7773203230303020323139350057696e646f7773203230303020352e3000"
        msg = msg.decode('hex')
        client.send(msg)
        ret = client.recv(2048)
        ret = ret.encode('hex')
        userid = ret[64:68]
        #print userid
        msg = "000001a0ff534d42730000000018012800000000000000000000000000008711" +userid + "b3720cff000000dfff02000100000000004201000000005cd0008065014e544c4d53535000030000001800180040000000c800c800580000000200020020010000000000002201000020002000220100000000000042010000050208a2c5c7000bd9e6d42ea94a4cbfdca45c0acf0bda02565d6dbda44587b776af94ef8b99eb2625127d8b0101000000000000801902e4f3cbd201cf0bda02565d6dbd0000000002001e00570049004e002d00500053004600420039003000340053004d003300310001001e00570049004e002d00500053004600420039003000340053004d003300310004001e00570049004e002d00500053004600420039003000340053004d003300310003001e00570049004e002d00500053004600420039003000340053004d0033003100070008002fb888e7f3cbd20100000000000000002e004a005600340061005a004e0067004600520058004d0061004b00570068006c0057696e646f7773203230303020323139350057696e646f7773203230303020352e3000"
        msg = msg.decode('hex')
        client.send(msg)
        client.recv(2048)

        msg = "00000063ff534d427300000000180120000000000000000000000000000087110000b3720dff000000dfff02000100000000000000000000000000400000002600002e0057696e646f7773203230303020323139350057696e646f7773203230303020352e3000"
        msg = msg.decode('hex')
        client.send(msg)
        ret = client.recv(2048)
        ret = ret.encode('hex')
        userid = ret[64:68]
        #print userid

        msg = "00000049ff534d42750000000018012800000000000000000000000000008711" + userid + "b37204ff000000000001001e00005c5c3139322e3136382e3235322e3133375c49504324003f3f3f3f3f00"
        msg = msg.decode('hex')
        client.send(msg)
        ret = client.recv(2048)
        ret = ret.encode('hex')
        userid = ret[64:68]
        treeid = ret[56:60]
        #print userid

        msg = "0000004aff534d422500000000180128000000000000000000000000" + treeid + "8711" + userid + "b3721000000000ffffffff0000000000000000000000004a0000004a0002002300000007005c504950455c00"
        msg = msg.decode('hex')
        client.send(msg)
        ret = client.recv(2048)
        ret = ret.encode('hex')
        #print ret
        if len(ret) > 26:
            #print ret
            x = ret[18:26]
            #print x
            if ret[18:26] == "050200c0":
                multiprint("%s\tis likely VULNERABLE to MS17-010!" % (host2,))
                msg = host2 + "\tis likely VULNERABLE to MS17-010!"
                write_log(msg)
            else:
                msg = host2 + "\tdoes NOT appear vulnerable"
                multiprint(msg)
                write_log(msg)
        else:
            #pass
            msg = host2 + "\tdoes NOT appear vulnerable"
            multiprint(msg)
            write_log(msg)
    except Exception,e:
        msg = host2 + "\t" + str(e)
        multiprint(msg)
        write_log(msg)
    finally:
        if connected:
            client.shutdown(socket.SHUT_RDWR)
        client.close()
    return

def process_single(ip, ip_list):
    if re.match(r'(?<![\.\d])(?:\d{1,3}\.){3}\d{1,3}(?![\.\d])', ip):
        ip_list.append(ip)

def process_line(ip_range, ip_list):
    s = ip_range.find("-")
    beginip = ip_range[0:s]
    ip = beginip.split('.')[0:3]
    beg = int(beginip.split('.')[3])
    end = int(ip_range[s+1:])
    for i in range(beg, end+1):
        tmp = ip[:]
        tmp.append(str(i))
        ip_list.append('.'.join(tmp))

def process_star(ip_range, ip_list):
    s = ip_range.find("*")
    ip = ip_range.split(".")[0:3]
    for i in range(1, 255):
        tmp = ip[:]
        tmp.append(str(i))
        ip_list.append('.'.join(tmp))
def process_comma(ip_range, ip_list):
    ips = ip_range.split(",")
    begip = ips[0]
    ip_list.append(begip)
    other = ips[1:]
    ip = begip.split('.')[0:3]
    for i in other:
        tmp = ip[:]
        tmp.append(i)
        ip_list.append('.'.join(tmp))
def process_slash(ip_range, ip_list):
    if -1!=ip_range.find("/"):
        try:
            ip_network = ipaddress.ip_network(unicode(ip_range))
        except Exception,e:
            multiprint ("IP format error: ip_range")
            print e
            return
        for ip in ip_network.hosts():
            ip_list.append(str(ip).strip())
def process_list(filename, ip_list):
    f_name = filename
    with open(f_name) as f_list:
        li_ip=f_list.readlines()
    for ele in li_ip:
        parseip(ele.strip(), ip_list)

def parseip(ip_range, ip_list):
    if -1 != ip_range.find("/"):
        process_slash(ip_range, ip_list)
    elif -1!=ip_range.find("-"):
        process_line(ip_range, ip_list)
    elif -1 != ip_range.find(","):
        process_comma(ip_range, ip_list)
    elif -1!=ip_range.find("*"):
        process_star(ip_range, ip_list)
    elif None!=re.match(r'(?<![\.\d])(?:\d{1,3}\.){3}\d{1,3}(?![\.\d])', ip_range):
        ip_list.append(ip_range)

def make_pool(thread, iplist_list):
    for ip_list in iplist_list:
        pool = threadpool.ThreadPool(thread)
        requests = threadpool.makeRequests(scan_ip, ip_list)
        [pool.putRequest(req) for req in requests]
        pool.wait()
        pool.dismissWorkers(thread, do_join=True)
        multiprint("one round over!\n")
def main_scan(arg, isIP):
    global thread
    ip_list=[]
    iplist_list = []
    if (isIP):
        parseip(arg, ip_list)
    else:
        process_list(arg, ip_list)

    if len(ip_list) > 1000:
        i = 255
        tmp = ip_list[0:255]
        iplist_list.append(tmp)
        while (i < len(ip_list)):
            if (i + 256 < len(ip_list)):
                tmp = ip_list[i:i+256]
                iplist_list.append(tmp)
                i += 256
            else:
                iplist_list.append(ip_list[i:])
                break
    else:
        iplist_list.append(ip_list)
    make_pool(thread, iplist_list)
    multiprint ("detect over!\n")
    #sys.exit(1)

def main():
    global logname
    global timeout
    global thread
    global g_logfd
    if len(sys.argv)<2:
        print "\nQihoo 360 MS17-010(NSA Eternalblue) detect program!"
        print "Copyright by 360GearTeam\n"
        print "Usage:\n"
        print "%s 192.168.1.1" % sys.argv[0]
        print "%s 192.168.1.0/24" % sys.argv[0]
        print "%s 192.168.1.1-23" % sys.argv[0]
        print "%s 192.168.1.*" % sys.argv[0]
        print "%s 192.168.1.1,2,3" % sys.argv[0]
        print "%s -list iplist.txt" % sys.argv[0]
        return
    logname = "ms17010_detect_results_" + timetag +".txt"
    start_time = time.time()

    parser = argparse.ArgumentParser()
    parser.add_argument("-t","--timeout", default=5,type=int, help="timeout")
    parser.add_argument("-n","--thread", default=50, type=int, help="threads")
    parser.add_argument("-o","--output",default=logname, help="out put filename")
    if not sys.argv[1].startswith("-"):
        parser.add_argument("ip", help="ip address, one of 192.168.1.1, 192.168.1.0/24,\
                       192.168.1.1-23, 192.168.1.*, 192.168.1.1,2,3")
        isIP = True;
    else:
        parser.add_argument("-list", "--list", help="ip files")
        isIP = False

    args = parser.parse_args()


    timeout = args.timeout
    thread = args.thread
    if (args.output != None):
        logname = args.output

    g_logfd = open(logname, "w")
    print "\nQihoo 360 MS17-010(NSA Eternalblue) detect program!"
    write_log("\nQihoo 360 MS17-010(NSA Eternalblue) detect program!")
    print "Copyright by 360GearTeam\n"
    write_log("Copyright by 360GearTeam\n\n")

    if (isIP and args.ip != None):
        main_scan(args.ip, True)
    elif(not isIP and args.list != None):
        main_scan(args.list, False)
    else:
        print "Please provide ip or file\n"
    #main_scan(args.ip? args.ip: args.list)
    g_logfd.close()
    print "use %d second" % (time.time()-start_time)

if '__main__'==__name__:
    main()
