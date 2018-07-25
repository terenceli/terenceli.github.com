---
layout: post
title: "Add a new qmp command for qemu "
description: "add qmp command"
category: 技术
tags: [qemu]
---
{% include JB/setup %}

There is a detail [documentation](https://github.com/qemu/qemu/blob/master/docs/devel/writing-qmp-commands.txt) for writing a new qmp command for qemu, I just make a note for this. As the documnetation said, to create a new qmp command needs the following four steps:

1. Define the command and any types it needs in the appropriate QAPI
   schema module.

2. Write the QMP command itself, which is a regular C function. Preferably,
   the command should be exported by some QEMU subsystem. But it can also be
   added to the qmp.c file

3. At this point the command can be tested under the QMP protocol

4. Write the HMP command equivalent. This is not required and should only be
   done if it does make sense to have the functionality in HMP. The HMP command
   is implemented in terms of the QMP command

The first step is to add the command in qapi-schema.json file. Add following command to the last of the file:

	{ 'command': 'qmp-test', 'data': {'value': 'int'} }

Second, add the QMP processing function, add following function to qmp.c file:

	unsigned int test_a = 0;

	void qmp_qmp_test(int64_t value, Error **errp)
	{
		if (value > 100 || value < 0)
		{
			error_setg(errp, QERR_INVALID_PARAMETER_VALUE, "value a", "not valid");
			return;
		}
		test_a = value;
	}

At this time, we can send qmp command to qemu. 

	{"execute":"qmp-test","arguments":{"value":80}}

Also we often want to send more human readable command, so we can add hmp command.

Add following to hmp-commands.hx in the middle of it:

	{
			.name       = "qmp-test",
			.args_type  = "value:i",
			.params     = "value",
			.help       = "set test a.",
			.cmd        = hmp_qmp_test,
		},

	STEXI
	@item qmp-test  @var{value}
	Set test a to @var{value}.
	ETEXI

Add following to last of hmp.c file:

	void hmp_qmp_test(Monitor *mon, const QDict *qdict)
	{
		int64_t value = qdict_get_int(qdict, "value");
		qmp_qmp_test(value, NULL);
	}

Add following to last of hmp.h file:

	void hmp_qmp_test(Monitor *mon, const QDict *qdict);

After compile the qemu, we can use 'qmp-test 80' command in the monitor.

