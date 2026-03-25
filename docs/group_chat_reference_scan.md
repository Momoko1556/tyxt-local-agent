# 参考项目可复用性评估（2026-03-19）

## 扫描对象

- `E:\参考模块\aibitat-main`
- `E:\参考模块\mahilo-main`
- `E:\参考模块\agent-squad-main`

## 结论

- 三个项目都不适合直接“整模块拷贝接入”到当前工程。
- 原因：当前项目是 Python + Flask + 单页 HTML（`frontend/TYXT_UI.html`）的既有架构，三者分别是独立多 Agent 编排框架（TypeScript 或独立 Python 服务），接入成本高于本轮“保旧扩新”目标。

## 可借鉴点

- `aibitat`：channel 对话 + `maxRounds` 防循环思路，适合借鉴“抑制重复刷屏/循环回复”策略。
- `mahilo`：AgentManager 的“跨 Agent 最近 N 轮上下文共享”思路，适合借鉴“按需多 Agent 轮转”策略门控。
- `agent-squad`：分类路由 + 主 Agent 编排（supervisor）思路，适合借鉴“优先级路由 + 单出口默认 + 必要时轮转”的决策框架。

## 本轮落地策略

- 不引入外部框架运行时，不改现有主架构。
- 在现有后端内新增群聊 store/router/prompt builder，并通过前端调用新接口完成群聊 UI 和管理能力。

