# M3.1 Source-to-Table Map、Availability 與 Conflict Policy

## 0. 文件控制

| 欄位 | 值 |
|---|---|
| Contract ID | `tw-alpha-m3-source-map/1.2.0` |
| Availability policy | `tw-alpha-m3-availability/1.2.0` |
| Conflict policy | `tw-alpha-m3-conflict/1.0.0` |
| Licensed-vendor policy | `tw-alpha-m3-licensed-vendor/1.0.0` |
| 狀態 | `approved-for-M3-shadow-build` |
| 建立日 | 2026-08-16 |
| 最後更新 | 2026-08-22（availability policy v1.2.0，納入 Owner 決定 D9：全額交割的保守 bound）|
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
| `TWSE-CALENDAR` | `holiday-schedule` | `trading_calendar_pit` | 當年度 | **僅 2026**；27 列、17 個落在固定期間內的休市日 |
| `TEJ-CALENDAR` | TEJ PRO 交易日清單 | `trading_calendar_pit` | 歷史全量 | **2025 年唯一來源**；`licensed-vendor-snapshot` |

**關鍵限制一**：休市表是「例外清單」，不是完整 session table。日期不在清單中**不構成** `official-open` 證據。

**關鍵限制二（2026-08-16 發現）**：`holidaySchedule` 端點**沒有年度參數，只回傳當年度**。本日查詢結果為民國 115 年（2026）27 列。**2025 年的官方行事曆已無法取得**，因為當時未擷取。此為資料源限制，非工具限制。

### 1.2.1 行事曆政策（`owner-approved-policy`）

Owner 於 2026-08-16 批准（[決定文件](../evidence/m3-owner-decisions-and-capture-feasibility-2026-08-16.md) D2）：

> **TPEx 與 TWSE 共用同一份證券市場行事曆。**

此推定標記為 `owner-approved-policy`，**不是** `publisher-exact`。採用共用行事曆而非國家行事曆的理由：

- **補班日**：政府為連假調移訂定的週六上班日，證券市場不開盤；
- **颱風假與臨時停市**：不會出現在年初公告中；歷史上亦有補行交易日。

因此**禁止**以「週一至週五減國定假日」產生交易日曆。

**年度來源分工**：

| 年度 | 行事曆來源 | Evidence state |
|---|---|---|
| 2025 | TEJ PRO 交易日清單 | `licensed-vendor-snapshot` |
| 2026 | 官方 `TWSE-CALENDAR` 已擷取 | `verified-snapshot` |

**交叉驗證**：官方日價檔存在與否作為佐證。TWSE 對非交易日回傳「很抱歉，沒有符合條件的資料!」，TPEx 回傳 `stat=ok` 但零列——兩者行為不同，都必須保存為 evidence，**不得**當成抓取失敗而重試掩蓋。零列**不是**休市的證明，只是佐證。

**衍生行動**：必須建立年度行事曆的例行擷取，避免 2027 年重蹈 2025 年覆轍。

### 1.3 證券生命週期

| Source ID | Endpoint | 目標表 | Scope | 限制 |
|---|---|---|---|---|
| `TWSE-MASTER` | `company-master` | `security_events` | `latest-observed` | current-only；無歷史版本 |
| `TPEX-MASTER` | `company-master` | `security_events` | `latest-observed` | current-only；無歷史版本 |
| `TWSE-LISTING-START-HIST` | `new-listing-history` | `security_events` | 全量 | 790 筆中 377 筆上市日 `missing-at-source` |
| `TPEX-LISTING-START-HIST` | `new-listing-history-year` | `security_events` | 逐年 | 僅 2020–2026 共 168 筆 |
| `TWSE-DELISTING` | `delisted-companies` | `security_events` | 全量 | 245 筆 |
| `TPEX-DELISTING-HIST` | `delisted-companies` | `security_events` | 全量 | 579 筆、569 unique keys |

| `TEJ-SECURITY-HIST` | TEJ PRO 上市下市歷史 | `security_events` | 歷史全量 | 補 377 筆 `missing-at-source`；`licensed-vendor-snapshot` |

**身份規則**：`security_instance_id` 由 `market + symbol + listing_interval` 導出。已證實 2301、2432 同時出現於 delisted 與 current 資料，因此 `symbol + market` 不得作為永久身份。

**缺上市日政策**（Owner 2026-08-16 決定 D3）：Owner 批准接受 TWSE 377 筆上市日 `missing-at-source`。但**接受缺漏不等於視為可交易**——這類證券在 as-of 查詢中維持 `membership_state=unknown`，不得自動 eligible。若 TEJ 能補上該日期，以 TEJ 值填入並標記 `licensed-vendor-snapshot`，且必須保留原始 `missing-at-source` 狀態供追溯。

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

### 1.8 TEJ PRO（Licensed-vendor lane，policy v1.0.0）

