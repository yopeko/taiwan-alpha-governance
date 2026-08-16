# M3.1 Source-to-Table Map、Availability 與 Conflict Policy

## 0. 文件控制

| 欄位 | 值 |
|---|---|
| Contract ID | `tw-alpha-m3-source-map/1.0.0` |
| Availability policy | `tw-alpha-m3-availability/1.0.0` |
| Conflict policy | `tw-alpha-m3-conflict/1.0.0` |
| 狀態 | `approved-for-M3-shadow-build` |
| 建立日 | 2026-08-16 |
| 上游 | [PIT warehouse contract](pit-warehouse-contract.md)、[M2 來源清冊](../m2-source-inventory.md) |
| 涵蓋來源 | M2 durable archive 的 36 個 endpoint-level P0 sources |
| 不涵蓋 | 交易成本、零股成交、帳本、策略評分（屬 M4 以後） |

本文件完成 M3.1 工作包要求的三項政策。它定義「哪個來源餵哪張表」、「資料何時可用於決策」、「同一事實有多個來源時如何取捨」，但**不宣稱**這些表已有足夠歷史覆蓋。實際覆蓋狀態一律以 coverage certificate 為準。

---

## 1. Source-to-Table Map（v1.0.0）

### 1.1 對應規則

- 一個 source 可餵多張表；一張表可由多個 source 餵入。
- 每一列必須保存 `source_id`，不得由 URL 或檔名推測。
- `historical` 與 `latest` 端點永遠視為**不同 scope**，即使指向同一事實。
- 標記 `current-only` 的來源**只能**描述觀測當下，不得回填任何歷史日期。

### 1.2 交易日曆

| Source ID | Endpoint | 目標表 | Scope | 限制 |
|---|---|---|---|---|
| `TWSE-CALENDAR` | `holiday-schedule` | `trading_calendar_pit` | 年度公告 | **僅 2026**；27 列、17 個落在固定期間內的休市日。TPEx 無對應來源 |

**關鍵限制**：休市表是「例外清單」，不是完整 session table。日期不在清單中**不構成** `official-open` 證據。目前沒有任何來源可證明固定期間內任一日為開市日。

### 1.3 證券生命週期

| Source ID | Endpoint | 目標表 | Scope | 限制 |
|---|---|---|---|---|
| `TWSE-MASTER` | `company-master` | `security_events` | `latest-observed` | current-only；無歷史版本 |
| `TPEX-MASTER` | `company-master` | `security_events` | `latest-observed` | current-only；無歷史版本 |
| `TWSE-LISTING-START-HIST` | `new-listing-history` | `security_events` | 全量 | 790 筆中 377 筆上市日 `missing-at-source` |
| `TPEX-LISTING-START-HIST` | `new-listing-history-year` | `security_events` | 逐年 | 僅 2020–2026 共 168 筆 |
| `TWSE-DELISTING` | `delisted-companies` | `security_events` | 全量 | 245 筆 |
| `TPEX-DELISTING-HIST` | `delisted-companies` | `security_events` | 全量 | 579 筆、569 unique keys |

**身份規則**：`security_instance_id` 由 `market + symbol + listing_interval` 導出。已證實 2301、2432 同時出現於 delisted 與 current 資料，因此 `symbol + market` 不得作為永久身份。缺上市日者保留 `missing-at-source`，**不得**自動視為 eligible。

### 1.4 每日股價

| Source ID | Endpoint | 目標表 | Scope | 限制 |
|---|---|---|---|---|
| `TWSE-PRICE-HIST` | `daily-prices-historical` | `daily_prices_pit` | `session:<date>` | 固定期間內僅 2026-07-02、2026-07-31 |
| `TPEX-PRICE-HIST` | `daily-prices-historical` | `daily_prices_pit` | `session:<date>` | 固定期間內僅 2026-07-31 |
| `TWSE-PRICE-LATEST` | `daily-prices-latest` | `daily_prices_pit` | `latest-observed` | current-only；不得回填歷史 |
| `TPEX-PRICE-LATEST` | `daily-prices-latest` | `daily_prices_pit` | `latest-observed` | current-only；不得回填歷史 |
| `TWSE-INDEX` | `market-index-historical` | `market_reference_pit` | `session:<date>` | 僅 2026-07-31 |
| `TPEX-INDEX` | `market-index-latest-history` | `market_reference_pit` | 混合 | scope 與 TWSE 不對稱 |

另有 `m2_dailyprice96_2026-08-03` 耐久封存，含 96 個 TWSE session（2020-10-19 至 2026-07-02），其中僅 1 個落在固定期間內。

