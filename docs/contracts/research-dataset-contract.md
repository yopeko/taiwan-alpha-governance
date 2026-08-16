# Research Dataset Package Contract

## 1. 目的

定義 Taiwan Core 匯出給 AlphaMaster 的唯讀、不可變、Point-in-time 研究資料封包。此封包只能產生 `research-only` 候選，不授權正式策略或交易。

## 2. Schema ID

`tw-alpha-dataset/1.0.0`

Reader 必須拒絕未知 major version。

## 3. 封包內容

| 檔案 | 必要 | 用途 |
|---|---:|---|
| `dataset_manifest.json` | 是 | lineage、schema、hash、時間及政策 |
| `bars.parquet` | 是 | 原始或明確標記調整政策的 OHLCV／amount |
| `universe.parquet` | 是 | 每個 session 的 eligibility 及原因 |
| `market_status.parquet` | 是 | 停牌、限制、缺值、交易狀態 |
| `corporate_actions.parquet` | 是 | 公司行動與官方可得時間 |
| `fundamentals_pit.parquet` | 依 feature set | PIT 基本面長表 |

新聞不包含於 v1 正式研究封包。若未來加入，必須另立 schema 及 evidence contract。

## 4. Manifest 必要欄位

| 欄位 | 語義 |
|---|---|
| `schema_id` | 固定 `tw-alpha-dataset/1.0.0` |
| `dataset_id` | 由 manifest 與檔案 hash 確定的不可變 ID |
| `created_at` | RFC 3339 UTC 時間 |
| `producer` | Taiwan Core 名稱、commit、dirty fingerprint |
| `session_timezone` | 固定 `Asia/Taipei` |
| `start_session`／`end_session` | 封包交易日範圍 |
| `decision_cutoff_policy` | 當日資訊可用截止規則 |
| `universe_policy_id` | 股票池規則版本 |
| `adjustment_policy_id` | 原始／調整價版本及定義 |
| `market_rule_version` | 建立資料時使用的市場規則版本 |
| `source_snapshot_ids` | 所有官方 raw snapshot ID |
| `feature_input_allowlist` | 允許提供給研究層的欄位 |
| `missing_value_policy` | 明示不可 forward-fill 的狀態 |
| `files` | 檔名、row count、schema、SHA-256 |
| `evidence_state` | `verified-snapshot` 或 `research-only` |

若 producer 工作樹不是 clean commit，`producer` 必須包含 tracked diff hash 與 untracked manifest hash；否則不得宣稱可重現。

## 5. `bars.parquet`

必要欄位：

- `symbol`: 字串，保留前導零；
- `market`: `TWSE` 或 `TPEX`；
- `session_date`: 台北交易日；
- `open`, `high`, `low`, `close`: 非負價格；
- `volume_shares`: 股數，不得混用張數；
- `turnover_ntd`: 成交金額；
- `available_at`: 此 observation 可供決策的時間；
- `source_snapshot_id`；
- `price_basis`: `raw_official` 或已批准的 adjustment policy；
- `quality_state`。

Primary key 為 `(symbol, market, session_date, price_basis)`。

若 AlphaMaster 需要 `time/open/high/low/close/volume` 相容視圖，由 adapter 產生；不得改變原欄位語義。Adapter 應把 `volume_shares` 映射為 `volume`，並保存 mapping version。

## 6. `universe.parquet`

必要欄位：

- `session_date`, `symbol`, `market`；
- `listed_as_of`, `delisted_as_of`；
- `security_type`；
- `eligible`；
- `eligibility_reasons`；
- `liquidity_state`；
- `metadata_evidence_state`；
- `source_snapshot_id`。

不得只輸出「今天仍存在」的股票。任何 `current_metadata_proxy` 必須使相關 PIT 欄位降級為 `research-only`，並在 manifest 列出影響範圍。

## 7. `market_status.parquet`

至少保存：

- 交易日及證券鍵；
- `tradable`；
- 停牌／恢復、注意／處置、變更交易方法及其他限制；
- 漲跌幅例外；
- 資料缺漏或 stale 狀態；
- `available_at` 與來源。

未知狀態不得自動轉成 `tradable=true`。

## 8. `corporate_actions.parquet`

至少保存 action type、ex-date、record/payment dates（若可得）、官方公布或首次可得時間、原始 reference、明確 adjustment factor、來源及證據狀態。

缺少官方 adjustment factor 的 share-changing event 不得用價格跳空推定後進入 formal 特徵。

## 9. `fundamentals_pit.parquet`

採長表：

- `symbol`, `market`；
- `metric`；
- `fiscal_period`；
- `value` 及 unit；
- `published_at`；
- `first_observed_at`；
- `revision_observed_at`；
- `source_record_id`；
- `evidence_state`。

研究切片只能選取 `published_at`／保守可得時間不晚於 decision cutoff 的版本。

## 10. 驗收及拒絕條件

拒絕整個封包：

- hash mismatch；
- 未知 major schema；
- 主鍵重複；
- session 日期不合法；
- OHLC 不可能或 volume／amount 為負；
- source snapshot 無法追溯；
- universe 或 market status 缺必要 session；
- adjustment policy 不明；
- 使用未聲明的 forward-fill；
- evidence state 高於來源實際證據。

研究完成後不得覆寫封包；資料修正必須產生新 `dataset_id`。

