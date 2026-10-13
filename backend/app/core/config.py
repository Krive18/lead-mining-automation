import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv


BACKEND_DIR = Path(__file__).resolve().parents[2]
WORKSPACE_DIR = BACKEND_DIR.parent
ENV_FILE_PATH = BACKEND_DIR / ".env"

load_dotenv(ENV_FILE_PATH)


@dataclass(frozen=True)
class AppConfig:
    app_name: str
    database_driver: str
    database_path: Path
    export_dir: Path
    log_dir: Path
    collector_batch_size: int
    collector_batch_cooldown_seconds: float
    enterprise_shareholder_expand_enabled: bool
    tianyancha_contact_expand_enabled: bool
    qcc_daily_quota: int
    qcc_monthly_quota: int
    qcc_api_key: str
    qcc_api_secret: str
    qixin_app_key: str
    qixin_secret_key: str
    qixin_base_url: str
    qixin_timeout_seconds: float
    qcc_public_web_headless: bool
    qcc_public_web_browser_channel: str
    qcc_public_web_page_timeout_ms: int
    qcc_public_web_request_interval_seconds: float
    qcc_public_web_manual_verify_enabled: bool
    qcc_public_web_manual_verify_timeout_seconds: int
    qcc_public_web_manual_verify_poll_seconds: float
    qcc_public_web_user_data_dir: Path
    fengniao_public_web_headless: bool
    fengniao_public_web_browser_channel: str
    fengniao_public_web_page_timeout_ms: int
    fengniao_public_web_request_interval_seconds: float
    fengniao_public_web_manual_verify_enabled: bool
    fengniao_public_web_manual_verify_timeout_seconds: int
    fengniao_public_web_manual_verify_poll_seconds: float
    fengniao_public_web_user_data_dir: Path
    douyin_public_web_headless: bool
    douyin_public_web_browser_channel: str
    douyin_public_web_page_timeout_ms: int
    douyin_public_web_request_interval_seconds: float
    douyin_public_web_manual_verify_enabled: bool
    douyin_public_web_manual_verify_timeout_seconds: int
    douyin_public_web_manual_verify_poll_seconds: float
    douyin_public_web_user_data_dir: Path
    allowed_origins: tuple
    mysql_host: str
    mysql_port: int
    mysql_user: str
    mysql_password: str
    mysql_database: str
    mysql_charset: str
    alibaba_1688_headless: bool
    alibaba_1688_browser_channel: str
    alibaba_1688_page_timeout_ms: int
    alibaba_1688_request_interval_seconds: float
    alibaba_tianyancha_enrich_delay_seconds: float
    alibaba_1688_detail_fallback_enabled: bool
    alibaba_1688_detail_fallback_limit: int
    alibaba_1688_manual_verify_enabled: bool
    alibaba_1688_manual_verify_timeout_seconds: int
    alibaba_1688_manual_verify_poll_seconds: float
    alibaba_1688_page_assistant_wait_seconds: int
    alibaba_1688_user_data_dir: Path
    alibaba_international_headless: bool
    alibaba_international_browser_channel: str
    alibaba_international_page_timeout_ms: int
    alibaba_international_request_interval_seconds: float
    alibaba_international_manual_verify_enabled: bool
    alibaba_international_user_data_dir: Path
    ai_page_recognition_enabled: bool
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    deepseek_timeout_seconds: float
    deepseek_max_input_chars: int
    web_search_provider: str
    web_search_api_key: str
    web_search_endpoint: str
    web_search_timeout_seconds: float
    web_search_request_interval_seconds: float
    web_search_max_results_per_query: int
    web_search_max_page_fetch_count: int


def parse_int(value: str, default_value: int) -> int:
    if value is None or value == "":
        return default_value
    try:
        return int(value)
    except ValueError:
        return default_value


def parse_float(value: str, default_value: float) -> float:
    if value is None or value == "":
        return default_value
    try:
        return float(value)
    except ValueError:
        return default_value


def parse_bool(value: str, default_value: bool) -> bool:
    if value is None or value == "":
        return default_value
    return value.lower() in ("1", "true", "yes", "on")


def resolve_workspace_path(value: str, default_path: Path) -> Path:
    if value is None or value == "":
        return default_path
    path = Path(value)
    if path.is_absolute():
        return path
    return WORKSPACE_DIR / path


