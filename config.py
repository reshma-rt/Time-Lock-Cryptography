from datetime import datetime, timedelta

UNLOCK_TIME = datetime.now() + timedelta(seconds=30)
REQUIRED_SHARES = 3