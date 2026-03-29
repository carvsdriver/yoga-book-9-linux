// SPDX-License-Identifier: GPL-2.0-only
/*
 * HID-BPF fixup for INGENIC 17EF:6161 touchscreen on Lenovo Yoga Book 9 14IAH10 (83KJ)
 *
 * Problem:
 *   hid-multitouch sets INPUT_PROP_BUTTONPAD when it detects BTN_LEFT in the
 *   HID descriptor (Usage Page: Button 0x09, Usage 0x01). This causes libinput
 *   to treat the touchscreen as a clickpad instead of a direct touch surface.
 *
 *   The descriptor has three button collections containing Usage 0x01 (BTN_LEFT):
 *     0xa42: in the touchpad/button report (report 0x50)
 *     0x33f: in the stylus report (report 0x14)
 *     0x69f: in the stylus report (report 0x28)
 *
 * Fix:
 *   Change Button Usage 0x01 -> 0x04 (BTN_SIDE) at all three locations.
 *   BTN_SIDE does not trigger INPUT_PROP_BUTTONPAD detection.
 *   The cert blobs are left intact to preserve HID_GROUP_MULTITOUCH_WIN_8
 *   and the named Touchscreen Top/Bottom input devices.
 *
 * Descriptor size: 2756 bytes.
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

SEC(HID_BPF_RDESC_FIXUP)
int BPF_PROG(hid_fix_rdesc_ingenic, struct hid_bpf_ctx *hctx)
{
	__u8 *data = hid_bpf_get_data(hctx, 0 /* offset */, 4096 /* size */);

	if (!data)
		return 0;

	/*
	 * Change Button Usage 0x01 (BTN_LEFT) -> 0x04 (BTN_SIDE)
	 * at all three occurrences to prevent INPUT_PROP_BUTTONPAD.
	 * Each is the byte immediately after the 0x09 Usage tag.
	 */
	if (data[0x33f] == 0x01)
		data[0x33f] = 0x04;

	if (data[0x69f] == 0x01)
		data[0x69f] = 0x04;

	if (data[0xa42] == 0x01)
		data[0xa42] = 0x04;

	return 0;
}

HID_BPF_OPS(ingenic_touchscreen) = {
	.hid_rdesc_fixup = (void *)hid_fix_rdesc_ingenic,
};

SEC("syscall")
int probe(struct hid_bpf_probe_args *ctx)
{
	ctx->retval = ctx->rdesc_size != 2756;
	if (ctx->retval)
		ctx->retval = -EINVAL;
	return 0;
}

char _license[] SEC("license") = "GPL";