@lru_cache
def get_config() -> AppConfig:
    database_path = resolve_workspace_path(
        os.getenv("LEAD_DATABASE_PATH"),
        BACKEND_DIR / "data" / "lead_mining.db",
    )
    export_dir = resolve_workspace_path(
        os.getenv("LEAD_EXPORT_DIR"),
        BACKEND_DIR / "exports",
    )
    log_dir = BACKEND_DIR / "logs"
    alibaba_1688_manual_verify_enabled = parse_bool(os.getenv("ALIBABA_1688_MANUAL_VERIFY_ENABLED"), True)
    default_alibaba_1688_headless = False if alibaba_1688_manual_verify_enabled else True
    alibaba_1688_user_data_dir = resolve_workspace_path(
        os.getenv("ALIBABA_1688_USER_DATA_DIR"),
        BACKEND_DIR / "data" / "browser-profile" / "1688",
    )
    alibaba_international_manual_verify_enabled = parse_bool(
        os.getenv("ALIBABA_INTERNATIONAL_MANUAL_VERIFY_ENABLED"),
        True,
    )
    default_alibaba_international_headless = False if alibaba_international_manual_verify_enabled else True
    alibaba_international_user_data_dir = resolve_workspace_path(
        os.getenv("ALIBABA_INTERNATIONAL_USER_DATA_DIR"),
        BACKEND_DIR / "data" / "browser-profile" / "alibaba-international",
    )
    qcc_public_web_manual_verify_enabled = parse_bool(os.getenv("QCC_PUBLIC_WEB_MANUAL_VERIFY_ENABLED"), True)
    default_qcc_public_web_headless = False if qcc_public_web_manual_verify_enabled else True
    qcc_public_web_user_data_dir = resolve_workspace_path(
        os.getenv("QCC_PUBLIC_WEB_USER_DATA_DIR"),
        BACKEND_DIR / "data" / "browser-profile" / "qcc",
    )
    fengniao_public_web_manual_verify_enabled = parse_bool(
        os.getenv("FENGNIAO_PUBLIC_WEB_MANUAL_VERIFY_ENABLED"),
        True,
    )
    default_fengniao_public_web_headless = False if fengniao_public_web_manual_verify_enabled else True
    fengniao_public_web_user_data_dir = resolve_workspace_path(
        os.getenv("FENGNIAO_PUBLIC_WEB_USER_DATA_DIR"),
        BACKEND_DIR / "data" / "browser-profile" / "fengniao",
    )
    douyin_public_web_manual_verify_enabled = parse_bool(
        os.getenv("DOUYIN_PUBLIC_WEB_MANUAL_VERIFY_ENABLED"),
        True,
    )
    default_douyin_public_web_headless = False if douyin_public_web_manual_verify_enabled else True
    douyin_public_web_user_data_dir = resolve_workspace_path(
        os.getenv("DOUYIN_PUBLIC_WEB_USER_DATA_DIR"),
        BACKEND_DIR / "data" / "browser-profile" / "douyin",
    )
    database_path.parent.mkdir(parents=True, exist_ok=True)
    export_dir.mkdir(parents=True, exist_ok=True)
    log_dir.mkdir(parents=True, exist_ok=True)
    alibaba_1688_user_data_dir.mkdir(parents=True, exist_ok=True)
    alibaba_international_user_data_dir.mkdir(parents=True, exist_ok=True)
    qcc_public_web_user_data_dir.mkdir(parents=True, exist_ok=True)
    fengniao_public_web_user_data_dir.mkdir(parents=True, exist_ok=True)
    douyin_public_web_user_data_dir.mkdir(parents=True, exist_ok=True)
    return AppConfig(
        app_name="lead-mining-local",
        database_driver=os.getenv("LEAD_DATABASE_DRIVER", "sqlite").lower(),
        database_path=database_path,
        export_dir=export_dir,
        log_dir=log_dir,
        collector_batch_size=parse_int(os.getenv("COLLECTOR_BATCH_SIZE"), 5),
        collector_batch_cooldown_seconds=parse_float(os.getenv("COLLECTOR_BATCH_COOLDOWN_SECONDS"), 45.0),
        enterprise_shareholder_expand_enabled=parse_bool(
            os.getenv("ENTERPRISE_SHAREHOLDER_EXPAND_ENABLED"),
            False,
        ),
        tianyancha_contact_expand_enabled=parse_bool(
            os.getenv("TIANYANCHA_CONTACT_EXPAND_ENABLED"),
            False,
        ),
        qcc_daily_quota=parse_int(os.getenv("QCC_DAILY_QUOTA"), 200),
        qcc_monthly_quota=parse_int(os.getenv("QCC_MONTHLY_QUOTA"), 5000),
        qcc_api_key=os.getenv("QCC_API_KEY", ""),
        qcc_api_secret=os.getenv("QCC_API_SECRET", ""),
        qixin_app_key=os.getenv("QIXIN_APP_KEY", ""),
        qixin_secret_key=os.getenv("QIXIN_SECRET_KEY", ""),
        qixin_base_url=os.getenv("QIXIN_BASE_URL", "https://api.qixin.com/APIService").rstrip("/"),
        qixin_timeout_seconds=parse_float(os.getenv("QIXIN_TIMEOUT_SECONDS"), 20.0),
        qcc_public_web_headless=parse_bool(os.getenv("QCC_PUBLIC_WEB_HEADLESS"), default_qcc_public_web_headless),
        qcc_public_web_browser_channel=os.getenv("QCC_PUBLIC_WEB_BROWSER_CHANNEL", "msedge"),
        qcc_public_web_page_timeout_ms=parse_int(os.getenv("QCC_PUBLIC_WEB_PAGE_TIMEOUT_MS"), 20000),
        qcc_public_web_request_interval_seconds=parse_float(
            os.getenv("QCC_PUBLIC_WEB_REQUEST_INTERVAL_SECONDS"),
            5.0,
        ),
        qcc_public_web_manual_verify_enabled=qcc_public_web_manual_verify_enabled,
        qcc_public_web_manual_verify_timeout_seconds=parse_int(
            os.getenv("QCC_PUBLIC_WEB_MANUAL_VERIFY_TIMEOUT_SECONDS"),
            300,
        ),
        qcc_public_web_manual_verify_poll_seconds=parse_float(
            os.getenv("QCC_PUBLIC_WEB_MANUAL_VERIFY_POLL_SECONDS"),
            2.0,
        ),
        qcc_public_web_user_data_dir=qcc_public_web_user_data_dir,
        fengniao_public_web_headless=parse_bool(
            os.getenv("FENGNIAO_PUBLIC_WEB_HEADLESS"),
            default_fengniao_public_web_headless,
        ),
        fengniao_public_web_browser_channel=os.getenv("FENGNIAO_PUBLIC_WEB_BROWSER_CHANNEL", "msedge"),
        fengniao_public_web_page_timeout_ms=parse_int(os.getenv("FENGNIAO_PUBLIC_WEB_PAGE_TIMEOUT_MS"), 20000),
        fengniao_public_web_request_interval_seconds=parse_float(
            os.getenv("FENGNIAO_PUBLIC_WEB_REQUEST_INTERVAL_SECONDS"),
            5.0,
        ),
        fengniao_public_web_manual_verify_enabled=fengniao_public_web_manual_verify_enabled,
        fengniao_public_web_manual_verify_timeout_seconds=parse_int(
            os.getenv("FENGNIAO_PUBLIC_WEB_MANUAL_VERIFY_TIMEOUT_SECONDS"),
            1800,
        ),
        fengniao_public_web_manual_verify_poll_seconds=parse_float(
            os.getenv("FENGNIAO_PUBLIC_WEB_MANUAL_VERIFY_POLL_SECONDS"),
            2.0,
        ),
        fengniao_public_web_user_data_dir=fengniao_public_web_user_data_dir,
        douyin_public_web_headless=parse_bool(
            os.getenv("DOUYIN_PUBLIC_WEB_HEADLESS"),
            default_douyin_public_web_headless,
        ),
        douyin_public_web_browser_channel=os.getenv("DOUYIN_PUBLIC_WEB_BROWSER_CHANNEL", "msedge"),
        douyin_public_web_page_timeout_ms=parse_int(os.getenv("DOUYIN_PUBLIC_WEB_PAGE_TIMEOUT_MS"), 20000),
        douyin_public_web_request_interval_seconds=parse_float(
            os.getenv("DOUYIN_PUBLIC_WEB_REQUEST_INTERVAL_SECONDS"),
            5.0,
        ),
        douyin_public_web_manual_verify_enabled=douyin_public_web_manual_verify_enabled,
        douyin_public_web_manual_verify_timeout_seconds=parse_int(
            os.getenv("DOUYIN_PUBLIC_WEB_MANUAL_VERIFY_TIMEOUT_SECONDS"),
            900,
        ),
        douyin_public_web_manual_verify_poll_seconds=parse_float(
            os.getenv("DOUYIN_PUBLIC_WEB_MANUAL_VERIFY_POLL_SECONDS"),
            2.0,
        ),
        douyin_public_web_user_data_dir=douyin_public_web_user_data_dir,
        allowed_origins=(
            "http://127.0.0.1:5173",
            "http://localhost:5173",
            "http://127.0.0.1:5174",
            "http://localhost:5174",
            "http://127.0.0.1:5175",
            "http://localhost:5175",
        ),
        mysql_host=os.getenv("MYSQL_HOST", "127.0.0.1"),
        mysql_port=parse_int(os.getenv("MYSQL_PORT"), 3306),
        mysql_user=os.getenv("MYSQL_USER", "root"),
        mysql_password=os.getenv("MYSQL_PASSWORD", ""),
        mysql_database=os.getenv("MYSQL_DATABASE", "lead_mining"),
        mysql_charset=os.getenv("MYSQL_CHARSET", "utf8mb4"),
        alibaba_1688_headless=parse_bool(os.getenv("ALIBABA_1688_HEADLESS"), default_alibaba_1688_headless),
        alibaba_1688_browser_channel=os.getenv("ALIBABA_1688_BROWSER_CHANNEL", "msedge"),
        alibaba_1688_page_timeout_ms=parse_int(os.getenv("ALIBABA_1688_PAGE_TIMEOUT_MS"), 20000),
        alibaba_1688_request_interval_seconds=parse_float(os.getenv("ALIBABA_1688_REQUEST_INTERVAL_SECONDS"), 18.0),
        alibaba_tianyancha_enrich_delay_seconds=parse_float(
            os.getenv("ALIBABA_TIANYANCHA_ENRICH_DELAY_SECONDS"),
            180.0,
        ),
        alibaba_1688_detail_fallback_enabled=parse_bool(
            os.getenv("ALIBABA_1688_DETAIL_FALLBACK_ENABLED"),
            False,
        ),
        alibaba_1688_detail_fallback_limit=parse_int(
            os.getenv("ALIBABA_1688_DETAIL_FALLBACK_LIMIT"),
            0,
        ),
        alibaba_1688_manual_verify_enabled=alibaba_1688_manual_verify_enabled,
        alibaba_1688_manual_verify_timeout_seconds=parse_int(
            os.getenv("ALIBABA_1688_MANUAL_VERIFY_TIMEOUT_SECONDS"),
            300,
        ),
        alibaba_1688_manual_verify_poll_seconds=parse_float(
            os.getenv("ALIBABA_1688_MANUAL_VERIFY_POLL_SECONDS"),
            2.0,
        ),
        alibaba_1688_page_assistant_wait_seconds=parse_int(
            os.getenv("ALIBABA_1688_PAGE_ASSISTANT_WAIT_SECONDS"),
            60,
        ),
        alibaba_1688_user_data_dir=alibaba_1688_user_data_dir,
        alibaba_international_headless=parse_bool(
            os.getenv("ALIBABA_INTERNATIONAL_HEADLESS"),
            default_alibaba_international_headless,
        ),
        alibaba_international_browser_channel=os.getenv("ALIBABA_INTERNATIONAL_BROWSER_CHANNEL", "msedge"),
        alibaba_international_page_timeout_ms=parse_int(
            os.getenv("ALIBABA_INTERNATIONAL_PAGE_TIMEOUT_MS"),
            25000,
        ),
        alibaba_international_request_interval_seconds=parse_float(
            os.getenv("ALIBABA_INTERNATIONAL_REQUEST_INTERVAL_SECONDS"),
            5.0,
        ),
        alibaba_international_manual_verify_enabled=alibaba_international_manual_verify_enabled,
        alibaba_international_user_data_dir=alibaba_international_user_data_dir,
        ai_page_recognition_enabled=parse_bool(os.getenv("AI_PAGE_RECOGNITION_ENABLED"), False),
        deepseek_api_key=os.getenv("DEEPSEEK_API_KEY", ""),
        deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/"),
        deepseek_model=os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"),
        deepseek_timeout_seconds=parse_float(os.getenv("DEEPSEEK_TIMEOUT_SECONDS"), 45.0),
        deepseek_max_input_chars=parse_int(os.getenv("DEEPSEEK_MAX_INPUT_CHARS"), 24000),
        web_search_provider=os.getenv("WEB_SEARCH_PROVIDER", "duckduckgo_html").lower(),
        web_search_api_key=os.getenv("WEB_SEARCH_API_KEY", ""),
        web_search_endpoint=os.getenv("WEB_SEARCH_ENDPOINT", ""),
        web_search_timeout_seconds=parse_float(os.getenv("WEB_SEARCH_TIMEOUT_SECONDS"), 20.0),
        web_search_request_interval_seconds=parse_float(os.getenv("WEB_SEARCH_REQUEST_INTERVAL_SECONDS"), 4.0),
        web_search_max_results_per_query=parse_int(os.getenv("WEB_SEARCH_MAX_RESULTS_PER_QUERY"), 8),
        web_search_max_page_fetch_count=parse_int(os.getenv("WEB_SEARCH_MAX_PAGE_FETCH_COUNT"), 40),
    )
