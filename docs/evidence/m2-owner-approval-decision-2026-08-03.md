# M2 三項 Owner 批准決定（2026-08-03）

| 欄位 | 值 |
|---|---|
| Decision ID | `M2-OWNER-APPROVAL-20260803-01` |
| Milestone | `M2` |
| 決定狀態 | `approved` |
| 記錄時間 | `2026-08-03T10:14:56Z` |
| 人工批准者 | 工作區使用者／Project Owner |
| 原始批准證據 | 本 Codex task 的使用者訊息：`3項全部批批准` |
| 記錄原則 | 這是人工決定的追加式紀錄；不回寫舊 quality decision，也不代表 Codex 具有批准權 |

## 批准 1：TWT49U 保存與使用範圍

Compliance／Project Owner 批准 `TWSE-ACTIONS-HIST`（TWT49U）這次已擷取資料用於：

- M2 不可變 raw／parse／quality 證據保存；
- M3 的正規化、point-in-time 檢查、研究及驗證；
- 專案內部重現與稽核。

限制：不得因本決定推論可公開再散布、轉售或繞過 TWSE／資料提供者條款；外部條款仍然有效。本決定只解除專案內部的 owner-approval gate，不把原始 `quarantined` quality manifest 改成 `accepted`。解除必須以唯一、可驗證的 append-only `released` event 完成。

## 批准 2：durable archive、backup 與 retention

Infrastructure Owner 批准下列配置：

- 正式 durable archive：`C:\project\tw-sepa-screener\data\raw_v2\m2_2026-08-03`；
- 分離磁碟備份：`E:\tw-sepa-screener-backup\raw_v2\m2_2026-08-03`；
- owner：工作區使用者／Project Owner；
- retention：無期限保留，`automatic_deletion=disabled`；
- 刪除或縮短 retention：必須取得 Data Owner、Infrastructure Owner 與 Compliance 的新人工批准；
- 驗收：主封存與備份必須逐檔 SHA-256 相同，且兩邊均需通過唯讀 archive audit；未通過不得宣告 M2 完成。

## 批准 3：M2 evidence 與 M3 使用範圍

Validation Owner 批准 M2 evidence bundle，並允許 M3：

- 唯讀使用 36 個 P0 source 的 durable M2 archive；
- 使用已驗證的 96-session daily-price shadow 範圍進行資料模型、PIT 與 migration 驗證；
- 建立新的 shadow／normalized dataset，並與 legacy 資料做可追溯比較。

這項批准不授權 M3 直接覆寫正式 DuckDB、legacy raw 或 stock master；不批准策略升級、自動下單或真實資金交易。任何 production cutover 必須在 M3 產生自己的對照、回復與 owner evidence 後另行決定。

## 完成條件

本決定本身不等於 M2 已完成。只有在 durable archive 落地、分離備份逐檔驗證、唯一 release event 建立、原 quality manifest 雜湊不變、雙份 archive audit 均為 `passed`，且 current governance 文件更新後，M2 才能改為 `complete`。
