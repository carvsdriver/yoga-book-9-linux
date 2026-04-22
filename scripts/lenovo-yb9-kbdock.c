// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * Lenovo Yoga Book 9 keyboard-dock detection
 *
 * The Yoga Book 9 ships with a detachable Bluetooth keyboard that magnetically
 * attaches to the bottom screen in one of two positions.  The EC tracks
 * attachment state in a 2-bit field called BKBD and signals changes via WMI
 * event 0xEB on the WM10 ACPI device.
 *
 * BKBD values:
 *   0 = keyboard detached
 *   1 = keyboard docked on the top half of the bottom screen
 *   2 = keyboard docked on the bottom half of the bottom screen
 *   3 = reserved / not observed
 *
 * This driver registers for the WMI event GUID, queries BKBD on probe and on
 * each event, reports SW_TABLET_MODE=0 when the keyboard is docked (either
 * position) and SW_TABLET_MODE=1 when detached, and exposes the raw BKBD
 * value in sysfs as "keyboard_position".
 *
 * Copyright (C) 2026 Dave Carey <carvsdriver@gmail.com>
 */

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/acpi.h>
#include <linux/dmi.h>
#include <linux/input.h>
#include <linux/module.h>
#include <linux/wmi.h>

/*
 * WM10 ACPI device (_UID "GMZN"):
 *   Event GUID — notify ID 0xEB fires on keyboard attachment change.
 *   Query GUID — object "AF", maps to WQAF(); returns 8-byte buffer
 *                {LFID=0x00060000, BKBD[31:0]}.
 */
#define YB9_KBDOCK_EVENT_GUID	"806BD2A2-177B-481D-BFB5-3BA0BB4A2285"
#define YB9_KBDOCK_QUERY_GUID	"E7F300FA-21CD-4003-ADAC-2696135982E6"

#define YB9_KBDOCK_QUERY_INSTANCE	0

/* BKBD encoding — keyboard always docks on the bottom screen */
#define BKBD_DETACHED		0
#define BKBD_TOP_HALF		1	/* docked on top half of bottom screen */
#define BKBD_BOTTOM_HALF	2	/* docked on bottom half of bottom screen */

static const struct dmi_system_id yb9_kbdock_dmi_table[] = {
	{
		/* Lenovo Yoga Book 9 14IAH10 */
		.matches = {
			DMI_MATCH(DMI_SYS_VENDOR,   "LENOVO"),
			DMI_MATCH(DMI_PRODUCT_NAME, "83KJ"),
		},
	},
	{ }
};

struct yb9_kbdock_priv {
	struct input_dev *input_dev;
	unsigned int bkbd;	/* last read BKBD value (0-3) */
};

/* Read current BKBD state via WQAF.  Returns 0-3 or -errno. */
static int yb9_kbdock_query(struct wmi_device *wdev)
{
	struct acpi_buffer out = { ACPI_ALLOCATE_BUFFER, NULL };
	union acpi_object *obj;
	acpi_status status;
	u32 bkbd;

	status = wmi_query_block(YB9_KBDOCK_QUERY_GUID,
				 YB9_KBDOCK_QUERY_INSTANCE, &out);
	if (ACPI_FAILURE(status)) {
		dev_warn(&wdev->dev, "WQAF query failed: %s\n",
			 acpi_format_exception(status));
		return -EIO;
	}

	obj = out.pointer;
	if (!obj) {
		dev_warn(&wdev->dev, "WQAF returned NULL\n");
		return -EIO;
	}

	/*
	 * WQAF returns an 8-byte buffer: bytes [0..3] = LFID (0x00060000),
	 * bytes [4..7] = BKBD value.  Guard against short buffers.
	 */
	if (obj->type == ACPI_TYPE_BUFFER && obj->buffer.length >= 8) {
		memcpy(&bkbd, obj->buffer.pointer + 4, sizeof(bkbd));
		bkbd &= 0x3;
	} else if (obj->type == ACPI_TYPE_INTEGER) {
		bkbd = obj->integer.value & 0x3;
	} else {
		dev_warn(&wdev->dev,
			 "WQAF: unexpected result type %d len %u\n",
			 obj->type,
			 obj->type == ACPI_TYPE_BUFFER
				? obj->buffer.length : 0);
		kfree(obj);
		return -EIO;
	}

	kfree(obj);
	return (int)bkbd;
}

