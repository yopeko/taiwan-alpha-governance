# Taiwan Alpha Governance Project

本倉庫保存台股 AlphaMaster 適配工作的治理、架構與跨專案契約，不保存或複製 AlphaMaster 原始碼，也不取代既有 `tw-sepa-screener`。

## 目前狀態

| 里程碑 | 狀態 | 完成日 | 主要產物 |
|---|---|---|---|
| M0 證據與市場契約 | complete | 2026-08-02 | [M0 專案契約](docs/m0-project-contract.md) |
| M1 架構與重用稽核 | complete | 2026-08-02 | [M1 架構與重用稽核](docs/m1-architecture-reuse-audit.md) |
| M2 官方不可變原始資料 | complete | 2026-08-03 | 36 sources、56 live observations、55 initial accepted + 1 released quarantine、0 unresolved；正式封存與 E: 備份均通過稽核。[M2 closure evidence](docs/evidence/m2-owner-approvals-release-and-durable-audit-2026-08-03.md) |
| M3 Point-in-time warehouse | in progress（M3.2 起 blocked）| - | M3.0／M3.1 complete。1,160 列 coverage ledger 顯示 `supported`＝0、缺 1,143 個 market-date；M3.2 需 Owner 決定。[M3 計畫](docs/m3-point-in-time-warehouse-plan.md)、[M3.1 證據](docs/evidence/m3-1-coverage-ledger-and-durable-archival-2026-08-16.md) |

詳細狀態及退出門檻見 [里程碑登錄表](docs/milestone-register.md)。

## 已採用的架構決策

`tw-sepa-screener` 是台股資料、Point-in-time、交易規則、帳本、正式策略版本與每日營運的權威系統；AlphaMaster 是候選因子與公式的研究引擎。兩者先保持獨立，以版本化資料集和候選策略封包溝通。完整理由見 [ADR-0001](docs/adr/0001-separate-taiwan-core-and-alphamaster-research.md)。

資料流固定為：

```text
TWSE / TPEx / MOPS
        |
        v
tw-sepa-screener official and point-in-time core
        |
        | research dataset package (read-only)
        v
AlphaMaster research laboratory
        |
        | research-only candidate package
        v
Taiwan validation and cash-ledger replay
        |
        v
shadow -> paper -> human-approved canary -> formal
```

AlphaMaster 不得直接寫入正式策略、紙上帳本或真實委託；AI 分析不得進入自動評分、升級或下單路徑。

## 核心契約

- [研究資料集契約](docs/contracts/research-dataset-contract.md)
- [候選策略封包契約](docs/contracts/strategy-candidate-contract.md)
- [證據來源登錄表](docs/evidence/source-register.md)
- [Official Raw Snapshot 契約](docs/contracts/raw-snapshot-contract.md)
- [M2 官方資料來源清冊](docs/m2-source-inventory.md)
- [M2 entry baseline](docs/evidence/tw-sepa-baseline-2026-08-02.md)
- [M2.2 capture foundation evidence](docs/evidence/m2-2-capture-foundation-2026-08-02.md)
- [M2.3 calendar／master isolated pilot evidence](docs/evidence/m2-3-calendar-master-pilot-2026-08-02.md)
- [M2.3 daily-price pilot and gap audit](docs/evidence/m2-3-daily-price-pilot-and-gap-audit-2026-08-03.md)
- [M2.6 exit verification](docs/evidence/m2-6-exit-verification-2026-08-03.md)
- [M2 三項 Owner 批准決定](docs/evidence/m2-owner-approval-decision-2026-08-03.md)
- [M2 批准、release、durable archive 與 restore closure](docs/evidence/m2-owner-approvals-release-and-durable-audit-2026-08-03.md)
- [M2 操作手冊](docs/m2-operations-runbook.md)
- [M3 Point-in-time warehouse 計畫](docs/m3-point-in-time-warehouse-plan.md)
- [M3 Point-in-time warehouse 契約](docs/contracts/pit-warehouse-contract.md)
- [M3 entry baseline](docs/evidence/m3-entry-baseline-2026-08-03.md)
- [M3 G0 Owner 決定](docs/evidence/m3-g0-owner-decision-2026-08-03.md)
- [M3.1 Source-to-Table Map、Availability 與 Conflict Policy](docs/contracts/m3-source-to-table-map.md)
- [M3.1 完成證據：耐久封存與 coverage ledger](docs/evidence/m3-1-coverage-ledger-and-durable-archival-2026-08-16.md)

