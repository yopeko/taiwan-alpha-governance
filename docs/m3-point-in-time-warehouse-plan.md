# M3 Point-in-time Warehouse 計畫

## 1. 文件狀態

| 欄位 | 值 |
|---|---|
| Plan ID | `tw-alpha-m3-plan-v0.3.0` |
| 狀態 | `in_progress` |
| 進場日期 | 2026-08-03 |
| 前置里程碑 | M0、M1、M2 `complete` |
| 本階段輸出 | 獨立、可回復、不可覆寫正式資料的 point-in-time shadow warehouse |
| 目前工作包 | M3.2 待啟動，但已量化證實缺乏輸入資料 |
| 最後更新 | 2026-08-16 |

M3 的目的不是先做選股，而是回答一個較基本的問題：在某個歷史決策時間，系統當時真正知道哪些股票、交易日、價格、交易狀態、公司行動及財務資訊。

## 2. 已批准範圍

本次依 Owner 對三項 M2 後續工作的批准，進入 M3。允許：

- 唯讀使用 M2 durable raw-v2 archive、96-session 日價修復 shadow 及 legacy DuckDB 作差異比較；
- 建立新的 M3 shadow warehouse、manifest、coverage certificate、驗證報告及回復產物；
- 將已通過 M2 archive、parser、quality、release gate 的觀測資料正規化；
- 對 `legacy-imported` 資料另立 lane，不把它冒充官方 raw-v2；
- 對未知、來源缺漏及 current-only 狀態明確標示並 fail closed。

本次不允許：

- 覆寫 `C:\project\tw-sepa-screener\data\tw_sepa.duckdb`；
- 修改 `C:\project\tw-sepa-screener\data\raw` 或 `data\stock_master.csv`；
- 把 `C:\tmp\tw-alpha-m2-shadow-20260803-02` 直接宣稱為 durable archive；
- 用今日 master、今日 status 或事後修訂值回填歷史未知狀態；
- 修改策略、AlphaMaster、紙上帳本、券商設定或真實資金流程。

## 3. M3 exit gate 與 G0 決定

Owner 已於 2026-08-03 批准 [`G0-A-fixed-window-certified-dates`](evidence/m3-g0-owner-decision-2026-08-03.md)：

- 固定基準期間為 2025-01-01 至 2026-08-03，首尾皆包含；
- 市場為 TWSE 與 TPEx，商品範圍延續 M0 的普通股；
- 每個 `market + calendar_date` 都必須在 coverage certificate 中有明確狀態；
- 只有 aggregate `reconstruction_state=supported` 的日期受到承諾；未列出、`partial`、`blocked` 或 `unknown` 一律 fail closed；
- M3 complete 前，固定期間內所有官方開市／特殊 session 都必須達到 `supported`，所有休市日都必須有可驗證的 `not-session`，不能以缺價格猜測休市。

「今天」在本決定中凍結為 2026-08-03，不是會自動向未來移動的日期。2026-08-04 以後只能透過新的 append-only certificate 版本逐日擴充。

## 4. 工作包

| 工作包 | 狀態 | 主要工作 | 完成證據 |
|---|---|---|---|
| M3.0 進場凍結 | `complete` | 記錄來源、程式與受保護資料指紋；驗證 M2 archive；確認 shadow 邊界 | [M3 entry baseline](evidence/m3-entry-baseline-2026-08-03.md) |
| M3.1 契約與來源映射 | `complete` | G0 已批准；完成資料表、時間語意、availability、衝突規則與 source-to-table map | [PIT warehouse contract](contracts/pit-warehouse-contract.md)、[G0 決定](evidence/m3-g0-owner-decision-2026-08-03.md)、[source-to-table map 與 policy](contracts/m3-source-to-table-map.md)、[M3.1 完成證據](evidence/m3-1-coverage-ledger-and-durable-archival-2026-08-16.md) |
| M3.1b 歷史抓取程式 | `complete` | 擴充抓取工具支援 TPEx 與任意日期範圍；抓取固定期間 TWSE／TPEx 日價；建立 TEJ licensed-vendor 匯入通道 | [M3.1b 完成證據](evidence/m3-1b-window-capture-2026-08-16.md)：1,160/1,160 零錯誤、耐久封存 tree `a07a4b5b…`、ledger v2 `unknown` 歸零 |
| M3.1c TEJ 匯入 | `pending` | 匯入交易日曆、上市下市歷史、財報申報日 | 待 Owner 提供 TEJ 匯出檔；規格見 [TEJ 匯入規格](contracts/tej-import-spec.md) |
| M3.2 Append-only staging | `pending` | 從通過 gate 的 observation 建立 lineage 完整的 staging；同輸入重建結果一致 | 已有 764 個交易日的日價輸入可用 |
| M3.3 日曆與證券生命週期 | `complete`（有已知限制）| 建立 trading_calendar_pit、security_events、security_intervals 與 security_instance_id | [M3.3 golden-date 測試](../tests/invariant/test_m3_3_golden_dates.py)：日曆 764 開市／396 休市／0 unknown；1,962 個 instance。**已知限制**：TEJ 匯入以 (market, symbol) 去重，代號重用會被合併，已標為 strict xfail |
| M3.4 每日股價與公司行動 | `pending` | 保留 `ohlc_state`、activity scope、公告／觀測時間及修訂；禁止推補 OHLC | price/action PIT tests |
| M3.5 市場狀態與財報 | `pending` | 納入停牌、處置、變更交易及 revision-safe 財報；缺覆蓋保持 unknown | cutoff/revision tests |
| M3.6 As-of reconstruction | `pending` | 唯一查詢入口依 session 與 knowledge cutoff 回傳狀態、理由、lineage、coverage | anti-lookahead tests |
| M3.7 重建與差異驗證 | `pending` | 重建可重現、受保護檔案不變、legacy 差異可解釋、restore 可行 | validation report |
| M3.8 Exit review | `pending` | 檢查 G0 所選門檻、coverage、rollback、Validation Owner 簽核 | M3 exit evidence |

