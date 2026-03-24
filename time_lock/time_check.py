from config import UNLOCK_TIME
from datetime import datetime

def is_time_valid():
    return datetime.now() >= UNLOCK_TIME