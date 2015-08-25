---
layout: post
title: "输出24点游戏所有解"
description: "面试"
category: 技术
tags: [算法]
---
{% include JB/setup %}


24点游戏，就是选4个数，对其运用加减乘除，得到24，可以使用括号。关于24点游戏的解法，《编程之美》上面说得比较清楚，我这里直接使用第二种解法。这里在合并S集的时候是不应该像书上说的去重的，因为虽然说产生的数一样，但是他们是不同的计算的方式产生的，如果这个时候去重会导致得不出正确的解法个数，正确的去重应该是在最后统计S[15]中24的个数时。下面是运行结果：

![](/assets/img/pointgame/1.PNG)

	#include <iostream>
	#include <vector>
	#include <set>
	#include <algorithm>
	#include <iterator>
	#include <string>
	#include <math.h>
	
	using namespace std;
	const double threHold = 1E-6;
	
	struct Node
	{
		double value;
		string exp;
		Node(double v, string s) :value(v), exp(s){}
		friend bool operator < (const Node &node1, const Node &node2)
		{
			return node1.value < node2.value;
		}
	};
	
	class PointGameSolver
	{
	public:
		PointGameSolver(initializer_list<double> li) :init(li)
		{
			S = new multiset<Node>[static_cast<int>(pow(2, init.size()))];
		}
		int getResult(set<string>& ans)
		{
			ans.clear();
			calc();
			return check(ans);
		}
		~PointGameSolver()
		{
			delete[] S;
		}
	private:
		int check(set<string>& result);
		multiset<Node> setS(int i);
		multiset<Node> getUnion(multiset<Node> a, multiset<Node> b);
		multiset<Node> fork(multiset<Node> a, multiset<Node> b);
		void calc();
		
		multiset<Node>  *S;
		vector<double> init;
	};
	
	int PointGameSolver::check(set<string>& result)
	{
		int count = 0;
		multiset<Node> ans = S[static_cast<int>(pow(2, init.size()) - 1)];
		for (auto it = ans.begin(); it != ans.end(); ++it)
		{
			if ((it->value - 0) > threHold && fabs(it->value - 24) < threHold)
			{
				count++;
				result.insert(it->exp);
			}
		}
		return result.size();
	}
	multiset<Node> PointGameSolver::setS(int i)
	{
		if (!S[i].empty())
			return S[i];
		for (int x = 1; x < i; ++x)
		{
			if ((x & i) == x)
				S[i] = getUnion(S[i], fork(setS(x), setS(i - x)));
		}
		return S[i];
	}
	multiset<Node> PointGameSolver::getUnion(multiset<Node> a, multiset<Node> b)
	{
		multiset<Node> result;
		copy(a.begin(), a.end(), inserter(result, result.begin()));
		copy(b.begin(), b.end(), inserter(result, result.begin()));
		return result;
	}
	multiset<Node> PointGameSolver::fork(multiset<Node> a, multiset<Node> b)
	{
		if (a.empty())
			return b;
		if (b.empty())
			return a;
		multiset<Node> result;
		for (auto ita = a.begin(); ita != a.end(); ++ita)
		{
			for (auto itb = b.begin(); itb != b.end(); ++itb)
			{
				result.insert(Node(ita->value + itb->value, "(" + ita->exp + "+" + itb->exp + ")"));
				result.insert(Node(ita->value * itb->value, "(" + ita->exp + "*" + itb->exp + ")"));
				result.insert(Node(ita->value - itb->value, "(" + ita->exp + "-" + itb->exp + ")"));
				result.insert(Node(itb->value - ita->value, "(" + itb->exp + "-" + ita->exp + ")"));
				if (!((fabs(ita->value - 0) < threHold)))
				{
					result.insert(Node(ita->value / itb->value, "(" + ita->exp + "/" + itb->exp + ")"));
				}
				if (!((fabs(itb->value - 0) < threHold)))
				{
					result.insert(Node(itb->value / ita->value, "(" + itb->exp + "/" + ita->exp + ")"));
				}
	
			}
		}
		return result;
	}
	void PointGameSolver::calc()
	{
		size_t n = init.size();
		for (size_t i = 0; i < n; ++i)
		{
			S[static_cast<int>(pow(2, i))].insert(Node(init[i], to_string((int)init[i])));
		}
		for (size_t i = 1; i < pow(2, n); ++i)
		{
			S[i] = setS(i);
		}
	}
	
	bool isValid(int *a, int n)
	{
		for (int i = 0; i < n; ++i)
		{
			if (a[i] < 1 || a[i] > 10)
				return false;
		}
		return true;
	}
	int _tmain(int argc, _TCHAR* argv[])
	{
		int data[4];
		while (1)
		{
			cout << "请输入4个数（1-10，空格隔开）：";
			int i = 0;
			while (cin >> data[i++])
			{
				if (i == 4)
					break;
			}
			if (cin && isValid(data, 4))
			{
				PointGameSolver pgs({ (double)data[0], (double)data[1], (double)data[2], (double)data[3] });
				set<string> ans;
				int count = pgs.getResult(ans);
				if (!count)
				{
					cout << "no solution\n";
				}
				else
				{
					cout << "total solutions :" << count << endl;
					for_each(ans.begin(), ans.end(), [](const string &s) {cout << s << endl; });
				}
			}
			else
				cout << "invalid input \n";
			cout << "\n";
	
			cout << "continue?(y/n):";
			if (!cin)
				cin.clear();
			cin.ignore(numeric_limits<streamsize>::max(), '\n');
			string str;
			cin >> str;
			if (str != "Y" && str != "y")
				break;
		}
	
		return 0;
	}
	


竟然有人看到了文末，那就扯点别的。这是UCloud的面试题，昨晚接到UCloud面试官的电话，简单说了下他们是做网络虚拟化的，问有没有兴趣。随意聊了一下，然后就在我准备接受一番血虐的时候，他直接就给我整个这个题，太直接了好嘛，有一种dota里面的“生死看淡，不服就干”的味道。然后我当然就查资料了，发现竟然是编程之美上面的，然后看了下思路，顺着书上的框架写好代码，完工之后才发现还要输出所有解。想了一会，之前想到甚至用tuple来保存表达式，后来想到还是直接string简单点，把multiset<double>，换成了multiset<Node>了，Node里面包括了值和产生此值的表达式，看起来也还算不错。