# Point-in-time Warehouse Contract

## 1. 文件控制

| 欄位 | 值 |
|---|---|
| Contract ID | `tw-alpha-pit-warehouse/1.0.0` |
| Coverage certificate | `tw-alpha-pit-coverage-certificate/1.0.0` |
| 版本 | `pit-warehouse-contract-v0.2.0` |
| 狀態 | `approved-for-M3-shadow-build; G0-approved-2026-08-03` |
| 生效範圍 | M3 shadow warehouse；不包含 production cutover |
| 上游 | 通過完整性與 quality disposition 驗證的 M2 immutable archives |
| 下游 | M4–M7 可重現資料集；目前不得直接供 formal／live execution |

## 2. 目的與非目標

本契約定義如何在指定 `decision_as_of` 重建當時可知的台股市場、股票生命週期、價格、交易狀態、公司行動與基本面資訊。

M3 必須回答兩個不同問題：

1. 事件或數值在市場上何時生效？
2. 系統在當時何時有足夠證據可以使用它？

M3 不負責交易成本、零股成交、帳本、策略評分、策略升級或下單。這些屬 M4 以後的里程碑。

## 3. 不可變輸入與資料集身分

每個 warehouse dataset 必須有 content-addressed `dataset_id`。最少納入：

- schema major/minor version；
- 每個上游 archive 的 tree hash；
- 每個採用 observation 的 `snapshot_id`、`parse_run_id`、`quality_run_id`；
- source-to-table mapping version；
- availability policy version；
- canonical conflict policy version；
- builder code、dependency 與 config hash；
- 各資料族聲明的 coverage interval；
- predecessor dataset ID 或 `null`。

相同 frozen inputs、版本與設定必須產生相同 `dataset_id`。重新執行只能重用相同 artifact，不得就地改寫。

## 4. 每筆資料的共同血緣

每筆 canonical 或 event row 至少保存：

| 欄位 | 規則 |
|---|---|
| `record_id` | canonical row identity 的 SHA-256 |
| `source_id` | M2 formal source ID，不可從 URL 猜測 |
| `snapshot_id` | raw observation identity |
| `parse_run_id` | immutable parser output identity |
| `quality_run_id` | initial quality identity |
| `effective_quality_state` | `accepted`、`released`、`quarantined` 等；`released` 不得改寫為 `accepted` |
| `source_record_fingerprint` | 原始 source row 或 canonical source slice 的穩定指紋 |
| `source_locator` | 可回到原 observation／row 的位置 |
| `row_hash` | canonical row bytes 的 SHA-256 |
| `supersedes_record_id` | 修正版指向前版；無則 `null` |
| `evidence_state` | `verified-snapshot`、`legacy-normalized-snapshot`、`research-only`、`assumption` 或 `blocked` |
| `coverage_state` | `covered`、`partial`、`official-no-data`、`missing-at-source`、`current-only`、`unknown` 或 `blocked` |

缺任一必要 lineage、未知 schema major、重複 identity 或 hash mismatch 均 fail closed。

## 5. 時間語意

以下欄位不可合併或互相冒充：

| 欄位 | 意義 |
|---|---|
| `effective_from`／`effective_to` | 市場事實生效區間；未知時保留 null + state |
| `publisher_released_at` | 可證明的官方公布時間；不知道不可推算成 exact |
| `first_observed_at` | 本系統第一次取得該 observation 的 UTC 時間 |
| `revision_observed_at` | 此修正版第一次觀測時間 |
| `decision_available_at` | 經批准 policy 判定最早可供決策的時間 |
| `availability_basis` | 產生 `decision_available_at` 的證據與 policy 類型 |

允許的 `availability_basis`：

- `publisher-exact`：原始資料可證明逐筆公布時間；
- `approved-conservative-bound`：Validation Owner 批准的保守截止政策；
- `first-observed-only`：沒有更早的可靠公布證據，使用首次觀測時間；
- `unknown-blocked`：無法安全決定，不可供 as-of 決策。

預設 `decision_available_at` 不得早於 `first_observed_at`。只有逐資料族另有批准、可重現且包含 revision 防護的 policy，才可使用更早的 `publisher_released_at` 或保守 bound。

任何 as-of query 必須滿足：

```text
decision_available_at <= decision_as_of
```

若不成立或時間未知，資料不得出現在 `known_information`，只能出現在 coverage／blocked reason。

## 6. Shadow warehouse 表

### 6.1 `warehouse_runs`

保存 dataset ID、輸入 fingerprints、builder、config、coverage、row counts、quality summary、published time、predecessor 及 rollback target。

### 6.2 `trading_calendar_pit`

主鍵包含 `market + session_date + record_id`。狀態至少為 `official-open`、`official-closed`、`special-session`、`observed-market-file` 或 `unknown`。不得用「週一至週五減假日」或缺價靜默推論完整官方交易日曆。

### 6.3 `security_events` 與 `security_intervals`

使用 `security_instance_id`，不可只用重複使用的 `symbol + market` 代表整個生命週期。事件包含上市、下市、改名、轉板、security type 與 master observation。官方缺上市日保留 `missing-at-source`；不得自動 eligible。

### 6.4 `daily_prices_pit`

保存 raw official price basis、`activity_scope`、`ohlc_state`、volume／turnover／transactions 及來源版本。historical／latest scope 衝突必須並存並由版本化 policy 選擇，禁止 last-write-wins。缺 OHLC 不補前值，也不能單憑 activity 推定 tradable。

### 6.5 `market_status_pit`

保存 suspension、attention、disposal、altered-trading 等事件與已知區間。查無事件、source current-only、無 coverage 是不同狀態；absence 不等於 `tradable=true`。

