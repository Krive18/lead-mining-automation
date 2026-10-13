# 1688 Category And Jitter Design

## Scope

- Put the precise 1688 search-card category text into the existing `product_name` field.
- Add randomized pacing around 1688 and Tianyancha public-page waits.

## Design

- Prefer 1688 card category text near the company name, for example `工装、制服务Polo衫 男式卫衣`.
- Fall back to the existing product extraction when the card category cannot be identified.
- Keep using `product_name`; do not add a new database column.
- Add small randomized waits to page-settle delays for 1688 and Tianyancha/enterprise public pages.
- Keep the existing manual-login/manual-verification behavior when a site shows login, captcha, or risk-control pages.

## Out Of Scope

- Do not bypass login, captcha, or verification pages.
- Do not change scoring, phone, legal person, or address extraction.
