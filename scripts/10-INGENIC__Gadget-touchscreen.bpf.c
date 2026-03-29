// SPDX-License-Identifier: GPL-2.0-only
/*
 * HID-BPF fixup for INGENIC 17EF:6161 touchscreen on Lenovo Yoga Book 9 14IAH10 (83KJ)
 *
 * Problem:
 *   The report descriptor contains a Microsoft Precision Touchpad certification
 *   blob (Usage 0xc5 in vendor page 0xff00, report 0x32). hid-core detects this
 *   and sets HID_GROUP_MULTITOUCH_WIN_8, causing hid-multitouch to apply
 *   MT_CLS_WIN_8 which unconditionally sets INPUT_PROP_BUTTONPAD. This makes
 *   libinput treat the touchscreen as a clickpad instead of a direct touch surface.
 *
 * Fix:
 *   Patch Usage 0xc5 -> 0xc6 at offset 0x352 in the first report collection
 *   (report 0x30). This prevents WIN_8 group detection so hid-multitouch falls
 *   back to plain touchscreen handling with INPUT_PROP_DIRECT.
 *
 *   The same certification blob appears again in the second collection (report 0x38)
 *   and is patched at offset 0x6a2 (same relative position + 0x360 collection offset).
 *
 * Verified: After patch, INPUT_PROP_BUTTONPAD is cleared, INPUT_PROP_DIRECT is set,
 * and libinput correctly identifies both screens as touch devices.
 */

#include "vmlinux.h"
#include "hid_bpf.h"
#include "hid_bpf_helpers.h"
#include <bpf/bpf_tracing.h>

#define VID_INGENIC  0x17EF
#define PID_YB9      0x6161

HID_BPF_CONFIG(
	HID_DEVICE(BUS_USB, HID_GROUP_MULTITOUCH_WIN_8, VID_INGENIC, PID_YB9)
);

/*
 * Patch the Microsoft cert blob usage out of the descriptor so hid-core
 * doesn't classify this as HID_GROUP_MULTITOUCH_WIN_8.
 *
 * Offset 0x352: Usage byte for the cert feature report in collection 0x30
 * Offset 0x6a2: Same field in collection 0x38 (second screen)
 * Change 0xc5 -> 0xc6 to avoid the WIN_8 detection.
 */
SEC(HID_BPF_RDESC_FIXUP)
int BPF_PROG(hid_fix_rdesc_ingenic, struct hid_bpf_ctx *hctx)
{
	__u8 *data = hid_bpf_get_data(hctx, 0 /* offset */, 4096 /* size */);

	if (!data)
		return 0;

	/* First collection (report 0x30): cert blob at 0x352 */
	if (data[0x352] == 0xc5)
		data[0x352] = 0xc6;

	/* Second collection (report 0x38): cert blob at 0x6a2 */
	if (data[0x6a2] == 0xc5)
		data[0x6a2] = 0xc6;

	return 0;
}

HID_BPF_OPS(ingenic_touchscreen) = {
	.hid_rdesc_fixup = (void *)hid_fix_rdesc_ingenic,
};

SEC("syscall")
int probe(struct hid_bpf_probe_args *ctx)
{
	/* Only attach to the multitouch interface (descriptor size 2756 bytes) */
	ctx->retval = ctx->rdesc_size != 2756;
	if (ctx->retval)
		ctx->retval = -EINVAL;
	return 0;
}

char _license[] SEC("license") = "GPL";
