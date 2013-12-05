---
layout: post
title: "【编程珠玑】第一章"
description: "读书笔记"
category: 技术
tags: [编程珠玑, 算法]
---
{% include JB/setup %}


问题：一个文件最多有n(n=1000w)个正整数，每一个正整数都&lt;n，并且它们是不重复的，如何使用一种快速的方法给这些正整数排序。要求内存最多是1M。

方法一：使用归并排序，归并排序的时间复杂度是nlgn。但是归并排序需要将数据一次全部读入内存，但是很明显需要的内存空间是1000w*4/(1024*1024)，大约是40M，占用空间太大。

方法二：可以将这些正整数分成40组，分别是[0--249999]、[250000--499999]....[9750000--9999999]，然后遍历40次这些整数，第一次找出[0--249999]里面的，第二次找出[250000--4999999]里面的。这样每次处理的是250000个数，内存上符合要求，但是时间太多，更何况I/O操作相当费时。

方法三：就是这一章的主题了，位图排序。其基本思想是用1个bit来表示[0--n]中数是否存在，如果存在这个bit置为1，否则置0。这样之后，再遍历一下，就排好序了，这样的使用的空间大致是n/(8\*1024\*1024)M，1000w大致就是1.25M。例如对于集合{1,2,3,5,8,13}，都小于20，假设我们有20个bit，则它的位图表示就是01110100100001000000，再一遍历，就排好了。这种方法的伪代码表示如下:


	for i = [0,n)
	    bit[i] = 0
	
	for each i in the input file
	    bit[i] = 1
	
	for i = [0,n)
	    if  bit[i] == 1
	        write i on the output file

 实际的代码如下：


	/* Copyright (C) 1999 Lucent Technologies */
	
	/* From 'Programming Pearls' by Jon Bentley */
	
	
	
	/* bitsort.c -- bitmap sort from Column 1
	
	*   Sort distinct integers in the range [0..N-1]
	
	*/


	#include <stdio.h>
	#define BITSPERWORD 32
	#define SHIFT 5
	#define MASK 0x1F
	#define N 10000000
	
	int a[1 + N/BITSPERWORD];
	
	void set(int i) {        a[i>>SHIFT] |=  (1<<(i & MASK)); }
	void clr(int i) {        a[i>>SHIFT] &= ~(1<<(i & MASK)); }
	int  test(int i){ return a[i>>SHIFT] &   (1<<(i & MASK)); }
	
	int main()
	{   
	    int i;
	    for (i = 0; i < N; i++)
	      clr(i);
	/*  Replace above 2 lines with below 3 for word-parallel init
	
	    int top = 1 + N/BITSPERWORD;
	    for (i = 0; i < top; i++)
	      a[i] = 0;
	*/
	    while (scanf("%d", &i) != EOF)
	        set(i);
	    for (i = 0; i < N; i++)
	        if (test(i))
	           printf("%d\n", i);
	
	    return 0;
	}


代码没有什么说的，就是需要注意下别人对位图的操作时比较巧妙的。 很明显，位图法的使用时有一些场景的：

<p>1.输入的数需要有一个范围</p>

<p>2.输入的数应该是没有重复，如果重复次数不超过m次，那么lgm个bit来表示1个数</p>

**课后问题：**

<p>1. 使用库函数排序</p>


	C语言

	/* Copyright (C) 1999 Lucent Technologies */
	/* From 'Programming Pearls' by Jon Bentley */
	
	/* qsortints.c -- Sort input set of integers using qsort */
	
	#include <stdio.h>
	#include <stdlib.h>
	
	int intcomp(int *x, int *y)
	{       
	    return *x - *y;
	}
	
	int a[1000000];
	
	int main()
	{   
	    int i, n=0;
	    while (scanf("%d", &a[n]) != EOF)
	        n++;
	    qsort(a, n, sizeof(int), intcomp);
	    for (i = 0; i < n; i++)
	        printf("%d\n", a[i]);
	    return 0;
	}
	C++语言
	
	/* Copyright (C) 1999 Lucent Technologies *//* From 'Programming Pearls' by Jon Bentley */
	
	/* sortints.cpp -- Sort input set of integers using STL set */
	
	#include <iostream>
	#include <set>
	using namespace std;
	
	int main()
	{       
	    set<int> S;
	    int i;
	    set<int>::iterator j;
	    while (cin >> i)
	        S.insert(i);
	    for (j = S.begin(); j != S.end(); ++j)
	        cout << *j << "\n";
	    return 0;
	}


<p>2. 位操作</p>


	#define BITSPERWORD 32
	#define SHIFT 5
	#define MASK 0x1F
	#define N 10000000
	int a[1 + N/BITSPERWORD];
	
	void set(int i) {        a[i>>SHIFT] |=  (1<<(i & MASK)); }
	void clr(int i) {        a[i>>SHIFT] &= ~(1<<(i & MASK)); }
	int  test(int i){ return a[i>>SHIFT] &   (1<<(i & MASK)); }


