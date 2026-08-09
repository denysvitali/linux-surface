#include <linux/module.h>
#include <linux/export-internal.h>
#include <linux/compiler.h>

MODULE_INFO(name, KBUILD_MODNAME);

__visible struct module __this_module
__section(".gnu.linkonce.this_module") = {
	.name = KBUILD_MODNAME,
	.init = init_module,
#ifdef CONFIG_MODULE_UNLOAD
	.exit = cleanup_module,
#endif
	.arch = MODULE_ARCH_INIT,
};

MODULE_INFO(intree, "Y");

KSYMTAB_DATA(slimbus_bus, "_gpl", "");
KSYMTAB_FUNC(__slim_driver_register, "_gpl", "");
KSYMTAB_FUNC(slim_driver_unregister, "_gpl", "");
KSYMTAB_FUNC(slim_register_controller, "_gpl", "");
KSYMTAB_FUNC(slim_unregister_controller, "_gpl", "");
KSYMTAB_FUNC(slim_report_absent, "_gpl", "");
KSYMTAB_FUNC(slim_get_device, "_gpl", "");
KSYMTAB_FUNC(of_slim_get_device, "_gpl", "");
KSYMTAB_FUNC(slim_device_report_present, "_gpl", "");
KSYMTAB_FUNC(slim_get_logical_addr, "_gpl", "");
KSYMTAB_FUNC(slim_msg_response, "_gpl", "");
KSYMTAB_FUNC(slim_alloc_txn_tid, "_gpl", "");
KSYMTAB_FUNC(slim_free_txn_tid, "_gpl", "");
KSYMTAB_FUNC(slim_do_transfer, "_gpl", "");
KSYMTAB_FUNC(slim_xfer_msg, "_gpl", "");
KSYMTAB_FUNC(slim_read, "_gpl", "");
KSYMTAB_FUNC(slim_readb, "_gpl", "");
KSYMTAB_FUNC(slim_write, "_gpl", "");
KSYMTAB_FUNC(slim_writeb, "_gpl", "");
KSYMTAB_FUNC(slim_ctrl_clk_pause, "_gpl", "");
KSYMTAB_FUNC(slim_stream_allocate, "_gpl", "");
KSYMTAB_FUNC(slim_stream_prepare, "_gpl", "");
KSYMTAB_FUNC(slim_stream_enable, "_gpl", "");
KSYMTAB_FUNC(slim_stream_disable, "_gpl", "");
KSYMTAB_FUNC(slim_stream_unprepare, "_gpl", "");
KSYMTAB_FUNC(slim_stream_free, "_gpl", "");

MODULE_INFO(depends, "");

