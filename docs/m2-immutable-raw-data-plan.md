# M2 不可變官方 Raw Data 實施藍圖

## 1. 文件控制

| 欄位 | 值 |
|---|---|
| 版本 | `m2-plan-v0.6.0` |
| 狀態 | `complete` |
| 開始日 | 2026-08-02 |
| 完成日 | 2026-08-03 |
| 完成結果 | 三項 Owner 決定、唯一 release event、durable archive、E: 分離 volume 備份與 restore audit 均已閉環 |
| Taiwan Core | `C:\project\tw-sepa-screener` |
| 上游研究層 | AlphaMaster，M2 無寫入權或執行權 |

## 2. M2 結果定義

M2 完成時，每一筆供 M3 或研究資料集使用的 P0 官方資料，都必須能回答：

1. 從哪個 publisher、端點、request 及時間取得？
2. 應用程式在解析前實際看到哪些 bytes？
3. 內容 hash、bytes、HTTP 狀態及 schema 是什麼？
4. 哪個 parser、程式指紋、依賴與設定產生 canonical rows？
5. 哪些 rows 被接受、拒絕、隔離，理由是什麼？
6. 若 parser 改版，能否不重新下載、也不覆寫舊結果而重解析？
7. 若官方修訂同一期間，是否同時保留舊版、新版及 supersession lineage？

只保存 normalized Parquet、只保存 source 字串或只能從當前 DB 反推，均不算完成。

## 3. Entry baseline 與核心發現

Entry evidence 見 [tw-sepa baseline](evidence/tw-sepa-baseline-2026-08-02.md)：

- HEAD `fb87f62…` 加 29 個 modified、116 個 git-visible untracked；
- tracked diff 為 5,812 insertions／362 deletions；
- legacy raw tree 4,988 檔、188,391,038 bytes；
- top-level 4,896 Parquet 全部可讀，共 17 種 Arrow schema；
- DuckDB 425,209,856 bytes、45 tables、910 columns；
- 資料相關 baseline tests 為 40 passed。

現有設計值得保留 atomic publication、來源 adapters、retry、日期／coverage fail-closed、PIT `available_at`、正規化 Parquet 與 regression tests。主要差距是現行 raw helper 實際保存 DataFrame 且同名覆寫，無法支持 byte-level provenance 或重解析。

## 4. Target data flow

```text
official endpoint
      |
      v
request policy + retry + rate limit
      |
      v
capture application-visible response bytes
      |
      +--> content-addressed immutable blob
      |
      +--> append-only observation manifest
                    |
                    v
             hash verification
                    |
                    v
        versioned parser + reject ledger
                    |
                    v
          quality/quarantine decision
                    |
                    v
       canonical PIT warehouse in M3
```

Legacy pipeline 在 migration 期間可並行讀取 normalized v1，但 raw v2 與 legacy evidence state 必須分開。禁止用轉存 DataFrame 的方式假裝已取得原始 response。

## 5. Work packages

### M2.0 Entry freeze — `complete`

產物：

- Git／dirty worktree fingerprint；
- Python、DuckDB、pandas、pyarrow、pytest 版本；
- DB file、schema 與 migration inventory；
- legacy raw tree content／schema fingerprint；
- 40-test read-only regression baseline。

此步驟沒有建立備份，也沒有授權整理工作樹。

### M2.1 Contract and source control — `complete`

產物：

- [raw snapshot contract](contracts/raw-snapshot-contract.md)；
- [official source inventory](m2-source-inventory.md)；
- P0/P1/P2/X 分級、owner、review cadence；
- raw／observation／parse 三層 ID 與 evidence state。

本節在 entry 時先以 `complete-for-design` 開始；後續 M2.2–M2.6 已依固定契約實作及驗收，因此完成態提升為 `complete`。

### M2.2 Capture foundation — `complete`

在 Taiwan Core 建立共用 capture envelope，不替換通用 `atomic_write_parquet`：

- response bytes capture；
- content-addressed blob write-once；
- append-only observation manifest；
- request secret redaction；
- hash verify；
- HTTP／transport failure evidence；
- source registry allowlist；
- idempotency 與 supersession。

優先以 fake HTTP response 和 temporary storage 測試，不碰現有 `data/raw` 或 production DuckDB。

完成證據見 [M2.2 capture foundation evidence](evidence/m2-2-capture-foundation-2026-08-02.md)。實作只新增 `raw_capture.py` 及其 14 項測試；完整專案為 362 passed，production raw tree 與 DuckDB hash 均未改變。

