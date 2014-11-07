---
layout: post
title: "Trie树与Word Puzzles"
description: "Tire && Word Puzzles"
category: 技术
tags: [算法]
---
{% include JB/setup %}



最近看书遇到一个word puzzles问题，大概的意思就是给定一个字母方阵和一些单词，在这个字母方阵中找出这些单词，可以是横、竖、斜对应的8个方向。比如给出如下的方阵如几个单词（这是一个OJ题）：
	
	MARGARITA, ALEMA, BARBECUE, TROPICAL, SUPREMA, LOUISIANA, CHEESEHAM, EUROPA, HAVAIANA, CAMPONESA

![](/assets/img/trie/1.jpg)

上面标出了前面3个单词。

最简单的就是暴力匹配了，对每一个单词遍历一下方阵。但是很明显效率受不了，网上学习了一下，Trie树是解决这个问题的很好的方案。下面先简要介绍一下Trie树。


<h3>Trie树简介</h3>

Trie树，又称字典树，单词查找树或者前缀树，是一种用于快速检索的多叉树结构，如英文字母的字典树是一个26叉树，数字的字典树是一个10叉树。Trie典型应用是用于统计和排序大量的字符串（但不仅限于字符串），所以经常被搜索引擎系统用于文本词频统计。它的优点是：最大限度地减少无谓的字符串比较，查询效率比哈希表高。

Trie树可以利用字符串的公共前缀来节约存储空间。如下图所示，该trie树用10个节点保存了6个字符串tea，ten，to，in，inn，int：

![](/assets/img/trie/2.jpg)

Trie树的基本性质可以归纳为：

* 根节点不包含字符，除根节点意外每个节点只包含一个字符。
* 从根节点到某一个节点，路径上经过的字符连接起来，为该节点对应的字符串。
* 每个节点的所有子节点包含的字符串不相同。


下面给出一个Trie简易实现，根据下面的这幅图代码是很容易理解的。

![](/assets/img/trie/3.png)


	#include <stdio.h>
	#include <stdlib.h>
	#include <string.h>
	
	#define ALPHABET_SIZE 26
	
	struct node
	{
		int data;
		struct node *link[ALPHABET_SIZE];
	};
	
	struct node *create_node()
	{
		struct node *q = (struct node*)malloc(sizeof(struct node));
		for (int i = 0; i < ALPHABET_SIZE; ++i)
		{
			q->link[i] = NULL;
		}
		q->data = -1;
		return q;
	}
	
	void insert_node(struct node* root, char *key)
	{
		int length = strlen(key);
		
		struct node *q = root;
		int i = 0;
		for (i = 0; i < length; ++i)
		{
			int index = key[i] - 'a';
			if (q->link[index] == NULL)
			{
				q->link[index] = create_node();
			}
			q = q->link[index];
		}
		q->data = i;
	}
	
	
	int search(struct node *root, char *key)
	{
		struct node *q = root;
		int length = strlen(key);
		int i = 0;
		for (i = 0; i < length; ++i)
		{
			int index = key[i] - 'a';
			if (q->link[index] != NULL)
				q = q->link[index];
			else
				break;
		}
		if (key[i] == '\0' && q->data != -1)
			return q->data;
		return -1;
	}
	
	
	void del(struct node *root)
	{
		if(root == NULL)
			return;
		for (int i = 0; i < ALPHABET_SIZE; ++i)
		{
			del(root->link[i]);
		}
		free(root);
	}
	int main()
	{
	 	struct node *root = create_node();
		insert_node(root, "by");
		insert_node(root, "program");
		insert_node(root, "programming");
		insert_node(root, "data structure");
		insert_node(root, "coding");
		insert_node(root, "code");
		printf("Search value:%d\n", search(root, "code"));
		printf("Search value:%d\n", search(root, "geeks"));
		printf("Search value:%d\n", search(root, "coding"));
		printf("Search value:%d\n", search(root, "programming"));
		del(root);
	}



<h3>Word Puzzles</h3>

主要思想就是先将单词建立起一颗Trie树，接着对字符方阵中的每个字符、每个方向进行暴力搜索，查找其是否存在于这颗Trie树中。因为个人不太喜欢用全局变量，就用C++写的，有一些C++11代码，还是觉得C++11代码太风骚。

