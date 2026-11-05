from datetime import datetime
from zoneinfo import ZoneInfo


def get_local_time():
    return datetime.now(ZoneInfo("Asia/Tbilisi"))