### M2.3 P0 adapter migration — `complete`

依序迁移：

1. calendar、TWSE／TPEx master；
2. TWSE／TPEx historical 及 latest daily prices；
3. market indices；
4. monthly revenue 與 latest quarterly statements；
5. historical MOPS、balance/cashflow；
6. corporate actions 與 listing-status evidence。

每個 adapter 先 capture，再 parse；不能在 `response.json()` 或 `response.text` 之後才建立 raw。

2026-08-02：第 1 項已用外部 temporary root 完成 fake-response、failure fixture 與三端點 live smoke。

2026-08-03：第 2 項建立四來源 temporary-only capture runner、prepared-request evidence、日期／OHLC／同日來源比較與 failure tests。Legacy audit 把 repair scope 從 94 修正為 96 sessions，96/96 已完成 raw、parse、quality shadow，production DB／legacy raw／stock master 前後 hash 相同。

其後完成其餘 P0 adapters。機器 registry 現有 36 個 endpoint-level sources；live 全來源演練保存 56 個 observations，36/36 source 均有 hash-verified raw。驗證封存已發布到核准的 durable root 並建立 E: 分離 volume 備份；正式 DuckDB、legacy raw 與 stock master 仍未切換，該 cutover 屬 M3 的另行驗證範圍。

### M2.4 Parser registry and replay — `complete`

- 每個 endpoint 有 stable `parser_id` 與 code/config/dependency fingerprint。
- raw blob 可選 parser 重跑；舊 parse output 不覆寫。
- 解析失敗 rows 進 reject ledger，不因 exception 消失。
- output schema 及 file hash 進 parse manifest。
- 36 個 source 各有唯一 parser binding；缺漏、重複或 endpoint mismatch 會 fail closed。
- 全來源 56/56 observations 離線 parsed；再次重播前後 parse／quality tree hash 均為 `ddc7d16b60b01fcf6110fa63f7c175f72bb09c0eea929f87375b59e3106c85a1`。

### M2.5 Quality and operations — `complete`

- source-specific schema／coverage／date／range checks；
- freshness、no-data、holiday、partial、stale 與 publisher failure 分離；
- daily capture completeness report；
- hash audit、orphan blob／manifest audit、missing parse audit；
- quarantine queue 與人工 release reason；
- disk capacity、retention proposal與備份策略；M2 預設不自動刪除。
- 完成 [M2 操作手冊](m2-operations-runbook.md)，包含重試、續跑、隔離、人工 release、備份、restore、磁碟與事故處理。
- 第二次乾淨演練的不可變初始決定為 55 accepted、1 quarantined；`TWSE-ACTIONS-HIST` 已由唯一 append-only release event 解除使用 gate，0 unresolved quarantine。原決定未改寫。

### M2.6 Backfill and exit verification — `complete`

- 先選每個 P0 source 至少一個正常、一個 empty/no-data、一個 schema/reject fixture。
- 在隔離路徑做 pilot capture；不寫現有 production raw／DB。
- 完成兩次 idempotent replay、一次 parser upgrade replay、一次 deliberate tamper test。
- 對近期連續交易日跑 P0 coverage；歷史不可重取資料維持 legacy evidence。
- 96-session daily-price shadow、全 P0 live capture、兩次離線 replay、parser 修正版 replay、防竄改與 security tests 均完成。
- 技術 exit snapshot 為完整測試 `477 passed`、M2 專屬與相鄰資料測試 `154 passed`、tamper／secret／path tests `7 passed`；加入 release-aware audit／replay 後最終完整專案為 `483 passed`。
- blocked 時點的詳細結果保留在 [M2 exit verification](evidence/m2-6-exit-verification-2026-08-03.md)；其後三項人工決定、release、durable archive、backup 與 restore 閉環見 [M2 closure evidence](evidence/m2-owner-approvals-release-and-durable-audit-2026-08-03.md)。

## 6. 驗收矩陣

