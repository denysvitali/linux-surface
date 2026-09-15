/* SPDX-License-Identifier: GPL-2.0 */
/*
 * Minimal ARM64 Image used only for the supervised watchdog-expiry proof.
 * It enters after kexec has quiesced Linux, masks every exception class and
 * intentionally makes no progress.  The already-armed APSS watchdog must be
 * the only path back to the unchanged spx-known-good GRUB default.
 */
	.section .text, "ax"
	.global _start
_start:
	b hang
	nop
	.quad 0x80000                 /* text_offset */
	.quad _image_end - _start     /* image_size */
	.quad 2                       /* little endian, 4 KiB pages */
	.quad 0
	.quad 0
	.quad 0
	.long 0x644d5241              /* ARM\x64 */
	.long 0
hang:
	msr daifset, #0xf
1:	wfe
	b 1b
	.balign 4096
_image_end:
