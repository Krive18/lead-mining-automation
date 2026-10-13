import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_config  # noqa: E402
from app.util.browser_profile_util import list_browser_profile_process_id, stop_process_id_list  # noqa: E402


def main() -> None:
    config = get_config()
    process_id_list = list_browser_profile_process_id(config.alibaba_1688_user_data_dir)
    if not process_id_list:
        print("没有发现 1688 采集专用浏览器进程。")
        return
    print(f"发现 1688 采集专用浏览器进程：{', '.join(str(item) for item in process_id_list)}")
    answer = input("确认关闭这些进程请输入 YES：").strip()
    if answer != "YES":
        print("已取消。")
        return
    stop_process_id_list(process_id_list)
    print("已关闭 1688 采集专用浏览器进程。")


if __name__ == "__main__":
    main()
