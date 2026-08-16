# Official Raw Snapshot Contract

## 1. 目的與邊界

本契約定義 Taiwan Core 擷取 TWSE、TPEx、MOPS 官方資料時，如何保存可驗證、不可就地改寫、可重解析的原始證據。它只處理來源擷取、provenance、parser lineage 與品質狀態，不定義策略、評分、回測、股數或下單。

Schema ID：`tw-alpha-raw-snapshot/1.0.0`。

Reader 必須拒絕未知 major version。任何欄位語義改變、hash 規則改變或 parser input 邊界改變，都必須提升 major version。

## 2. 三種 ID 必須分離

| ID | 生成方式 | 用途 |
|---|---|---|
| `blob_id` | `sha256(payload.bin)` | 識別完全相同的 application-visible response bytes；可去重但不可改寫 |
| `snapshot_id` | 對規範化 observation core 做 SHA-256 | 識別一次來源觀測；即使 payload 相同，不同擷取時間仍是不同 observation |
| `parse_run_id` | 對 `snapshot_id + parser_id + parser_code_hash + parser_config_hash` 做 SHA-256 | 識別一次可重現解析；新 parser 不得覆寫舊解析結果 |

`payload.bin` 是 HTTP client 在 JSON、文字、CSV 或 HTML 解碼前交給應用程式的 bytes。不得把 Python dict、DataFrame 或重新序列化 JSON 稱為 raw payload。

## 3. Artifact 結構

邏輯結構固定為：

```text
raw_blobs/sha256/<first-two>/<blob_id>/payload.bin
raw_observations/<publisher>/<endpoint_id>/<yyyy>/<mm>/<dd>/<snapshot_id>/manifest.json
parsed_observations/<parser_id>/<yyyy>/<mm>/<dd>/<parse_run_id>/
    parse_manifest.json
    rows.parquet
    rejects.parquet          optional
```

實體儲存可使用本機檔案系統、object store 或等價 append-only storage，但路徑可變不代表 ID 或 hash 規則可變。Manifest 必須以 UTF-8 JSON 保存，禁止在內容不變時只靠檔名或修改時間認定相同。

## 4. Raw manifest 必要欄位

| 欄位 | 規則 |
|---|---|
| `schema_id` | 固定 `tw-alpha-raw-snapshot/1.0.0` |
| `snapshot_id` | 依本契約規範生成 |
| `blob_id`／`payload_sha256` | 必須相同，皆為 payload bytes SHA-256 |
| `payload_bytes` | 非負整數，必須與實際檔案相符 |
| `publisher` | `TWSE`、`TPEX`、`MOPS` 或經批准的新官方 publisher |
| `source_id` | 來源清冊中的穩定 ID |
| `endpoint_id` | 穩定邏輯端點 ID，不直接以可漂移 URL 當 ID |
| `request_method` | `GET` 或 `POST` 等實際方法 |
| `request_url` | 去除 credentials 後的實際 URL |
| `request_parameters` | 排序後的非機密 query／form 欄位；秘密必須遮罩 |
| `request_fingerprint` | 對 method、URL、已遮罩且規範化參數及必要 headers 做 SHA-256 |
| `fetched_at` | RFC 3339 UTC，來源觀測完成時間 |
| `session_timezone` | 固定 `Asia/Taipei` |
| `logical_period` | 交易日、月份、季度、公告區間或 `latest-observed` |
| `http_status` | 實際 status；非 2xx 也必須可留下 observation |
| `content_type`／`content_encoding` | 原始 response headers 所示值；缺值明示 `null` |
| `response_headers` | allowlist：`Date`、`ETag`、`Last-Modified`、`Content-Type`、`Content-Encoding`、`Content-Length`、`Retry-After` 及 request/correlation ID |
| `transport_attempt` | 第幾次 retry、timeout policy、client identifier |
| `capture_status` | 見狀態機 |
| `evidence_state` | 見證據狀態 |
| `producer` | Taiwan Core commit；dirty 時加 tracked diff 與 untracked manifest hash |
| `contract_version` | 本契約版本 |
| `created_at` | manifest 建立時間，RFC 3339 UTC |

Response 的 cookie、authorization、API token、個資與本機絕對秘密路徑不得寫入 manifest。無法確定是否為秘密的 header 預設不保存。

## 5. Observation core 與 hash 規則

`snapshot_id` 的 observation core 至少包含：

- `schema_id`；
- `publisher`、`source_id`、`endpoint_id`；
- `request_method`、`request_fingerprint`；
- `fetched_at`；
- `logical_period`；
- `http_status`；
- `payload_sha256`、`payload_bytes`。

Core 使用 UTF-8、key 依 Unicode code point 排序、無多餘空白的 canonical JSON，再取 SHA-256。`created_at`、本機路徑或非決定性 process ID 不得放入 core。

同一 payload 可共用一個 blob，但每次實際觀測都保留自己的 manifest。若使用 cached response，必須明示 `transport_attempt.cache_state`，不得偽裝成新 HTTP 擷取。

## 6. 狀態機

### 6.1 Capture status

```text
requested -> captured -> hash-verified
         \-> http-error-captured
         \-> transport-failed
```

- `captured`：已保存完整 payload 與 manifest，不代表內容可解析。
- `hash-verified`：重新讀取檔案所得 hash、bytes 與 manifest 相符。
- `http-error-captured`：HTTP 非成功或官方回傳錯誤狀態，但 response body 已保存。
- `transport-failed`：沒有完整 response body；仍保存 request、exception class、時間與 retry 資訊，但不可捏造 `blob_id`。

### 6.2 Parse status

```text
not-attempted -> parsed -> quality-accepted
             \-> parse-rejected
             \-> quality-quarantined
```

