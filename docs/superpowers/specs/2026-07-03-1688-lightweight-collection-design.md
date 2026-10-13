# 1688 Lightweight Collection Design

## Goal

Reduce 1688 risk-control triggers while improving useful lead volume and product-category accuracy.

The 1688 stage should no longer rely on opening company/detail pages. It should collect only public search-result card data: company/factory name, displayed city, and product subcategories. Tianyancha enrichment remains responsible for legal person, phone, and registered address.

## Confirmed Scope

- Use option 1 as the main path: list-page-only collection on 1688.
- Keep option 2 as a configurable fallback: very limited detail-page enrichment only when the list card has no usable product subcategory.
- The fallback must be disabled by default to reduce risk-control exposure.
- Product column uses the list-card product subcategory, not generic industry, city, age, area, staff count, certification, processing tags, or Tianyancha business scope.
- Preferred Guangdong cities are Guangzhou, Qingyuan, Foshan, and Dongguan.

## Current Problems

1. The current 1688 collector still attempts to open detail pages, expand details, and reveal phone fields. This increases risk-control exposure.
2. Product extraction currently falls back through generic product cleanup and public-field repair. That can turn the product column into values like city, years, industry fallback, or unrelated business-scope text.
3. Tianyancha enrichment can later affect product fields, which conflicts with the desired source of truth: the 1688 list-card small category.
4. City priority currently favors Guangzhou, Dongguan, and Foshan, but does not include Qingyuan in the top priority set.

## Proposed Architecture

### 1688 List-Card Collector

The 1688 collector should parse search result cards and build leads directly from card data.

Each parsed card should expose:

- `company_name`: the visible title company/factory name.
- `product_name`: 2-3 product subcategory tokens displayed beside or below the company name.
- `city`: visible card city when available.
- `raw_text`: bounded card text for scoring, dedupe, and debugging.
- `shop_url` / `profile_url`: kept only when available from card links, but not opened during normal collection.

### Product Subcategory Extractor

The product extractor should prefer structured card positions and then use guarded text parsing.

Accepted product examples:

- `粉扑、美妆蛋、洗脸扑`
- `手机保护套、iPhone保护套`
- `女式T恤、半身裙、女士短裤`
- `连衣裙、女式T恤、大码连衣裙`

Rejected noise examples:

- Factory labels: `超级工厂`, `实力工厂`, `源头工厂`
- Years and metrics: `2年`, `2500㎡`, `90员工`, `7x24H响应`
- Service tags: `来图加工`, `来样加工`, `清加工`, `包工包料`
- Credentials: `CCC认证`, `ISO认证`, `A类纳税人`, `可开专票`
- Broad labels: `服装产品`, `美妆产品`, `广东`, `广州`, `东莞`

The stored product value should keep at most three accepted tokens, joined with `、`.

### Region Priority

Search keyword expansion should prioritize:

1. `广州 + keyword`
2. `清远 + keyword`
3. `佛山 + keyword`
4. `东莞 + keyword`
5. Original keyword as broader Guangdong fallback

The 1688 search URL should keep the Guangdong province filter. Result cards from the four priority cities should be accepted first. Other Guangdong cities may be used only as fill-in candidates when the collection limit is not reached.

### Tianyancha Enrichment

Tianyancha should enrich only:

- legal person
- contact name
- phone
- company status
- registered address
- business scope
- risk tag

Tianyancha should not overwrite a non-empty 1688 list-card product subcategory. It may fill product only when 1688 product is empty.

### Risk-Control Behavior

Default 1688 behavior:

- Do not click company cards.
- Do not open detail pages.
- Do not click phone/contact buttons.
- Do not click inquiry or chat controls.
- Continue using request jitter and batch cooldown.
- If a login or verification page appears, open the login flow and wait for manual QR login, then continue from the search page.

Optional fallback behavior:

- Controlled by a backend config flag.
- Disabled by default.
- Only allowed when a card has a valid company name but no valid product subcategory.
- Must run with a strict low cap per task.

## Data Flow

1. User starts an `alibaba_1688` task.
2. Backend expands keywords using the preferred city order.
3. Playwright opens 1688 factory search result pages with Guangdong filter.
4. The page parser extracts visible card data without clicking into details.
5. The collector filters cards by company validity, industry relevance, Guangdong evidence, and product-subcategory quality.
6. Leads are deduped and stored with 1688 product subcategory preserved.
7. After 1688 collection cools down, Tianyancha enriches by company name.
8. Repository merge keeps 1688 product when it is already valid.

## Error Handling

- If 1688 returns no cards, record diagnostics with searched keywords and parsed raw item count.
- If product extraction fails for a card, keep the lead only when fallback is enabled or another accepted product signal exists.
- If risk control appears, pause for manual login instead of continuing to click.
- If Tianyancha enrichment fails, keep the 1688 list-card leads rather than discarding them.

## Testing Plan

Add focused tests for:

- Product extraction from card text containing company name, city, factory labels, subcategories, area, staff count, and service tags.
- Product extraction keeps first 2-3 valid subcategories and rejects noise.
- Search keyword expansion order includes Guangzhou, Qingyuan, Foshan, Dongguan before the original keyword.
- Collector builds leads from candidates without calling detail enrichment in default mode.
- Tianyancha merge does not overwrite an existing valid 1688 product subcategory.

## Out Of Scope

- Reworking frontend task UI.
- Changing non-1688 collectors.
- Adding paid 1688 APIs.
- Bypassing or defeating platform security controls.
