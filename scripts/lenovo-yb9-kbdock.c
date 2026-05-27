// SPDX-License-Identifier: GPL-2.0-or-later
/*
 * Lenovo Yoga Book 9 keyboard-dock detection
 *
 * The Yoga Book 9 ships with a detachable Bluetooth keyboard that magnetically
 * attaches to the bottom screen in one of two positions.  The EC tracks
 * attachment state in a 2-bit field called BKBD and signals changes via WMI
 * event 0xEB on the WM10 ACPI device (_UID "GMZN").
 *
 * BKBD values:
 *   0 = keyboard detached
 *   1 = keyboard docked on the top half of the bottom screen
 *   2 = keyboard docked on the bottom half of the bottom screen
 *   3 = reserved / not observed
 *
 * Two WMI interfaces are used (documented in embedded BMOF, WQDD, 20705 bytes):
 *
 *   LENOVO_BTKBD_EVENT (event GUID, 806BD2A2-...)
 *     WmiDataId(1) uint32 Status — _WED(0xEB) returns EC.BKBD directly.
 *     The notify callback receives BKBD as an integer; no separate query needed.
 *
 *   LENOVO_FEATURE_STATUS_DATA (block GUID, E7F300FA-...)
 *     WmiDataId(1) uint32 IDs   = 0x00060000 (feature selector)
 *     WmiDataId(2) uint32 Status = BKBD value
 *     Used on probe and resume to read initial state.
 *
 * SW_TABLET_MODE=1 is reported when the keyboard is detached;
 * SW_TABLET_MODE=0 when docked in either position (keyboard present).
 * The raw BKBD value is exposed via the sysfs attribute "keyboard_position".
 *
 * Copyright (C) 2026 Dave Carey <carvsdriver@gmail.com>
 */

#include <linux/acpi.h>
#include <linux/dmi.h>
#include <linux/input.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/pm.h>
#include <linux/wmi.h>

#define YB9_KBDOCK_EVENT_GUID	"806BD2A2-177B-481D-BFB5-3BA0BB4A2285"
#define YB9_KBDOCK_QUERY_GUID	"E7F300FA-21CD-4003-ADAC-2696135982E6"

/* BKBD encoding */
#define BKBD_DETACHED		0
#define BKBD_TOP_HALF		1
#define BKBD_BOTTOM_HALF	2

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

/*
 * Shared state between the event and block WMI drivers.  Protected by lock.
 * The lock may be held across wmidev_query_block() calls (which can sleep);
 * block_remove() acquires the lock before clearing block_wdev, ensuring
 * block_wdev remains valid for the duration of any in-progress query.
 */
static struct {
	struct mutex lock;
	struct input_dev *input_dev;	/* set by event probe */
	struct wmi_device *block_wdev;	/* set by block probe */
} yb9;

/*
 * Read BKBD from the block device via wmidev_block_query().
 * Returns 0-3 on success, -errno on failure.  Caller must hold yb9.lock.
 */
static int yb9_kbdock_query_locked(struct device *log_dev)
{
	union acpi_object *obj;
	u32 bkbd;

	if (!yb9.block_wdev)
		return -ENODEV;

	obj = wmidev_block_query(yb9.block_wdev, 0);
	if (!obj) {
		dev_warn(log_dev, "WQAF returned NULL\n");
		return -EIO;
	}

	/*
	 * LENOVO_FEATURE_STATUS_DATA: 8-byte buffer {IDs=0x00060000, Status=BKBD}.
	 */
	if (obj->type == ACPI_TYPE_BUFFER && obj->buffer.length >= 8) {
		memcpy(&bkbd, obj->buffer.pointer + 4, sizeof(bkbd));
		bkbd &= 0x3;
	} else if (obj->type == ACPI_TYPE_INTEGER) {
		bkbd = obj->integer.value & 0x3;
	} else {
		dev_warn(log_dev, "WQAF: unexpected type %d len %u\n",
			 obj->type,
			 obj->type == ACPI_TYPE_BUFFER ? obj->buffer.length : 0);
		kfree(obj);
		return -EIO;
	}

	kfree(obj);
	return (int)bkbd;
}

/* Report SW_TABLET_MODE from BKBD.  Caller must hold yb9.lock. */
static void yb9_kbdock_report_locked(int bkbd, struct device *log_dev)
{
	int tablet = (bkbd == BKBD_DETACHED) ? 1 : 0;

	input_report_switch(yb9.input_dev, SW_TABLET_MODE, tablet);
	input_sync(yb9.input_dev);
	dev_dbg(log_dev, "BKBD=%d SW_TABLET_MODE=%d\n", bkbd, tablet);
}

/* ------------------------------------------------------------------
 * sysfs
 * ------------------------------------------------------------------ */

static ssize_t keyboard_position_show(struct device *dev,
				      struct device_attribute *attr, char *buf)
{
	int bkbd;

	mutex_lock(&yb9.lock);
	bkbd = yb9_kbdock_query_locked(dev);
	mutex_unlock(&yb9.lock);

	if (bkbd < 0)
		return bkbd;
	return sysfs_emit(buf, "%u\n", (unsigned int)bkbd);
}
static DEVICE_ATTR_RO(keyboard_position);

static struct attribute *yb9_kbdock_attrs[] = {
	&dev_attr_keyboard_position.attr,
	NULL,
};
ATTRIBUTE_GROUPS(yb9_kbdock);

/* ------------------------------------------------------------------
 * Event WMI driver — LENOVO_BTKBD_EVENT
 * ------------------------------------------------------------------ */

