# Milestone Register

基準日期：2026-08-17（M3 已完成）。

| Milestone | 狀態 | 證據 | Exit gate | 下一動作 |
|---|---|---|---|---|
| M0 證據與市場契約 | `complete` | [m0-project-contract.md](m0-project-contract.md) | 市場、證據、時間、成本、資金、軌道、禁止事項及 owner 均明確 | 契約變更須更新版本及理由 |
| M1 架構與重用稽核 | `complete` | [m1-architecture-reuse-audit.md](m1-architecture-reuse-audit.md)、[ADR-0001](adr/0001-separate-taiwan-core-and-alphamaster-research.md) | AlphaMaster／Taiwan Core 權責及兩個 artifact contract 無歧義 | Upstream 或架構變更時重驗 |
| M2 不可變官方 raw data | `complete` | [M2 closure evidence](evidence/m2-owner-approvals-release-and-durable-audit-2026-08-03.md)、[Owner 決定](evidence/m2-owner-approval-decision-2026-08-03.md)、[M2 exit verification](evidence/m2-6-exit-verification-2026-08-03.md)、[操作手冊](m2-operations-runbook.md)、[M2 藍圖](m2-immutable-raw-data-plan.md)、[來源清冊](m2-source-inventory.md)、[daily-price／gap evidence](evidence/m2-3-daily-price-pilot-and-gap-audit-2026-08-03.md)、[raw 契約](contracts/raw-snapshot-contract.md) | 36/36 sources；55 initial accepted + 1 released quarantine；0 unresolved；durable archive、分離備份與 restore audit 通過 | 依核准範圍進入 M3；production cutover 仍須 M3 自己的對照、回復與 owner evidence |
| M3 Point-in-time warehouse | `complete`（附七項已記錄例外）| [M3 計畫](m3-point-in-time-warehouse-plan.md)、[PIT 契約](contracts/pit-warehouse-contract.md)、[source-to-table map](contracts/m3-source-to-table-map.md)、[TEJ 匯入規格](contracts/tej-import-spec.md)、[G0 決定](evidence/m3-g0-owner-decision-2026-08-03.md)、[G0 修訂 D9–D10](evidence/m3-g0-amendment-d9-d10-2026-08-16.md)、[M3.7 驗證報告](evidence/m3-7-validation-2026-08-17.json)、[M3.8 Exit review](evidence/m3-8-exit-review-2026-08-17.md) | 2025-01-01 至 2026-08-03 每個 TWSE／TPEx calendar date 都有 certificate；開市／特殊 session 全為 `supported`、休市日有官方 `not-session`；未列或 partial／blocked／unknown 皆 fail closed | **G0 §5 條件 1、2、3、5 全部通過；條件 4 已大幅補齊**（M3.9 以 TEJ 補上市公告日 95.4%；M3.11 上櫃行動晉升且全為 `publisher-exact`；M3.10 減資取得公告日）。Validation Owner 已於 2026-08-17 簽核。M3.7 五項驗證全 `passed`，legacy 逐日列數零差異。七項例外全部已記錄並有測試盯著，其中 #1 與 #2 已解除。**下一步 M4**；production cutover 仍需 G4 |
| M4 台股規則與成本 | `in_progress` | [M4 規則與成本契約](contracts/m4-market-rules-contract.md)、參考實作 `m4/`、**99 passed** | 零股、tick、漲跌停、停牌、費用、稅、T+2 有規則與邊界測試 | 檔位由 406,445 筆官方收盤價實測推導；漲跌停以 1,665 筆官方公布值驗證，減資恢復日另以 20 筆官方值驗證。剩餘：除權息日漲跌停官方計算式，以及上游化至 Taiwan Core。**券商費率不阻擋 M4**（M0 只要求條款可設定），它阻擋的是 M10 |
| M5 Cash/share simulator | `pending` | - | 帳本恆等式與不可能交易阻擋通過 | 依 M4 schema 實作 |
| M6 AlphaMaster adapter | `pending` | - | frozen dataset 可重現研究 run | 使用 dataset contract |
| M7 Nested validation | `pending` | - | sealed OOS 未被重複選模、baseline 公平 | 使用 candidate contract |
| M8 Governance UI | `pending` | - | formal transition 可稽核，AI 無批准權 | M7 後開始 |
| M9 Shadow／paper | `pending` | - | 各至少 60 交易日且差異受控 | 無法由歷史回測替代 |
| M10 NT$10,000 canary | `blocked` | 券商、費率、零股成交證據未定 | 對帳、風險、停止及 rollback 完整 | 需人工批准 |
| M11 持續改進 | `pending` | - | 所有變更可重現且無法跳過 promotion gate | Formal 前先建 registry |
| M12 Broker integration | `blocked` | 尚未選券商 | sandbox -> paper -> canary | 不授權目前開始 |

## M0／M1／M2 完成及進入 M3 不代表

- AlphaMaster 已可用於台股正式回測；
- `tw-sepa-screener` 當前髒工作樹已封存；
- 任一策略已通過 M7；
- 已取得券商費率或下單權；
- NT$10,000 已獲准投入真實交易。
- M2 完成不代表 M3 可覆寫正式 DuckDB、legacy raw 或 stock master；目前只批准唯讀／shadow migration 範圍。
- M3 `in_progress` 不代表已有完整歷史 coverage、已可正式回測，或 production cutover 已批准。
- M3.1／M3.1b `complete` 不代表已有可重建的歷史；coverage ledger v2 中 `supported` 仍為 0。
- 抓到 764 個交易日的日價不代表這些日期可供回測；缺 market_status 與 security_lifecycle 歷史，仍不足以重建當時的可交易股票池。
- Owner 批准抓取程式不代表資料已抓到；抓到資料也不代表該日期成為 `supported`，仍須通過完整資料族 coverage 檢查。
- 2025 年官方交易行事曆已永久無法取得（端點只回傳當年度），該年度改依 TEJ `licensed-vendor-snapshot`，證據等級低於官方。

## 變更規則

- M0 的市場、資金、風險、證據或禁止事項改變時，提升契約版本並記錄批准。
- M1 的責任邊界、整合方向、AlphaMaster major upstream 或 license 改變時，更新稽核及 ADR。
- 只有滿足 exit gate 才可將 milestone 標為 `complete`。
- 未解決的外部依賴必須標為 `blocked`，不可用 `complete with caveats` 掩蓋。
