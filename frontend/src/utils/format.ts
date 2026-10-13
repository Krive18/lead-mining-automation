export function formatSourceType(sourceType: string) {
  const sourceTypeMap: Record<string, string> = {
    douyin_qcc: '抖音线索',
    qcc_public_web: '企业公开页',
    fengniao_public_web: '美亚风鸟',
    aiqicha_public_web: '爱企查',
    qixin_public_web: '启信宝',
    tianyancha_public_web: '天眼查',
    ai_web_search: 'AI 1688搜企',
    alibaba_1688: '1688采集',
    alibaba_1688_page_assistant: '1688页面助手',
    alibaba_1688_page_import: '1688普通页面导入',
    alibaba_international: '阿里国际站',
    made_in_china_tianyancha: '中国制造网+天眼查',
  };
  return sourceTypeMap[sourceType] ?? sourceType;
}

export function formatTaskStatus(status: string) {
  const statusMap: Record<string, string> = {
    pending: '待执行',
    running: '准备中',
    collecting: '采集公开线索',
    waiting_manual: '等待人工验证',
    verifying: '企业信息核验',
    scoring: '评分分级',
    saving: '写入线索库',
    completed: '已完成',
    failed: '失败',
  };
  return statusMap[status] ?? status;
}

export function isActiveTaskStatus(status: string) {
  return ['pending', 'running', 'collecting', 'waiting_manual', 'verifying', 'scoring', 'saving'].includes(status);
}

export function getTaskStagePercent(status: string) {
  const stagePercentMap: Record<string, number> = {
    pending: 8,
    running: 16,
    collecting: 34,
    waiting_manual: 46,
    verifying: 56,
    scoring: 74,
    saving: 90,
    completed: 100,
    failed: 100,
  };
  return stagePercentMap[status] ?? 0;
}

export function formatTaskCount(taskStatus: string, countValue: number) {
  if (isActiveTaskStatus(taskStatus) && countValue === 0) {
    return '处理中';
  }
  return String(countValue);
}

export function formatVerificationStatus(status: string) {
  const statusMap: Record<string, string> = {
    verified: '已核验',
    mocked: '历史核验',
    not_found: '未查到',
    skipped: '未核验',
    quota_limited: '额度不足',
    public_web: '可见字段',
  };
  return statusMap[status] ?? status;
}

export function getVerificationStatusTitle(status: string) {
  if (status === 'mocked') {
    return '历史版本产生的核验状态，当前版本已停止产出此类结果。';
  }
  if (status === 'skipped') {
    return '未调用企业信息 API，可能是 API 未配置、额度不足或本任务关闭了核验。';
  }
  if (status === 'public_web') {
    return '页面可见字段直接入库，未调用官方 API。';
  }
  return '';
}

export function formatTaskName(taskName: string) {
  return taskName
    .replace(/企查查公开页试验/g, '企业公开页')
    .replace(/企查查试验/g, '企业公开页')
    .replace(/美亚风鸟公开页/g, '美亚风鸟')
    .replace(/爱企查公开页/g, '爱企查')
    .replace(/启信宝公开页/g, '启信宝')
    .replace(/天眼查公开页/g, '天眼查')
    .replace(/中国制造网公开页/g, '中国制造网')
    .replace(/1688公开页面/g, '1688')
    .replace(/普通页面/g, '页面');
}
