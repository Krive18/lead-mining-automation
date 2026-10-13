# Enterprise Address Design

## Scope

Only improve the `registered_address` field for Qixinbao and Tianyancha public-web collection.

## Design

- Keep the existing database and API field: `registered_address`.
- Improve public-web address parsing so labels such as `企业地址`, `联系地址`, `通讯地址`, `注册地址`, `住所`, and `经营场所` can populate `registered_address`.
- Show `registered_address` in the lead table.
- Add `registered_address` to Excel export.

## Out Of Scope

- Do not change legal person, phone, risk, scoring, or contact extraction.
- Do not add new database columns.
- Do not add Qixinbao API integration in this change.
