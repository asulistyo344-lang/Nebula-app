import firebase_admin
from firebase_admin import credentials, messaging
from typing import Optional
import logging
from config import settings

logger = logging.getLogger(__name__)
_initialized = False

def init_firebase():
    global _initialized
    if _initialized:
        return
    try:
        cred = credentials.Certificate(settings.FIREBASE_CREDENTIALS_PATH)
        firebase_admin.initialize_app(cred)
        _initialized = True
        logger.info("Firebase initialized")
    except Exception as e:
        logger.warning(f"Firebase init failed (push notifications disabled): {e}")

def send_signal_push(
    tokens: list[str],
    pair: str,
    direction: str,
    entry: Optional[float],
    signal_id: str,
) -> dict:
    """
    Send push notification to list of FCM tokens.
    Returns dict with success/failure counts.
    """
    if not _initialized or not tokens:
        return {"success": 0, "failure": 0}

    dir_emoji = "🟢▲" if direction == "LONG" else "🔴▼"
    entry_str = f"{entry:,.4f}".rstrip("0").rstrip(".") if entry else "—"

    notification = messaging.Notification(
        title=f"NEBULA · {pair} {dir_emoji}",
        body=f"{direction} signal · Entry {entry_str}",
    )

    data = {
        "signal_id": str(signal_id),
        "pair": pair,
        "direction": direction,
        "entry": str(entry) if entry else "",
        "type": "signal",
    }

    # Batch send (FCM allows up to 500 tokens per batch)
    success_count = 0
    failure_count = 0

    for i in range(0, len(tokens), 500):
        batch = tokens[i:i+500]
        message = messaging.MulticastMessage(
            notification=notification,
            data=data,
            tokens=batch,
            android=messaging.AndroidConfig(
                priority="high",
                notification=messaging.AndroidNotification(
                    sound="default",
                    channel_id="nebula_signals",
                ),
            ),
        )
        try:
            response = messaging.send_each_for_multicast(message)
            success_count += response.success_count
            failure_count += response.failure_count
        except Exception as e:
            logger.error(f"FCM batch send error: {e}")
            failure_count += len(batch)

    logger.info(f"FCM push sent: {success_count} success, {failure_count} failure")
    return {"success": success_count, "failure": failure_count}
