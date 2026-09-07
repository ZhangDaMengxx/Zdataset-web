import test from "node:test";
import assert from "node:assert/strict";

import { escapeHtml, formatBytes, formatDate, formatProgress, QUALITY_LABELS, STATUS_LABELS } from "../format.js";

test("formats indexed manifest sizes", () => {
  assert.equal(formatBytes(0), "0 B");
  assert.equal(formatBytes(2048), "2.00 KB");
  assert.equal(formatBytes(undefined), "--");
});

test("formats progress defensively", () => {
  assert.equal(formatProgress(-4), "0%");
  assert.equal(formatProgress(52.6), "53%");
  assert.equal(formatProgress(800), "100%");
});

test("keeps pass and not evaluated semantically distinct", () => {
  assert.equal(QUALITY_LABELS.pass, "通过");
  assert.equal(QUALITY_LABELS.not_evaluated, "未评估");
  assert.equal(STATUS_LABELS.processing, "处理中");
  assert.equal(STATUS_LABELS.skipped, "已跳过");
});

test("escapes untrusted manifest text", () => {
  assert.equal(escapeHtml('<script a="1">'), "&lt;script a=&quot;1&quot;&gt;");
  assert.equal(formatDate("not-a-date"), "--");
});
