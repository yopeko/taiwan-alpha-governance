# M2 官方資料封存操作手冊

版本：`m2-runbook-v1.1.0`  
日期：2026-08-03  
適用程式：`C:\project\tw-sepa-screener`

## 1. 操作邊界

- 只接收來源清冊內的 TWSE、TPEx、MOPS 官方端點。
- HTTP 回應必須先保存原始 bytes，之後才可解析。
- 原始檔、解析結果、拒絕明細及品質決定均只新增，不覆寫。
- 缺值、無成交、官方無資料、停牌及抓取失敗是不同狀態；禁止用前值補齊。
- M2 不寫選股分數、不修改策略、不匯入正式 DuckDB，也不授權下單。
- 未通過授權或人工簽核的來源必須留在隔離區。

## 2. 封存內容

每個封存根目錄至少包含：

```text
raw_blobs/                 依 SHA-256 保存的原始 bytes
raw_observations/          request、response、時間、來源與 hash manifest
parsed_observations/       固定 schema 的 rows、rejects 與 parser manifest
quality_events/            品質檢查及接受／隔離決定
quality_releases/          人工解除隔離事件；不得改寫原決定
capture_runs/              全來源擷取摘要
replay_runs/               全來源重播摘要
shadow_runs/               每日股價缺口隔離演練摘要
```

`parse_manifest.json` 與 `quality_manifest.json` 是完成標記。只有資料檔、沒有完成標記的目錄視為半成品，稽核必須報錯。

## 3. 每日固定流程

1. 確認系統時間、磁碟空間、官方來源清冊與當次 producer fingerprint。
2. 用無隱藏重試的 session 擷取；每次重試都要有獨立 attempt 證據。
3. 對每個 observation 驗證 SHA-256、路徑與 manifest。
4. 只用 source ID 與 endpoint ID 精確選擇唯一 parser；不可從 URL 猜測。
5. 產生 rows、reject ledger、schema hash、程式與依賴指紋。
6. 執行品質規則；任何 blocking reject、截斷、授權待審或不明狀態均隔離。
7. 執行全封存稽核，確認沒有 orphan blob、缺 parse、缺 quality 或半成品。
8. 比對正式 DuckDB、舊 raw tree、stock master 的前後 fingerprint；隔離演練必須完全相同。

全 P0 擷取命令範本：

```powershell
.\.venv\Scripts\python.exe -m tw_sepa_screener.m2_p0_capture `
  --output-root C:\tmp\tw-alpha-m2-p0-YYYYMMDD-NN `
  --reference-session YYYY-MM-DD `
  --statement-year YYYY --statement-quarter Q --revenue-month M `
  --producer-commit COMMIT --dirty-fingerprint FINGERPRINT
```

離線重播命令範本：

```powershell
.\.venv\Scripts\python.exe -m tw_sepa_screener.m2_p0_replay `
  --archive-root C:\tmp\tw-alpha-m2-p0-YYYYMMDD-NN `
  --producer-commit COMMIT --dirty-fingerprint FINGERPRINT
```

目前 capture／replay 命令仍只允許核准的暫存 staging root，避免直接碰正式資料。已批准的 durable snapshot 位於 `C:\project\tw-sepa-screener\data\raw_v2\m2_2026-08-03`，E: 備份位於 `E:\tw-sepa-screener-backup\raw_v2\m2_2026-08-03`。後續增量發布不得以 `Copy-Item -Force` 或覆寫方式合併；M3 必須先建立 append-only promotion／rollback evidence。

## 4. 重試與續跑

- HTTP 429 或 5xx：依 `Retry-After` 或有限退避重試；每次 attempt 都要保存。
- DNS、timeout、TLS：保存 transport-failure manifest；不得偽造成官方空資料。
- 4xx：保存錯誤 response bytes 並停止；先檢查參數、權限或授權。
- JSON／HTML schema 不符：原始 bytes 已保存後，parser 產生 payload reject；不得重新下載來掩蓋第一次失敗。
- 已存在且 hash 相同的 raw、parse、quality 直接重用；相同 ID 但 bytes 不同時 fail closed。
- 官方修訂同一期間時，保存新 observation，舊版不刪除；另建 supersession 關係。

## 5. 無資料與缺值