## 5. 來源到 canonical table 的順序

來源到 canonical table 的完整逐來源對應、availability 與 conflict policy 見 [M3.1 Source-to-Table Map](contracts/m3-source-to-table-map.md)。以下為順序摘要。

| 順序 | 資料族群 | M2 可用材料 | M3 主要輸出 | 目前限制 |
|---|---|---|---|---|
| 1 | 來源與 coverage | 56 個 durable observations、quality/release events | `warehouse_runs`、`source_observations`、`coverage_certificates` | 96-session shadow 已於 2026-08-16 耐久封存；固定期間 coverage ledger 已建立，`supported`＝0 |
| 2 | 交易日曆 | 2026 官方休市／特殊日期、觀察到的市場檔 | `trading_calendar_pit` | 尚非完整歷史 session table |
| 3 | 證券生命週期 | current master、上市／下市事件 | `security_events`、`security_intervals` | 缺 listing date；symbol 會重用；ETF 不在 M0 universe |
| 4 | 每日股價 | durable 2026-07-31、96 個 TWSE 修復日、legacy 比較資料 | `daily_prices_pit` | shadow 非連續、TPEx 歷史未補齊、部分官方列無 OHLC |
| 5 | 市場狀態 | 停牌、注意、處置及變更交易來源 | `market_status_pit` | 多數 current-only；來源沒有列出不代表可交易 |
| 6 | 公司行動 | 除權息及相關官方來源 | `corporate_actions_pit` | 部分 `announced_at` 不明；不得提早於首次觀測使用 |
| 7 | 財報 | 月營收、季報、資產負債與現金流 parser outputs | `fundamentals_pit` | 目前主要只有 2026-06／2026Q1，部分樣本缺精確發布時間 |

## 6. 不可省略的時間與狀態規則

- `effective_*` 表示事件何時對市場有效；`first_observed_at` 表示系統何時首次取得；`decision_available_at` 表示何時可用於決策，三者不得混用。
- 除非有已批准且可驗證的保守政策，`decision_available_at` 不得早於 `first_observed_at`。
- 修訂資料追加新版本，不覆寫舊版本；歷史查詢看不到 cutoff 之後才觀測到的修訂。
- 缺上市日、缺狀態覆蓋、缺 OHLC、來源範圍不一致及 `missing-at-source` 都必須保留狀態與理由。
- `unknown`、`blocked`、`official-no-data`、`current-only`、`legacy-imported` 不可合併為空值或默認可交易。
- TWSE 與 TPEx 同 symbol、同 symbol 的不同生命週期，必須透過 `security_instance_id` 區分。

## 7. 唯一歷史重建介面

M3 的查詢語意固定為：

```text
reconstruct(as_of_session, decision_as_of, markets, security_types, dataset_id)
```

每個證券至少回傳：

- `membership_state`；
- `session_state`；
- `market_status_state`；
- `price_state`；
- `tradability_state`；
- `reason_codes`；
- 所有採用記錄的 lineage；
- coverage certificate 及輸出 hash。

任何必需證據不足時，結果只能是 `unknown` 或 `blocked`，不能自行推定為 eligible／tradable。M3 只重建市場資訊狀態；零股、費用、稅、漲跌停與 T+2 等完整交易判斷仍屬 M4。