## 已凍結的 M0 基線

- 市場：TWSE 與 TPEx 普通股；其他商品必須另立契約。
- 頻率：收盤後日線研究與低頻決策。
- 起始資金：NT$10,000，僅作流程驗證資金。
- 部位：只做多、現股、最多兩檔、單檔上限 45%、保留至少 10% 現金。
- 禁止：融資、槓桿、放空、借券、當沖及未經批准的自動下單。
- 策略：`research-sandbox`、`challenger`、`formal` 分離；目前沒有獲准的真實資金正式策略。
- 升級：只能按 `idea -> research -> validated -> shadow -> paper -> canary -> formal` 前進，不得跳級。

## M2 完成結果與 M3 邊界

M2 已完成：36 個 endpoint-level P0 sources 各有唯一 offline parser；56 個 hash-verified observations 全部 parsed。不可變初始決定仍正確保留為 55 accepted、1 quarantined；`TWSE-ACTIONS-HIST` 另有唯一且可驗證的人工 `released` event，因此 unresolved quarantine 為 0。每日股價舊稱「94 天缺口」已修正為 96 天 full-market repair scope，96/96 完成隔離 raw／parse／quality shadow，且正式 DuckDB、legacy raw 與 stock master 前後 hash 相同。

正式 durable archive 位於 `C:\project\tw-sepa-screener\data\raw_v2\m2_2026-08-03`，E: 分離 volume 備份位於 `E:\tw-sepa-screener-backup\raw_v2\m2_2026-08-03`；兩份逐檔雜湊相同且 archive audit 均為 `passed`，另完成一次新目錄 restore drill。OS 權限未能證明 C:／E: 位於不同實體裝置，因此不把它宣稱為 off-device backup。M3 只獲准唯讀使用與建立 shadow／normalized dataset；尚未獲准覆寫正式 DuckDB、legacy raw、stock master、策略或交易設定。

M2 只能建立官方不可變原始資料層及其追溯驗收。M0/M1/M2 不授權：

- 修改既有正式或紙上策略；
- 合併 AlphaMaster PR #1；
- 連接券商下單；
- 使用 NT$10,000 進行真實交易；
- 將任何 AlphaMaster 因子宣稱為已驗證台股策略。

## M3 目前狀態（2026-08-16 更新）

M3.0 進場凍結與 M3.1 契約與來源映射皆已 `complete`；M3.2 起為 `blocked`，原因是缺輸入資料而非尚未動工。

G0 已於 2026-08-03 批准：固定基準期間為 2025-01-01 至 2026-08-03，TWSE 與 TPEx 分開逐日認證。只有 coverage certificate 明確標為 `supported` 的 market-date 受到承諾；未列、`partial`、`blocked` 或 `unknown` 一律拒絕使用。

2026-08-16 已建立符合 G0 粒度的 1,160 列 coverage ledger，結果為：

| State | TWSE | TPEx | 合計 |
|---|---:|---:|---:|
| `supported` | 0 | 0 | **0** |
| `not-session` | 17 | 0 | 17 |
| `partial` | 2 | 1 | 3 |
| `unknown` | 561 | 579 | 1,140 |

固定期間內耐久日價 session 只有 TWSE 2026-07-02、2026-07-31 與 TPEx 2026-07-31；2025 全年沒有任何官方歷史證據；TPEx 完全沒有交易日曆來源。96-session TWSE 修復 shadow 已耐久封存（primary 與 E: backup 逐檔雜湊一致、96/96 blob 重驗通過），但它僅含 TWSE 且只有 1 個 session 落在固定期間內。

因此 M3 exit **無法**在取得新的歷史官方資料前達成，尚缺 1,143 個 market-date。下一步需要 Owner 決定歷史抓取程式、TPEx 日曆來源、證券生命週期歷史來源，或以新的 G0 版本調整固定期間。詳見 [M3.1 完成證據](docs/evidence/m3-1-coverage-ledger-and-durable-archival-2026-08-16.md)。

所有 M3 產物仍必須落在獨立 shadow；缺資料保持 `unknown` 或 `blocked`，不得用今日狀態、事後修訂或 legacy 資料補成歷史真相。2026-08-04 以後不會因「到今天」而自動加入支援範圍。
