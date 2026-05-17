// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * Lenovo Yoga Book 9 keyboard-dock detection
 *
 * Reports SW_TABLET_MODE based on keyboard attachment state and exposes the
 * raw dock position via sysfs.
 *
 * Copyright (C) 2026 Dave Carey <carvsdriver@gmail.com>
 */

#define pr_fmt(fmt) KBUILD_MODNAME ": " fmt

#include <linux/acpi.h>
#include <linux/bitfield.h>
#include <linux/cleanup.h>
#include <linux/dmi.h>
#include <linux/input.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/wmi.h>

/*
 * WM10 ACPI device (_UID "GMZN") exposes two relevant WMI GUIDs:
 *   YB9_KBDOCK_EVENT_GUID — notify ID 0xEB fires on attachment state change.
 *   YB9_KBDOCK_QUERY_GUID — object "AF" (WQAF), returns an 8-byte buffer
 *                           whose upper four bytes hold the BKBD value.
 *
 * BKBD encoding:
 *   0 (BKBD_DETACHED)    — keyboard detached       → SW_TABLET_MODE = 1
 *   1 (BKBD_TOP_HALF)    — docked, top half        → SW_TABLET_MODE = 0
 *   2 (BKBD_BOTTOM_HALF) — docked, bottom half     → SW_TABLET_MODE = 0
 *   3                    — reserved; treated as an error
 */
#define YB9_KBDOCK_EVENT_GUID		"806BD2A2-177B-481D-BFB5-3BA0BB4A2285"
#define YB9_KBDOCK_QUERY_GUID		"E7F300FA-21CD-4003-ADAC-2696135982E6"
#define YB9_KBDOCK_QUERY_INSTANCE	0

#define BKBD_DETACHED		0
#define BKBD_TOP_HALF		1
#define BKBD_BOTTOM_HALF	2
#define BKBD_MASK		GENMASK(1, 0)

/* Distinguish the two GUIDs via the id_table context field. */
enum yb9_guid_type { YB9_GUID_EVENT, YB9_GUID_QUERY };

/*
 * Both GUIDs are children of the same ACPI device (WM10).  Store the query
 * WMI device globally so the event-device probe and notify path can reach it
 * via wmidev_block_query().  Protected by yb9_query_lock during probe/remove.
 */
static struct wmi_device *yb9_query_wdev;
static DEFINE_MUTEX(yb9_query_lock);

struct yb9_kbdock_priv {
	struct wmi_device *query_wdev;
	struct input_dev *input_dev;
	unsigned int bkbd;
};

/* Returns 0–2 on success, -errno on error. */
static int yb9_kbdock_query(struct wmi_device *event_wdev,
			     struct wmi_device *query_wdev)
{
	u32 bkbd;

	union acpi_object *obj __free(kfree) =
		wmidev_block_query(query_wdev, YB9_KBDOCK_QUERY_INSTANCE);
	if (!obj) {
		dev_warn(&event_wdev->dev, "WQAF query returned NULL\n");
		return -EIO;
	}

	/*
	 * WQAF returns an 8-byte buffer: bytes [0..3] = LFID (0x00060000),
	 * bytes [4..7] = BKBD value.  Guard against short buffers.
	 */
	if (obj->type == ACPI_TYPE_BUFFER && obj->buffer.length >= 8)
		memcpy(&bkbd, obj->buffer.pointer + 4, sizeof(bkbd));
	else if (obj->type == ACPI_TYPE_INTEGER)
		bkbd = obj->integer.value;
	else {
		dev_warn(&event_wdev->dev,
			 "WQAF: unexpected result type %d len %u\n",
			 obj->type, obj->type == ACPI_TYPE_BUFFER ? obj->buffer.length : 0);
		return -EIO;
	}

	bkbd = FIELD_GET(BKBD_MASK, bkbd);
	if (bkbd == 3) {
		dev_warn(&event_wdev->dev, "BKBD value 3 is reserved\n");
		return -EINVAL;
	}

	return bkbd;
}

static void yb9_kbdock_update(struct wmi_device *wdev)
{
	struct yb9_kbdock_priv *priv = dev_get_drvdata(&wdev->dev);
	int tablet_mode;
	int bkbd;

	bkbd = yb9_kbdock_query(wdev, priv->query_wdev);
	if (bkbd < 0)
		return;

	priv->bkbd = bkbd;
	tablet_mode = (bkbd == BKBD_DETACHED) ? 1 : 0;

	input_report_switch(priv->input_dev, SW_TABLET_MODE, tablet_mode);
	input_sync(priv->input_dev);

	dev_dbg(&wdev->dev, "BKBD=%u tablet_mode=%d\n", bkbd, tablet_mode);
}

static void yb9_kbdock_notify(struct wmi_device *wdev, union acpi_object *data)
{
	yb9_kbdock_update(wdev);
}

static ssize_t keyboard_position_show(struct device *dev,
				      struct device_attribute *attr, char *buf)
{
	static const char * const names[] = {
		"detached", "top-half", "bottom-half",
	};
	struct yb9_kbdock_priv *priv = dev_get_drvdata(dev);
	unsigned int bkbd = priv->bkbd;

	if (WARN_ON_ONCE(bkbd >= ARRAY_SIZE(names)))
		return -EINVAL;
	return sysfs_emit(buf, "%u (%s)\n", bkbd, names[bkbd]);
}
static DEVICE_ATTR_RO(keyboard_position);

static struct attribute *yb9_kbdock_attrs[] = {
	&dev_attr_keyboard_position.attr,
	NULL,
};
ATTRIBUTE_GROUPS(yb9_kbdock);

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

static int yb9_kbdock_probe(struct wmi_device *wdev, const void *ctx)
{
	enum yb9_guid_type type = (enum yb9_guid_type)(uintptr_t)ctx;
	struct yb9_kbdock_priv *priv;
	struct input_dev *input_dev;
	struct wmi_device *qwdev;
	int err;

	if (type == YB9_GUID_QUERY) {
		mutex_lock(&yb9_query_lock);
		yb9_query_wdev = wdev;
		mutex_unlock(&yb9_query_lock);
		return 0;
	}

	if (!dmi_check_system(yb9_kbdock_dmi_table))
		return -ENODEV;

	mutex_lock(&yb9_query_lock);
	qwdev = yb9_query_wdev;
	mutex_unlock(&yb9_query_lock);
	if (!qwdev)
		return -EPROBE_DEFER;

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

	priv->query_wdev = qwdev;
	priv->input_dev = input_dev;
	dev_set_drvdata(&wdev->dev, priv);

	yb9_kbdock_update(wdev);
	return 0;
}

static void yb9_kbdock_remove(struct wmi_device *wdev)
{
	mutex_lock(&yb9_query_lock);
	if (wdev == yb9_query_wdev)
		yb9_query_wdev = NULL;
	mutex_unlock(&yb9_query_lock);
}

static const struct wmi_device_id yb9_kbdock_wmi_id_table[] = {
	{ .guid_string = YB9_KBDOCK_EVENT_GUID, .context = (void *)YB9_GUID_EVENT },
	{ .guid_string = YB9_KBDOCK_QUERY_GUID, .context = (void *)YB9_GUID_QUERY },
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
	.remove   = yb9_kbdock_remove,
	.notify   = yb9_kbdock_notify,
};
module_wmi_driver(yb9_kbdock_driver);

MODULE_AUTHOR("Dave Carey <carvsdriver@gmail.com>");
MODULE_DESCRIPTION("Lenovo Yoga Book 9 keyboard dock detection");
MODULE_LICENSE("GPL");