Owner 於 2026-08-16 確認 TEJ PRO 授權**允許本地快照長期保留**，且涵蓋歷史財報申報日與上市下市歷史兩個模組（決定 D5）。

| TEJ 用途 | 補的缺口 | 目標表 |
|---|---|---|
| 交易日清單 | 2025 官方行事曆已無法取得 | `trading_calendar_pit` |
| 上市／下市歷史日期 | TWSE 377 筆 `missing-at-source` | `security_events` |
| 財報申報日 | 多數財報缺精確 `publisher_released_at` | `fundamentals_pit` |

#### 不可違反的規則

1. **TEJ 永不進入 canonical lane。** 所有 TEJ 衍生列的 `evidence_state` 固定為 `licensed-vendor-snapshot`。官方來源存在時，官方一律優先。
2. **只採用帶有明確日期欄位的 TEJ 資料。** TEJ 是會被修訂的現值資料庫；今日查詢 2025 年得到的是「今日所知的 2025 年」，不是「2025 年當時所知」。沒有申報日／發布日欄位的資料**不得**用於推導 `decision_available_at`。
3. **每次抓取必須保存快照與抓取時間**，並納入 `dataset_id` 的 fingerprint。不得今日抓取後即當成歷史事實。
4. **價格不使用 TEJ。** 官方端點已驗證可供應 2025-2026 全市場逐檔日價；且 M0 契約要求正式驗證使用原始官方價，調整價須可重建。
5. **授權邊界**：本 lane 僅供本專案內部研究與驗證。散布、對外提供服務或商業部署前必須重新確認 TEJ 授權條款。

#### Availability basis

TEJ 資料的 `availability_basis` 只允許兩種：

- `publisher-exact`：TEJ 欄位本身即為官方申報日／發布日；
- `unknown-blocked`：無日期欄位，不得用於 as-of 決策。

**不允許**對 TEJ 資料使用 `first-observed-only`，因為那會把「我們今天抓到」誤記為「當時可得」，正是本專案要防止的偷看未來。

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

v1.0.0 把「市場狀態」與「公司行動」各視為單一資料族。實際建置後兩者都不成立：
同一張表裡的事件來自公告結構完全不同的端點，有的逐筆附公告日期，有的一個都沒有。
一列共用的預設值只能取最弱者，會把有公告日期的事件也一併封鎖。因此改為逐來源列出。

| 資料族／來源 | 預設 basis | 是否允許早於 `first_observed_at` |
|---|---|---|
| 交易日曆 | `publisher-exact`（公告日期明確時） | 允許，但僅限公告日期可證明者 |
| 證券生命週期 | `first-observed-only` | 否 |
| 每日股價 | `approved-conservative-bound` = session date 當日 `15:00 Asia/Taipei` | 是，限本政策定義的保守 bound |
| **市場狀態**：處置／注意（TWSE punish、notice；TPEx disposal、attention）| `publisher-exact` | **是**，來源逐筆附 `公告日期` 欄位 |
| **市場狀態**：減資停牌（TWTAUU + TWTAVUDetail）| `publisher-exact`，取 `FILE_DATE`；三日期未滿足 `公告 <= 停牌 < 恢復` 即退回 `unknown-blocked` | **是**，見 §2.2.1 |
| **市場狀態**：面額變更停牌（TWTB8U）| `unknown-blocked` | 不適用——無任何來源提供公告日期 |
| **市場狀態**：全額交割（TEJ 公司基本資料）| `approved-conservative-bound` = `effective_from`；見 §2.2.2 | **是**，限本政策定義的保守 bound |
| **市場狀態**：停牌（一般）| 不在表中 | 不適用——依 D8 由價格缺漏推定，僅作為 reason code |
| **公司行動**：TWSE 除權息（TWT49U）| `first-observed-only` | 否——端點完全不提供公告日期 |
| **公司行動**：TPEx 除權息（MOPS 公告文件）| `publisher-exact`，取自 observation 的公告定址鍵 | **是**，每筆行動即以其公告為單位取得 |
| **公司行動**：減資恢復買賣 | 同上「市場狀態：減資停牌」 | 同上 |
| **公司行動**：面額變更恢復買賣 | `unknown-blocked` | 不適用 |
| **公司行動**：TEJ 除息公告日補充 | 見 §1.8，`licensed-vendor-snapshot` | 依 §1.8 |
| 月營收 | `approved-conservative-bound` = 期後次月 10 日 `23:59 Asia/Taipei` | 是 |
| 季報 | `first-observed-only` | 否（法定期限差異大，暫不設 bound） |

**每日股價 bound 的理由**：官方收盤資料於交易日盤後發布，保守取 15:00 而非實際發布時刻，可確保不早於真實可得時間。此 bound 只適用於 `session:` scope 的 historical 端點，**不適用**於 `latest-observed`。

