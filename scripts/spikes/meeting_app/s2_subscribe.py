"""SPIKE S2: ONE subscription for every meeting the app is installed in, by RSC alone.

Usage: s2_subscribe.py <teams-app-id> <public-host>   (recordings + transcripts; 55-minute expiry)"""
import datetime as dt
import sys

from rsc import graph

app_id, host = sys.argv[1], sys.argv[2]
expiry = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=55)).strftime("%Y-%m-%dT%H:%M:%SZ")
for feed in ("getAllRecordings", "getAllTranscripts"):
    print(feed, *graph("POST", "/subscriptions", {
        "changeType": "created",
        "notificationUrl": f"https://{host}/graph/notifications",
        "lifecycleNotificationUrl": f"https://{host}/graph/lifecycle",
        "resource": f"appCatalogs/teamsApps/{app_id}/installedToOnlineMeetings/{feed}"
                    "?useResourceSpecificConsentBasedAuthorization=true",
        "expirationDateTime": expiry, "clientState": "spike"}))