**OHLC 規則**：`ohlc_state` 必須明確區分 `complete`、`source-reported-no-regular-ohlc`、`activity-without-ohlc`。缺 OHLC **不補前值**，且有成交活動不等於可交易。

### 1.5 市場狀態

| Source ID | Endpoint | 目標表 | Scope |
|---|---|---|---|
| `TWSE-TRADING-SUSPENSION` | `trading-status-suspension` | `market_status_pit` | current-only |
| `TWSE-TRADING-NOTICE` | `trading-status-notice` | `market_status_pit` | current-only |
| `TWSE-TRADING-PUNISH` | `trading-status-punish` | `market_status_pit` | current-only |
| `TWSE-TRADING-ALTERED-TRADING` | `trading-status-altered-trading` | `market_status_pit` | current-only |
| `TPEX-TRADING-SUSPENSION-TODAY` | `trading-status-suspension-today` | `market_status_pit` | current-only |
| `TPEX-TRADING-SUSPENSION-HISTORY` | `trading-status-suspension-history` | `market_status_pit` | 歷史 |
| `TPEX-TRADING-DISPOSAL` | `trading-status-disposal` | `market_status_pit` | current-only |
| `TPEX-TRADING-WARNING` | `trading-status-warning` | `market_status_pit` | current-only |
| `TPEX-TRADING-ALTERED-TRADING` | `trading-status-altered-trading` | `market_status_pit` | current-only |

**absence 規則**：來源未列出某證券，有三種互不相同的意義——「查無事件」、「來源本身為 current-only」、「該日期無 coverage」。三者都**不得**折疊為 `tradable=true`。

### 1.6 公司行動

| Source ID | Endpoint | 目標表 | Scope | 限制 |
|---|---|---|---|---|
| `TWSE-ACTIONS-HIST` | `exright-historical` | `corporate_actions_pit` | `range:` | 唯一 released quarantine；僅 2026-07-31 |
| `TWSE-ACTIONS-CURRENT` | `exright-current` | `corporate_actions_pit` | current-only | — |
| `TPEX-ACTIONS-DAILY` | `exright-daily` | `corporate_actions_pit` | current-only | — |
| `TPEX-ACTIONS-PREPOST` | `exright-prepost` | `corporate_actions_pit` | current-only | — |
| `MOPS-TPEX-ACTIONS-LIST` | `tpex-exright-history-list` | `corporate_actions_pit` | 歷史 | 需與 detail 配對 |
| `MOPS-TPEX-ACTIONS-DETAIL` | `tpex-exright-history-detail` | `corporate_actions_pit` | 歷史 | — |

**調整規則**：不得由價格跳空反推正式 adjustment factor。缺 `announced_at` 者最早只能自 `first_observed_at` 起使用。

### 1.7 財報

| Source ID | Endpoint | 目標表 | 目前覆蓋 |
|---|---|---|---|
| `MOPS-REVENUE-HIST` | `monthly-revenue-historical` | `fundamentals_pit` | 主要 2026-06 |
| `TWSE-REVENUE-LATEST` / `TPEX-REVENUE-LATEST` | `monthly-revenue-latest` | `fundamentals_pit` | current-only |
| `MOPS-INCOME-HIST` | `quarterly-income-historical` | `fundamentals_pit` | 主要 2026Q1 |
| `TWSE-INCOME-LATEST` / `TPEX-INCOME-LATEST` | `quarterly-income-latest` | `fundamentals_pit` | current-only |
| `MOPS-BALANCE-HIST` | `balance-sheet-company-historical` | `fundamentals_pit` | 2 家樣本（2330、6488）2026Q1 |
| `MOPS-CASHFLOW-HIST` | `cashflow-company-historical` | `fundamentals_pit` | 2 家樣本（2330、6488）2026Q1 |

**修訂規則**：修訂追加新 record 並 `supersedes_record_id` 指向前版，**不得**覆寫舊值後沿用舊 `available_at`。

---

## 2. Availability 與 Cutoff Policy（v1.0.0）

### 2.1 基本不等式

任何 as-of 查詢必須同時滿足：

```text
decision_available_at <= decision_as_of
effective_from        <= as_of_session
```

任一條件不成立或時間未知，該筆資料不得進入 `known_information`，只能出現在 coverage 或 blocked reason。

### 2.2 逐資料族的 availability basis

