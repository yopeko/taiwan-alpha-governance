# M2.2 Immutable Raw Capture Foundation Evidence

## 1. 結論

M2.2 `Capture foundation` 已完成隔離式實作與回歸驗證，證據狀態為 `verified-current`。它新增 raw bytes capture、content-addressed write-once blob、append-only observation manifest、source allowlist、secret redaction、HTTP／transport failure evidence、hash verification、idempotency 與 supersession 支援。

M2 整體仍是 `in_progress`。本輪沒有把任何 TWSE、TPEx 或 MOPS adapter 接上新 store，沒有 live HTTP capture，也沒有建立 parser registry；這些分別屬 M2.3 與 M2.4。

## 2. 變更範圍

只在 `C:\project\tw-sepa-screener` 新增兩個 untracked 檔案：

| 檔案 | SHA-256 | 用途 |
|---|---|---|
| `src/tw_sepa_screener/raw_capture.py` | `b9df41e95a69ac9e578eaf4a3e01061820f4bda8632563b6acd2104012733bc4` | capture foundation |
| `tests/test_raw_capture.py` | `8b65460414710b34d5a4b9b2753749f052ec53d900b486b28d435bcfb3c0ea3a` | 14 項 isolation／integrity tests |

未修改：

- `storage.write_raw_snapshot` 與 `atomic_write_parquet`；
- TWSE、TPEx、MOPS、calendar、master 或 financial adapters；
- `data/raw` legacy tree；
- `data/tw_sepa.duckdb`；
- strategy、simulation、paper account 或交易設定。

## 3. Foundation 行為

### 3.1 Source allowlist

`RawSourceDefinition` 綁定：

- stable `source_id`；
- publisher；
- endpoint ID；
- 允許的 HTTPS URL prefix；
- HTTP methods。

任何 source、publisher、endpoint、URL host/path 或 method 不一致，都會在建立 store artifact 前 fail closed。Registry 不提供自動 fallback。

### 3.2 Write-once publication

- Blob ID 是 exact application-visible response bytes 的 SHA-256。
- Blob 先寫入同 volume temporary file，flush／fsync 後以 hard link 原子發布。
- 目標已存在時只接受 byte-for-byte 相同內容。
- 不支援 same-volume hard-link semantics 的 filesystem 直接失敗，不退回可能覆寫的 rename。
- Manifest 使用相同 write-once 行為。

### 3.3 Observation identity

`snapshot_id` 由 canonical observation core 生成，包含 source、endpoint、request fingerprint、`fetched_at`、logical period、HTTP status、payload hash 與 bytes。

- 相同 observation 重跑回傳同 ID 且不更新 mtime。
- 相同 payload 在新擷取時間建立不同 observation，但共用 blob。
- 同期間修訂建立新 observation，可使用 `supersedes_snapshot_id` 保留 lineage。
- raw manifest 固定 `parse_status=not-attempted`；parser output 不得回寫 raw manifest。

### 3.4 Secret 與 metadata 控制

- URL query 從 `request_url` 移除，參數排序後另存。
- token、authorization、cookie、API key、password、credential、secret、signature 類欄位改為 `[REDACTED]`。
- Request headers 僅保存安全 allowlist，加上已遮罩的敏感 header 名稱。
- Response headers 僅保存 contract allowlist；`Set-Cookie` 不保存。
- Manifest verifier 會檢查 source registry、snapshot path、request fingerprint、capture／evidence state、contract version、content metadata 與 payload hash。

### 3.5 Failure evidence

- HTTP 非 2xx：保存 response bytes，狀態為 `http-error-captured + quarantined`。
- Transport failure：保存 request、時間、stable error type 與 retry metadata；`blob_id`、payload hash、bytes 和 HTTP status 必須為 null。
- 任何 raw manifest evidence escalation、路徑 ID 不一致或 payload tamper 都 fail closed。

## 4. 驗證結果

| 驗證 | 結果 |
|---|---|
| Targeted pytest | `13 passed in 0.28s` |
| Full pytest | `362 passed in 73.34s` |
| Ruff | `All checks passed` |
| mypy | `Success: no issues found in 1 source file` |

14 個 targeted tests 覆蓋：

- exact bytes 與完整 manifest；
- sequential idempotency；
- 16 次／8 workers concurrent identical capture；
- revised payload 與 supersession；
- same blob／different observation；
- payload tamper；
- query／parameter／header secret redaction；
- HTTP 429 capture；
- transport failure without blob；
- free-form transport error message rejection；
- unknown source、publisher、method 與 host rejection；
- manifest evidence escalation；
- manifest path mismatch；
- decoded text 與 naive timestamp rejection。

## 5. Production data non-mutation evidence

M2 entry 與本輪結束後數值完全相同：

| Artifact | Entry | M2.2 後 |
|---|---|---|
| legacy raw tree files | 4,988 | 4,988 |
| legacy raw tree bytes | 188,391,038 | 188,391,038 |
| legacy raw content manifest SHA-256 | `9b09a95aae389c9502d48201066f9470a86792ec834db1c6a0d32132b9a6993b` | 相同 |
| DuckDB bytes | 425,209,856 | 425,209,856 |
| DuckDB SHA-256 | `c948a1bd62ff141eabd2216bec358a1b8ea129dd0821bcc785bffe75648bbfba` | 相同 |

## 6. Worktree post-state

| 項目 | Entry | M2.2 後 |
|---|---|---|
| HEAD | `fb87f62f8c2c68e2b85982cd102a35fd935bc0a4` | 相同 |
| tracked modified | 29 | 29 |
| git-visible untracked | 116 | 118 |
| untracked bytes | 855,844 | 894,193 |
| untracked manifest SHA-256 | `dc19e51d676728608378d60ebc9ce2548ed741d608c0986da6b3352804a34fe4` | `c75cb74475219d9769a389a59e2580c05bcc58e7431d2654444370b722a17b32` |

差異只有第 2 節兩個新增檔案。工作樹仍不是 clean commit 或可重現 release，沒有 stage 或 commit。

## 7. 剩餘限制與下一 gate

- Foundation 是 local filesystem implementation；正式部署到不支援 hard links 的 filesystem 或 object store 前，必須提供等價 conditional create／write-once semantics。
- 尚未保存 live official response，不能把任何 source 標成 raw-v2 migrated。
- 尚未實作 parser ID、parse-run manifest、reject ledger 或 reparse。
- 尚未做 source-specific date、schema、coverage、holiday 或 empty-response quality 判定。
- `TPEX-LISTING-STATUS` 仍是 source gap。

下一 gate 是 M2.3：先以 `TWSE-CALENDAR` 與 TWSE／TPEx master 做 isolated adapter pilot；必須先 capture bytes，再 parse，且 pilot 初期仍不得寫 production `data/raw` 或 DuckDB。

## 8. Rollback

由於本輪只新增兩個 untracked 檔案，技術回滾目標是移除 `raw_capture.py` 與 `test_raw_capture.py`。Production DB 與 legacy raw 不需復原。未經使用者明確要求，不執行刪除或回滾。
