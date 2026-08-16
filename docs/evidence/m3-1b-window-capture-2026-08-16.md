# M3.1b 完成證據：固定期間全量抓取與 Coverage Ledger v2（2026-08-16）

## 結論

M3.1b 工作包 `complete`。依 Owner 決定 D1 抓取 2025-01-01 至 2026-08-03 的 TWSE 與 TPEx 官方日價，1,160/1,160 個 market-date 全部取得明確結果，零錯誤。

**Coverage ledger 的 `unknown` 由 1,140 降為 0。** 固定期間內每一個 market-date 現在都有官方證據支撐其狀態。

`supported` 仍為 0，但阻擋原因已由「沒有資料」轉為「四個特定資料族缺覆蓋」，且其中三個有明確解法。

抓取與封存期間未修改 `tw_sepa.duckdb`、legacy raw、`stock_master.csv`、M2 封存、策略或交易設定。

---

## 1. 抓取執行

| 欄位 | 值 |
|---|---|
| Schema ID | `tw-alpha-m3-window-capture/1.0.0` |
| 期間 | 2025-01-01 至 2026-08-03（580 calendar dates）|
| 市場 | TWSE、TPEx |
| 請求總數 | **1,160** |
| 開始 | 2026-08-16T12:54:53Z |
| 完成 | 2026-08-16T13:12:43Z（約 18 分鐘）|
| 請求間隔 | 0.7 秒 |
| `production_unchanged` | `true` |

### 結果分布

| Outcome | 數量 | 意義 |
|---|---:|---|
| `captured` | **764** | 官方回傳全市場收盤表，該日確為交易 session |
| `official-no-data` | 198 | TWSE 明確回覆「很抱歉，沒有符合條件的資料!」|
| `official-zero-rows` | 198 | TPEx 回傳 `stat=ok` 但零列 |
| transport / parse error | **0** | — |

1,160 個 observation 全部入庫（`capture_status=hash-verified`）。TWSE 共 503,884 個價格列、TPEx 373,486 列。

---

## 2. 決定性發現一：兩市場交易日完全一致

| 指標 | TWSE | TPEx |
|---|---:|---:|
| 交易日 | **382** | **382** |
| 非交易日 | 198 | 198 |
| 僅單一市場交易的日期 | 0 | 0 |

`calendars_identical = true`。580 天內兩個市場的開市日**零分歧**。

**意義**：Owner 決定 D2 的「TPEx 與 TWSE 共用證券市場行事曆」原本標記為 `owner-approved-policy`（推定），現在得到 1,160 筆來自兩個獨立官方端點的實證支持。政策標記維持不變（實證不等於官方公告），但可信度大幅提升。

非交易日組成：週末 166 天、平日休市 32 天。期間內**沒有**補行交易的週末 session。

---

## 3. 決定性發現二：官方年度行事曆會漏掉臨時休市

以已擷取的官方 2026 行事曆（17 個落在期間內的休市日）與實際抓取結果交叉比對：

| 比對項目 | 結果 |
|---|---|
| 官方列為休市、實測亦休市 | 17／17 |
| 官方列為休市、實測卻開市 | **0** |
| 官方未列、實測卻休市（平日）| **1：2026-07-10（週五）** |

**2026-07-10 兩個市場都休市，但這天不在官方年度行事曆中**，性質上屬臨時休市（颱風假等）。

**意義**：若依 Owner 原始指示「比照國家行事曆，週六日及國定假日休市」推算，會把 2026-07-10 誤判為交易日，PIT 倉庫將宣稱一個從未存在的 session。這證實 [M3.1 契約 §1.2.1](../contracts/m3-source-to-table-map.md) 禁止推算交易日曆、要求逐日實證的規定是必要的，不是形式主義。

---

## 4. 耐久封存

| Copy | 路徑 | Files | Bytes |
|---|---|---:|---:|
| 暫存來源 | `C:\tmp\tw-alpha-m3-capture-20260816-01` | 2,125 | 146,741,197 |
| Primary | `C:\project\tw-sepa-screener\data\raw_v2\m3_window_2025-01-01_2026-08-03` | 2,125 | 146,741,197 |
| Backup | `E:\tw-sepa-screener-backup\raw_v2\m3_window_2025-01-01_2026-08-03` | 2,125 | 146,741,197 |