- 官方明確空清單、查無資料或 schema placeholder：記為 `official_no_data`，可有零 canonical rows，但要有 exclusion ledger。
- 非四碼普通股：保留為 `excluded`，不可默默略過。
- 欄位缺漏或格式錯誤：記為 `rejected`，品質隔離。
- TWSE listing-start 的 377 筆無日期來源列保留為 `event_date=null` 與 `event_date_state=missing-at-source`；不得用其他欄位猜日期。
- OHLC 缺值不等於停牌。只有交易狀態來源能提供停牌證據。

## 6. 隔離與人工解除

隔離是不可變的初始品質決定。人工解除只能新增事件，至少包含：

- actor；
- 完整理由；
- 可追溯 ticket、法務／授權文件或官方更正證據；
- 前一個事件 ID。

禁止直接改 `quality_manifest.json`、刪除 reject，或以「程式可讀」作為解除理由。`TWSE-ACTIONS-HIST` 已由 Decision `M2-OWNER-APPROVAL-20260803-01` 及唯一 release event `3cf981611005079d2557ce974035a5449339ebfdfbb1f2be91eb62e82ec6866a` 解除；初始 quarantine 與 manifest SHA-256 仍保持不變。再次 release 會被視為 duplicate 並 fail closed。

## 7. 完整性與防竄改

每次發布前後都要驗證：

- raw payload hash 與 bytes；
- observation identity、request 參數及來源 allowlist；
- rows／rejects Parquet hash、schema、row count；
- parser／config／dependency hash；
- quality manifest、初始事件與事件鏈 hash；
- orphan blob、missing blob、missing parse、missing quality、incomplete parse／quality directory；
- 所有預期 P0 source 至少一筆 `hash-verified` observation。

任何單一 byte 被改動，稽核必須失敗。測試不得在正式封存上做破壞；先複製到一次性測試目錄或使用 pytest temporary directory。

## 8. 磁碟、備份與保存

- 自動刪除固定為 `disabled`。
- 70% 使用率：提醒；85%：停止非必要 backfill；95%：停止新擷取並升級事件。
- 已批准 baseline 是 C: primary + E: second-volume copy、無期限 retention；OS 權限未能證明兩個 volume 位於不同實體裝置，因此不得稱為 off-device backup。
- 建議至少兩份不同磁碟的加密備份，另有一份離線或異地副本。
- 備份單位是整個封存根目錄，包含 raw、parse、quality 與 run manifests。
- 每季做一次唯讀 restore drill：還原到新目錄、執行 hash audit、離線 replay，並比對 row／reject／schema hash。
- 2026-08-03 初次 restore drill 已通過：396 files、tree SHA-256 `31f31094…1934a0`；offline replay run `cc2543a5…bd516` 為 55 accepted + 1 released，production unchanged。
- retention 只能由 Data Owner、Infrastructure Owner 與 Compliance 共同批准；刪除工具不屬 M2 預設能力。

## 9. 安全檢查

- request query、header、cookie 與 body 都要套用 secret redaction。
- 只允許清冊中的 scheme、host、path、method 及必要參數。
- parser 不可連網、讀正式 DB 或使用目前時間。
- HTML 的 security rejection／攔截頁要成為 payload reject，不可當成零筆財報。
- manifest 與 log 不保存 token、cookie、密碼或完整 exception message。
- 所有讀取路徑必須在指定 archive root 內，防止 path traversal。

## 10. 事故處理

| 狀況 | 動作 |
|---|---|
| 官方端點 schema 改變 | 保存 raw、隔離、開新 parser 版本、用舊 raw 重播比較 |
| hash 不一致 | 立即停止發布，保留現場，對 blob、manifest、備份做三方比對 |
| 只有 rows 沒有 manifest | 視為半成品；不得手動補 manifest，改用同一 raw 重新跑 |
| 來源持續回傳空資料 | 與交易日曆、官方狀態及其他官方端點交叉確認；不得補前值 |
| 磁碟不足 | 停止 backfill，擴容或建立經批准的備份；不得臨時刪 raw |
| 誤觸正式資料 | 立刻停止、保存 before／after fingerprint、交由 owner 判定回復方式 |

## 11. 交班清單

- 本次 capture／replay run ID 與根目錄。
- 來源數、observation 數、accepted／quarantined／failed 數。
- 所有 blocking issues 與 owner。
- 正式資料前後 fingerprint。
- 測試結果與版本指紋。
- 下一次允許執行的動作；不得把待批准事項寫成已完成。