**月營收 bound 的理由**：台灣上市櫃公司月營收申報期限為次月 10 日。取當日 23:59 為最早可決策時間是保守做法。若實際觀測早於此 bound，仍以 bound 為準（較晚者勝）。

### 2.2.1 減資 `FILE_DATE` 判為 `publisher-exact`（Owner 決定 D11）

交易所的減資公告文件以 `TWTAVUDetail?STK_NO=…&FILE_DATE=…` 定址。回應本身
**沒有**任何一欄叫「公告日期」，因此把 `FILE_DATE` 當成公布日期是一項判斷，
需要 Validation Owner 裁決而非建置者自行認定。

支持的證據：

| 項目 | 內容 |
|---|---|
| 來源 | 交易所自己用來定址其公告文件的日期參數 |
| 順序 | 20/20 早於停止買賣日 |
| 非機械衍生 | 19/20 落在停牌前一個交易日；**2101 南港例外**，公告 2025-09-02、停牌 2025-09-04，中間 09-03 為交易日。若 `FILE_DATE` 是由停牌日回推的計算值，不會出現這個例外 |
| 發布延遲上界 | 唯一待執行的 1563，`FILE_DATE` 2026-08-18，2026-08-19 已可在預告表看到 |

**殘餘不確定性與其上界**：取得的是日期而非帶時分的發布紀錄。若真實發布時間晚於
`FILE_DATE`，回測會比實際更早知道減資。因 19/20 的公告至停牌僅隔一個交易日，
**最大前視暴露為一個交易日**。

Owner 於 2026-08-19 裁決採 `publisher-exact`，並要求保留 `公告 <= 停牌 < 恢復`
的 fail-closed 檢查：任一筆不成立即退回 `unknown-blocked`，不寫入公告日期。
決定紀錄見 [D11](../evidence/m3-owner-decision-d11-2026-08-19.md)。

### 2.3 不允許的 availability 推定

- 不得因為「資料現在存在」就推定它在歷史某日已存在。
- 不得以 legacy DuckDB 的 `available_at` 作為 canonical basis；legacy 財報 overwrite 語意會把後期修訂值配到最早日期。
- 季報不設保守 bound，因為不同公司、不同類型的法定申報期限差異過大，設定單一 bound 會系統性低估可得時間。
- 任何新的 bound 必須經 Validation Owner 批准，且必須可重現、含 revision 防護。
- **不得逕自把請求鍵裡的日期當成公布日期。** 端點常以日期定址其文件（`FILE_DATE`、
  `STOP_DATE` 之類），那是定址鍵，不是發布者對發布時間的陳述。要當成 `publisher-exact`
  必須逐案舉證並經 Validation Owner 裁決，且必須連同最大前視暴露一併記錄；
  §2.2.1 是目前唯一獲准的案例。
- 一個資料族內若不同來源的公告結構不同，**不得**以單一預設值概括。逐來源判定，
  取不到公告日期者維持 `unknown-blocked`，不得向下相容成 `first-observed-only`
  再靠首次觀測時間蒙混——首次觀測落在擷取當下，對歷史 cutoff 一律不可用。

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
4. `licensed-vendor-snapshot`（TEJ PRO）——**僅限**官方來源不存在或已無法取得的欄位，且該筆須帶明確日期欄位；
5. 其他一律 `unknown`。

`legacy-normalized-snapshot` 與 `licensed-vendor-snapshot` **永遠不進入** canonical lane。前者只進比較／coverage lane；後者可補 canonical 查詢結果，但必須保留自己的 evidence state，不得被誤讀為官方資料。

官方與 TEJ 對同一事實不一致時：**官方勝**，差異寫入 `data_quality_events`，兩筆並存。

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

1. ~~固定期間內沒有任何來源可證明 `official-open`~~ → 2026 用官方行事曆，2025 用 TEJ（§1.2.1）。**但 2025 官方版本已永久無法取得**。
2. ~~TPEx 完全沒有交易日曆來源~~ → 由 §1.2.1 的共用行事曆政策處理，標記 `owner-approved-policy`。
3. **市場狀態**仍沒有歷史版本，只有 current snapshot；TEJ 未涵蓋此項。這是目前最大的未解缺口。
4. 季報 availability 沒有保守 bound，只能用 `first-observed-only`（TEJ 申報日可改善此項）。
5. 固定期間內耐久日價覆蓋僅 3 個 market-date；抓取程式（M3.1b）執行後才會改變。
6. 尚未建立年度行事曆的例行擷取，2027 年有重蹈 2025 年覆轍的風險。

這些缺口的量化結果見 [M3.1 coverage ledger 與耐久封存證據](../evidence/m3-1-coverage-ledger-and-durable-archival-2026-08-16.md)。
