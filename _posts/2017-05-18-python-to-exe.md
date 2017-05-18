---
layout: post
title: "Python打包成exe"
description: "python2exe"
category: 技术
tags: [Python]
---
{% include JB/setup %}

这篇文章非常简单，主要做一下记录，以后方便查询。

Python简单易用经常被用来开发脚本。但是为了在其他地方运行，可能不仅需要安装Python解释器，
还得安装一些依赖库。这篇文章介绍一下使用pyinstaller打包exe的过程。
使用如下例子：

	#test.py
	import sys

	def main():
		print "Hello world"
		print sys.argv[0]
	if '__main__' == __name__:
		main()

首先安装pyinstaller:

	pip install pyinstaller

按照[官网](http://www.pyinstaller.org/)的说法，这个时候在Python的目录下使用

	pyinstaller test.py

就能够生产exe，虽然确实是在dist/test目录下面生成了exe，但是如果放到其他地方，会有错误：

	Error loading Python DLL: E:\study\python27.dll (error code 126)

可以使用如下命令解决：

	D:\Python27>pyinstaller --clean --win-private-assemblies -F test.py

这样在dist会生产exe，并且把需要的Python和相关的包全部打包，即可随意放到一个环境运行。