## 8. 驗證閘門

| Gate | 批准者 | 通過條件 |
|---|---|---|
| G0 支援期間 | Owner | `approved`：2025-01-01 至 2026-08-03，TWSE／TPEx 逐 market-date certificate；只承諾 `supported` |
| G1 schema／來源映射 | Data Owner | 每欄來源、時間、缺值及衝突政策無歧義 |
| G2 staging acceptance | Data Owner + Validation Owner | 僅合格 observation 進 canonical lane；重建 hash 穩定 |
| G3 as-of correctness | Validation Owner | 上市前不出現、下市後排除、未來修訂不可見、未知不變成可交易 |
| G4 publication／cutover | Owner | shadow 對照、restore、rollback 及受保護指紋證據完整 |

## 9. 進度與下一個安全動作

2026-08-16 已完成前三項，證據見 [M3.1 完成證據](evidence/m3-1-coverage-ledger-and-durable-archival-2026-08-16.md)：

1. ~~將 96-session TWSE 修復 shadow 依 M2 契約移入耐久、可稽核位置~~ → **完成**。primary 與 E: backup 逐檔雜湊一致，96/96 blob 重驗通過。
2. ~~完成 source-to-table map、availability/cutoff policy 與 conflict policy~~ → **完成**，見 [M3.1 契約](contracts/m3-source-to-table-map.md)。
3. ~~建立固定期間的 market-date coverage ledger~~ → **完成**。1,160 列；`supported`＝0、`not-session`＝17、`partial`＝3、`unknown`＝1,140。
4. M3.2 append-only staging → **阻擋**。固定期間內只有 3 個 market-date 有耐久 session 級觀測，現在建 staging 只會產生空殼。

### Owner 決定已於 2026-08-16 取得

五項決定全文見 [Owner 決定與抓取可行性](evidence/m3-owner-decisions-and-capture-feasibility-2026-08-16.md)：

| # | 決定 |
|---|---|
| D1 | 批准歷史官方資料抓取程式（限固定期間）|
| D2 | TPEx 與 TWSE 共用證券市場行事曆（`owner-approved-policy`，非國家行事曆）|
| D3 | 接受 377 筆缺上市日；但維持 `membership_state=unknown`，不自動 eligible |
| D4 | 維持固定期間 2025-01-01 至 2026-08-03 |
| D5 | TEJ PRO 納入 licensed-vendor lane（授權允許長期保留快照）|

**已驗證**：TWSE 與 TPEx 的 2025 年歷史日價端點都可供料（2025-01-02 分別為 1,274 與 943 檔）。

**新發現的阻擋**：`holidaySchedule` 端點只回傳當年度，**2025 年官方行事曆已永久無法取得**，改由 TEJ 供應。

### M3.1b 已完成（2026-08-16）

1,160/1,160 market-date 全部取得明確官方結果，零錯誤，18 分鐘完成。764 個交易日、396 個非交易日。Coverage ledger `unknown` 由 1,140 降為 **0**。詳見 [M3.1b 完成證據](evidence/m3-1b-window-capture-2026-08-16.md)。

兩項實證發現：

- **兩市場交易日完全一致**（382 對 382，零分歧），D2 的共用行事曆政策得到實證支持；
- **2026-07-10 兩市場休市但不在官方年度行事曆中**，證實禁止推算交易日曆的規定是必要的。

### `supported` 仍為 0 的精確原因

| 阻擋資料族 | 影響 market-date | 解法 |
|---|---:|---|
| `market_status=current-only` | 764 | **無任何已批准來源** ⛔ |
| `security_lifecycle=current-only` | 764 | TEJ 上市下市歷史（已批准，待匯入）|
| `fundamental=partial` | 764 | TEJ 財報申報日（已批准，待匯入）|
| `corporate_action=unknown` | 763 | 官方除權息歷史逐日抓取 |

### 待辦

1. **需 Owner 決定**：歷史市場狀態（停牌／處置／注意／變更交易）從哪裡取得。現有 9 個來源全為 current-only，TEJ 已確認的模組不含此項。這是 M3 exit 的首要阻擋項。
2. M3.1c：取得 TEJ 匯出檔後匯入三個模組。
3. 擴充抓取工具涵蓋官方除權息歷史。
4. 建立年度行事曆例行擷取，避免 2027 年重蹈 2025 年覆轍。

M3.2 啟動後仍不得使用舊 `ScreenerStore` 的 replace／overwrite 路徑。抓到資料**不等於**該日期成為 `supported`，仍須通過完整資料族 coverage 檢查。

