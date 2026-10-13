import argparse
import time

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from app.core.config import get_config
from app.core.constant import (
    SOURCE_TYPE_ALIBABA_1688,
    SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
    SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB,
)


def build_warmup_config(source_type: str):
    config = get_config()
    if source_type == SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB:
        return {
            "display_name": "tianyancha",
            "url": "https://www.tianyancha.com/search?key=%E6%9C%8D%E8%A3%85%E5%B7%A5%E5%8E%82",
            "user_data_dir": config.qcc_public_web_user_data_dir.parent / "tianyancha",
            "browser_channel": config.qcc_public_web_browser_channel,
            "page_timeout_ms": config.qcc_public_web_page_timeout_ms,
        }
    if source_type == SOURCE_TYPE_ALIBABA_1688:
        return {
            "display_name": "1688",
            "url": "https://login.1688.com/member/signin.htm",
            "user_data_dir": config.alibaba_1688_user_data_dir,
            "browser_channel": config.alibaba_1688_browser_channel,
            "page_timeout_ms": config.alibaba_1688_page_timeout_ms,
        }
    if source_type == SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA:
        return {
            "display_name": "made-in-china",
            "url": "https://cn.made-in-china.com/",
            "user_data_dir": config.qcc_public_web_user_data_dir.parent / "made-in-china",
            "browser_channel": config.qcc_public_web_browser_channel,
            "page_timeout_ms": config.qcc_public_web_page_timeout_ms,
        }
    raise RuntimeError(f"Unsupported warmup source_type: {source_type}")


def launch_warmup_browser(source_type: str) -> None:
    warmup_config = build_warmup_config(source_type)
    warmup_config["user_data_dir"].mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        context_args = {
            "headless": False,
            "locale": "zh-CN",
            "viewport": {"width": 1366, "height": 900},
        }
        if warmup_config["browser_channel"]:
            context_args["channel"] = warmup_config["browser_channel"]
        try:
            context = playwright.chromium.launch_persistent_context(
                str(warmup_config["user_data_dir"]),
                **context_args,
            )
        except PlaywrightError:
            context_args.pop("channel", None)
            context = playwright.chromium.launch_persistent_context(
                str(warmup_config["user_data_dir"]),
                **context_args,
            )

        try:
            page = context.pages[0] if context.pages else context.new_page()
            try:
                page.goto(
                    warmup_config["url"],
                    wait_until="domcontentloaded",
                    timeout=warmup_config["page_timeout_ms"],
                )
            except PlaywrightTimeoutError:
                pass
            except PlaywrightError:
                pass
            print(f"{warmup_config['display_name']} warmup browser opened. Close it after login or verification.")
            while True:
                try:
                    if not context.pages:
                        break
                    time.sleep(1)
                except PlaywrightError:
                    break
        finally:
            try:
                context.close()
            except PlaywrightError:
                pass


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-type", required=True)
    args = parser.parse_args()
    launch_warmup_browser(args.source_type)


if __name__ == "__main__":
    main()
