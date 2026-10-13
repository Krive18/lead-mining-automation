# 中国制造网 + 天眼查全自动采集设计

## 背景

当前系统已经支持多条公开页采集链路，其中 `1688 + 天眼查` 的形态最接近本次需求：先从行业平台采集候选企业名，再按企业名进入天眼查公开页补全法人、联系电话、经营范围和注册地址，最后复用现有广东过滤、评分、去重、入库流程。

本次新增一条全自动链路：`中国制造网 + 天眼查`。中国制造网只作为公开企业名候选来源，不承担联系方式补全。联系方式、法人和企业注册信息统一由天眼查补全。

## 目标

- 前端新增采集方向 `中国制造网 + 天眼查`。
- 前端采集方向中移除显示 `企查查` 和 `爱企查`，保留其他方向。
- 后端新增 source type：`made_in_china_tianyancha`。
- 自动访问中国制造网，按用户关键词搜索，切换到 `公司信息`，筛选 `华南`，提取公司名称。
- 提供 `中国制造网预登录` 能力，方便提前处理登录态、验证码或安全校验。
- 优先保留广东企业；如果中国制造网页面只提供华南信号，则让天眼查注册地址做最终广东确认。
- 使用现有天眼查公开页采集器按企业名补全法人、联系电话、经营范围、注册地址、企业状态和风险标签。
- 继续复用现有任务、评分、去重、导出、日志和 MySQL 数据结构。

## 非目标

- 不从中国制造网抓取登录后才可见的联系方式。
- 不点击 `在线交谈`、`发联系信`、`发布询价单` 等需要登录或互动的按钮。
- 不删除后端旧的 `qcc_public_web`、`aiqicha_public_web` 常量和历史数据兼容逻辑。
- 不在本阶段实现 `中国制造网 + 启信宝`，但设计上保留后续替换补全源的空间。
- 不新增数据库表。

## 推荐方案

采用和 `Alibaba1688TianyanchaCollector` 一致的组合采集模式，新增：

- `SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA = "made_in_china_tianyancha"`
- `MadeInChinaPublicPageCollector`
- `MadeInChinaTianyanchaCollector`

`MadeInChinaPublicPageCollector` 只负责中国制造网搜索和公司名抽取。`MadeInChinaTianyanchaCollector` 负责把中国制造网候选企业名交给现有天眼查采集器补全，并合并字段。

这种方案比直接扩展 1688 采集器更清晰，因为中国制造网的搜索入口、标签、地区筛选和卡片结构都和 1688 不同。它也比一开始抽象成通用 B2B 平台采集框架更稳，因为当前只新增一个平台，过早抽象会扩大改动面。

## 后端设计

### Source Type

在 `backend/app/core/constant.py` 增加：

```text
SOURCE_TYPE_MADE_IN_CHINA_TIANYANCHA = "made_in_china_tianyancha"
```

在 `TaskCreateDTO` 和 `CollectedLeadDTO` 的 `source_type` Literal 中加入该值。

### CollectorFactory

在 `CollectorFactory.get_collector` 中增加分支：

```text
made_in_china_tianyancha -> MadeInChinaTianyanchaCollector()
```

### TaskService

将 `made_in_china_tianyancha` 加入公开页类型集合，使其不调用企查查额度和接口：

- `PUBLIC_WEB_ONLY_SOURCE_TYPE_SET`
- `PHONE_REQUIRED_SOURCE_TYPE_SET`

任务名称显示为：

```text
中国制造网+天眼查 目标行业 线索采集
```

空结果诊断文案说明：

```text
中国制造网本次未采集到公司信息；请确认关键词足够具体，例如“手机壳工厂”“数据线厂家”，并确认页面没有访问限制。
```

### 中国制造网预登录

新增 `中国制造网预登录` 能力，使用独立浏览器资料目录：

```text
backend/data/browser-profile/made-in-china
```

预登录入口打开 `https://cn.made-in-china.com/`。用户可以在弹出的浏览器中完成登录、验证码或安全校验，完成后关闭浏览器，再启动正式采集任务。正式采集复用同一资料目录，以保留登录态和站点信任状态。

该预登录只用于保证搜索和公司列表页面稳定访问，不用于抓取登录后才可见的联系方式，也不自动点击站内沟通、发信或询价功能。

### 中国制造网采集器

`MadeInChinaPublicPageCollector` 的职责：

1. 生成或打开搜索页。
2. 输入或拼接关键词。
3. 切换到 `公司信息`。
4. 选择地区 `华南`。
5. 滚动列表加载结果。
6. 从公司卡片中抽取企业名、产品摘要、页面 URL、地区文本。
7. 对企业名去重和过滤。

中国制造网采集器只读取公开可见内容。考虑到站点存在登录入口，系统提供预登录能力；若正式采集时仍出现验证码、访问过频、安全校验或登录遮挡，则记录任务事件并提示先完成预登录后重试。

### 搜索与地区策略

优先使用稳定 URL 构造；如果 URL 参数不稳定，则使用 Playwright 操作页面：

1. 打开 `https://cn.made-in-china.com/`。
2. 确认搜索类型为 `产品`。
3. 输入关键词并点击搜索。
4. 在结果页点击 `公司信息` 标签。
5. 点击地区筛选，选择 `华南`。