<p>3. 位图排序与系统排序 位图排序最快，qsort比stl sort快</p>

<p>4. 随机生成[0,n)之间不重复的随机数</p>

	/* Copyright (C) 1999 Lucent Technologies */
	/* From 'Programming Pearls' by Jon Bentley */
	
	/* bitsortgen.c -- gen $1 distinct integers from U[0,$2) */
	
	#include <stdio.h>
	#include <stdlib.h>
	#include <time.h>
	#define MAXN 2000000
	int x[MAXN];
	
	int randint(int a, int b)
	{       
	    return a + (RAND_MAX * rand() + rand()) % (b + 1 - a);
	}
	
	int main(int argc, char *argv[])
	{       
	    int i, k, n, t, p;
	    srand((unsigned) time(NULL));
	    k = atoi(argv[1]);
	    n = atoi(argv[2]);
	    for (i = 0; i < n; i++)
	        x[i] = i;
	    for (i = 0; i < k; i++) {
	        p = randint(i, n-1);
	        t = x[p]; x[p] = x[i]; x[i] = t;
	        printf("%d\n", x[i]);
	    }
	    return 0;
	}


<p>5. 最开始实现的需要1.25M，如果内存1M是严格限制的。应该分两次读取，第一次读取0到4999999之间的数，第二次读取5000000到10000000之间的数，这样需要的内存空间约是6.25M。 下面给出july博客中的一个实现：</p>


	#include <iostream>
	#include <ctime>
	#include <bitset>
	
	using namespace std;
	
	const int max_each_scan = 5000000;
	int main()
	{
	     clock_t begin = clock();
	     bitset<max_each_scan + 1> bitmap;
	     bitmap.reset();
	
	     FILE* fp_unsorted_file = fopen("data.txt","r");
	     int num;
	     while(fscanf(fp_unsorted_file,"%d ",&num) != EOF)
	     {
	          if (num < max_each_scan)
	          {
	               bitmap.set(num,1);
	          }
	     }
	
	     FILE* fp_sort_file = fopen("sort.txt","w");
	     for (int i = 0; i < max_each_scan; ++i)
	     {
	          if (bitmap[i] == 1)
	          {
	               fprintf(fp_sort_file,"%d ",i);
	          }
	     }
	
	     int result = fseek(fp_unsorted_file,0,SEEK_SET);
	     if (result)
	     {
	          printf("fseek failed\n");
	     }
	     else
	     {
	          bitmap.reset();
	          while(fscanf(fp_unsorted_file,"%d ",&num) != EOF)
	          {
	               if (num >= max_each_scan && num < 10000000)
	               {
	                    num -= max_each_scan;
	                    bitmap.set(num,1);
	               }
	          }
	          for (int i = 0; i < max_each_scan; ++i)
	          {
	               if (bitmap[i] == 1)
	               {
	                    fprintf(fp_sort_file, "%d ",i + max_each_scan );
	               }
	          }
	
	     }
	
	     clock_t end = clock();
	     cout << "位图耗时:" << (end - begin) / CLK_TCK << "s" << endl;
	     return 0;
	}

<p>6. 如果每个数据最多出现10次，那么需要4个bit来记录一个数。视内存情况决定使用单次或者多路排序。</p>

<p>7. 程序输入的安全性检验，数据不应超过一次，不应该小于0或者大于n。</p>

<p>8. 如果免费电话号码有800、878、888等，如何查看一个号码是否是免费号码。 暂时只想到这个方法，跟本章思想一样，就是有n个号码就是耗内存1.25M*n。</p>

<p>9. 避免初始化问题 网上google才理解了答案的意思。具体操作是声明两个数组from to以及一个变量top=0；</p>


	if(from[i] < top && to[from[i]] == i)  
	{  
	    printf("has used!\n")  
	}  
	else  
	{  
	    a[i] = 1;  
	    from[i] = top;  
	    to[top] = i;  
	    top++;  
	}  


top变量用来记录已经初始化过的元素个数，from[i]=top，相当于保持a[i]是第几个初始化过的元素，to[top]=i，用来致命第top个初始化的元素在data里的下标是多少。因此每次访问一个data元素时，判断from[i] &lt; top，即data[i]元素是否被初始化过，但当top很大时，from[i]里被内存随便赋予的初始化值可能真的小于top，这时候我们就还需要to[from[i]] == i 的判断了来保证from[i] &lt; top不是因为内存随意赋给from[i]的值本身就小于top而是初始化后小于的。这个还是要自己理解。

<p>10. 使用电话号码最后两位作为客户的哈希索引，进行分类。</p>
