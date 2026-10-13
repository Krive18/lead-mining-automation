import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.core.config import get_config
from app.util.time_util import get_current_time_text

try:
    import pymysql
except ImportError:
    pymysql = None

DATABASE_DRIVER_SQLITE = "sqlite"
DATABASE_DRIVER_MYSQL = "mysql"
WORKSPACE_DIR = Path(__file__).resolve().parents[3]
MYSQL_INIT_SQL_PATH = WORKSPACE_DIR / "database" / "init.sql"

SQLITE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS lead_task (
    id TEXT PRIMARY KEY,
    task_name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    industry TEXT NOT NULL,
    keyword_text TEXT NOT NULL,
    target_city TEXT NOT NULL DEFAULT '',
    collect_limit INTEGER NOT NULL,
    is_qcc_enabled INTEGER NOT NULL DEFAULT 1,
    qcc_limit INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    total_count INTEGER NOT NULL DEFAULT 0,
    success_count INTEGER NOT NULL DEFAULT 0,
    failed_count INTEGER NOT NULL DEFAULT 0,
    gmt_create TEXT NOT NULL,
    gmt_modified TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lead_record (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_keyword TEXT NOT NULL,
    industry TEXT NOT NULL,
    suspected_company_name TEXT NOT NULL,
    company_name TEXT NOT NULL,
    company_name_en TEXT NOT NULL DEFAULT '',
    douyin_nickname TEXT NOT NULL DEFAULT '',
    product_name TEXT NOT NULL DEFAULT '',
    shop_level TEXT NOT NULL DEFAULT '',
    contact_name TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    phone_source TEXT NOT NULL DEFAULT '',
    website_url TEXT NOT NULL DEFAULT '',
    shop_url TEXT NOT NULL DEFAULT '',
    profile_url TEXT NOT NULL DEFAULT '',
    sample_video_url TEXT NOT NULL DEFAULT '',
    is_blue_v INTEGER NOT NULL DEFAULT 0,
    is_enterprise_verified INTEGER NOT NULL DEFAULT 0,
    company_status TEXT NOT NULL DEFAULT '',
    unified_social_credit_code TEXT NOT NULL DEFAULT '',
    legal_person TEXT NOT NULL DEFAULT '',
    business_scope TEXT NOT NULL DEFAULT '',
    registered_address TEXT NOT NULL DEFAULT '',
    province TEXT NOT NULL DEFAULT '',
    city TEXT NOT NULL DEFAULT '',
    district TEXT NOT NULL DEFAULT '',
    city_source TEXT NOT NULL DEFAULT '',
    city_confidence TEXT NOT NULL DEFAULT '',
    risk_tag TEXT NOT NULL DEFAULT '',
    verification_status TEXT NOT NULL,
    confidence TEXT NOT NULL,
    score INTEGER NOT NULL DEFAULT 0,
    level TEXT NOT NULL,
    assignment_status TEXT NOT NULL DEFAULT 'unassigned',
    gmt_create TEXT NOT NULL,
    gmt_modified TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS qcc_usage_log (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    company_name TEXT NOT NULL,
    interface_name TEXT NOT NULL,
    consume_count INTEGER NOT NULL DEFAULT 1,
    is_success INTEGER NOT NULL DEFAULT 1,
    failure_reason TEXT NOT NULL DEFAULT '',
    gmt_create TEXT NOT NULL,
    gmt_modified TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS task_event_log (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    event_level TEXT NOT NULL,
    event_message TEXT NOT NULL,
    gmt_create TEXT NOT NULL,
    gmt_modified TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS keyword_config (
    id TEXT PRIMARY KEY,
    industry TEXT NOT NULL,
    keyword TEXT NOT NULL,
    keyword_type TEXT NOT NULL,
    is_enabled INTEGER NOT NULL DEFAULT 1,
    gmt_create TEXT NOT NULL,
    gmt_modified TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lead_record_task_id ON lead_record(task_id);
CREATE INDEX IF NOT EXISTS idx_lead_record_company_name ON lead_record(company_name);
CREATE INDEX IF NOT EXISTS idx_lead_record_level ON lead_record(level);
CREATE INDEX IF NOT EXISTS idx_lead_record_assignment_status ON lead_record(assignment_status);
CREATE INDEX IF NOT EXISTS idx_qcc_usage_log_gmt_create ON qcc_usage_log(gmt_create);
CREATE INDEX IF NOT EXISTS idx_task_event_log_task_id ON task_event_log(task_id);

CREATE TABLE IF NOT EXISTS system_config (
    id TEXT PRIMARY KEY,
    config_key TEXT NOT NULL UNIQUE,
    config_value TEXT NOT NULL,
    remark TEXT NOT NULL DEFAULT '',
    gmt_create TEXT NOT NULL,
    gmt_modified TEXT NOT NULL
);
"""

MYSQL_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS lead_task (
    id VARCHAR(64) PRIMARY KEY,
    task_name VARCHAR(128) NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    industry VARCHAR(32) NOT NULL,
    keyword_text TEXT NOT NULL,
    target_city VARCHAR(255) NOT NULL DEFAULT '',
    collect_limit INT NOT NULL,
    is_qcc_enabled TINYINT NOT NULL DEFAULT 1,
    qcc_limit INT NOT NULL DEFAULT 0,
    status VARCHAR(32) NOT NULL,
    total_count INT NOT NULL DEFAULT 0,
    success_count INT NOT NULL DEFAULT 0,
    failed_count INT NOT NULL DEFAULT 0,
    gmt_create DATETIME NOT NULL,
    gmt_modified DATETIME NOT NULL,
    INDEX idx_lead_task_gmt_create (gmt_create),
    INDEX idx_lead_task_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS lead_record (
    id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL,
    source_type VARCHAR(32) NOT NULL,
    source_keyword VARCHAR(128) NOT NULL,
    industry VARCHAR(32) NOT NULL,
    suspected_company_name VARCHAR(128) NOT NULL,
    company_name VARCHAR(128) NOT NULL,
    company_name_en VARCHAR(255) NOT NULL DEFAULT '',
    douyin_nickname VARCHAR(128) NOT NULL DEFAULT '',
    product_name VARCHAR(128) NOT NULL DEFAULT '',
    shop_level VARCHAR(255) NOT NULL DEFAULT '',
    contact_name VARCHAR(64) NOT NULL DEFAULT '',
    phone VARCHAR(512) NOT NULL DEFAULT '',
    phone_source VARCHAR(64) NOT NULL DEFAULT '',
    website_url VARCHAR(512) NOT NULL DEFAULT '',
    shop_url VARCHAR(512) NOT NULL DEFAULT '',
    profile_url VARCHAR(512) NOT NULL DEFAULT '',
    sample_video_url VARCHAR(512) NOT NULL DEFAULT '',
    is_blue_v TINYINT NOT NULL DEFAULT 0,
    is_enterprise_verified TINYINT NOT NULL DEFAULT 0,
    company_status VARCHAR(32) NOT NULL DEFAULT '',
    unified_social_credit_code VARCHAR(18) NOT NULL DEFAULT '',
    legal_person VARCHAR(64) NOT NULL DEFAULT '',
    business_scope TEXT NOT NULL,
    registered_address VARCHAR(256) NOT NULL DEFAULT '',
    province VARCHAR(32) NOT NULL DEFAULT '',
    city VARCHAR(32) NOT NULL DEFAULT '',
    district VARCHAR(64) NOT NULL DEFAULT '',
    city_source VARCHAR(64) NOT NULL DEFAULT '',
    city_confidence VARCHAR(16) NOT NULL DEFAULT '',
    risk_tag VARCHAR(128) NOT NULL DEFAULT '',
    verification_status VARCHAR(32) NOT NULL,
    confidence VARCHAR(32) NOT NULL,
    score INT NOT NULL DEFAULT 0,
    level VARCHAR(8) NOT NULL,
    assignment_status VARCHAR(32) NOT NULL DEFAULT 'unassigned' COMMENT '线索分发状态：unassigned=未分配，assigned=已分配',
    gmt_create DATETIME NOT NULL,
    gmt_modified DATETIME NOT NULL,
    INDEX idx_lead_record_task_id (task_id),
    INDEX idx_lead_record_company_name (company_name),
    INDEX idx_lead_record_level (level),
    INDEX idx_lead_record_city (city),
    INDEX idx_lead_record_assignment_status (assignment_status),
    INDEX idx_lead_record_gmt_create (gmt_create)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS qcc_usage_log (
    id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL,
    company_name VARCHAR(128) NOT NULL,
    interface_name VARCHAR(64) NOT NULL,
    consume_count INT NOT NULL DEFAULT 1,
    is_success TINYINT NOT NULL DEFAULT 1,
    failure_reason VARCHAR(256) NOT NULL DEFAULT '',
    gmt_create DATETIME NOT NULL,
    gmt_modified DATETIME NOT NULL,
    INDEX idx_qcc_usage_log_task_id (task_id),
    INDEX idx_qcc_usage_log_gmt_create (gmt_create)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS task_event_log (
    id VARCHAR(64) PRIMARY KEY,
    task_id VARCHAR(64) NOT NULL,
    event_level VARCHAR(32) NOT NULL,
    event_message VARCHAR(512) NOT NULL,
    gmt_create DATETIME NOT NULL,
    gmt_modified DATETIME NOT NULL,
    INDEX idx_task_event_log_task_id (task_id),
    INDEX idx_task_event_log_gmt_create (gmt_create)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS keyword_config (
    id VARCHAR(64) PRIMARY KEY,
    industry VARCHAR(32) NOT NULL,
    keyword VARCHAR(128) NOT NULL,
    keyword_type VARCHAR(32) NOT NULL,
    is_enabled TINYINT NOT NULL DEFAULT 1,
    gmt_create DATETIME NOT NULL,
    gmt_modified DATETIME NOT NULL,
    INDEX idx_keyword_config_industry (industry),
    INDEX idx_keyword_config_keyword_type (keyword_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS system_config (
    id VARCHAR(64) PRIMARY KEY,
    config_key VARCHAR(128) NOT NULL,
    config_value VARCHAR(512) NOT NULL,
    remark VARCHAR(256) NOT NULL DEFAULT '',
    gmt_create DATETIME NOT NULL,
    gmt_modified DATETIME NOT NULL,
    UNIQUE KEY uk_system_config_key (config_key)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
"""

KEYWORD_SEED = (
    ("keyword-3c-001", "3C数码", "3C批发", "industry"),
    ("keyword-3c-002", "3C数码", "手机壳工厂", "industry"),
    ("keyword-3c-003", "3C数码", "数据线厂家", "industry"),
    ("keyword-3c-004", "3C数码", "跨境3C", "industry"),
    ("keyword-cloth-001", "服装", "服装工厂", "industry"),
    ("keyword-cloth-002", "服装", "女装批发", "industry"),
    ("keyword-cloth-003", "服装", "服装OEM", "industry"),
    ("keyword-cloth-004", "服装", "跨境服装", "industry"),
    ("keyword-beauty-001", "美妆个护", "化妆品工厂", "industry"),
    ("keyword-beauty-002", "美妆个护", "护肤品OEM", "industry"),
    ("keyword-beauty-003", "美妆个护", "彩妆代工", "industry"),
    ("keyword-beauty-004", "美妆个护", "美妆供应链", "industry"),
    ("keyword-business-001", "通用", "工厂", "business"),
    ("keyword-business-002", "通用", "批发", "business"),
    ("keyword-business-003", "通用", "OEM", "business"),
    ("keyword-business-004", "通用", "供应链", "business"),
)

SYSTEM_CONFIG_SEED = (
    ("config-qcc-daily-quota", "qcc_daily_quota", "200", "启信宝每日本地调用额度上限，可在前端额度页调整"),
    ("config-qcc-monthly-quota", "qcc_monthly_quota", "5000", "启信宝每月本地调用额度上限，可在前端额度页调整"),
)


def get_database_driver() -> str:
    config = get_config()
    return DATABASE_DRIVER_MYSQL if config.database_driver == DATABASE_DRIVER_MYSQL else DATABASE_DRIVER_SQLITE


def convert_sql(sql_text: str) -> str:
    if get_database_driver() == DATABASE_DRIVER_MYSQL:
        return sql_text.replace("?", "%s")
    return sql_text


def create_mysql_database_if_needed() -> None:
    config = get_config()
    if pymysql is None:
        raise RuntimeError("pymysql is required when LEAD_DATABASE_DRIVER=mysql")
    connection = pymysql.connect(
        host=config.mysql_host,
        port=config.mysql_port,
        user=config.mysql_user,
        password=config.mysql_password,
        charset=config.mysql_charset,
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{config.mysql_database}` "
                f"DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
    finally:
        connection.close()


def get_connection() -> sqlite3.Connection:
    config = get_config()
    if get_database_driver() == DATABASE_DRIVER_MYSQL:
        if pymysql is None:
            raise RuntimeError("pymysql is required when LEAD_DATABASE_DRIVER=mysql")
        return pymysql.connect(
            host=config.mysql_host,
            port=config.mysql_port,
            user=config.mysql_user,
            password=config.mysql_password,
            database=config.mysql_database,
            charset=config.mysql_charset,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )
    connection = sqlite3.connect(config.database_path)
    connection.row_factory = sqlite3.Row
    return connection


def execute(connection, sql_text: str, parameters=()):
    cursor = connection.cursor()
    cursor.execute(convert_sql(sql_text), parameters)
    return cursor


def fetch_one(connection, sql_text: str, parameters=()):
    cursor = execute(connection, sql_text, parameters)
    return cursor.fetchone()


def fetch_all(connection, sql_text: str, parameters=()):
    cursor = execute(connection, sql_text, parameters)
    return cursor.fetchall()


@contextmanager
def get_transaction() -> Iterator[sqlite3.Connection]:
    connection = get_connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


@contextmanager
def get_read_connection() -> Iterator[sqlite3.Connection]:
    connection = get_connection()
    try:
        yield connection
    finally:
        connection.close()


def execute_sql_script(connection, sql_script: str) -> None:
    for statement in sql_script.split(";"):
        clean_statement = statement.strip()
        if clean_statement:
            execute(connection, clean_statement)


def execute_mysql_schema(connection) -> bool:
    if MYSQL_INIT_SQL_PATH.exists():
        execute_sql_script(connection, MYSQL_INIT_SQL_PATH.read_text(encoding="utf-8"))
        return True
    execute_sql_script(connection, MYSQL_SCHEMA_SQL)
    return False


def row_to_mapping(row):
    if isinstance(row, dict):
        return row
    return dict(row)


def column_exists(connection, table_name: str, column_name: str) -> bool:
    if get_database_driver() == DATABASE_DRIVER_MYSQL:
        row = fetch_one(connection, f"SHOW COLUMNS FROM {table_name} LIKE ?", (column_name,))
        return row is not None
    row_list = fetch_all(connection, f"PRAGMA table_info({table_name})")
    return any(row_to_mapping(row)["name"] == column_name for row in row_list)


def index_exists(connection, table_name: str, index_name: str) -> bool:
    if get_database_driver() == DATABASE_DRIVER_MYSQL:
        row = fetch_one(connection, f"SHOW INDEX FROM {table_name} WHERE Key_name = ?", (index_name,))
        return row is not None
    row_list = fetch_all(connection, f"PRAGMA index_list({table_name})")
    return any(row_to_mapping(row)["name"] == index_name for row in row_list)


def migrate_schema(connection) -> None:
    if get_database_driver() != DATABASE_DRIVER_MYSQL:
        if not column_exists(connection, "lead_task", "target_city"):
            execute(
                connection,
                "ALTER TABLE lead_task ADD COLUMN target_city TEXT NOT NULL DEFAULT ''",
            )
        if not column_exists(connection, "lead_record", "company_name_en"):
            execute(
                connection,
                "ALTER TABLE lead_record ADD COLUMN company_name_en TEXT NOT NULL DEFAULT ''",
            )
        if not column_exists(connection, "lead_record", "shop_level"):
            execute(
                connection,
                "ALTER TABLE lead_record ADD COLUMN shop_level TEXT NOT NULL DEFAULT ''",
            )
        if not column_exists(connection, "lead_record", "assignment_status"):
            execute(
                connection,
                "ALTER TABLE lead_record ADD COLUMN assignment_status TEXT NOT NULL DEFAULT 'unassigned'",
            )
        if not column_exists(connection, "lead_record", "unified_social_credit_code"):
            execute(
                connection,
                "ALTER TABLE lead_record ADD COLUMN unified_social_credit_code TEXT NOT NULL DEFAULT ''",
            )
        for column_name in ("province", "city", "district", "city_source", "city_confidence"):
            if not column_exists(connection, "lead_record", column_name):
                execute(
                    connection,
                    f"ALTER TABLE lead_record ADD COLUMN {column_name} TEXT NOT NULL DEFAULT ''",
                )
        execute(
            connection,
            "CREATE INDEX IF NOT EXISTS idx_lead_record_assignment_status ON lead_record(assignment_status)",
        )
        execute(
            connection,
            "CREATE INDEX IF NOT EXISTS idx_lead_record_city ON lead_record(city)",
        )
        return
    if not column_exists(connection, "lead_task", "target_city"):
        execute(
            connection,
            """
            ALTER TABLE lead_task
            ADD COLUMN target_city VARCHAR(255) NOT NULL DEFAULT ''
            AFTER keyword_text
            """,
        )
    execute(
        connection,
        """
        ALTER TABLE lead_task
        MODIFY target_city VARCHAR(255) NOT NULL DEFAULT ''
        """,
    )
    execute(
        connection,
        """
        ALTER TABLE lead_record
        MODIFY phone VARCHAR(512) NOT NULL DEFAULT '' COMMENT '最终联系电话，可用中文分号保存多个公开电话'
        """,
    )
    if not column_exists(connection, "lead_record", "unified_social_credit_code"):
        execute(
            connection,
            """
            ALTER TABLE lead_record
            ADD COLUMN unified_social_credit_code VARCHAR(18) NOT NULL DEFAULT ''
            AFTER company_status
            """,
        )
    if not column_exists(connection, "lead_record", "company_name_en"):
        execute(
            connection,
            """
            ALTER TABLE lead_record
            ADD COLUMN company_name_en VARCHAR(255) NOT NULL DEFAULT ''
            AFTER company_name
            """,
        )
    if not column_exists(connection, "lead_record", "shop_level"):
        execute(
            connection,
            """
            ALTER TABLE lead_record
            ADD COLUMN shop_level VARCHAR(255) NOT NULL DEFAULT ''
            AFTER product_name
            """,
        )
    if not column_exists(connection, "lead_record", "province"):
        execute(
            connection,
            """
            ALTER TABLE lead_record
            ADD COLUMN province VARCHAR(32) NOT NULL DEFAULT ''
            AFTER registered_address
            """,
        )
    if not column_exists(connection, "lead_record", "city"):
        execute(
            connection,
            """
            ALTER TABLE lead_record
            ADD COLUMN city VARCHAR(32) NOT NULL DEFAULT ''
            AFTER province
            """,
        )
    if not column_exists(connection, "lead_record", "district"):
        execute(
            connection,
            """
            ALTER TABLE lead_record
            ADD COLUMN district VARCHAR(64) NOT NULL DEFAULT ''
            AFTER city
            """,
        )
    if not column_exists(connection, "lead_record", "city_source"):
        execute(
            connection,
            """
            ALTER TABLE lead_record
            ADD COLUMN city_source VARCHAR(64) NOT NULL DEFAULT ''
            AFTER district
            """,
        )
    if not column_exists(connection, "lead_record", "city_confidence"):
        execute(
            connection,
            """
            ALTER TABLE lead_record
            ADD COLUMN city_confidence VARCHAR(16) NOT NULL DEFAULT ''
            AFTER city_source
            """,
        )
    if not column_exists(connection, "lead_record", "assignment_status"):
        execute(
            connection,
            """
            ALTER TABLE lead_record
            ADD COLUMN assignment_status VARCHAR(32) NOT NULL DEFAULT 'unassigned'
            COMMENT '线索分发状态：unassigned=未分配，assigned=已分配'
            AFTER level
            """,
        )
    if not index_exists(connection, "lead_record", "idx_lead_record_assignment_status"):
        execute(
            connection,
            "ALTER TABLE lead_record ADD INDEX idx_lead_record_assignment_status (assignment_status)",
        )
    if not index_exists(connection, "lead_record", "idx_lead_record_city"):
        execute(
            connection,
            "ALTER TABLE lead_record ADD INDEX idx_lead_record_city (city)",
        )


def init_database() -> None:
    if get_database_driver() == DATABASE_DRIVER_MYSQL:
        create_mysql_database_if_needed()
    with get_transaction() as connection:
        if get_database_driver() == DATABASE_DRIVER_MYSQL:
            is_external_sql_used = execute_mysql_schema(connection)
            migrate_schema(connection)
            if is_external_sql_used:
                return
            insert_keyword_sql = """
                INSERT IGNORE INTO keyword_config
                    (id, industry, keyword, keyword_type, is_enabled, gmt_create, gmt_modified)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                """
        else:
            connection.executescript(SQLITE_SCHEMA_SQL)
            migrate_schema(connection)
            insert_keyword_sql = """
                INSERT OR IGNORE INTO keyword_config
                    (id, industry, keyword, keyword_type, is_enabled, gmt_create, gmt_modified)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                """
        insert_config_sql = """
            INSERT OR IGNORE INTO system_config
                (id, config_key, config_value, remark, gmt_create, gmt_modified)
            VALUES (?, ?, ?, ?, ?, ?)
            """
        if get_database_driver() == DATABASE_DRIVER_MYSQL:
            insert_config_sql = """
                INSERT IGNORE INTO system_config
                    (id, config_key, config_value, remark, gmt_create, gmt_modified)
                VALUES (?, ?, ?, ?, ?, ?)
                """
        current_time = get_current_time_text()
        for keyword_id, industry, keyword, keyword_type in KEYWORD_SEED:
            execute(
                connection,
                insert_keyword_sql,
                (keyword_id, industry, keyword, keyword_type, current_time, current_time),
            )
        for config_id, config_key, config_value, remark in SYSTEM_CONFIG_SEED:
            execute(
                connection,
                insert_config_sql,
                (config_id, config_key, config_value, remark, current_time, current_time),
            )