采集器需要支持多种页面形态：

- 首页搜索后跳转到结果页。
- 产品信息页切换到公司信息页。
- 公司信息页分页或无限滚动。

如果无法完成地区筛选，仍可采集候选，但必须把日志写清楚：本轮未确认中国制造网华南筛选，后续以天眼查注册地址确认广东。

### 企业名过滤

企业名必须通过现有 `clean_company_name_text` 和企业名有效性规则。新增中国制造网噪音词过滤：

- 中国制造网
- Made-in-China
- 首页
- 产品信息
- 公司信息
- 采购信息
- 供应商
- 热门产品
- 发布询价单
- 在线交谈
- 发联系信
- 查看更多公司信息

只保留强企业后缀或可信工厂名称，例如：

- 有限公司
- 有限责任公司
- 股份有限公司
- 工厂
- 厂
- 商行
- 经营部

产品名如 `手机壳工厂`、类目名如 `手机套`、筛选标签如 `华南` 不应作为企业名入库。

### 天眼查补全

`MadeInChinaTianyanchaCollector.collect` 流程：

1. 调用 `MadeInChinaPublicPageCollector.collect` 得到中国制造网候选列表。
2. 提取候选企业名，去重。
3. 调用 `EnterprisePublicWebCollector.create_tianyancha_collector().collect_by_company_names`。
4. 按企业名归一化 key 合并补全结果。
5. 保留 source_type 为 `made_in_china_tianyancha`。
6. 天眼查匹配不到时保留候选，但电话为空，风险标记为 `天眼查待补全` 或 `未见公开电话`。

字段合并规则沿用 1688：

- 电话优先使用天眼查补全结果。
- 法人、企业状态、经营范围、注册地址优先使用天眼查补全结果。
- 中国制造网的产品摘要可作为 `product_name`。
- 中国制造网公司页 URL 可作为 `profile_url`。
- 中国制造网地区/筛选文本进入 `region_text`，辅助广东判断。

## 前端设计

`TaskComposer.vue` 中采集方向调整：

保留：

- `启信宝`
- `天眼查`
- `AI 1688搜企`
- `1688 + 天眼查`
- `中国制造网 + 天眼查`

移除显示：

- `企查查`
- `爱企查`

默认采集方向保持当前的 `1688 + 天眼查`。`中国制造网 + 天眼查` 作为新增按钮，由用户主动选择。

`中国制造网 + 天眼查` 的引导文案：

```text
先从中国制造网公开公司列表提取企业名，并筛选华南；再按企业名进入天眼查补全法人、联系电话和注册地址。
```

该方向显示 `预登录中国制造网` 按钮。`is_qcc_enabled` 自动为 false，`qcc_limit` 为 0。

`format.ts`、线索筛选和导出来源展示增加：

```text
made_in_china_tianyancha -> 中国制造网+天眼查
```

## 数据库与兼容性

不新增数据库表和字段。新链路复用：

- `lead_task.source_type`
- `lead_record.source_type`
- `task_event_log`

历史 `qcc_public_web` 和 `aiqicha_public_web` 数据仍可显示、筛选和导出。前端只是隐藏新建任务入口，不清理历史记录。

## 错误处理

- 中国制造网无结果：任务日志提示更换具体产品词。
- 未找到公司信息标签：尝试从可见文本中抽取企业名，并记录降级日志。
- 华南筛选失败：继续采集候选，后续以天眼查注册地址确认广东。
- 页面访问限制：记录访问限制提示，避免误判为无结果。
- 登录态失效或安全校验：提示用户先点击 `预登录中国制造网`，完成登录/验证后关闭浏览器再重新采集。
- 天眼查补全失败：保留中国制造网候选，任务不中断。
- 企业名全部被过滤：记录过滤原因，便于调整关键词或页面选择器。

## 测试计划

后端测试与验证：

- `TaskCreateDTO` 接受 `made_in_china_tianyancha`。
- `CollectorFactory` 能返回 `MadeInChinaTianyanchaCollector`。
- 模拟中国制造网公司列表 HTML，可抽取企业名。
- 产品名、类目、按钮文案不会被当作企业名。
- 天眼查补全异常时，组合采集器仍返回中国制造网候选。
- `TaskService` 对新 source type 不调用企查查额度。

前端测试与验证：

- `npm run build` 通过。
- 采集方向不再显示 `企查查` 和 `爱企查`。
- 采集方向显示 `中国制造网 + 天眼查`。
- 选择该方向后，企查查核验保持禁用，额度为 0，并显示 `预登录中国制造网` 按钮。

集成验证：

- 使用关键词 `手机壳工厂` 创建 `中国制造网 + 天眼查` 单次任务。
- 任务日志出现中国制造网搜索、公司信息切换、华南筛选、天眼查补全事件。
- 最终线索至少包含企业名；天眼查可匹配时包含法人、电话、注册地址。
- 入库数据 source_type 为 `made_in_china_tianyancha`。

## 后续扩展

后续若要做 `中国制造网 + 启信宝`，建议抽出一个小型补全源接口：

```text
collect_by_company_names(industry, company_name_list, collect_limit)
```

届时 `MadeInChinaTianyanchaCollector` 和未来 `MadeInChinaQixinCollector` 可以共享中国制造网候选采集器，只替换企业信息补全器。
