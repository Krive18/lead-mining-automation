import argparse
import sys
from pathlib import Path
from urllib.parse import quote_plus

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import get_config  # noqa: E402
from app.util.browser_profile_util import list_browser_profile_process_id  # noqa: E402


def build_start_url(keyword: str) -> str:
    if not keyword:
        return "https://www.1688.com/"
    return f"https://s.1688.com/company/company_search.htm?keywords={quote_plus(keyword)}"


def open_browser(keyword: str) -> None:
    config = get_config()
    process_id_list = list_browser_profile_process_id(config.alibaba_1688_user_data_dir)
    if process_id_list:
        process_text = ", ".join(str(process_id) for process_id in process_id_list)
        raise RuntimeError(f"1688 采集专用浏览器仍在运行，请先关闭后再预热。进程：{process_text}")
    context_args = {
        "headless": False,
        "locale": "zh-CN",
        "viewport": {"width": 1366, "height": 900},
    }
    if config.alibaba_1688_browser_channel:
        context_args["channel"] = config.alibaba_1688_browser_channel

    with sync_playwright() as playwright:
        try:
            context = playwright.chromium.launch_persistent_context(
                str(config.alibaba_1688_user_data_dir),
                **context_args,
            )
        except PlaywrightError:
            if "channel" not in context_args:
                raise
            context_args.pop("channel")
            context = playwright.chromium.launch_persistent_context(
                str(config.alibaba_1688_user_data_dir),
                **context_args,
            )

        page = context.new_page()
        page.goto(build_start_url(keyword), wait_until="domcontentloaded", timeout=30000)
        print("")
        print("1688 预热浏览器已打开。")
        print("请在打开的 Edge 窗口里手动登录、完成平台正常验证，并手动搜索/打开几个公开店铺页面。")
        print("确认不再出现“遇到问题/看不见验证码”的反馈页后，回到这里按 Enter 关闭浏览器。")
        print("随后再回到系统启动 1688 公开页面采集任务。")
        print("")
        input("完成预热后按 Enter：")
        context.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="打开 1688 采集共用浏览器资料目录，用于人工登录和预热。")
    parser.add_argument("--keyword", default="", help="可选，打开 1688 公司搜索关键词页，例如：服装工厂")
    args = parser.parse_args()
    open_browser(args.keyword.strip())


if __name__ == "__main__":
    main()
