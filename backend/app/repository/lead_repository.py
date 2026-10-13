import re
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Dict, List, Optional

from app.core.constant import (
    ACTIVE_TASK_STATUS_TUPLE,
    ASSIGNMENT_STATUS_ASSIGNED,
    ASSIGNMENT_STATUS_UNASSIGNED,
    SOURCE_TYPE_ALIBABA_1688,
    SOURCE_TYPE_ALIBABA_INTERNATIONAL,
    SOURCE_TYPE_ALIBABA_1688_PAGE_ASSISTANT,
    SOURCE_TYPE_ALIBABA_1688_PAGE_IMPORT,
    SOURCE_TYPE_AI_WEB_SEARCH,
    SOURCE_TYPE_AIQICHA_PUBLIC_WEB,
    SOURCE_TYPE_DOUYIN_QCC,
    SOURCE_TYPE_FENGNIAO_PUBLIC_WEB,
    SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,
    SOURCE_TYPE_QIXIN_PUBLIC_WEB,
    SOURCE_TYPE_QCC_PUBLIC_WEB,
    SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB,
)
from app.core.config import get_config
from app.core.database import (
    DATABASE_DRIVER_MYSQL,
    execute,
    fetch_all,
    fetch_one,
    get_database_driver,
    get_read_connection,
    get_transaction,
)
from app.util.contact_name_util import normalize_contact_name
from app.util.address_util import clean_registered_address_text
from app.util.credit_code_util import clean_unified_social_credit_code
from app.util.phone_filter_util import clean_public_phone_text
from app.util.product_name_util import is_non_product_label, repair_product_name_for_source
from app.util.region_parse_util import extract_region_info, is_better_region_info
from app.util.time_util import get_current_date_text, get_current_month_text, get_current_time_text


MAX_EVENT_MESSAGE_LENGTH = 500
MAX_LEAD_PAGE_SIZE = 200
EXPORT_LEAD_LIMIT = 100000
PRIMARY_CITY_FILTER_LIST = ["广州", "东莞", "佛山", "深圳", "中山", "惠州", "珠海", "汕头"]

SOURCE_GROUP_TYPE_MAP = {
    "qcc": (SOURCE_TYPE_QCC_PUBLIC_WEB,),
    "aiqicha": (SOURCE_TYPE_AIQICHA_PUBLIC_WEB,),
    "qixin": (SOURCE_TYPE_QIXIN_PUBLIC_WEB,),
    "tianyancha": (SOURCE_TYPE_TIANYANCHA_PUBLIC_WEB,),
    "ai_web": (SOURCE_TYPE_AI_WEB_SEARCH,),
    "fengniao": (SOURCE_TYPE_FENGNIAO_PUBLIC_WEB,),
    "douyin": (SOURCE_TYPE_DOUYIN_QCC,),
    "alibaba_international": (SOURCE_TYPE_ALIBABA_INTERNATIONAL,),
    "alibaba_tianyancha": (SOURCE_TYPE_ALIBABA_1688,),
    "made_in_china": (SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA,),
    "alibaba": (
        SOURCE_TYPE_ALIBABA_1688_PAGE_ASSISTANT,
        SOURCE_TYPE_ALIBABA_1688_PAGE_IMPORT,
    ),
}


def row_to_dict(row) -> Dict:
    if row is None:
        return {}
    data = row if isinstance(row, dict) else dict(row)
    return {key: normalize_database_value(value) for key, value in data.items()}


def normalize_database_value(value):
    if isinstance(value, Decimal):
        if value == value.to_integral_value():
            return int(value)
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.strftime("%Y-%m-%d %H:%M:%S") if isinstance(value, datetime) else value.isoformat()
    return value


