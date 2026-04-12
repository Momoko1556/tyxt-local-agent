export type UiLocale = 'en' | 'zh';

export const RESOURCE_LABELS: Record<string, Record<UiLocale, string>> = {
  document: { en: 'Bedroom', zh: '卧室' },
  images: { en: 'Theater', zh: '剧场' },
  memory: { en: 'Workshop', zh: '工坊' },
  skills: { en: 'Lounge', zh: '休息室' },
  gateway: { en: 'Living Room', zh: '客厅' },
  log: { en: 'Archive', zh: '档案室' },
  mcp: { en: 'Gallery', zh: '展厅' },
  schedule: { en: 'Archive', zh: '档案室' },
  alarm: { en: 'Theater', zh: '剧场' },
  agent: { en: 'Main Hall', zh: '主厅' },
  task_queues: { en: 'Living Room', zh: '客厅' },
  break_room: { en: 'Study', zh: '书房' }
};

export const UI_TEXT = {
  title: { en: 'TYXT Visual Space', zh: 'TYXT 可视化空间' },
  recentActivity: { en: 'Recent Events', zh: '最近事件' },
  noActivity: { en: 'No recent events yet.', zh: '暂时没有新的事件。' },
  archiveLive: { en: 'TYXT SPACE', zh: 'TYXT 空间' },
  quickRooms: { en: 'Room Navigator', zh: '房间导航' },
  statsAssets: { en: 'objects', zh: '物件' },
  statsLive: { en: 'online', zh: '在线' },
  statsEvents: { en: 'events', zh: '事件' },
  waiting: { en: 'standby', zh: '待机' },
  hideInfo: { en: 'Hide Panel', zh: '隐藏侧栏' },
  showInfo: { en: 'Show Panel', zh: '显示侧栏' },
  shortcuts: { en: 'Shortcuts', zh: '快捷键' },
  search: { en: 'Search', zh: '搜索' },
  copyContext: { en: 'Copy Summary', zh: '复制摘要' },
  close: { en: 'Close', zh: '关闭' },
  grid: { en: 'Grid', zh: '网格' },
  list: { en: 'List', zh: '列表' },
  allKinds: { en: 'All Types', zh: '全部类型' },
  recommended: { en: 'Recommended', zh: '推荐' },
  newest: { en: 'Newest', zh: '最新' },
  oldest: { en: 'Oldest', zh: '最早' },
  largest: { en: 'Largest', zh: '最大' },
  smallest: { en: 'Smallest', zh: '最小' },
  theme: { en: 'Theme', zh: '主题' },
  debug: { en: 'Debug', zh: '调试' },
  clawSkin: { en: 'Avatar', zh: '形象' },
  preview: { en: 'Preview', zh: '预览' },
  loadingPreview: { en: 'Loading preview…', zh: '预览加载中…' },
  open: { en: 'Open', zh: '打开' },
  openFolder: { en: 'Open Folder', zh: '打开目录' },
  copyPath: { en: 'Copy Path', zh: '复制路径' },
  copyExcerpt: { en: 'Copy Excerpt', zh: '复制摘录' },
  openSource: { en: 'Open Source', zh: '打开来源' },
  copySource: { en: 'Copy Source', zh: '复制来源' },
  openTopItem: { en: 'Open Top Item', zh: '打开首项' },
  copyDetail: { en: 'Copy Detail', zh: '复制详情' },
  topItem: { en: 'Top Item', zh: '首项' },
  recentEvents: { en: 'Recent Events', zh: '最近事件' },
  status: { en: 'Status', zh: '状态' },
  source: { en: 'Source', zh: '来源' },
  signal: { en: 'Signal', zh: '信号' },
  focus: { en: 'Focus', zh: '焦点' },
  pointer: { en: 'Pointer', zh: '指针' },
  client: { en: 'Client', zh: '屏幕' },
  scene: { en: 'Scene', zh: '场景' },
  lastClick: { en: 'Last Click', zh: '上次点击' },
  clickClient: { en: 'Click Client', zh: '点击屏幕' },
  stageInside: { en: 'Inside Stage', zh: '在场景内' },
  stageOutside: { en: 'Outside Stage', zh: '场景外' },
  active: { en: 'Active', zh: '活跃' },
  idle: { en: 'Idle', zh: '空闲' },
  alert: { en: 'Alert', zh: '告警' },
  offline: { en: 'Offline', zh: '离线' }
} as const;

export function resourceLabel(id: string, locale: UiLocale): string {
  return RESOURCE_LABELS[id]?.[locale] ?? id;
}

export function uiText<K extends keyof typeof UI_TEXT>(key: K, locale: UiLocale): string {
  return UI_TEXT[key][locale];
}