Tree SHA-256（三份相同）：`a07a4b5b1775398bfbf6b32bdeaaa4dc13d1c35f7cdd8fa66ba4b680a38dbc43`

三份副本各自獨立重算全部 **1,160 個 blob** 的 SHA-256，與 `blob_id` 及 `payload_sha256` 三方比對：`hash_mismatches=0`、`missing_blobs=0`、逐檔與來源完全一致。

Archival record ID：`tw-alpha-m3-window-archival-20260816-01`，retention 無期限、`automatic_deletion=disabled`。

**限制**：C: 與 E: 為不同磁碟機代號，但受 OS 權限限制仍無法證明位於不同實體裝置，因此不宣稱為異地備份。

---

## 5. Coverage Ledger v2

| 欄位 | 值 |
|---|---|
| Certificate ID | `tw-alpha-m3-coverage-ledger-20260816-02` |
| Supersedes | `tw-alpha-m3-coverage-ledger-20260816-01` |
| 列數 | 1,160 |
| Ledger SHA-256 | `97f7d3cd28af6d7515ee6a805831d8939f52a4af3fff43420cc295fcbbf50b1f` |

### 前後對照

| State | v1（抓取前）| v2（抓取後）| 變化 |
|---|---:|---:|---|
| `supported` | 0 | 0 | — |
| `not-session` | 17 | **396** | +379 |
| `partial` | 3 | **764** | +761 |
| `unknown` | 1,140 | **0** | **−1,140** |

**最重要的變化是 `unknown` 歸零。** 先前 98.28% 的 market-date 沒有任何證據；現在每一個都有官方觀測支撐。

### session_state 判定依據

- `official-open`：官方回傳該日全市場收盤表。收盤表存在本身即為 session 發生的直接證據，強度高於行事曆推論。
- `official-closed`：官方端點明確回覆無資料。若該日在官方行事曆中，reason code 為 `official-holiday-schedule-listed`；若不在（如 2026-07-10），則為 `closure-corroborated-by-both-markets-absence`，兩者都記錄在 ledger 中可追溯。

---

## 6. `supported` 仍為 0 的精確原因

764 個 `partial`（即全部交易日）各自缺以下資料族：

| 阻擋資料族 | 影響 market-date | 解法 | 狀態 |
|---|---:|---|---|
| `market_status=current-only` | 764 | **無任何已批准來源** | ⛔ 最大缺口 |
| `security_lifecycle=current-only` | 764 | TEJ 上市下市歷史 | ✅ 已批准，待匯入 |
| `fundamental=partial` | 764 | TEJ 財報申報日 | ✅ 已批准，待匯入 |
| `corporate_action=unknown` | 763 | 官方除權息歷史逐日抓取 | 🔧 可用既有工具擴充 |

四項中三項有明確解法。**`market_status`（停牌、處置、注意、變更交易）是目前唯一沒有來源的資料族**，且 TEJ 模組清單未涵蓋。這是 M3 exit 的新首要阻擋項。

---

## 7. 需要 Owner 決定的新事項

**歷史市場狀態（停牌／處置／注意／變更交易）從哪裡取得？**

現有 9 個市場狀態來源全部是 current-only 快照，無法描述任何歷史日期。可能方向：

1. 確認 TEJ 是否有交易狀態歷史模組（Owner 先前確認的兩個模組不含此項）；
2. 尋找官方是否提供歷史處置／注意股查詢；
3. 或由 Owner 明確接受「歷史市場狀態不可得」，並據此調整 `supported` 的定義——但這會降低 PIT 重建的保證強度，必須是明示的新 G0 版本，不得由執行方自行放寬。

在此決定之前，即使 TEJ 匯入完成，`supported` 仍會是 0。

---

## 8. 本輪未做也未獲授權的事

- 未覆寫正式 DuckDB、legacy raw、stock master（抓取前後指紋相同）；
- 未匯入任何 TEJ 資料（尚未取得匯出檔）；
- 未建立 M3.2 append-only staging；
- 未修改策略、AlphaMaster、紙上帳本或券商設定；
- 未將 M3 標為 `complete`。
