---
layout: post
title: "遍历序列确定二叉树"
description: "面试笔试"
category: 技术
tags: [算法]
---
{% include JB/setup %}


我们知道二叉树的遍历一般分为三种（前序、中序、后序），现在的问题是根据任意两种遍历序列确定这颗二叉树。一般的，“前序+中序”，“中序+后序”的模式都能唯一确定二叉树，而“前序+后序”是不能唯一确定二叉树的。[这篇文章](http://www.binarythink.net/2012/12/binary-tree-info-theory/)从信息论的角度从定性的角度说明了这个问题。（下面大部分都是从网上看来的，自己做了一个综合而已）

下面我们对这三种情况分别进行讨论。

一. 已知二叉树的前序序列和中序序列


1、确定树的根节点。树根是当前树中所有元素在前序遍历中最先出现的元素。

2、求解树的子树。找出根节点在中序遍历中的位置，根左边的所有元素就是左子树，根右边的所有元素就是右子树。若根节点左边或右边为空，则该方向子树为空；若根节点左边和右边都为空，则根节点已经为叶子节点。

3、递归求解树。将左子树和右子树分别看成一棵二叉树，重复1、2、3步，直到所有的节点完成定位。

二、已知二叉树的后序序列和中序序列

1、确定树的根。树根是当前树中所有元素在后序遍历中最后出现的元素。

2、求解树的子树。找出根节点在中序遍历中的位置，根左边的所有元素就是左子树，根右边的所有元素就是右子树。若根节点左边或右边为空，则该方向子树为空；若根节点左边和右边都为空，则根节点已经为叶子节点。

3、递归求解树。将左子树和右子树分别看成一棵二叉树，重复1、2、3步，直到所有的节点完成定位。

下面是代码


	#include "stdafx.h"
	#include <stdlib.h>
	#include <stdio.h>
	#include <string.h>
	
	
	typedef struct _node
	{
	     int v;
	     struct _node* left;
	     struct _node* right;
	}node;
	
	char pre[50] = "ABDHLEKCFG";
	char mid[50] = "HLDBEKAFCG";
	char post[50] = "LHDKEBFGCA";
	
	int Possition(char c)
	{
	     return strchr(mid,c) - mid;
	}
	node* root1;//这里弄成全局变量主要是为了调试
	node* root2;
	
	//i: 子树的前序序列字符串的首字符在pre[]中的下标
	//j: 子树的中序序列字符串的首字符在mid[]中的下标
	//len: 子树的字符串序列的长度
	
	void PreMidCreateTree(node **root,int i,int j,int len)
	{
	     int m;
	     if(len <= 0)
	          return;
	     *root = (node*)malloc(sizeof(node));
	     (*root)->v = pre[i];
	     (*root)->left = NULL;
	     (*root)->right = NULL;
	     m = Possition(pre[i]);
	     PreMidCreateTree(&((*root)->left),i+1,j,m-j);//确定递归区间要非常注意，仔细体会
	     PreMidCreateTree(&((*root)->right),i+(m-j)+1,m+1,len-1-(m-j));
	}
	
	
	//i: 子树的后序序列字符串的尾字符在post[]中的下标
	//j: 子树的中序序列字符串的首字符在mid[]中的下标
	//len: 子树的字符串序列的长度
	
	void MidPostCreateTree(node **root,int i,int j,int len)
	{
	     int m;
	     if(len <= 0)
	          return;
	     *root = (node*)malloc(sizeof(node));
	     (*root)->v = post[i];
	     (*root)->left = NULL;
	     (*root)->right = NULL;
	     m = Possition(post[i]);
	     MidPostCreateTree(&((*root)->left),i-1-(len-1-(m-j)),j,m-j);
	     MidPostCreateTree(&((*root)->right),i-1,m+1,len-1-(m-j));
	}
	
	void PreOrder(node *root)
	{
	     if(root)
	     {
	          printf("%c",root->v);
	          PreOrder(root->left);
	          PreOrder(root->right);
	     }
	}
	
	void PostOrder(node *root)
	{
	     if(root)
	     {
	          PostOrder(root->left);
	          PostOrder(root->right);
	          printf("%c",root->v);
	     }
	    
	}
	
	int main()
	{
	     node  *root2= NULL;
	     PreMidCreateTree(&root1, 0, 0, strlen(mid));
	     PostOrder(root1); 
	     printf("\n");
	     MidPostCreateTree(&root2, strlen(post)-1, 0, strlen(mid));
	     PreOrder(root2);
	     printf("\n");
	     return 0;
	}

三. 已知二叉树的前序序列和后序序列

这种情况下一般不能唯一确定一颗二叉树，但是可以确定有多少种二叉树的可能形态。

思路如下：我们先看一个简单例子，前序序列为ABCD，后序序列为CBDA

（1） 前序遍历和后序遍历的最后一个字母必定是根，即都是 A

（2） 前序遍历的第二个字母是 B 也必定是某颗子树的根（左右无法确定）。那么 B 在后序遍历中一定出现在它所在子树的最后，因此我们可以通过查找 B 在后序遍历中的位置来得到左子树的所有节点，即为 B 和 C ，剩下的 D 就是右子树的节点了

（3） 分别用同样的方法分析左子树 BC 及右子树 D ， D 只有一个根，形态是唯一的， BC 只有一颗子树，它可以是左也可以是右

（4） 最后看看有多少个节点（假设是 n ）是只有一颗子树的，用乘法 pow (2,n)就是结果

下面推广到所有的二叉树

首先我们需要设几个变量：

	pre[50]; // 前序遍历的数组
	post[50]; // 后序遍历的数组
	length; // 数组的长度
	count; // 记录只有一个子树的节点的个数

(1) 如果 length == 1 ，显然结果唯一

(2) 当顶点多余 1 时，说明存在子树，必然有 pre[0]==post[length-1]; 如果 pre[1] == post[length-2]; 说明从 1 到 length-1 都是 PreStr[0] 的子树，至于是左还是右就无法确定，此时 count++ 。对剩下的 pre[1] 到 pre[length-1] 与 post[0] 到 post[length-2] 作为一颗新树进行处理

(3) 如果 pre[1] != post[length-2], 显然存在左右子树 (post 中以与 pre[1] 相等的位置分为左右子树 ) ，对左右子树分别作为一颗独立的子树进行处理


	#include <stdio.h>
	#include <stdlib.h>
	
	
	char pre[50];//= "ABDHLEKCFG";
	char mid[50];//= "HLDBEKAFCG";
	char post[50];//= "LHDKEBFGCA";
	int count;
	void calc(int prebeg,int preend,int postbeg,int postend)
	{
	     int i;
	     if(prebeg>=preend)
	          return;
	     for(i = postbeg; i <= postend - 1; ++i)
	     {
	          if(pre[prebeg+1]==post[i])
	               break;
	     }
	     if(i == postend - 1)
	          count++;
	     calc(prebeg+1,prebeg+1+(i-postbeg),postbeg,i);
	     calc(prebeg+1+(i-postbeg)+1,preend,i+1,postend-1);
	}
	
	int Pow(int n)
	{
	    int i;
	    int m = 1;
	
	    for(i = 0; i < n; i++)
	    {
	        m *= 2;
	    }
	
	    return m;
	}
	
	int main()
	{
	     int length;
	    scanf("%s", pre);
	    scanf("%s", post);
	
	    length = strlen(pre);
	    count = 0;
	
	    calc(0,length-1,0,length-1);
	    printf("%d\n", Pow(count));
	    return 0;
	}