static void yb9_kbdock_update(struct wmi_device *wdev)
{
	struct yb9_kbdock_priv *priv = dev_get_drvdata(&wdev->dev);
	int bkbd;
	int tablet_mode;

	bkbd = yb9_kbdock_query(wdev);
	if (bkbd < 0)
		return;

	priv->bkbd = bkbd;

	/*
	 * Report tablet mode only when the keyboard is fully detached.
	 * Both docked positions (top-half and bottom-half of the bottom screen)
	 * indicate a physical keyboard is present — report laptop mode.
	 */
	tablet_mode = (bkbd == BKBD_DETACHED) ? 1 : 0;

	input_report_switch(priv->input_dev, SW_TABLET_MODE, tablet_mode);
	input_sync(priv->input_dev);

	dev_dbg(&wdev->dev, "BKBD=%u tablet_mode=%d\n", bkbd, tablet_mode);
}

static void yb9_kbdock_notify(struct wmi_device *wdev, union acpi_object *data)
{
	yb9_kbdock_update(wdev);
}

/* sysfs: keyboard_position — exposes raw BKBD value */
static ssize_t keyboard_position_show(struct device *dev,
				      struct device_attribute *attr, char *buf)
{
	struct yb9_kbdock_priv *priv = dev_get_drvdata(dev);
	static const char * const names[] = {
		"detached", "top-half", "bottom-half", "unknown"
	};
	unsigned int bkbd = priv->bkbd;

	if (bkbd > 3)
		bkbd = 3;
	return sysfs_emit(buf, "%u (%s)\n", bkbd, names[bkbd]);
}
static DEVICE_ATTR_RO(keyboard_position);

static struct attribute *yb9_kbdock_attrs[] = {
	&dev_attr_keyboard_position.attr,
	NULL,
};
ATTRIBUTE_GROUPS(yb9_kbdock);

static int yb9_kbdock_probe(struct wmi_device *wdev, const void *ctx)
{
	struct yb9_kbdock_priv *priv;
	struct input_dev *input_dev;
	int err;

	if (!dmi_check_system(yb9_kbdock_dmi_table)) {
		dev_dbg(&wdev->dev, "not a Yoga Book 9, skipping\n");
		return -ENODEV;
	}

	priv = devm_kzalloc(&wdev->dev, sizeof(*priv), GFP_KERNEL);
	if (!priv)
		return -ENOMEM;

	input_dev = devm_input_allocate_device(&wdev->dev);
	if (!input_dev)
		return -ENOMEM;

	input_dev->name = "Lenovo Yoga Book 9 keyboard dock switch";
	input_dev->phys = YB9_KBDOCK_EVENT_GUID "/input0";
	input_dev->id.bustype = BUS_HOST;
	input_dev->dev.parent = &wdev->dev;
	input_set_capability(input_dev, EV_SW, SW_TABLET_MODE);

	err = input_register_device(input_dev);
	if (err) {
		dev_err(&wdev->dev, "failed to register input device: %d\n", err);
		return err;
	}

	priv->input_dev = input_dev;
	dev_set_drvdata(&wdev->dev, priv);

	/* Report initial state */
	yb9_kbdock_update(wdev);
	return 0;
}

static const struct wmi_device_id yb9_kbdock_wmi_id_table[] = {
	{ .guid_string = YB9_KBDOCK_EVENT_GUID },
	{ }
};
MODULE_DEVICE_TABLE(wmi, yb9_kbdock_wmi_id_table);

static struct wmi_driver yb9_kbdock_driver = {
	.driver = {
		.name = "lenovo-yb9-kbdock",
		.dev_groups = yb9_kbdock_groups,
	},
	.id_table = yb9_kbdock_wmi_id_table,
	.probe    = yb9_kbdock_probe,
	.notify   = yb9_kbdock_notify,
};
module_wmi_driver(yb9_kbdock_driver);

MODULE_AUTHOR("Dave Carey <carvsdriver@gmail.com>");
MODULE_DESCRIPTION("Lenovo Yoga Book 9 keyboard dock detection");
MODULE_LICENSE("GPL");
