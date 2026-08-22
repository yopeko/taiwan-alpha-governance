# Taiwan Alpha Governance Project

本倉庫保存台股 AlphaMaster 適配工作的治理、架構與跨專案契約，不保存或複製 AlphaMaster 原始碼，也不取代既有 `tw-sepa-screener`。

## 目前狀態

| 里程碑 | 狀態 | 完成日 | 主要產物 |
|---|---|---|---|
| M0 證據與市場契約 | complete | 2026-08-02 | [M0 專案契約](docs/m0-project-contract.md) |
| M1 架構與重用稽核 | complete | 2026-08-02 | [M1 架構與重用稽核](docs/m1-architecture-reuse-audit.md) |
| M2 官方不可變原始資料 | complete | 2026-08-03 | 36 sources、56 live observations、55 initial accepted + 1 released quarantine、0 unresolved；正式封存與 E: 備份均通過稽核。[M2 closure evidence](docs/evidence/m2-owner-approvals-release-and-durable-audit-2026-08-03.md) |
| M3 Point-in-time warehouse | complete（附七項已記錄例外）| 2026-08-17 | G0 §5 條件 1、2、3、5 通過，條件 4 部分通過。Validation Owner 已簽核。[Exit review](docs/evidence/m3-8-exit-review-2026-08-17.md)、[M3 計畫](docs/m3-point-in-time-warehouse-plan.md) |
| M4 台股規則與成本 | in progress | - | 參考實作與 50 項測試完成；檔位由 406,445 筆官方收盤價實測推導。剩除權息日漲跌停公式、減資、新上市前五日與上游化。[M4 契約](docs/contracts/m4-market-rules-contract.md) |

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
- [M3 Owner 決定 D1–D5 與抓取可行性驗證](docs/evidence/m3-owner-decisions-and-capture-feasibility-2026-08-16.md)
- [TEJ PRO 匯入規格](docs/contracts/tej-import-spec.md)
- [M3.1b 完成證據：固定期間全量抓取與 ledger v2](docs/evidence/m3-1b-window-capture-2026-08-16.md)
- [M3.1c TEJ licensed-vendor lane 匯入](docs/evidence/m3-1c-tej-import-2026-08-16.md)
- [M3 Owner 決定 D6–D8 與市場狀態抓取](docs/evidence/m3-owner-decisions-d6-d8-2026-08-16.md)
- [M3.1e 公司行動抓取與 coverage ledger v3](docs/evidence/m3-1e-corporate-actions-and-ledger-v3-2026-08-16.md)
- [M3 G0 修訂 v2.0.0 與決定 D9–D10](docs/evidence/m3-g0-amendment-d9-d10-2026-08-16.md)
- [M3.1f TPEx 公司行動與 coverage ledger v4](docs/evidence/m3-1f-tpex-actions-and-ledger-v4-2026-08-16.md)
- [M3.2 Append-only staging](docs/evidence/m3-2-staging-2026-08-16.md)
- [M3.8 Exit review 與 Validation Owner 簽核](docs/evidence/m3-8-exit-review-2026-08-17.md)
- [M3.9 公司行動取得公告日期](docs/evidence/m3-9-action-availability-2026-08-18.md)
- [M3.10 減資公告日與停止買賣日](docs/evidence/m3-10-reduction-announcement-linkage-2026-08-19.md)
- [M3 Owner 決定 D11：減資 FILE_DATE 的 availability basis](docs/evidence/m3-owner-decision-d11-2026-08-19.md)
- [M3.11 TPEx 公司行動晉升 canonical 表](docs/evidence/m3-11-tpex-actions-promotion-2026-08-19.md)
- [M3.12 變更股票面額取得官方來源](docs/evidence/m3-12-par-value-change-2026-08-19.md)
- [M3.13 上櫃減資與變更股票面額](docs/evidence/m3-13-tpex-reduction-par-value-2026-08-19.md)
- [M3.14 公司行動接入 as-of 重建](docs/evidence/m3-14-actions-in-asof-2026-08-19.md)
- [M3.15 合併兩份 corporate_actions_pit](docs/evidence/m3-15-single-action-table-2026-08-19.md)
- [M4 台股規則與成本契約](docs/contracts/m4-market-rules-contract.md)
- [M4.1 除權息日漲跌停由官方法規解決](docs/evidence/m4-1-ex-rights-limits-2026-08-19.md)
- [M4.2 上游化至 Taiwan Core 與指紋異動](docs/evidence/m4-2-upstream-to-taiwan-core-2026-08-19.md)
- [M5 現金／股票帳本](docs/evidence/m5-cash-share-ledger-2026-08-19.md)
- [M6 Phase 0：既有 SEPA 回測的誠實成本重算](docs/evidence/m6-phase0-cost-recompute-2026-08-20.md)
- [M6 Phase 2：凍結研究資料集](docs/evidence/m6-phase2-research-dataset-2026-08-20.md)
- [M6 Phase 3：帳本驅動的回測](docs/evidence/m6-phase3-ledger-backtest-2026-08-20.md)
- [稽核：FinMind 免費層日線交叉驗證](docs/evidence/audit-finmind-crossvalidation-2026-08-21.md)
- [M3 Owner 決定 D9：全額交割的 availability basis](docs/evidence/m3-owner-decision-d9-2026-08-22.md)

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

## M3 完成狀態（2026-08-17）

M3.0 至 M3.8 全部 `complete`，Validation Owner 已於 2026-08-17 簽核。完整核對見 [Exit review](docs/evidence/m3-8-exit-review-2026-08-17.md)。

**Coverage ledger v4**（1,160 個 market-date）：

| State | 嚴格（僅官方）| 依 G0 v2.0.0 D9（含授權廠商）|
|---|---:|---:|
| `supported` | 0 | **764** |
| `not-session` | 396 | 396 |
| `partial` | 764 | **0** |
| `unknown` | 0 | **0** |

**G0 §5 退出條件**：條件 1、2、3、5 全部通過；**條件 4 部分通過**——生命週期、價格、市場狀態、財報四族符合 PIT 規則，公司行動不符。

**M3.7 驗證**：五項全 `passed`。staging 與三組 canonical 表重建逐檔一致；restore drill 163 檔相同；受保護 stores 未變動；legacy 逐日列數**零差異**（2025-01-02、2025-10-17、2026-08-03 各 1,878／1,920／1,982 完全相符）。

**M3.6 as-of 介面**：18 項 anti-lookahead 測試通過，含 knowability 述詞、限制單調性、fail-closed 與決定性。

### 七項已記錄例外

| # | 例外 |
|---|---|
| 1 | ~~TWT49U 無公告日期~~ **2026-08-18 大幅解除**：2,279/2,388（95.4%）取得公告日，as-of 可見度由 0 升至 2,279；餘 109 筆 TEJ 未涵蓋 |
| 2 | TPEx 公司行動尚未晉升 canonical 表 |
| 3 | TEJ 去重鍵為 `(market, symbol)`，代號重用被合併 |
| 4 | 停牌依 D8 價格缺漏推定，非官方證據 |
| 5 | 34 個來源無 quality policy，停在 `gated-parse-only` |
| 6 | 34 檔證券因來源缺市場別被拒 |
| 7 | 2025 年官方行事曆已永久不可得，改依 TEJ |

全部有測試盯著；補上來源時測試會失敗並提醒更新。

### M3 完成不代表

資料可用於正式回測（M4 交易規則、M5 帳本未完成）、production cutover 已批准（仍需 G4）、或 2026-08-04 以後的日期受到承諾。所有 M3 產物仍落在獨立 shadow。
