# M3 Entry Baseline — 2026-08-03

## 結論

M3 已正式進入 `in_progress`，M3.0 進場凍結已完成，M3.1 契約工作已開始。這不是 M3 完成聲明，也不授權 production cutover。

本次檢查均為唯讀。沒有修改 `tw_sepa.duckdb`、legacy raw、`stock_master.csv`、M2 durable archive、策略或交易設定。

## 1. 進場分類與權限

- 變更類型：`data/governance`。
- 目前里程碑：M3 Point-in-time warehouse。
- 策略軌道：不適用；沒有建立、升級或修改策略。
- 允許輸出：新的 shadow warehouse 與其契約、manifest、coverage、驗證證據。
- 禁止輸出：正式資料覆寫、AlphaMaster 整合、paper/canary/formal 策略、券商操作與真實資金交易。

## 2. 受保護基線

檢查時間：`2026-08-03T13:21:48.4393230Z`。

| 對象 | 大小／數量 | SHA-256 或 manifest SHA-256 |
|---|---:|---|
| `C:\project\tw-sepa-screener\data\tw_sepa.duckdb` | 426,258,432 bytes | `b35ee8e6e76e6e6e12a14a241d03dcf8d8252a4d9756c56972ef28d05fcd26f1` |
| `C:\project\tw-sepa-screener\data\raw` | 4,991 files；188,514,234 bytes | `6c69763e244bf4bf6b096ccd052ebafc4b05dfccc23441dc1999506f6a7d2e03` |
| `C:\project\tw-sepa-screener\data\stock_master.csv` | 174,314 bytes | `f179c40e945bfc1e80a2f46922f26605d92b68043ca07841aed89ac7fa8e166c` |
| source-state：`src/`、`tests/`、`pyproject.toml` | 180 tracked + untracked files | `d4ef6c0f50f4c480d39c9f1e7baa3fc10eac8b0fe27b584e1c35c7c80e3b5ee9` |

這些指紋是 M3 shadow build 前後對照基線。若之後有任一值改變，build 必須停止並記錄 concurrent-change evidence，不得把差異算成 M3 自己的輸出。

預定的獨立 M3 shadow root 為 `C:\tmp\tw-alpha-m3-shadow-20260803-01`；進場時確認不存在，因此沒有把舊輸出誤認為本次產物。

## 3. M2 durable archive 驗證

| 項目 | Primary archive | 分離備份 |
|---|---|---|
| 路徑 | `C:\project\tw-sepa-screener\data\raw_v2\m2_2026-08-03` | `E:\tw-sepa-screener-backup\raw_v2\m2_2026-08-03` |
| 檔案 | 396 | 396 |
| bytes | 15,293,847 | 15,293,847 |
| tree SHA-256 | `31f31094f772c3c9a4f78e6234497a74fdf40e28560e6f88dd9415d43e1934a0` | 相同 |
| archive audit | `passed` | `passed` |

Primary archive 共有 56 組 raw／parse／quality observations：55 組 initial `accepted`，1 組保留 initial `quarantined` 並有可驗證的 `released` event；unresolved 與 archive issues 都是 0。

## 4. 96-session 日價修復 shadow

| 欄位 | 值 |
|---|---|
| 路徑 | `C:\tmp\tw-alpha-m2-shadow-20260803-02` |
| 狀態 | 暫存 shadow；不是 durable main archive |
| audit | 96 raw／parse／quality，96 `accepted`，0 blockers |
| 日期範圍 | 2020-10-19 至 2026-07-02，96 個不連續 TWSE sessions |
| 價格列 | 92,967 |
| complete OHLC | 92,663 |
| source-reported no regular OHLC | 304 |
| 有正活動但無 OHLC | 185；保留缺值，不補價、不推定可交易 |
| tree | 673 files；26,537,610 bytes |
| tree SHA-256 | `e1d103ec147462705cf8ee03c032f622bc75f328cc6e0a28d10a2490e32683c3` |
| run ID | `3ca7b2d4d3b7e8a2711466bb584f6fbe54f6ccedfea34c5677015552435e81d7` |
| target hash | `5ecf26e039b4d7fb9f6a2ff6bcc6aa2563d0c058f44f88102fce77c83eb7ab10` |

這批資料可作 M3 staging 候選，但必須先完成耐久封存與再次 audit。不得因 96/96 通過就宣稱已覆蓋 2020–2026 的所有交易日，也不得宣稱已涵蓋 TPEx。

## 5. Legacy DuckDB 唯讀盤點

| 表 | 列／key | 期間或重要限制 |
|---|---:|---|
| `stock_master` | 1,977 | current snapshot；上市日 1962-02-09 至 2026-07-28；無 delisted/version history |
| `daily_prices` | 2,551,035；2,067 instruments | 2020-08-03 至 2026-08-03；24,286 列缺 OHLC |
| `monthly_revenue` | 134,701 | period 2020-07-31 至 2026-06-30；含大量非 official legacy rows |
| `quarterly_financials` | 45,070 | period 2020-06-30 至 2026-03-31；現有 overwrite 語意不具 revision-safe PIT 保證 |
| `corporate_actions` | 2,858 | action date 2022-03-16 至 2026-08-17；同 key 可覆寫 |
| `market_session_status` | 53 | 不是正式交易日曆，亦非完整歷史市場狀態 |

Legacy DuckDB 有較長期間，可用於差異檢查及標示為 `legacy-imported` 的研究 lane，但沒有完整 raw-v2 lineage，不能作 `verified-snapshot` canonical evidence。尤其財報更新可能把後來修訂值配到最早 available date，直接沿用會造成未來資訊洩漏。

## 6. 已確認的 coverage 缺口

- Durable M2 每日股價主體只有 2026-07-31；96-session repair 是 TWSE、非連續且尚未耐久封存。
- TWSE 與 TPEx 日價 historical/latest endpoint 在活動欄範圍上有差異；不可 last-write-wins。
- Current master 是 TWSE 1,087、TPEx 890，沒有可靠的完整 security type 與歷史版本。
- TWSE listing events 790 筆，其中 377 筆 listing date 為 `missing-at-source`；TPEx listing history 目前只涵蓋 2020–2026 的 168 筆。
- TWSE delisting 245 筆；TPEx delisting 579 筆、569 個 unique keys。2301 與 2432 同時出現在 delisted 與 current 資料，證明不能只用 `symbol + market` 當永久身份。
- 八個出現在價格、卻不在 company master 的 TWSE symbols 是 ETF；M0 只含普通股，預設不得混入 universe。
- Calendar 目前只有 2026 的 24 個休市例外與 3 個特殊日期，不是完整逐日 session table。
- 市場狀態多數為 current／2026；來源沒列出不能解讀為正常交易。
- 部分公司行動缺 `announced_at`；在批准 policy 前，只能從 `first_observed_at` 起使用。
- MOPS 月營收主要只有 2026-06，損益表主要只有 2026Q1；資產負債與現金流目前只是少數公司樣本，且部分沒有精確 `available_at`。

## 7. 進場判定

| 判定 | 結果 |
|---|---|
| M2 前置 gate | 通過 |
| M3 shadow 設計／唯讀 staging | 已批准 |
| M3.0 entry freeze | `complete` |
| M3.1 PIT contract | `in_progress` |
| Production cutover | 未批准 |
| M3 exit | 未通過 |
| 下一個 Owner gate | G0：選擇固定全量期間，或版本化 supported-date exit gate |

進場採取 fail-closed：資料缺口不會被靜默填補，current snapshot 不會被回推成歷史事實，legacy 資料不會被冒充官方資料，未來才觀測到的資訊也不得出現在較早 cutoff。

