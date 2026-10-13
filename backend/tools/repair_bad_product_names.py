import argparse
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import execute, fetch_all, get_read_connection, get_transaction, row_to_mapping
from app.util.product_name_util import derive_product_from_business_text, is_non_product_label
from app.util.time_util import get_current_time_text


DEFAULT_SOURCE_TYPE = "alibaba_1688"
REPAIR_FIELD_LIST = [
    "id",
    "source_type",
    "source_keyword",
    "industry",
    "company_name",
    "product_name",
    "business_scope",
    "registered_address",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview or repair obviously bad lead_record.product_name values.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write repairs to the database. Without this flag, only preview changes.",
    )
    parser.add_argument(
        "--source-type",
        default=DEFAULT_SOURCE_TYPE,
        help=f"Source type to repair. Use 'all' for every source. Default: {DEFAULT_SOURCE_TYPE}.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum number of repairable rows to preview/apply. 0 means no limit.",
    )
    parser.add_argument(
        "--preview-size",
        type=int,
        default=30,
        help="Number of repair examples to print.",
    )
    return parser.parse_args()


def load_rows(source_type: str) -> List[Dict]:
    field_text = ", ".join(REPAIR_FIELD_LIST)
    sql_text = f"SELECT {field_text} FROM lead_record"
    parameters: Tuple = ()
    if source_type and source_type != "all":
        sql_text += " WHERE source_type = ?"
        parameters = (source_type,)
    sql_text += " ORDER BY gmt_modified DESC"
    with get_read_connection() as connection:
        rows = fetch_all(connection, sql_text, parameters)
    return [row_to_mapping(row) for row in rows]


def build_repair_candidates(rows: Iterable[Dict], limit: int = 0) -> Tuple[List[Dict], int]:
    repair_list: List[Dict] = []
    skipped_bad_count = 0
    for row in rows:
        old_product = str(row.get("product_name") or "").strip()
        if not old_product:
            continue
        if not is_non_product_label(old_product):
            continue
        business_text = " ".join(
            [
                str(row.get("business_scope") or ""),
                str(row.get("registered_address") or ""),
            ]
        )
        new_product = derive_product_from_business_text(
            business_text,
            str(row.get("industry") or ""),
        ).strip()
        if not new_product or new_product == old_product or is_non_product_label(new_product):
            skipped_bad_count += 1
            continue
        repair_list.append(
            {
                "id": row.get("id"),
                "source_type": row.get("source_type") or "",
                "source_keyword": row.get("source_keyword") or "",
                "company_name": row.get("company_name") or "",
                "old_product": old_product,
                "new_product": new_product,
            }
        )
        if limit > 0 and len(repair_list) >= limit:
            break
    return repair_list, skipped_bad_count


def apply_repairs(repair_list: List[Dict]) -> int:
    if not repair_list:
        return 0
    current_time = get_current_time_text()
    updated_count = 0
    with get_transaction() as connection:
        for repair in repair_list:
            cursor = execute(
                connection,
                """
                UPDATE lead_record
                SET product_name = ?,
                    gmt_modified = ?
                WHERE id = ?
                  AND product_name = ?
                """,
                (
                    repair["new_product"],
                    current_time,
                    repair["id"],
                    repair["old_product"],
                ),
            )
            updated_count += cursor.rowcount
    return updated_count


def print_preview(repair_list: List[Dict], skipped_bad_count: int, preview_size: int) -> None:
    print(f"Repairable rows: {len(repair_list)}")
    print(f"Bad rows skipped because no safe replacement was found: {skipped_bad_count}")
    for index, repair in enumerate(repair_list[: max(preview_size, 0)], start=1):
        company_name = repair["company_name"]
        source_keyword = repair["source_keyword"]
        old_product = repair["old_product"]
        new_product = repair["new_product"]
        print(f"{index}. {company_name} | {old_product} -> {new_product} | keyword={source_keyword}")
    if preview_size >= 0 and len(repair_list) > preview_size:
        print(f"... {len(repair_list) - preview_size} more rows hidden")


def main() -> int:
    args = parse_args()
    source_type = "" if args.source_type == "all" else args.source_type
    rows = load_rows(source_type)
    repair_list, skipped_bad_count = build_repair_candidates(rows, args.limit)
    print_preview(repair_list, skipped_bad_count, args.preview_size)
    if not args.apply:
        print("Dry-run only. Re-run with --apply to write these product_name repairs.")
        return 0
    updated_count = apply_repairs(repair_list)
    print(f"Updated rows: {updated_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