| 資料族 | 預設 basis | 是否允許早於 `first_observed_at` |
|---|---|---|
| 交易日曆 | `publisher-exact`（公告日期明確時） | 允許，但僅限公告日期可證明者 |
| 證券生命週期 | `first-observed-only` | 否 |
| 每日股價 | `approved-conservative-bound` = session date 當日 `15:00 Asia/Taipei` | 是，限本政策定義的保守 bound |
| 市場狀態 | `first-observed-only` | 否 |
| 公司行動 | `publisher-exact`（有 `announced_at`）否則 `first-observed-only` | 僅前者 |
| 月營收 | `approved-conservative-bound` = 期後次月 10 日 `23:59 Asia/Taipei` | 是 |
| 季報 | `first-observed-only` | 否（法定期限差異大，暫不設 bound） |

**每日股價 bound 的理由**：官方收盤資料於交易日盤後發布，保守取 15:00 而非實際發布時刻，可確保不早於真實可得時間。此 bound 只適用於 `session:` scope 的 historical 端點，**不適用**於 `latest-observed`。

**月營收 bound 的理由**：台灣上市櫃公司月營收申報期限為次月 10 日。取當日 23:59 為最早可決策時間是保守做法。若實際觀測早於此 bound，仍以 bound 為準（較晚者勝）。

### 2.3 不允許的 availability 推定

- 不得因為「資料現在存在」就推定它在歷史某日已存在。
- 不得以 legacy DuckDB 的 `available_at` 作為 canonical basis；legacy 財報 overwrite 語意會把後期修訂值配到最早日期。
- 季報不設保守 bound，因為不同公司、不同類型的法定申報期限差異過大，設定單一 bound 會系統性低估可得時間。
- 任何新的 bound 必須經 Validation Owner 批准，且必須可重現、含 revision 防護。

### 2.4 Cutoff 與 revision 互動

修訂版只有在 `revision_observed_at <= decision_as_of` 時才可見。較早 cutoff 的查詢必須看到當時版本，即使後來已被 supersede。實作上以 `supersedes_record_id` 鏈向前追溯，**不得**刪除或改寫舊 record。

---

## 3. Canonical Conflict Policy（v1.0.0）

### 3.1 衝突類型與處置

| 衝突類型 | 處置 | 禁止做法 |
|---|---|---|
| `historical` 與 `latest` scope 對同一 session 給出不同值 | 兩筆並存，canonical 選 `historical`；差異寫入 `data_quality_events` | last-write-wins |
| 同一 session 兩次觀測值不同 | 保留兩筆，較早者為 canonical，較晚者標為 revision | 靜默覆寫 |
| TWSE 與 TPEx 同 symbol | 以 `security_instance_id` 分離，永不合併 | 以 symbol 去重 |
| 同 symbol 不同生命週期（下市後重用） | 不同 `security_instance_id` | 視為同一證券 |
| 官方列出但無 OHLC | `ohlc_state = source-reported-no-regular-ohlc` | 補前值或視為停牌 |
| 有成交活動但無 OHLC | `ohlc_state = activity-without-ohlc` | 推定可交易 |
| MOPS list 與 detail 不一致 | 保留兩者，標 `partial`，不選 canonical | 任選其一 |
| 官方來源與 legacy DuckDB 不一致 | 官方勝；legacy 差異寫入 `data_quality_events` | 以 legacy 補官方缺口 |

### 3.2 優先順序

當同一事實有多個合格來源時，依序：

1. `historical` scope 的官方 endpoint；
2. `latest` scope 的官方 endpoint（**僅限**其 `logical_period` 明確涵蓋該日期）；
3. `official-no-data` 明示證據；
4. 其他一律 `unknown`。

`legacy-normalized-snapshot` **永遠不進入** canonical lane，只進比較／coverage lane。

### 3.3 Fail-closed 條件

以下情況必須 fail closed，不得以預設值繞過：

- 缺任一必要 lineage 欄位；
- 未知 schema major version；
- 重複 `record_id`；
- `row_hash` 不符；
- `decision_available_at` 未知；
- `effective_quality_state` 為 `quarantined` 且無有效 release；
- coverage certificate 未列出該 market-date。

---

## 4. 本政策未解決的事項

以下為已知且**未**由本文件解決的缺口，必須在 M3 後續工作包或新的 Owner 決定處理：

1. 固定期間內沒有任何來源可證明 `official-open`；需要新的官方日曆歷史抓取程式。
2. TPEx 完全沒有交易日曆來源。
3. 證券生命週期與市場狀態沒有歷史版本，只有 current snapshot。
4. 季報 availability 沒有保守 bound，只能用 `first-observed-only`。
5. 固定期間內耐久日價覆蓋僅 3 個 market-date；其餘 1,157 個無官方 session 級觀測。

這些缺口的量化結果見 [M3.1 coverage ledger 與耐久封存證據](../evidence/m3-1-coverage-ledger-and-durable-archival-2026-08-16.md)。
