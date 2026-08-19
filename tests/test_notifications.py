from r2sync.notifications.notifier import NotificationManager


def test_notification_manager_dispatch():
    notifier = NotificationManager(app_id="r2sync-test")
    # Dispatches safely across platforms
    res = notifier.show_toast(
        title="Backup Complete",
        message="50 files backed up successfully.",
        notification_type="success",
    )
    assert res is True
