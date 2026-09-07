export const STATUS_LABELS = {
  pending: "待处理",
  processing: "处理中",
  completed: "完成",
  failed: "失败",
  queued: "排队中",
  running: "运行中",
  cancelled: "已取消",
  skipped: "已跳过",
};

export const QUALITY_LABELS = {
  pass: "通过",
  fail: "失败",
  not_evaluated: "未评估",
};

export function formatBytes(value) {
  if (!Number.isFinite(value) || value < 0) return "--";
  if (value < 1024) return `${value} B`;
  const units = ["KB", "MB", "GB", "TB", "PB"];
  let size = value / 1024;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  const digits = size >= 100 ? 0 : size >= 10 ? 1 : 2;
  return `${size.toFixed(digits)} ${units[index]}`;
}

export function formatDate(value) {
  if (!value) return "--";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "--";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(date);
}

export function formatProgress(value) {
  const number = Number(value);
  return `${Math.min(100, Math.max(0, Number.isFinite(number) ? Math.round(number) : 0))}%`;
}

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