class LeadRepository:
    def insert_task(self, task_data: Dict) -> None:
        with get_transaction() as connection:
            execute(
                connection,
                """
                INSERT INTO lead_task (
                    id, task_name, source_type, industry, keyword_text, target_city, collect_limit,
                    is_qcc_enabled, qcc_limit, status, gmt_create, gmt_modified
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_data["id"],
                    task_data["task_name"],
                    task_data["source_type"],
                    task_data["industry"],
                    task_data["keyword_text"],
                    task_data.get("target_city", ""),
                    task_data["collect_limit"],
                    task_data["is_qcc_enabled"],
                    task_data["qcc_limit"],
                    task_data["status"],
                    task_data["gmt_create"],
                    task_data["gmt_modified"],
                ),
            )

    def get_task(self, task_id: str) -> Optional[Dict]:
        with get_read_connection() as connection:
            row = fetch_one(
                connection,
                "SELECT * FROM lead_task WHERE id = ?",
                (task_id,),
            )
            return row_to_dict(row) if row else None

    def list_task(self) -> List[Dict]:
        with get_read_connection() as connection:
            rows = fetch_all(
                connection,
                "SELECT * FROM lead_task ORDER BY gmt_create DESC LIMIT 80",
            )
            return [row_to_dict(row) for row in rows]

    def update_task_status(
        self,
        task_id: str,
        status: str,
        total_count: Optional[int] = None,
        success_count: Optional[int] = None,
        failed_count: Optional[int] = None,
    ) -> None:
        task = self.get_task(task_id)
        if task is None:
            return
        with get_transaction() as connection:
            execute(
                connection,
                """
                UPDATE lead_task
                SET status = ?,
                    total_count = ?,
                    success_count = ?,
                    failed_count = ?,
                    gmt_modified = ?
                WHERE id = ?
                """,
                (
                    status,
                    total_count if total_count is not None else task["total_count"],
                    success_count if success_count is not None else task["success_count"],
                    failed_count if failed_count is not None else task["failed_count"],
                    get_current_time_text(),
                    task_id,
                ),
            )

    def insert_lead(self, lead_data: Dict) -> None:
        lead_data = dict(lead_data)
        lead_data["phone"] = clean_public_phone_text(lead_data.get("phone", ""), include_service=True)
        lead_data["contact_name"] = normalize_contact_name(lead_data.get("contact_name", ""))
        lead_data["legal_person"] = normalize_contact_name(lead_data.get("legal_person", ""))
        lead_data["unified_social_credit_code"] = clean_unified_social_credit_code(
            lead_data.get("unified_social_credit_code", "")
        )
        lead_data["registered_address"] = clean_registered_address_text(lead_data.get("registered_address", ""))
        lead_data["product_name"] = repair_product_name_for_source(
            lead_data.get("product_name", ""),
            lead_data.get("industry", ""),
            lead_data.get("source_keyword", ""),
            lead_data.get("business_scope", ""),
            lead_data.get("registered_address", ""),
            lead_data.get("source_type", ""),
        )
        lead_data.update(self.prepare_region_info(lead_data))
        if not lead_data["phone"]:
            lead_data["phone_source"] = ""
        with get_transaction() as connection:
            execute(
                connection,
                """
                INSERT INTO lead_record (
                    id, task_id, source_type, source_keyword, industry,
                    suspected_company_name, company_name, company_name_en, douyin_nickname,
                    product_name, shop_level, contact_name, phone, phone_source,
                    website_url, shop_url, profile_url,
                    sample_video_url, is_blue_v, is_enterprise_verified, company_status,
                    unified_social_credit_code, legal_person, business_scope, registered_address,
                    province, city, district, city_source, city_confidence, risk_tag,
                    verification_status, confidence, score, level, assignment_status,
                    gmt_create, gmt_modified
                )
                VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    lead_data["id"],
                    lead_data["task_id"],
                    lead_data["source_type"],
                    lead_data["source_keyword"],
                    lead_data["industry"],
                    lead_data["suspected_company_name"],
                    lead_data["company_name"],
                    lead_data.get("company_name_en", ""),
                    lead_data["douyin_nickname"],
                    lead_data["product_name"],
                    lead_data.get("shop_level", ""),
                    lead_data["contact_name"],
                    lead_data["phone"],
                    lead_data["phone_source"],
                    lead_data["website_url"],
                    lead_data["shop_url"],
                    lead_data["profile_url"],
                    lead_data["sample_video_url"],
                    lead_data["is_blue_v"],
                    lead_data["is_enterprise_verified"],
                    lead_data["company_status"],
                    lead_data["unified_social_credit_code"],
                    lead_data["legal_person"],
                    lead_data["business_scope"],
                    lead_data["registered_address"],
                    lead_data["province"],
                    lead_data["city"],
                    lead_data["district"],
                    lead_data["city_source"],
                    lead_data["city_confidence"],
                    lead_data["risk_tag"],
                    lead_data["verification_status"],
                    lead_data["confidence"],
                    lead_data["score"],
                    lead_data["level"],
                    lead_data.get("assignment_status", ASSIGNMENT_STATUS_UNASSIGNED),
                    lead_data["gmt_create"],
                    lead_data["gmt_modified"],
                ),
            )

    def prepare_region_info(self, lead_data: Dict) -> Dict:
        current_region = {
            "province": self.clean_duplicate_value(lead_data.get("province")),
            "city": self.clean_duplicate_value(lead_data.get("city")),
            "district": self.clean_duplicate_value(lead_data.get("district")),
            "city_source": self.clean_duplicate_value(lead_data.get("city_source")),
            "city_confidence": self.clean_duplicate_value(lead_data.get("city_confidence")),
        }
        parsed_region = extract_region_info(
            registered_address=lead_data.get("registered_address", ""),
            company_name=lead_data.get("company_name", ""),
            suspected_company_name=lead_data.get("suspected_company_name", ""),
            source_keyword=lead_data.get("source_keyword", ""),
        )
        if is_better_region_info(parsed_region, current_region):
            return parsed_region
        if current_region["city"]:
            return current_region
        return parsed_region

    def find_duplicate_lead_id(self, lead_data: Dict) -> str:
        source_type = self.clean_duplicate_value(lead_data.get("source_type"))
        value_condition_list = []
        parameters = [source_type]
        for field_name in ("company_name", "suspected_company_name", "profile_url", "shop_url"):
            field_value = self.clean_duplicate_value(lead_data.get(field_name))
            if not field_value or field_value in ("未公开", "号码皆未公开"):
                continue
            if field_name in ("company_name", "suspected_company_name"):
                value_condition_list.append("(company_name = ? OR suspected_company_name = ?)")
                parameters.extend([field_value, field_value])
            else:
                value_condition_list.append(f"{field_name} = ?")
                parameters.append(field_value)
        if not source_type or not value_condition_list:
            return ""
        sql_text = f"""
            SELECT id
            FROM lead_record
            WHERE source_type = ?
              AND ({' OR '.join(value_condition_list)})
            ORDER BY gmt_create DESC
            LIMIT 1
        """
        with get_read_connection() as connection:
            row = fetch_one(connection, sql_text, tuple(parameters))
        row_data = row_to_dict(row)
        return row_data.get("id", "")

    def list_lead_identity(self, source_type: str) -> List[Dict]:
        clean_source_type = self.clean_duplicate_value(source_type)
        if not clean_source_type:
            return []
        with get_read_connection() as connection:
            rows = fetch_all(
                connection,
                """
                SELECT company_name, suspected_company_name, profile_url, shop_url
                FROM lead_record
                WHERE source_type = ?
                """,
                (clean_source_type,),
            )
        return [row_to_dict(row) for row in rows]

    def list_alibaba_1688_tianyancha_enrichment_candidate(self, limit: int, task_id: str = "") -> List[Dict]:
        safe_limit = min(max(int(limit or 1), 1), 300)
        scan_limit = max(safe_limit * 8, 200)
        clean_task_id = self.clean_duplicate_value(task_id)
        task_filter_sql = ""
        query_parameters = [SOURCE_TYPE_ALIBABA_1688]
        if clean_task_id:
            task_filter_sql = "AND task_id = ?"
            query_parameters.append(clean_task_id)
        query_parameters.append(scan_limit)
        with get_read_connection() as connection:
            rows = fetch_all(
                connection,
                f"""
                SELECT id, task_id, source_keyword, industry, suspected_company_name, company_name,
                       product_name, phone, contact_name, legal_person, registered_address,
                       shop_url, profile_url
                FROM lead_record
                WHERE source_type = ?
                  {task_filter_sql}
                ORDER BY
                    CASE WHEN phone IS NULL OR phone = '' THEN 0 ELSE 1 END,
                    gmt_modified DESC,
                    gmt_create DESC
                LIMIT ?
                """,
                tuple(query_parameters),
            )
        result_list = []
        seen_company_set = set()
        for row in rows:
            row_data = row_to_dict(row)
            company_name = self.clean_duplicate_value(
                row_data.get("suspected_company_name") or row_data.get("company_name")
            )
            if not company_name or company_name in seen_company_set:
                continue
            phone = clean_public_phone_text(row_data.get("phone", ""), include_service=True)
            contact_name = self.visible_database_value(row_data.get("contact_name", ""))
            legal_person = self.visible_database_value(row_data.get("legal_person", ""))
            registered_address = self.visible_database_value(row_data.get("registered_address", ""))
            if phone and contact_name and legal_person and registered_address:
                continue
            seen_company_set.add(company_name)
            row_data["enrichment_company_name"] = company_name
            result_list.append(row_data)
            if len(result_list) >= safe_limit:
                break
        return result_list

    def count_lead_by_task_id(self, task_id: str) -> int:
        clean_task_id = self.clean_duplicate_value(task_id)
        if not clean_task_id:
            return 0
        with get_read_connection() as connection:
            row = fetch_one(
                connection,
                "SELECT COUNT(*) AS lead_count FROM lead_record WHERE task_id = ?",
                (clean_task_id,),
            )
        row_data = row_to_dict(row)
        return int(row_data.get("lead_count") or 0)

    def delete_unassigned_lead_without_public_phone(self, task_id: str = "") -> int:
        sql_text = """
            SELECT id, phone
            FROM lead_record
            WHERE assignment_status = ?
        """
        parameters = [ASSIGNMENT_STATUS_UNASSIGNED]
        clean_task_id = self.clean_duplicate_value(task_id)
        if clean_task_id:
            sql_text += " AND task_id = ?"
            parameters.append(clean_task_id)

        with get_transaction() as connection:
            rows = fetch_all(connection, sql_text, tuple(parameters))
            lead_id_list = []
            for row in rows:
                row_data = row_to_dict(row)
                if not clean_public_phone_text(row_data.get("phone", ""), include_service=True):
                    lead_id = row_data.get("id")
                    if lead_id:
                        lead_id_list.append(lead_id)
            if not lead_id_list:
                return 0
            placeholders = ",".join(["?"] * len(lead_id_list))
            cursor = execute(
                connection,
                f"DELETE FROM lead_record WHERE id IN ({placeholders})",
                tuple(lead_id_list),
            )
            return cursor.rowcount

    def update_lead_public_fields(self, lead_id: str, lead_data: Dict) -> None:
        if not lead_id:
            return

        def clean_value(field_name: str) -> str:
            return self.clean_duplicate_value(lead_data.get(field_name))

        def visible_value(field_name: str) -> str:
            field_value = clean_value(field_name)
            if field_name == "phone":
                field_value = clean_public_phone_text(field_value, include_service=True)
            if field_name in ("contact_name", "legal_person"):
                field_value = normalize_contact_name(field_value)
            return "" if field_value in ("未公开", "号码皆未公开", "-") else field_value

        current_record = self.get_lead_by_id(lead_id)
        merged_phone = clean_public_phone_text(
            self.merge_multi_value(current_record.get("phone", ""), visible_value("phone")),
            include_service=True,
        )
        merged_phone_source = self.merge_multi_value(
            current_record.get("phone_source", ""),
            visible_value("phone_source"),
        )
        if not merged_phone:
            merged_phone_source = ""
        current_contact_name = normalize_contact_name(self.visible_database_value(current_record.get("contact_name", "")))
        new_contact_name = visible_value("contact_name")
        merged_contact_name = new_contact_name or current_contact_name
        current_legal_person = normalize_contact_name(self.visible_database_value(current_record.get("legal_person", "")))
        new_legal_person = visible_value("legal_person")
        merged_legal_person = new_legal_person or current_legal_person
        merged_unified_social_credit_code = clean_unified_social_credit_code(
            visible_value("unified_social_credit_code")
            or self.visible_database_value(current_record.get("unified_social_credit_code", ""))
        )
        cleaned_registered_address = clean_registered_address_text(clean_value("registered_address"))
        current_product_name = self.visible_database_value(current_record.get("product_name", ""))
        new_product_name = repair_product_name_for_source(
            clean_value("product_name"),
            lead_data.get("industry", ""),
            lead_data.get("source_keyword", ""),
            clean_value("business_scope"),
            cleaned_registered_address,
            clean_value("source_type"),
        )
        if not current_product_name or is_non_product_label(current_product_name):
            merged_product_name = new_product_name
        else:
            merged_product_name = current_product_name
        merged_risk_tag = self.clean_public_risk_tag(
            self.merge_multi_value(current_record.get("risk_tag", ""), clean_value("risk_tag")),
            merged_phone,
            merged_contact_name,
        )
        region_lead_data = dict(lead_data)
        region_lead_data["registered_address"] = cleaned_registered_address
        new_region = self.prepare_region_info(region_lead_data)
        current_region = {
            "province": self.clean_duplicate_value(current_record.get("province")),
            "city": self.clean_duplicate_value(current_record.get("city")),
            "district": self.clean_duplicate_value(current_record.get("district")),
            "city_source": self.clean_duplicate_value(current_record.get("city_source")),
            "city_confidence": self.clean_duplicate_value(current_record.get("city_confidence")),
        }
        merged_region = new_region if is_better_region_info(new_region, current_region) else current_region

        current_time = get_current_time_text()
        field_value_list = [
            ("phone", merged_phone),
            ("phone_source", merged_phone_source),
            ("contact_name", merged_contact_name),
            ("product_name", merged_product_name),
            ("legal_person", merged_legal_person),
            ("unified_social_credit_code", merged_unified_social_credit_code),
            ("company_status", clean_value("company_status")),
            ("business_scope", clean_value("business_scope")),
            ("registered_address", cleaned_registered_address),
            ("province", merged_region.get("province", "")),
            ("city", merged_region.get("city", "")),
            ("district", merged_region.get("district", "")),
            ("city_source", merged_region.get("city_source", "")),
            ("city_confidence", merged_region.get("city_confidence", "")),
            ("risk_tag", merged_risk_tag),
            ("shop_url", clean_value("shop_url")),
            ("profile_url", clean_value("profile_url")),
            ("suspected_company_name", clean_value("suspected_company_name")),
            ("company_name", clean_value("company_name")),
        ]
        set_sql_list = []
        parameters = []
        for field_name, field_value in field_value_list:
            if field_name in ("company_name", "suspected_company_name"):
                set_sql_list.append(
                    f"{field_name} = CASE "
                    f"WHEN ({field_name} IS NULL OR {field_name} = '' OR {field_name} = '未公开') "
                    f"AND ? <> '' THEN ? "
                    f"WHEN ({field_name} LIKE '%%榜第%%' OR {field_name} LIKE '7x24H响应%%') "
                    f"AND ? <> '' THEN ? "
                    f"ELSE {field_name} END"
                )
                parameters.extend([field_value, field_value, field_value, field_value])
                continue
            if field_name in ("phone", "phone_source"):
                set_sql_list.append(f"{field_name} = ?")
                parameters.append(field_value)
                continue
            if field_name in ("province", "city", "district", "city_source", "city_confidence"):
                set_sql_list.append(f"{field_name} = ?")
                parameters.append(field_value)
                continue
            if field_name == "risk_tag":
                set_sql_list.append(f"{field_name} = ?")
                parameters.append(field_value)
                continue
            if field_name in ("contact_name", "legal_person"):
                set_sql_list.append(f"{field_name} = ?")
                parameters.append(field_value)
                continue
            set_sql_list.append(
                f"{field_name} = CASE "
                f"WHEN ({field_name} IS NULL OR {field_name} = '' OR {field_name} = '未公开' OR {field_name} = '-') "
                f"AND ? <> '' THEN ? ELSE {field_name} END"
            )
            parameters.extend([field_value, field_value])
        parameters.extend([current_time, lead_id])
        with get_transaction() as connection:
            execute(
                connection,
                f"""
                UPDATE lead_record
                SET {', '.join(set_sql_list)},
                    gmt_modified = ?
                WHERE id = ?
                """,
                tuple(parameters),
            )
            score = int(lead_data.get("score") or 0)
            if score > 0:
                execute(
                    connection,
                    """
                    UPDATE lead_record
                    SET score = ?,
                        level = ?,
                        gmt_modified = ?
                    WHERE id = ?
                      AND score < ?
                    """,
                    (score, lead_data.get("level", ""), current_time, lead_id, score),
                )

    @staticmethod
    def clean_duplicate_value(value) -> str:
        return str(value or "").strip()

    @staticmethod
    def visible_database_value(value) -> str:
        clean_value = str(value or "").strip()
        return "" if clean_value in ("未公开", "号码皆未公开", "-") else clean_value

    @classmethod
    def clean_public_risk_tag(cls, risk_tag: str, phone: str, contact_name: str) -> str:
        has_phone = bool(re.search(r"\d{7,}", phone or ""))
        has_contact = bool(cls.visible_database_value(contact_name))
        clean_tag_list = []
        for raw_tag in re.split(r"[；;,，]+", risk_tag or ""):
            tag = raw_tag.strip()
            if not tag:
                continue
            if has_phone and "未见电话" in tag:
                continue
            if has_phone and has_contact and ("待补全" in tag or "缺少公开电话或联系人" in tag):
                continue
            clean_tag_list.append(tag)
        return "；".join(clean_tag_list)[:128]

    @staticmethod
    def merge_multi_value(left_value: str, right_value: str) -> str:
        result_list = []
        dedupe_set = set()
        for raw_value in (left_value, right_value):
            for item in re.split(r"[；;,，]+", str(raw_value or "")):
                clean_item = item.strip()
                if not clean_item or clean_item in dedupe_set or clean_item in ("未公开", "号码皆未公开", "-"):
                    continue
                dedupe_set.add(clean_item)
                result_list.append(clean_item)
        return "；".join(result_list)

    def get_lead_by_id(self, lead_id: str) -> Dict:
        clean_lead_id = self.clean_duplicate_value(lead_id)
        if not clean_lead_id:
            return {}
        with get_read_connection() as connection:
            row = fetch_one(connection, "SELECT * FROM lead_record WHERE id = ?", (clean_lead_id,))
        return row_to_dict(row)

    def list_lead(
        self,
        level: str = "",
        source_type: str = "",
        source_group: str = "",
        industry: str = "",
        keyword: str = "",
        city: str = "",
        assignment_status: str = "",
        page: int = 1,
        page_size: int = 50,
    ) -> Dict:
        safe_page = max(page, 1)
        safe_page_size = min(max(page_size, 1), MAX_LEAD_PAGE_SIZE)
        offset = (safe_page - 1) * safe_page_size
        where_sql, parameters = self.build_lead_where_clause(
            level=level,
            source_type=source_type,
            source_group=source_group,
            industry=industry,
            keyword=keyword,
            city=city,
            assignment_status=assignment_status,
        )
        count_sql = f"SELECT COUNT(1) AS count_value FROM lead_record {where_sql}"
        list_sql = f"""
            SELECT * FROM lead_record
            {where_sql}
            ORDER BY gmt_create DESC, score DESC
            LIMIT ? OFFSET ?
        """
        with get_read_connection() as connection:
            total_count = fetch_one(connection, count_sql, tuple(parameters))["count_value"]
            rows = fetch_all(connection, list_sql, tuple(parameters + [safe_page_size, offset]))
        return {
            "items": [row_to_dict(row) for row in rows],
            "total": total_count,
            "page": safe_page,
            "page_size": safe_page_size,
        }

    def list_lead_for_export(
        self,
        levels: List[str],
        source_type: str = "",
        source_group: str = "",
        industry: str = "",
        keyword: str = "",
        city: str = "",
        assignment_status: str = "",
    ) -> List[Dict]:
        clean_level_list = [level for level in levels if level]
        if not clean_level_list:
            clean_level_list = ["A", "B"]
        where_sql, parameters = self.build_lead_where_clause(
            source_type=source_type,
            source_group=source_group,
            industry=industry,
            keyword=keyword,
            city=city,
            assignment_status=assignment_status,
        )
        placeholders = ",".join(["?"] * len(clean_level_list))
        where_sql += f" AND level IN ({placeholders})"
        parameters.extend(clean_level_list)
        sql_text = f"""
            SELECT * FROM lead_record
            {where_sql}
            ORDER BY score DESC, gmt_create DESC
            LIMIT ?
        """
        with get_read_connection() as connection:
            rows = fetch_all(connection, sql_text, tuple(parameters + [EXPORT_LEAD_LIMIT]))
        return [row_to_dict(row) for row in rows]

    def build_lead_where_clause(
        self,
        level: str = "",
        source_type: str = "",
        source_group: str = "",
        industry: str = "",
        keyword: str = "",
        city: str = "",
        assignment_status: str = "",
    ) -> tuple:
        sql_text = "WHERE 1 = 1"
        parameters = []
        if level:
            sql_text += " AND level = ?"
            parameters.append(level)
        source_type_list = self.resolve_source_type_list(source_type, source_group)
        if source_type_list:
            placeholders = ",".join(["?"] * len(source_type_list))
            sql_text += f" AND source_type IN ({placeholders})"
            parameters.extend(source_type_list)
        if industry:
            sql_text += " AND industry = ?"
            parameters.append(industry)
        if assignment_status:
            sql_text += " AND assignment_status = ?"
            parameters.append(assignment_status)
        if city:
            if city == "其他":
                placeholders = ",".join(["?"] * len(PRIMARY_CITY_FILTER_LIST))
                sql_text += f" AND (city = '' OR city NOT IN ({placeholders}))"
                parameters.extend(PRIMARY_CITY_FILTER_LIST)
            else:
                sql_text += " AND city = ?"
                parameters.append(city)
        if keyword:
            sql_text += """
                AND (
                    company_name LIKE ?
                    OR suspected_company_name LIKE ?
                    OR source_keyword LIKE ?
                    OR product_name LIKE ?
                    OR phone LIKE ?
                    OR city LIKE ?
                    OR registered_address LIKE ?
                )
            """
            keyword_text = f"%{keyword}%"
            parameters.extend([
                keyword_text,
                keyword_text,
                keyword_text,
                keyword_text,
                keyword_text,
                keyword_text,
                keyword_text,
            ])
        return sql_text, parameters

    def resolve_source_type_list(self, source_type: str, source_group: str) -> List[str]:
        if source_type:
            return [source_type]
        if not source_group or source_group == "all":
            return []
        return list(SOURCE_GROUP_TYPE_MAP.get(source_group, ()))

    def update_assignment_status(self, lead_id_list: List[str], assignment_status: str = ASSIGNMENT_STATUS_ASSIGNED) -> int:
        clean_id_list = [lead_id for lead_id in lead_id_list if lead_id]
        if not clean_id_list:
            return 0
        placeholders = ",".join(["?"] * len(clean_id_list))
        with get_transaction() as connection:
            cursor = execute(
                connection,
                f"""
                UPDATE lead_record
                SET assignment_status = ?,
                    gmt_modified = ?
                WHERE id IN ({placeholders})
                """,
                tuple([assignment_status, get_current_time_text()] + clean_id_list),
            )
            return cursor.rowcount

    def clear_lead(self) -> int:
        with get_transaction() as connection:
            cursor = execute(connection, "DELETE FROM lead_record")
            return cursor.rowcount

    def delete_lead_by_id(self, lead_id: str) -> int:
        if not lead_id:
            return 0
        with get_transaction() as connection:
            cursor = execute(connection, "DELETE FROM lead_record WHERE id = ?", (lead_id,))
            return cursor.rowcount

    def insert_qcc_usage(self, usage_data: Dict) -> None:
        with get_transaction() as connection:
            execute(
                connection,
                """
                INSERT INTO qcc_usage_log (
                    id, task_id, company_name, interface_name, consume_count,
                    is_success, failure_reason, gmt_create, gmt_modified
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    usage_data["id"],
                    usage_data["task_id"],
                    usage_data["company_name"],
                    usage_data["interface_name"],
                    usage_data["consume_count"],
                    usage_data["is_success"],
                    usage_data["failure_reason"],
                    usage_data["gmt_create"],
                    usage_data["gmt_modified"],
                ),
            )

    def insert_task_event(self, task_id: str, event_level: str, event_message: str) -> None:
        current_time = get_current_time_text()
        safe_event_message = (event_message or "")[:MAX_EVENT_MESSAGE_LENGTH]
        with get_transaction() as connection:
            execute(
                connection,
                """
                INSERT INTO task_event_log (
                    id, task_id, event_level, event_message, gmt_create, gmt_modified
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    uuid.uuid4().hex,
                    task_id,
                    event_level,
                    safe_event_message,
                    current_time,
                    current_time,
                ),
            )

    def list_task_event(self, limit: int = 80) -> List[Dict]:
        with get_read_connection() as connection:
            rows = fetch_all(
                connection,
                """
                SELECT * FROM task_event_log
                ORDER BY gmt_create DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [row_to_dict(row) for row in rows]

    def list_keyword_config(self) -> List[Dict]:
        with get_read_connection() as connection:
            rows = fetch_all(
                connection,
                """
                SELECT * FROM keyword_config
                WHERE is_enabled = 1
                ORDER BY industry, keyword_type, keyword
                """,
            )
            return [row_to_dict(row) for row in rows]

    def get_config_value(self, config_key: str, default_value: int) -> int:
        with get_read_connection() as connection:
            row = fetch_one(
                connection,
                "SELECT config_value FROM system_config WHERE config_key = ?",
                (config_key,),
            )
        if not row:
            return default_value
        try:
            return int(row_to_dict(row)["config_value"])
        except (TypeError, ValueError):
            return default_value

    def get_usage_setting(self) -> Dict:
        config = get_config()
        return {
            "daily_quota": self.get_config_value("qcc_daily_quota", config.qcc_daily_quota),
            "monthly_quota": self.get_config_value("qcc_monthly_quota", config.qcc_monthly_quota),
        }

    def update_usage_setting(self, daily_quota: int, monthly_quota: int) -> None:
        current_time = get_current_time_text()
        with get_transaction() as connection:
            self.upsert_system_config(
                connection,
                "config-qcc-daily-quota",
                "qcc_daily_quota",
                str(daily_quota),
                "启信宝每日本地调用额度上限，可在前端额度页调整",
                current_time,
            )
            self.upsert_system_config(
                connection,
                "config-qcc-monthly-quota",
                "qcc_monthly_quota",
                str(monthly_quota),
                "启信宝每月本地调用额度上限，可在前端额度页调整",
                current_time,
            )

    def upsert_system_config(
        self,
        connection,
        config_id: str,
        config_key: str,
        config_value: str,
        remark: str,
        current_time: str,
    ) -> None:
        if get_database_driver() == DATABASE_DRIVER_MYSQL:
            execute(
                connection,
                """
                INSERT INTO system_config
                    (id, config_key, config_value, remark, gmt_create, gmt_modified)
                VALUES (?, ?, ?, ?, ?, ?)
                ON DUPLICATE KEY UPDATE
                    config_value = VALUES(config_value),
                    remark = VALUES(remark),
                    gmt_modified = VALUES(gmt_modified)
                """,
                (config_id, config_key, config_value, remark, current_time, current_time),
            )
            return
        execute(
            connection,
            """
            INSERT INTO system_config
                (id, config_key, config_value, remark, gmt_create, gmt_modified)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(config_key) DO UPDATE SET
                config_value = excluded.config_value,
                remark = excluded.remark,
                gmt_modified = excluded.gmt_modified
            """,
            (config_id, config_key, config_value, remark, current_time, current_time),
        )

    def get_usage_summary(self) -> Dict:
        usage_setting = self.get_usage_setting()
        current_date = get_current_date_text()
        current_month = get_current_month_text()
        daily_sql = """
            SELECT COALESCE(SUM(consume_count), 0) AS consume_count
            FROM qcc_usage_log
            WHERE substr(gmt_create, 1, 10) = ?
            """
        monthly_sql = """
            SELECT COALESCE(SUM(consume_count), 0) AS consume_count
            FROM qcc_usage_log
            WHERE substr(gmt_create, 1, 7) = ?
            """
        if get_database_driver() == DATABASE_DRIVER_MYSQL:
            daily_sql = """
                SELECT COALESCE(SUM(consume_count), 0) AS consume_count
                FROM qcc_usage_log
                WHERE DATE_FORMAT(gmt_create, '%%Y-%%m-%%d') = ?
                """
            monthly_sql = """
                SELECT COALESCE(SUM(consume_count), 0) AS consume_count
                FROM qcc_usage_log
                WHERE DATE_FORMAT(gmt_create, '%%Y-%%m') = ?
                """
        with get_read_connection() as connection:
            daily_count = normalize_database_value(
                fetch_one(connection, daily_sql, (current_date,))["consume_count"]
            )
            monthly_count = normalize_database_value(
                fetch_one(connection, monthly_sql, (current_month,))["consume_count"]
            )
            recent_rows = fetch_all(
                connection,
                """
                SELECT * FROM qcc_usage_log
                ORDER BY gmt_create DESC
                LIMIT 20
                """,
            )
        return {
            "daily_used": daily_count,
            "daily_quota": usage_setting["daily_quota"],
            "daily_remaining": max(usage_setting["daily_quota"] - daily_count, 0),
            "monthly_used": monthly_count,
            "monthly_quota": usage_setting["monthly_quota"],
            "monthly_remaining": max(usage_setting["monthly_quota"] - monthly_count, 0),
            "recent_usage": [row_to_dict(row) for row in recent_rows],
        }

    def get_dashboard(self) -> Dict:
        active_task_count = self.get_active_task_count()
        usage_summary = self.get_usage_summary()
        with get_read_connection() as connection:
            task_count = fetch_one(
                connection,
                "SELECT COUNT(1) AS count_value FROM lead_task",
            )["count_value"]
            lead_count = fetch_one(
                connection,
                "SELECT COUNT(1) AS count_value FROM lead_record",
            )["count_value"]
            high_value_count = fetch_one(
                connection,
                "SELECT COUNT(1) AS count_value FROM lead_record WHERE level IN ('A', 'B')",
            )["count_value"]
        return {
            "task_count": task_count,
            "lead_count": lead_count,
            "high_value_count": high_value_count,
            "running_count": active_task_count,
            "usage_summary": usage_summary,
        }

    def get_active_task_count(self) -> int:
        active_status_placeholder = ",".join(["?"] * len(ACTIVE_TASK_STATUS_TUPLE))
        with get_read_connection() as connection:
            return fetch_one(
                connection,
                f"SELECT COUNT(1) AS count_value FROM lead_task WHERE status IN ({active_status_placeholder})",
                ACTIVE_TASK_STATUS_TUPLE,
            )["count_value"]