Capture 與 parse 狀態不可合併。成功下載但 schema 漂移應是 `hash-verified + parse-rejected`，不能因 parser 失敗而刪除 raw evidence。

### 6.3 Evidence state

| 狀態 | 語義 |
|---|---|
| `official-captured` | publisher 與 request 已確認，payload 完整且 hash 可驗證 |
| `verified-snapshot` | raw、manifest、parser lineage、品質檢查均通過，可供下游引用 |
| `research-only` | 來源或時點不足以支持正式決策，只可研究 |
| `quarantined` | hash、schema、範圍、授權或內容有未解問題；下游正式 reader 必須拒絕 |

不得把 `official-captured` 自動提升為 `verified-snapshot`。

## 7. Parse manifest 必要欄位

| 欄位 | 規則 |
|---|---|
| `parse_schema_id` | `tw-alpha-parse-run/1.0.0` |
| `parse_run_id` | 依第 2 節生成 |
| `snapshot_id`／`blob_id` | 回指唯一 raw observation 與 blob |
| `parser_id` | 穩定名稱，例如 `twse-mi-index/1` |
| `parser_code_hash` | parser source 與必要 mapping 的 SHA-256 |
| `producer` | commit／dirty fingerprint |
| `dependency_fingerprint` | Python、pandas、pyarrow 及 lockfile hash |
| `parser_config`／`parser_config_hash` | 影響解析的所有選項；不得留隱含環境預設 |
| `started_at`／`completed_at` | RFC 3339 UTC |
| `row_count`／`reject_count` | 明確整數 |
| `output_schema_hash` | Arrow schema canonical representation 的 SHA-256 |
| `output_sha256` | `rows.parquet` bytes 的 SHA-256 |
| `quality_checks` | 每項檢查的 ID、版本、結果與統計 |
| `parse_status`／`evidence_state` | 不得高於 raw 與 quality 能支持的狀態 |

Parser 更新必須產生新 `parse_run_id`。舊輸出可被標記 superseded，但不可刪除或覆寫。

## 8. 不可變與 idempotency 規則

- 任何既有 `blob_id` 路徑內容不同時立即 fail closed。
- 任何既有 `snapshot_id` manifest 內容不同時立即 fail closed。
- 相同 observation core 重跑可回傳既有 `snapshot_id`，但不得更新其時間或內容。
- 同一邏輯交易日若官方內容修訂，新的 payload hash 必須建立新 observation；以 `supersedes_snapshot_id` 建立關係，不可覆蓋舊檔。
- Parser、品質規則或依賴版本改變時建立新 parse run。
- 清除、壓縮、搬移或保留期限政策另立契約；M2 預設禁止自動刪除。

## 9. Quality 與 fail-closed 最低要求

每個 P0 source 必須定義：

- HTTP／官方 status 檢查；
- content type 與最小 bytes；
- schema fingerprint 或明確欄位 allowlist；
- 交易日／報表期一致性；
- row count、symbol coverage 與相較前期異常；
- primary key 重複；
- 數值範圍、OHLC、成交量與金額不可能值；
- 台股代碼、market 與單位正規化；
- stale、missing、partial、holiday 與 no-data 分離；
- 所有 reject rows 及理由可追溯。

未知欄位、欄位改名、資料日期不一致或 coverage 明顯不足時，不得以空值、欄位猜測或非官方 fallback 靜默通過。

## 10. Legacy raw v1 分類

現有 `data/raw/*.parquet` 是解析後正規化資料，依本契約標為 `legacy-normalized-snapshot`。它們可作回歸、交叉檢查與歷史研究，但不能回溯宣稱為 `official-captured`，因為缺少原始 response bytes、完整 request／response manifest、capture hash 及 parser lineage。

Legacy 檔案不得就地轉換成假的 raw v2。若官方端點仍可重取，建立新的 observation；若不可重取，保留 legacy evidence state 並明示缺口。

## 11. 安全、授權與個資

- 只擷取來源清冊批准的官方端點和公開資料。
- 遵守官方使用條款、速率限制與合理 retry/backoff。
- Browser automation 所得 API response 仍需記錄頁面入口、API endpoint、request 參數及 browser/client 版本。
- 商業資料、券商資料、TEJ、licensed feed 與使用者帳戶資料不可因格式相同而混入官方 raw namespace。
- `Yahoo consensus prototype`、MIS prototype 和任何未核准來源固定為 research-only 或 quarantine。

## 12. 契約驗收

- [x] 相同 observation 重跑不新增不同 ID，且不改寫舊檔；M2.2 sequential 與 concurrent tests 通過。
- [x] 同交易日內容修訂產生新 snapshot 並保留 supersession lineage；M2.2 foundation test 通過。
- [x] 任一 byte 被改動時 hash 驗證失敗；M2.2 deliberate tamper test 通過。
- [x] 非 2xx、非 JSON、空 payload 與 schema drift 均留下可診斷證據；M2.3–M2.6 failure fixtures 與 quality evidence 通過。
- [x] 同一 raw 可由兩版 parser 重解析，兩份輸出並存；parser upgrade replay 與 immutable output tests 通過。
- [x] parser output 能回指 raw blob、observation、code 與 dependency fingerprint；56/56 parse manifests 經 archive audit 驗證。
- [x] manifest 不含 credentials、cookies、token 或未批准 request／response headers；M2.2 unit tests與 M2.6 security review 通過。
- [x] P0 reader 對 unknown schema、missing provenance 或 unresolved quarantine fail closed；有效 release 必須有唯一、完整且可驗證的事件鏈。

本清單已全數通過；完整 owner、release、durable archive、restore 與 final test evidence 見 [M2 closure evidence](../evidence/m2-owner-approvals-release-and-durable-audit-2026-08-03.md)。
