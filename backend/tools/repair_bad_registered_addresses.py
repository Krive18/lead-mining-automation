import argparse
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import execute, fetch_all, get_read_connection, get_transaction, row_to_mapping
from app.service.collector_service import EnterprisePublicWebCollector
from app.util.time_util import get_current_time_text


JSON_ADDRESS_TOKEN_LIST = [
    '"longitude"',
    '"latitude"',
    '"sourceDisplayWeight"',
    '"reportYear"',
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview or repair lead_record.registered_address values polluted by map JSON.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write repairs to the database. Without this flag, only preview changes.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Maximum rows to preview/apply. 0 means no limit.",
    )
    return parser.parse_args()


def load_polluted_rows() -> List[Dict]:
    where_sql = " OR ".join(["registered_address LIKE ?"] * len(JSON_ADDRESS_TOKEN_LIST))
    parameters = tuple(f"%{token}%" for token in JSON_ADDRESS_TOKEN_LIST)
    with get_read_connection() as connection:
        rows = fetch_all(
            connection,
            f"""
            SELECT id, company_name, registered_address
            FROM lead_record
            WHERE {where_sql}
            ORDER BY gmt_modified DESC
            """,
            parameters,
        )
    return [row_to_mapping(row) for row in rows]


def build_repair_list(rows: Iterable[Dict], limit: int = 0) -> List[Dict]:
    collector = EnterprisePublicWebCollector.create_tianyancha_collector()
    repair_list = []
    for row in rows:
        old_address = row.get("registered_address") or ""
        new_address = collector.clean_registered_address_value(old_address)
        if new_address == old_address:
            continue
        repair_list.append(
            {
                "id": row.get("id"),
                "company_name": row.get("company_name") or "",
                "old_address": old_address,
                "new_address": new_address,
            }
        )
        if limit > 0 and len(repair_list) >= limit:
            break
    return repair_list


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
                SET registered_address = ?,
                    gmt_modified = ?
                WHERE id = ?
                  AND registered_address = ?
                """,
                (
                    repair["new_address"],
                    current_time,
                    repair["id"],
                    repair["old_address"],
                ),
            )
            updated_count += cursor.rowcount
    return updated_count


def main() -> int:
    args = parse_args()
    repair_list = build_repair_list(load_polluted_rows(), args.limit)
    print(f"Repairable rows: {len(repair_list)}")
    for index, repair in enumerate(repair_list[:30], start=1):
        old_preview = repair["old_address"][:80]
        new_preview = repair["new_address"] or "<empty>"
        print(f"{index}. {repair['company_name']} | {old_preview!r} -> {new_preview!r}")
    if not args.apply:
        print("Dry-run only. Re-run with --apply to write these registered_address repairs.")
        return 0
    print(f"Updated rows: {apply_repairs(repair_list)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