static void yb9_kbdock_notify(struct wmi_device *wdev, union acpi_object *data)
{
	u32 bkbd;

	/*
	 * _WED(0xEB) returns EC.BKBD directly as an integer
	 * (LENOVO_BTKBD_EVENT WmiDataId(1) uint32 Status).
	 */
	if (!data || data->type != ACPI_TYPE_INTEGER) {
		dev_warn(&wdev->dev, "unexpected event data type %d\n",
			 data ? data->type : -1);
		return;
	}
	bkbd = data->integer.value & 0x3;

	mutex_lock(&yb9.lock);
	if (yb9.input_dev)
		yb9_kbdock_report_locked(bkbd, &wdev->dev);
	mutex_unlock(&yb9.lock);
}

static int yb9_kbdock_event_probe(struct wmi_device *wdev, const void *ctx)
{
	struct input_dev *input_dev;
	int bkbd, err;

	if (!dmi_check_system(yb9_kbdock_dmi_table))
		return -ENODEV;

	input_dev = devm_input_allocate_device(&wdev->dev);
	if (!input_dev)
		return -ENOMEM;

	input_dev->name = "Lenovo Yoga Book 9 keyboard dock switch";
	input_dev->phys = YB9_KBDOCK_EVENT_GUID "/input0";
	input_dev->id.bustype = BUS_HOST;
	input_set_capability(input_dev, EV_SW, SW_TABLET_MODE);

	err = input_register_device(input_dev);
	if (err)
		return err;

	mutex_lock(&yb9.lock);
	yb9.input_dev = input_dev;
	/* Read initial state if the block device has already probed. */
	if (yb9.block_wdev) {
		bkbd = yb9_kbdock_query_locked(&wdev->dev);
		if (bkbd >= 0)
			yb9_kbdock_report_locked(bkbd, &wdev->dev);
	}
	mutex_unlock(&yb9.lock);

	return 0;
}

static void yb9_kbdock_event_remove(struct wmi_device *wdev)
{
	mutex_lock(&yb9.lock);
	yb9.input_dev = NULL;
	mutex_unlock(&yb9.lock);
}

static int yb9_kbdock_resume(struct device *dev)
{
	int bkbd;

	mutex_lock(&yb9.lock);
	if (yb9.input_dev && yb9.block_wdev) {
		bkbd = yb9_kbdock_query_locked(dev);
		if (bkbd >= 0)
			yb9_kbdock_report_locked(bkbd, dev);
	}
	mutex_unlock(&yb9.lock);
	return 0;
}

static DEFINE_SIMPLE_DEV_PM_OPS(yb9_kbdock_pm_ops, NULL, yb9_kbdock_resume);

static const struct wmi_device_id yb9_kbdock_event_id_table[] = {
	{ .guid_string = YB9_KBDOCK_EVENT_GUID },
	{ }
};
MODULE_DEVICE_TABLE(wmi, yb9_kbdock_event_id_table);

static struct wmi_driver yb9_kbdock_event_driver = {
	.driver = {
		.name = "lenovo-yb9-kbdock",
		.dev_groups = yb9_kbdock_groups,
		.pm = pm_sleep_ptr(&yb9_kbdock_pm_ops),
	},
	.id_table = yb9_kbdock_event_id_table,
	.no_singleton = true,
	.probe = yb9_kbdock_event_probe,
	.remove = yb9_kbdock_event_remove,
	.notify = yb9_kbdock_notify,
};

/* ------------------------------------------------------------------
 * Block WMI driver — LENOVO_FEATURE_STATUS_DATA
 * ------------------------------------------------------------------ */

static int yb9_kbdock_block_probe(struct wmi_device *wdev, const void *ctx)
{
	int bkbd;

	if (!dmi_check_system(yb9_kbdock_dmi_table))
		return -ENODEV;

	mutex_lock(&yb9.lock);
	yb9.block_wdev = wdev;
	/* Read initial state if the event device has already probed. */
	if (yb9.input_dev) {
		bkbd = yb9_kbdock_query_locked(&wdev->dev);
		if (bkbd >= 0)
			yb9_kbdock_report_locked(bkbd, &wdev->dev);
	}
	mutex_unlock(&yb9.lock);
	return 0;
}

static void yb9_kbdock_block_remove(struct wmi_device *wdev)
{
	mutex_lock(&yb9.lock);
	yb9.block_wdev = NULL;
	mutex_unlock(&yb9.lock);
}

static const struct wmi_device_id yb9_kbdock_block_id_table[] = {
	{ .guid_string = YB9_KBDOCK_QUERY_GUID },
	{ }
};

static struct wmi_driver yb9_kbdock_block_driver = {
	.driver = {
		.name = "lenovo-yb9-kbdock-block",
	},
	.id_table = yb9_kbdock_block_id_table,
	.no_singleton = true,
	.probe = yb9_kbdock_block_probe,
	.remove = yb9_kbdock_block_remove,
};

/* ------------------------------------------------------------------
 * Module init / exit
 * ------------------------------------------------------------------ */

static int __init yb9_kbdock_init(void)
{
	int ret;

	mutex_init(&yb9.lock);

	ret = wmi_driver_register(&yb9_kbdock_event_driver);
	if (ret)
		return ret;

	ret = wmi_driver_register(&yb9_kbdock_block_driver);
	if (ret) {
		wmi_driver_unregister(&yb9_kbdock_event_driver);
		return ret;
	}
	return 0;
}
module_init(yb9_kbdock_init);

static void __exit yb9_kbdock_exit(void)
{
	wmi_driver_unregister(&yb9_kbdock_block_driver);
	wmi_driver_unregister(&yb9_kbdock_event_driver);
}
module_exit(yb9_kbdock_exit);

MODULE_AUTHOR("Dave Carey <carvsdriver@gmail.com>");
MODULE_DESCRIPTION("Lenovo Yoga Book 9 keyboard dock detection");
MODULE_LICENSE("GPL");