| ID | 驗收情境 | 預期 | 目前狀態 |
|---|---|---|---|
| M2-A01 | 第一次正常擷取 | raw bytes、manifest、hash、source、時間齊全 | `passed-m2.2` |
| M2-A02 | 完全相同 observation 重跑 | 回傳同 ID，不改寫、不重複 | `passed-m2.2`，含 concurrent capture |
| M2-A03 | 同期間官方修訂 | 新 snapshot，舊 snapshot 保留並建立 supersedes | `passed-m2.2` |
| M2-A04 | payload 任一 byte 被改動 | hash audit fail closed | `passed-m2.2` |
| M2-A05 | HTTP 403／429／500 | 保存允許的 error body／headers／retry；不進 canonical | `passed-pilot`；429 經 captured session 後由既有 adapter raise |
| M2-A06 | timeout／DNS／連線中斷 | transport failure 有 request evidence；不捏造 blob | `passed-pilot`；ConnectTimeout 留 manifest 並 re-raise |
| M2-A07 | JSON 變 HTML／欄位漂移 | raw 保留、parse rejected、alert | `passed`；payload reject 與 quality quarantine 均可追溯 |
| M2-A08 | 同 raw 由 parser v1/v2 解析 | 兩個 parse run 並存，可比較 | `passed`；parser／dependency 變更產生不同 run，舊結果保留 |
| M2-A09 | request 含 token／cookie | manifest 與 log 無秘密 | `passed`；secret redaction、query 移除與 path containment 已測 |
| M2-A10 | 市場日期 stale／不一致 | quarantine，不得 fallback 為最近日期 | `passed`；wrong historical、stale latest 與 frozen expected session fail closed |
| M2-A11 | 全市場 coverage 異常 | fail closed 且保存 raw | `passed`；minimum rows、duplicate、zero-row、OHLC state 與 activity 非負檢查 |
| M2-A12 | empty holiday response | 與 transport／publisher failure明確區分 | `passed`；known-session empty 阻擋，官方明確 no-data 另記 exclusion |
| M2-A13 | 解析有 reject rows | reject 檔、原因、row fingerprint 可追溯 | `passed`；blocking reject 隔離，scope exclusion 保留但不冒充錯誤 |
| M2-A14 | legacy v1 檔案 | 標 `legacy-normalized-snapshot`，不偽升級 | `documented` |
| M2-A15 | P0 source 完整性 | 每個 P0 有正常 capture、reparse 與 quality evidence | 55 initial accepted + 1 released quarantine；0 unresolved；archive audit passed |
| M2-A16 | listing-status 歷史 | TWSE／TPEx listing、delisting／轉板來源可支持 M3 | TPEx source gap 已補；TWSE 377 筆缺日期保留為 missing-at-source，M3 不得猜值 |

## 7. Definition of Done

只有以下條件全部成立，里程碑才可改成 `complete`：

- [x] P0 source inventory 無未處置的 endpoint／license／schema owner；`TWSE-ACTIONS-HIST` 以 Owner 決定及唯一 release event 閉環。
- [x] 所有新 P0 observation 符合 raw contract，hash audit 100% 通過。
- [x] 原始 bytes、request、時間、來源、response metadata 與 parser lineage 可追溯。
- [x] 同 logical period 不覆寫；修訂與重抓可區分。
- [x] 每個 P0 parser 可離線重解析，且舊 parse run 保留。
- [x] schema drift、partial data、stale、holiday、transport failure 均 fail closed。
- [x] legacy 4,988 files 有明確 evidence state，未被偽裝成 raw v2。
- [x] 新舊 pipeline 對照結果經 Validation Owner 審核；96-session shadow 與 production non-mutation evidence 已簽核。
- [x] 測試、hash、coverage、security review 與 operator runbook 附在 evidence bundle。
- [x] `TPEX-LISTING-STATUS` 缺口已補齊，且 TWSE 缺日期範圍被明確保留／阻擋而非靜默放行。
- [x] durable raw-v2 位置、E: 分離 volume 備份、owner 與無期限 retention 經 Infrastructure Owner 批准，逐檔 hash、雙份 audit 與 restore drill 通過；實體裝置是否分離未經 OS 證實。

## 8. M2 不授權事項

- 不修改 `research-sandbox`、`challenger` 或 `formal` 策略。
- 不執行 AlphaMaster training、factor promotion 或候選匯入。
- 不修改 NT$10,000 風險、股數或成本設定。
- 不使用 Yahoo、opaque sentiment 或商業來源靜默補官方缺值。
- 不整理、reset、commit 或刪除 `tw-sepa-screener` 的使用者 dirty worktree。
- 不連接券商、不下單、不啟用真實資金。

## 9. 下一個安全動作

M2 已完成。下一個安全動作是依 [Owner 決定](evidence/m2-owner-approval-decision-2026-08-03.md) 進入 M3：只讀取 durable M2 archive，建立 point-in-time／normalized shadow warehouse，並產生新舊對照、回復及 owner evidence。M3 在另行批准前不得覆寫正式 DuckDB、legacy raw 或 stock master。