输入如下：

	20 20 10
	QWSPILAATIRAGRAMYKEI
	AGTRCLQAXLPOIJLFVBUQ
	TQTKAZXVMRWALEMAPKCW
	LIEACNKAZXKPOTPIZCEO
	FGKLSTCBTROPICALBLBC
	JEWHJEEWSMLPOEKORORA
	LUPQWRNJOAAGJKMUSJAE
	KRQEIOLOAOQPRTVILCBZ
	QOPUCAJSPPOUTMTSLPSF
	LPOUYTRFGMMLKIUISXSW
	WAHCPOIYTGAKLMNAHBVA
	EIAKHPLBGSMCLOGNGJML
	LDTIKENVCSWQAZUAOEAL
	HOPLPGEJKMNUTIIORMNC
	LOIUFTGSQACAXMOPBEIO
	QOASDHOPEPNBUYUYOBXB
	IONIAELOJHSWASMOUTRK
	HPOIYTJPLNAQWDRIBITG
	LPOINUYMRTEMPTMLMNBO
	PAFCOPLHAVAIANALBPFS
	MARGARITA
	ALEMA
	BARBECUE
	TROPICAL
	SUPREMA
	LOUISIANA
	CHEESEHAM
	EUROPA
	HAVAIANA
	CAMPONESA

20表示方阵大小，10表示单词大小


输出：坐标+方向

	0 15 G
	2 11 C
	7 18 A
	4 8 C
	16 13 B
	4 15 E
	10 3 D
	5 1 E
	19 7 C
	11 11 H

下面是代码

	#include <iostream>
	#include <fstream>
	#include <vector>
	#include <algorithm>
	#include <iterator>
	#include <string>
	#include <tuple>
	
	using namespace std;
	
	struct Node
	{
		int data;
		struct Node *child[26];
	};
	
	class WordPuzzles
	{
	public:
		
		WordPuzzles(ifstream &in);
		void insert_node(string word, int num);
		void search_words(int x, int y, int dir);
		void do_work();
	private:
	
		Node *create_node()
		{
			Node *q = new Node();
			q->data = -1;
			for (int i = 0; i < 26; ++i)
			{
				q->child[i] = NULL;
			}
			return q;
		}
	
		static int dx[8];//方向
		static int dy[9];
		int row, col, counts;
		vector<string> wordmap, words;
		vector<tuple<int, int, int, char>>  ans; 
		Node *root;
	};
	
	int WordPuzzles::dx[] = { -1, -1, 0, 1, 1, 1, 0, -1 };
	int WordPuzzles::dy[] = { 0, 1, 1, 1, 0, -1, -1, -1 };
	
	WordPuzzles::WordPuzzles(ifstream &in)
	{
		in >> row >> col >> counts;
		printf("the row is:%d,col is:%d,counts is:%d\n", row, col, counts);
		for (int i = 0; i < row; ++i)
		{
			string str;
			in >> str;
			wordmap.push_back(str);
		}
		cout << "the map is " << endl;
		copy(wordmap.begin(), wordmap.end(), ostream_iterator<string>(cout, "\n"));
	
		for (int i = 0; i < counts; ++i)
		{
			string str;
			in >> str;
			words.push_back(str);
		}
		cout << "the words is " << endl;
		copy(words.begin(), words.end(), ostream_iterator<string>(cout, "\n"));
	
	
		root = create_node();
	
		for (vector<string>::iterator it = words.begin(); it != words.end(); ++it)
		{
			insert_node(*it, it - words.begin());
		}
	}
	
	void WordPuzzles :: insert_node(string word, int num)
	{
		Node *q = root;
		for (int i = 0; i < word.size(); ++i)
		{
			int index = word[i] - 'A';
			if (q->child[index] == NULL)
			{
				q->child[index] = create_node();
			}
			q = q->child[index];
		}
		q->data = num;
	}
	
	
	void WordPuzzles::search_words(int x,int y,int dir)
	{
		Node *q = root;
		int xtmp = x, ytmp = y;
		while (xtmp >= 0 && xtmp < row && ytmp >= 0 && ytmp < col)
		{
			if (!q->child[wordmap[xtmp][ytmp] - 'A'])
				break;
			else
				q = q->child[wordmap[xtmp][ytmp] - 'A'];
			if (q->data != -1)
			{
				
				ans.push_back(make_tuple(q->data,x, y, dir));
				q->data = -1;
				
			}
			xtmp += dx[dir];
			ytmp += dy[dir];
		}
	}
	
	void WordPuzzles::do_work()
	{
		for (int i = 0; i < row; ++i)
		{
			for (int j = 0; j < col; ++j)
			{
				for (int k = 0; k < 8; ++k)
					search_words(i, j, k);
			}
		}
	
		sort(ans.begin(), ans.end(),
			[](const tuple<int, int, int, char>& a, const tuple<int, int, int, char> &b)
		{
			return get<0>(a) < get<0>(b);
		});
	
		for (auto &it : ans)
		{
			cout << get<1>(it) << " " << get<2>(it) << " " << (char)(get<3>(it) +'A') << endl;
		}
	}
	
	int main()
	{
		
		
		ifstream in("word.txt");
		WordPuzzles wp(in);
		wp.do_work();
		
	}