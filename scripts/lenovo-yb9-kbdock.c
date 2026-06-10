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
#include <linux/bitfield.h>
#include <linux/bits.h>
#include <linux/cleanup.h>
#include <linux/dev_printk.h>
#include <linux/dmi.h>
#include <linux/input.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/pm.h>
#include <linux/slab.h>
#include <linux/wmi.h>

#define YB9_KBDOCK_EVENT_GUID	"806BD2A2-177B-481D-BFB5-3BA0BB4A2285"
#define YB9_KBDOCK_QUERY_GUID	"E7F300FA-21CD-4003-ADAC-2696135982E6"

/* 2-bit EC field encoding the keyboard dock position */
#define BKBD_FIELD		GENMASK(1, 0)

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
	struct mutex lock; /* protects input_dev and block_wdev */
	struct input_dev *input_dev;	/* set by event probe */
	struct wmi_device *block_wdev;	/* set by block probe */
} yb9 = {
	.lock = __MUTEX_INITIALIZER(yb9.lock),
};

/**
 * yb9_kbdock_query_locked() - Read BKBD from the block device.
 * @log_dev: Device for logging.
 *
 * Context: Caller must hold yb9.lock.
 * Returns: 0-3 on success, -errno on failure.
 */
static int yb9_kbdock_query_locked(struct device *log_dev)
{
	struct wmi_buffer out = {};
	u32 bkbd;
	int ret;

	if (!yb9.block_wdev)
		return -ENODEV;

	ret = wmidev_query_block(yb9.block_wdev, 0, &out);
	if (ret) {
		dev_warn(log_dev, "WQAF failed: %d\n", ret);
		return ret;
	}

	u8 *data __free(kfree) = out.data;

	/*
	 * LENOVO_FEATURE_STATUS_DATA: 8-byte buffer {IDs=0x00060000, Status=BKBD}.
	 * BKBD is at bytes 4-7.
	 */
	if (out.length < 8) {
		dev_warn(log_dev, "WQAF: buffer too short (%zu)\n", out.length);
		return -EIO;
	}

	memcpy(&bkbd, data + 4, sizeof(bkbd));
	return FIELD_GET(BKBD_FIELD, bkbd);
}

/* Report SW_TABLET_MODE from BKBD.  Caller must hold yb9.lock. */
static void yb9_kbdock_report_locked(int bkbd, struct device *log_dev)
{
	int tablet = (bkbd == BKBD_DETACHED) ? 1 : 0;

	input_report_switch(yb9.input_dev, SW_TABLET_MODE, tablet);
	input_sync(yb9.input_dev);
	dev_dbg(log_dev, "BKBD=%d SW_TABLET_MODE=%d\n", bkbd, tablet);
}

/* Read BKBD and report if both WMI devices are ready.  Caller must hold yb9.lock. */
static void yb9_kbdock_sync_locked(struct device *log_dev)
{
	int bkbd;

	if (!yb9.input_dev || !yb9.block_wdev)
		return;

	bkbd = yb9_kbdock_query_locked(log_dev);
	if (bkbd >= 0)
		yb9_kbdock_report_locked(bkbd, log_dev);
}

/* ------------------------------------------------------------------
 * sysfs
 * ------------------------------------------------------------------ */

static ssize_t keyboard_position_show(struct device *dev,
				      struct device_attribute *attr, char *buf)
{
	int bkbd;

	guard(mutex)(&yb9.lock);
	bkbd = yb9_kbdock_query_locked(dev);
	if (bkbd < 0)
		return bkbd;
	return sysfs_emit(buf, "%d\n", bkbd);
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
	bkbd = FIELD_GET(BKBD_FIELD, data->integer.value);

	guard(mutex)(&yb9.lock);
	if (yb9.input_dev)
		yb9_kbdock_report_locked(bkbd, &wdev->dev);
}

static int yb9_kbdock_event_probe(struct wmi_device *wdev, const void *ctx)
{
	struct input_dev *input_dev;
	int err;

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

	guard(mutex)(&yb9.lock);
	yb9.input_dev = input_dev;
	yb9_kbdock_sync_locked(&wdev->dev);
	return 0;
}

static void yb9_kbdock_event_remove(struct wmi_device *wdev)
{
	guard(mutex)(&yb9.lock);
	yb9.input_dev = NULL;
}

static int yb9_kbdock_resume(struct device *dev)
{
	guard(mutex)(&yb9.lock);
	yb9_kbdock_sync_locked(dev);
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
	if (!dmi_check_system(yb9_kbdock_dmi_table))
		return -ENODEV;

	guard(mutex)(&yb9.lock);
	yb9.block_wdev = wdev;
	yb9_kbdock_sync_locked(&wdev->dev);
	return 0;
}

static void yb9_kbdock_block_remove(struct wmi_device *wdev)
{
	guard(mutex)(&yb9.lock);
	yb9.block_wdev = NULL;
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
