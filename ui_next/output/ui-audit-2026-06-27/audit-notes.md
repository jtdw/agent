# 2026-06-27 聊天工作区截图验收记录

## 验收范围

- 页面模式：智能聊天整页工作区的底部输入区、右侧任务栏、消息区域。
- 浮窗模式：地图工作台里的左侧悬浮聊天窗 footer，与右侧“数据与工具”任务栏同屏表现。
- thinking / 任务卡：通过任务卡视觉验收 harness 覆盖“实时任务卡与公开过程”状态。

## 截图证据

- `07-page-1280-tuned.png`：页面模式 1280 宽度验收图。
- `08-task-card-narrow-tuned.png`：430px 窄屏任务卡验收图。
- `09-floating-1280-tuned.png`：地图工作台浮窗模式 1280 宽度验收图。

## 结论

- 页面模式右侧任务栏未发生裁切；浏览器实测是完整可见的。早先 in-app 截图出现的裁切更像截图视口裁剪问题。
- 页面模式 footer 已压缩为紧凑结构，高度约从 244px 降到 196px。
- 浮窗模式 footer 原先在 1280 视口下没有触发窄屏规则，导致 428px 宽浮窗里的 footer 高约 307px；已改成 `.is-floating` 自带紧凑规则，复测约 192px，与页面模式基本一致。
- 窄屏任务卡 header 中标题身份区已独占一行，不再被运行状态胶囊挤成极窄列。
- 右侧任务栏和浮窗聊天同屏时保持独立边界、无重叠，底部 dock 不遮挡聊天输入核心控件。

## 已验证命令

- `node tests/chatComposerExperience.test.mjs`
- `node tests/chatTaskCardAndResults.test.mjs`
- `npm test`
- `npm run build`

## 未覆盖说明

- 真实模型流式回复中的瞬时 thinking 占位需要登录态和实际任务触发，本次没有强造后端任务；已用真实 `ChatMessageRenderer` 的视觉 harness 覆盖稳定的公开过程 / 任务卡状态。
