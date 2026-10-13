from datetime import datetime


def get_current_time_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_current_date_text() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def get_current_month_text() -> str:
    return datetime.now().strftime("%Y-%m")


def get_file_time_text() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")
