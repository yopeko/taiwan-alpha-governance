# M3.1 完成證據：耐久封存、Coverage Ledger 與 Concurrent-change 記錄（2026-08-16）

## 結論

M3.1 工作包 `complete`。本輪完成三件事：96-session 日價 shadow 耐久封存、M3.1 三項政策定案、固定期間 1,160 列 coverage ledger 建立。

**同時得到一個決定性的負面結果**：固定期間內達到 `supported` 的 market-date 數量為 **0**。M3 exit gate 在取得新的歷史官方資料前**無法**達成。這不是缺陷，而是 fail-closed 設計正確運作的結果——系統拒絕把「沒有證據」當成「可以重建」。

本輪所有操作為新增式。沒有修改 `tw_sepa.duckdb`、legacy raw、`stock_master.csv`、M2 primary／backup archive、策略或交易設定。

---

## 1. Concurrent-change 記錄（非 M3 造成）

[M3 entry baseline](m3-entry-baseline-2026-08-03.md) 記錄的受保護指紋在 2026-08-16 重驗時已改變。歸因如下。

| 對象 | 2026-08-03 baseline | 2026-08-16 觀測 |
|---|---|---|
| `tw_sepa.duckdb` | 426,258,432 bytes / `b35ee8e6…` | 438,841,344 bytes / `74c8a040de34ddcf9113437865347d69031ae8169ac2677036b5eacc34d8f4b3` |
| legacy raw | 4,991 檔 / 188,514,234 bytes / `6c69763e…` | 4,995 檔 / 188,703,875 bytes / `a9075b73f1913896c67ee332841c382daf2f901b5717097155aed69711690afe` |
| `stock_master.csv` | 174,314 bytes / `f179c40e…` | 174,497 bytes / `39bea140a2c3ab7bf1288cdad2b7b68796a10cf0b4cf085367f54ff886e3f98f` |
| source-state（180 檔） | `d4ef6c0f…` | `d4ef6c0f50f4c480d39c9f1e7baa3fc10eac8b0fe27b584e1c35c7c80e3b5ee9`（**未變**） |
| HEAD | `fb87f62f…` | `fb87f62f8c2c68e2b85982cd102a35fd935bc0a4`（**未變**） |

**歸因證據**：`data/processed/daily_workflow_status.json` 顯示既有 Windows 排程 daily workflow `run_id=20260815T164014`、`status=success`、執行時間 2026-08-15 16:40:14 至 16:43:37 (+08:00)。新增的 4 個 legacy raw 檔為 `market_daily_20260814`、`market_indices_20260814`、`mops_revenue_twse_202607`、`mops_revenue_tpex_202607`。原始碼指紋與 HEAD 皆未變，證明變動來自資料排程而非程式或本輪工作。

依 [PIT 契約](../contracts/pit-warehouse-contract.md) §9，保留此 concurrent-change evidence，**不回復、不覆寫**。以上 2026-08-16 觀測值成為後續 M3 build 的新對照基線。

**M2 不可變層完全未受影響**：primary 與 E: backup 的 tree SHA-256 皆仍為 `31f31094f772c3c9a4f78e6234497a74fdf40e28560e6f88dd9415d43e1934a0`，archive audit 均 `passed`，55 accepted + 1 released、0 unresolved、0 blocking issues。

本輪工作前後再次比對，三項受保護 stores 的指紋完全相同，證明本輪未寫入任何受保護位置。

---

## 2. 96-session 日價 shadow 耐久封存

原暫存位置 `C:\tmp\tw-alpha-m2-shadow-20260803-02` 已依 M2 契約複製到耐久位置。

| Copy | 路徑 | Files | Bytes | Tree SHA-256 |
|---|---|---:|---:|---|
| 暫存來源 | `C:\tmp\tw-alpha-m2-shadow-20260803-02` | 673 | 26,537,610 | `e1d103ec…32683c3` |
| Primary | `C:\project\tw-sepa-screener\data\raw_v2\m2_dailyprice96_2026-08-03` | 673 | 26,537,610 | 相同 |
| Backup | `E:\tw-sepa-screener-backup\raw_v2\m2_dailyprice96_2026-08-03` | 673 | 26,537,610 | 相同 |

三份逐檔 SHA-256 完全一致，且 tree hash 與 [M3 entry baseline](m3-entry-baseline-2026-08-03.md) 記錄的 `e1d103ec147462705cf8ee03c032f622bc75f328cc6e0a28d10a2490e32683c3` 相符。

**內容重驗**（三份各自獨立執行）：

```text
raw_observations   = 96
blobs_verified     = 96   （逐檔重算 SHA-256，與 blob_id 及 payload_sha256 三方相符）
blob_hash_mismatch = 0
missing_blobs      = 0
parse_manifests    = 96
quality_event_files= 192
unique_sessions    = 96   （session:2020-10-19 .. session:2026-07-02）
shadow run state   = passed，96/96 accepted，0 failed
```

Archival record 寫入兩份耐久副本：`archival_record_2026-08-16.json`，SHA-256 `a71c27ff2dc8ac722181b6864c9c5994a126ec42e1d5ee4f317bffb2b45a9f84`，`record_id = tw-alpha-m3-dailyprice96-archival-20260816-01`，retention 無期限、`automatic_deletion=disabled`。

不可變的 `run_manifest.json` 仍記載 `output_policy = temporary-shadow-only-no-production-writer`，**未被改寫**；耐久性由上述獨立的 append-only record 主張，與 M2 處理 release event 的方式一致。