### 6.6 `corporate_actions_pit`

保存 action date、announcement、reference price、dividend／rights、adjustment evidence 及 revision lineage。`announced_at` 缺失時，最多只能在 `first_observed_at` 後使用。不可從價格跳空反推正式 adjustment factor。

### 6.7 `fundamentals_pit`

使用長表保存 period、statement type、metric、value、statement category、公布／首次觀測／修正時間及 availability basis。修正版新增 record 並 supersede 舊版，不得覆寫舊值後沿用舊 `available_at`。

### 6.8 `data_quality_events` 與 `coverage_certificates`

保存資料族 coverage、missing-at-source、scope conflict、current-only、legacy-only、parser／policy version 及 query-time blocked reasons。

Coverage certificate 的最低主體粒度是 `dataset_id + market + calendar_date`。固定 G0 期間中的每個 calendar date 都必須分別列出 TWSE 與 TPEx 狀態。每列至少包含 `session_state`、aggregate `reconstruction_state`、各必要資料族 coverage、例外、reason codes、lineage、policy version 與 certificate hash。

Aggregate `reconstruction_state` 只允許：

- `supported`：可依指定 cutoff 重建；
- `not-session`：有官方日曆證據的非交易日；
- `partial`：部分資料族不足；
- `blocked`：存在明確阻擋條件；
- `unknown`：沒有足夠證據判定。

未列入 certificate 的 market-date 等同 `unknown`。只有 `supported` 受到資料重建承諾；`not-session` 只承諾正確回傳非交易日，不授權產生交易。

## 7. As-of reconstruction contract

查詢輸入至少包含：

- `as_of_session`；
- `decision_as_of`（含時區）；
- markets；
- security types；
- dataset ID；
- coverage policy version。

輸出不得只回傳被篩完的股票，必須包含：

- `eligible`、`ineligible`、`unknown`、`blocked` 狀態；
- 每個狀態的 reason codes；
- 使用的 price／status／action／fundamental records 及 lineage；
- 各資料族 coverage certificate；
- 是否存在任何 `decision_available_at > decision_as_of`；
- dataset、query config 及 output hash。

只要 security lifecycle、calendar 或關鍵 market-status coverage 不足，系統不得默認可交易；必須回傳 `unknown` 或 `blocked`。

## 8. 輸入 evidence gate

M3 staging 只能接收：

1. M2 audit 驗證通過的 accepted observations；
2. 原 quality decision 為 quarantined、但有唯一且 audit 驗證通過的 release；
3. 明示為 `legacy-normalized-snapshot` 的 legacy rows，只能進比較／coverage lane，不可升格為 official raw-v2；
4. 明示 `official-no-data`、`missing-at-source` 或 `current-only` 的狀態 evidence。

Quarantined 且 unresolved、無 lineage、未知 source ID、未核准 licensed data 或 security rejection 均不得進 warehouse canonical lane。

## 9. Publication、production protection 與 rollback

- Builder 只能發布到全新、空白、核准的 shadow root。
- Builder 必須拒絕 output 指向或涵蓋 production DuckDB、legacy raw、stock master、M2 primary 或 M2 backup。
- M2 inputs 永遠 read-only；M3 artifact 只新增，不覆寫。
- build 前後比對 protected fingerprints；若既有排程並行更新，保留 concurrent-change evidence，不回復或覆寫它。
- Shadow rollback 是停止引用新 dataset ID，回到 predecessor；不得為 rollback 改 production。
- Production reader pointer、cutover、reconciliation 及正式 rollback 需要新的 G4 Owner 批准。

## 10. Coverage 與 M3 exit

G0 Owner 決定採 `G0-A-fixed-window-certified-dates`，完整決定見 [M3 G0 Owner Decision](../evidence/m3-g0-owner-decision-2026-08-03.md)。

- 固定基準期間：2025-01-01 至 2026-08-03，首尾皆包含。
- 市場：TWSE、TPEx；商品範圍延續 M0 普通股。
- 固定期間共有 580 個 calendar dates；兩市場分開列示，因此基準 certificate 至少需要 1,160 個 market-date 狀態列。
- 每個 dataset manifest 仍須逐資料族聲明 `supported_from`、`supported_to`、markets、coverage state 及已知例外。
- 查詢超出 certificate、未列日期、`partial`、`blocked` 或 `unknown` 必須 fail closed。
- 2026-08-04 以後不會自動受到「到今天」批准；必須以新的 append-only certificate 版本逐日加入。

M3 complete 前，固定期間內每個 calendar date 都必須有 TWSE 與 TPEx 狀態；所有官方開市／特殊 session 必須為 `supported`，所有休市日必須有可驗證的 `not-session`。任何遺漏、`partial`、`blocked` 或 `unknown` 都會阻止 M3 complete。

此外仍須通過完整 coverage evidence、anti-lookahead、deterministic rebuild、legacy diff、protected-store non-mutation、restore 與 Validation Owner signoff。

## 11. 最低驗收測試

- 相同 inputs／config 產生相同 dataset ID 與 table hashes；
- 未知 schema major、duplicate key、hash mismatch、缺 lineage fail closed；
- `decision_available_at > decision_as_of` 永不洩漏；
- revision 不會改寫舊 record 或提早可見；
- current master／status 不會回填歷史；
- missing listing date 不會自動 eligible；
- symbol reuse 產生不同 security instance；
- historical／latest price scope conflict 被保存且可解釋；
- missing OHLC／status coverage 不被補值或默認 tradable；
- restore 到另一空目錄可重建相同 hashes；
- protected production fingerprints build 前後完全相同，或有明確 concurrent-change event 並停止發布。
