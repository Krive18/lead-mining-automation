/*
  精准客户数据挖掘本地系统 - MySQL 8.0 初始化脚本
*/

SET NAMES utf8mb4;

CREATE DATABASE IF NOT EXISTS `lead_mining`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

USE `lead_mining`;

CREATE TABLE IF NOT EXISTS `lead_task` (
  `id` varchar(64) NOT NULL COMMENT '任务主键，当前使用 uuid hex，项目适配字段',
  `task_name` varchar(128) NOT NULL COMMENT '任务名称，例如：抖音+企查查 服装 线索采集',
  `source_type` varchar(32) NOT NULL COMMENT '采集来源类型：douyin_qcc 抖音+企查查；alibaba_1688 1688',
  `industry` varchar(32) NOT NULL COMMENT '目标行业：3C数码、服装、美妆个护',
  `keyword_text` text NOT NULL COMMENT '本任务关键词，多个关键词使用英文逗号分隔',
  `target_city` varchar(255) NOT NULL DEFAULT '' COMMENT '目标地区，1688可保存广东省或多个广东地级市',
  `collect_limit` int NOT NULL COMMENT '本任务计划采集数量',
  `is_qcc_enabled` tinyint NOT NULL DEFAULT 1 COMMENT '是否调用企查查核验，0 否，1 是',
  `qcc_limit` int NOT NULL DEFAULT 0 COMMENT '本任务企查查调用额度上限',
  `status` varchar(32) NOT NULL COMMENT '任务状态：pending 待执行、running 准备中、collecting 采集公开线索、verifying 企查查核验、scoring 评分分级、saving 写入线索库、completed 已完成、failed 失败',
  `total_count` int NOT NULL DEFAULT 0 COMMENT '任务处理总数量',
  `success_count` int NOT NULL DEFAULT 0 COMMENT '任务成功处理数量',
  `failed_count` int NOT NULL DEFAULT 0 COMMENT '任务失败处理数量',
  `gmt_create` datetime NOT NULL COMMENT '创建时间',
  `gmt_modified` datetime NOT NULL COMMENT '最近修改时间',
  PRIMARY KEY (`id`),
  KEY `idx_lead_task_gmt_create` (`gmt_create`),
  KEY `idx_lead_task_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='线索采集任务表';

CREATE TABLE IF NOT EXISTS `lead_record` (
  `id` varchar(64) NOT NULL COMMENT '线索主键，当前使用 uuid hex，项目适配字段',
  `task_id` varchar(64) NOT NULL COMMENT '所属任务 id，对应 lead_task.id',
  `source_type` varchar(32) NOT NULL COMMENT '采集来源类型：douyin_qcc 抖音+企查查；alibaba_1688 1688',
  `source_keyword` varchar(128) NOT NULL COMMENT '命中或搜索使用的来源关键词',
  `industry` varchar(32) NOT NULL COMMENT '命中行业：3C数码、服装、美妆个护',
  `suspected_company_name` varchar(128) NOT NULL COMMENT '从公开页面抽取的疑似企业名称',
  `company_name` varchar(128) NOT NULL COMMENT '企查查核验后的标准企业名称；未核验时等于疑似企业名称',
  `company_name_en` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '英文公司名称',
  `douyin_nickname` varchar(128) NOT NULL DEFAULT '' COMMENT '抖音账号昵称，仅抖音来源有值',
  `product_name` varchar(128) NOT NULL DEFAULT '' COMMENT '产品或主营品类',
  `shop_level` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '店铺等级',
  `contact_name` varchar(64) NOT NULL DEFAULT '' COMMENT '公开联系人姓名，未公开则为空',
  `phone` varchar(512) NOT NULL DEFAULT '' COMMENT '最终联系电话，可用中文分号保存多个公开电话',
  `phone_source` varchar(64) NOT NULL DEFAULT '' COMMENT '电话来源，例如：抖音公开主页、1688公开店铺、企查查企业电话',
  `website_url` varchar(512) NOT NULL DEFAULT '' COMMENT '公开官网链接',
  `shop_url` varchar(512) NOT NULL DEFAULT '' COMMENT '公开店铺入口链接',
  `profile_url` varchar(512) NOT NULL DEFAULT '' COMMENT '来源主页链接，例如抖音主页或 1688 店铺页',
  `sample_video_url` varchar(512) NOT NULL DEFAULT '' COMMENT '代表视频链接，仅抖音来源有值',
  `is_blue_v` tinyint NOT NULL DEFAULT 0 COMMENT '是否蓝 V，0 否，1 是',
  `is_enterprise_verified` tinyint NOT NULL DEFAULT 0 COMMENT '是否企业认证，0 否，1 是',
  `company_status` varchar(32) NOT NULL DEFAULT '' COMMENT '企查查企业登记状态，例如：存续、在业、注销、吊销',
  `unified_social_credit_code` varchar(18) NOT NULL DEFAULT '' COMMENT '统一社会信用代码',
  `legal_person` varchar(64) NOT NULL DEFAULT '' COMMENT '法定代表人',
  `business_scope` text NOT NULL COMMENT '经营范围',
  `registered_address` varchar(256) NOT NULL DEFAULT '' COMMENT '注册地址',
  `risk_tag` varchar(128) NOT NULL DEFAULT '' COMMENT '风险标签，例如：低风险、经营异常待复核',
  `verification_status` varchar(32) NOT NULL COMMENT '核验状态：verified、mocked、not_found、skipped、quota_limited',
  `confidence` varchar(32) NOT NULL COMMENT '主体匹配置信度：high、medium、low',
  `score` int NOT NULL DEFAULT 0 COMMENT '线索评分，范围 0-100',
  `level` varchar(8) NOT NULL COMMENT '线索评级：A、B、C、D',
  `assignment_status` varchar(32) NOT NULL DEFAULT 'unassigned' COMMENT '线索分发状态：unassigned=未分配，assigned=已分配',
  `gmt_create` datetime NOT NULL COMMENT '创建时间',
  `gmt_modified` datetime NOT NULL COMMENT '最近修改时间',
  PRIMARY KEY (`id`),
  KEY `idx_lead_record_task_id` (`task_id`),
  KEY `idx_lead_record_company_name` (`company_name`),
  KEY `idx_lead_record_level` (`level`),
  KEY `idx_lead_record_assignment_status` (`assignment_status`),
  KEY `idx_lead_record_gmt_create` (`gmt_create`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='最终招商线索表';

CREATE TABLE IF NOT EXISTS `qcc_usage_log` (
  `id` varchar(64) NOT NULL COMMENT '企查查调用日志主键，当前使用 uuid hex，项目适配字段',
  `task_id` varchar(64) NOT NULL COMMENT '所属任务 id，对应 lead_task.id',
  `company_name` varchar(128) NOT NULL COMMENT '本次调用查询的企业名称',
  `interface_name` varchar(64) NOT NULL COMMENT '企查查接口名称，例如 enterprise_detail',
  `consume_count` int NOT NULL DEFAULT 1 COMMENT '本次调用消耗额度数量',
  `is_success` tinyint NOT NULL DEFAULT 1 COMMENT '接口调用是否成功，0 否，1 是',
  `failure_reason` varchar(256) NOT NULL DEFAULT '' COMMENT '失败原因，成功时为空',
  `gmt_create` datetime NOT NULL COMMENT '创建时间',
  `gmt_modified` datetime NOT NULL COMMENT '最近修改时间',
  PRIMARY KEY (`id`),
  KEY `idx_qcc_usage_log_task_id` (`task_id`),
  KEY `idx_qcc_usage_log_gmt_create` (`gmt_create`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='企查查额度调用日志表';

CREATE TABLE IF NOT EXISTS `task_event_log` (
  `id` varchar(64) NOT NULL COMMENT '任务事件日志主键，当前使用 uuid hex，项目适配字段',
  `task_id` varchar(64) NOT NULL COMMENT '所属任务 id，对应 lead_task.id',
  `event_level` varchar(32) NOT NULL COMMENT '事件级别：info、warning、error',
  `event_message` varchar(512) NOT NULL COMMENT '事件说明',
  `gmt_create` datetime NOT NULL COMMENT '创建时间',
  `gmt_modified` datetime NOT NULL COMMENT '最近修改时间',
  PRIMARY KEY (`id`),
  KEY `idx_task_event_log_task_id` (`task_id`),
  KEY `idx_task_event_log_gmt_create` (`gmt_create`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='任务运行事件日志表';

CREATE TABLE IF NOT EXISTS `keyword_config` (
  `id` varchar(64) NOT NULL COMMENT '关键词配置主键，当前使用固定业务 id，项目适配字段',
  `industry` varchar(32) NOT NULL COMMENT '所属行业：3C数码、服装、美妆个护、通用',
  `keyword` varchar(128) NOT NULL COMMENT '关键词内容',
  `keyword_type` varchar(32) NOT NULL COMMENT '关键词类型：industry 行业关键词；business 商业属性词',
  `is_enabled` tinyint NOT NULL DEFAULT 1 COMMENT '是否启用，0 否，1 是',
  `gmt_create` datetime NOT NULL COMMENT '创建时间',
  `gmt_modified` datetime NOT NULL COMMENT '最近修改时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_keyword_config_keyword` (`industry`, `keyword`, `keyword_type`),
  KEY `idx_keyword_config_industry` (`industry`),
  KEY `idx_keyword_config_keyword_type` (`keyword_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='关键词配置表';

CREATE TABLE IF NOT EXISTS `system_config` (
  `id` varchar(64) NOT NULL COMMENT '系统配置主键，当前使用固定业务 id，项目适配字段',
  `config_key` varchar(128) NOT NULL COMMENT '配置键，例如 qcc_daily_quota',
  `config_value` varchar(512) NOT NULL COMMENT '配置值',
  `remark` varchar(256) NOT NULL DEFAULT '' COMMENT '配置说明',
  `gmt_create` datetime NOT NULL COMMENT '创建时间',
  `gmt_modified` datetime NOT NULL COMMENT '最近修改时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_system_config_key` (`config_key`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='系统配置表';

INSERT IGNORE INTO `keyword_config`
  (`id`, `industry`, `keyword`, `keyword_type`, `is_enabled`, `gmt_create`, `gmt_modified`)
VALUES
  ('keyword-3c-001', '3C数码', '3C批发', 'industry', 1, NOW(), NOW()),
  ('keyword-3c-002', '3C数码', '手机壳工厂', 'industry', 1, NOW(), NOW()),
  ('keyword-3c-003', '3C数码', '数据线厂家', 'industry', 1, NOW(), NOW()),
  ('keyword-3c-004', '3C数码', '跨境3C', 'industry', 1, NOW(), NOW()),
  ('keyword-cloth-001', '服装', '服装工厂', 'industry', 1, NOW(), NOW()),
  ('keyword-cloth-002', '服装', '女装批发', 'industry', 1, NOW(), NOW()),
  ('keyword-cloth-003', '服装', '服装OEM', 'industry', 1, NOW(), NOW()),
  ('keyword-cloth-004', '服装', '跨境服装', 'industry', 1, NOW(), NOW()),
  ('keyword-beauty-001', '美妆个护', '化妆品工厂', 'industry', 1, NOW(), NOW()),
  ('keyword-beauty-002', '美妆个护', '护肤品OEM', 'industry', 1, NOW(), NOW()),
  ('keyword-beauty-003', '美妆个护', '彩妆代工', 'industry', 1, NOW(), NOW()),
  ('keyword-beauty-004', '美妆个护', '美妆供应链', 'industry', 1, NOW(), NOW()),
  ('keyword-business-001', '通用', '工厂', 'business', 1, NOW(), NOW()),
  ('keyword-business-002', '通用', '批发', 'business', 1, NOW(), NOW()),
  ('keyword-business-003', '通用', 'OEM', 'business', 1, NOW(), NOW()),
  ('keyword-business-004', '通用', '供应链', 'business', 1, NOW(), NOW());

INSERT IGNORE INTO `system_config`
  (`id`, `config_key`, `config_value`, `remark`, `gmt_create`, `gmt_modified`)
VALUES
  ('config-qcc-daily-quota', 'qcc_daily_quota', '200', '企查查每日本地调用额度上限，可在前端额度页调整', NOW(), NOW()),
  ('config-qcc-monthly-quota', 'qcc_monthly_quota', '5000', '企查查每月本地调用额度上限，可在前端额度页调整', NOW(), NOW());