**範圍限制（必須隨附引用）**：此封存僅含 TWSE，不含 TPEx；96 個 session 不連續；固定期間內只有 1 個 session（2026-07-02）。它**不能**單獨滿足 G0-A。

---

## 3. 固定期間 Coverage Ledger

依 [G0 Owner 決定](m3-g0-owner-decision-2026-08-03.md) 建立 2025-01-01 至 2026-08-03、TWSE 與 TPEx 分列的逐日 ledger。

| 欄位 | 值 |
|---|---|
| Certificate ID | `tw-alpha-m3-coverage-ledger-20260816-01` |
| 狀態 | `gap-ledger-only-not-a-supported-date-certificate` |
| Calendar dates | 580 |
| 列數 | **1,160**（符合 G0 最低粒度要求）|
| Ledger 路徑 | `C:\project\tw-sepa-screener\data\raw_v2\m3_coverage_ledger_2026-08-16\coverage_ledger.csv` |
| Ledger SHA-256 | `d72899d424dfe577a0ca3d00bb76cf2ffd908ec2523fa7def64d5f52e6f1f9f1` |
| Summary SHA-256 | `56e8596e54e3e9d4f20f3a478af4113278e420745e22040a90d30114b7b8ec89` |
| 本倉庫副本 | [m3-coverage-ledger-2026-08-16.csv](m3-coverage-ledger-2026-08-16.csv)、[m3-coverage-summary-2026-08-16.json](m3-coverage-summary-2026-08-16.json)（逐檔 SHA-256 與上列相同）|
| 重現腳本 | [`scripts/m3/build_coverage_ledger.py`](../../scripts/m3/build_coverage_ledger.py) |

### 3.1 Aggregate reconstruction_state 分布

| State | TWSE | TPEx | 合計 | 佔比 |
|---|---:|---:|---:|---:|
| `supported` | 0 | 0 | **0** | 0.00% |
| `not-session` | 17 | 0 | 17 | 1.47% |
| `partial` | 2 | 1 | 3 | 0.26% |
| `unknown` | 561 | 579 | 1,140 | 98.28% |

### 3.2 固定期間內實際存在的證據

**耐久日價 session**：

- TWSE：2026-07-02、2026-07-31（共 2 個）
- TPEx：2026-07-31（共 1 個）

**官方休市證據**：TWSE 17 日（2026-01-01、02-12 至 02-20 之春節連假、02-27、02-28、04-03 至 04-06、05-01、06-19）。TPEx **0 日**——沒有任何 TPEx 日曆來源。

### 3.3 為何 `supported` 為 0

即使 2026-07-31 兩市場都有日價，仍只能是 `partial`，因為：

1. **無開市證據**：休市表是例外清單。日期不在清單中不構成 `official-open` 證據，而契約明文禁止「週一至週五減假日」的推論。
2. **證券生命週期為 current-only**：只有今日 master snapshot，無歷史版本，無法回答「該日有哪些證券在市」。
3. **市場狀態為 current-only**：無法回答該日哪些證券停牌、處置或變更交易。
4. **財報覆蓋僅 2026-06 月營收與 2026Q1**，且資產負債／現金流只有 2330 與 6488 兩家樣本。

2025 年全年（365 日 × 2 市場 = 730 列）**沒有任何一項**官方歷史證據，全部為 `unknown`。

---

## 4. M3.1 政策交付

[M3.1 Source-to-Table Map、Availability 與 Conflict Policy](../contracts/m3-source-to-table-map.md) 已定案，涵蓋：

- **Source-to-table map v1.0.0**：36 個 P0 sources 逐一對應 7 張 canonical 表，標註 scope 與限制；
- **Availability／cutoff policy v1.0.0**：逐資料族的 `availability_basis`，含兩項經定義的保守 bound（日價 session 日 15:00、月營收次月 10 日 23:59），並說明季報為何**不**設 bound；
- **Conflict policy v1.0.0**：8 類衝突處置、4 級優先順序、7 項 fail-closed 條件。

---

## 5. 本輪未做也未獲授權的事

- 未覆寫正式 DuckDB、legacy raw、stock master（前後指紋相同）；
- 未建立 M3.2 append-only staging（缺歷史資料，建了也只會是空殼）；
- 未執行任何官方來源的新歷史抓取；
- 未修改策略、AlphaMaster、紙上帳本或券商設定；
- 未將 M3 標為 `complete`。

---

## 6. M3 exit 的實際阻擋項

依 G0-A，M3 complete 需要固定期間內**所有**官方開市／特殊 session 為 `supported`、所有休市日有 `not-session`。目前差距為 1,143 個 market-date。要縮小差距，必須先取得 Owner 對下列事項的決定：

1. **歷史官方資料抓取程式**：需逐日抓取 2025-01-01 起的 TWSE／TPEx 日價與相關端點，估計 580 日 × 2 市場的 session 級請求量，須先確認來源的歷史端點是否提供該期間、以及可接受的抓取速率與重試政策。
2. **TPEx 交易日曆來源**：目前完全沒有；需要確認官方是否提供，若無則 TPEx 永遠無法達到 `not-session` 判定。
3. **證券生命週期歷史版本**：current-only master 無法支撐任何歷史日期；需決定是接受 `missing-at-source` 比例，或另尋來源。
4. **是否縮小 G0 期間**：若 2025 年資料不可得，Owner 可考慮把固定期間改為可實際達成的較短區間，但這需要新的 G0 版本與批准，不得由執行方自行縮小。

在上述決定之前，M3.2 起的工作包無法產生有意義的輸出。
