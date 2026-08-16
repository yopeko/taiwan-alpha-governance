# M2 官方資料來源清冊

## 1. 文件控制

| 欄位 | 值 |
|---|---|
| 版本 | `m2-source-inventory-v0.6.0` |
| 狀態 | `complete` |
| 盤點日 | 2026-08-03 |
| 台股核心 | `C:\project\tw-sepa-screener` |
| 適用契約 | [Official Raw Snapshot Contract](contracts/raw-snapshot-contract.md) |

本清冊同時記錄「官方來源是否存在」、「本地 adapter 是否存在」及「是否已有合格 raw v2」。三者不可混為一談。2026-08-03 已建立 36 個 endpoint-level P0 source、36 個一對一 parser，並完成 56 個 live observations 的 raw capture、replay 與 quality。不可變初始決定為 55 accepted、1 quarantined；`TWSE-ACTIONS-HIST` 已依 Owner 決定由唯一 release event 解除 gate，0 unresolved。完整封存已發布到 durable root、建立 E: 分離 volume 備份並通過 restore audit。

## 2. 優先等級

| 等級 | 定義 | M2 退出要求 |
|---|---|---|
| P0 | 建立 PIT 股票池、日線、財務、公司行動所必需 | 全部必須有 raw v2、parser lineage、品質與重解析證據 |
| P1 | 提升研究或事件稽核，但不進 v1 正式研究封包 | 可延後；若被下游使用則必須先符合 raw v2 |
| P2 | 紙上營運、prototype 或未來資料 | 不阻擋 M2；固定 research-only／quarantine |
| X | 非官方、商業授權或與 M2 無關 | 不得混入官方 namespace |

## 3. P0 清冊（M2 entry family-level baseline）

本節保留 M2 entry 時的 family-level adapter／保存缺口，不回寫成事後狀態。2026-08-03 endpoint-level 完成結果以第 8 節為準。

| Source ID | Publisher／資料族 | 端點或傳輸 | M2 entry adapter | M2 entry 保存 | 當時缺口與 M2 動作 |
|---|---|---|---|---|---|
| `TWSE-CALENDAR` | TWSE 開休市 | `GET openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule` | `sources/calendar.py` | `pilot-verified`：2026-08-02 isolated live raw-v2；production 尚未切換 | 已證明 capture-before-parse；仍須區分週末、官方休市、臨時休市及抓取失敗並建立 durable schedule |
| `TWSE-MASTER` | 上市公司基本資料 | `GET .../opendata/t187ap03_L` | `stock_master.py` | `pilot-verified`：完整 live payload 1,093 rows；production 仍只寫 current CSV／DuckDB | 已保留完整 pilot payload；仍須每日 observation 與 listing-status lineage，不能只保留 4 碼普通股過濾結果 |
| `TPEX-MASTER` | 上櫃公司基本資料 | `GET .../openapi/v1/mopsfin_t187ap03_O` | `stock_master.py` | `pilot-verified`：完整 live payload 890 rows；production 仍只寫 current CSV／DuckDB | 已保留完整 pilot payload；仍須補歷史下櫃／轉板 evidence，不能以今天 master 回填歷史 |
| `TWSE-PRICE-HIST` | 上市全市場日收盤 | `GET www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX` | `sources/twse.py` | `shadow-verified`；legacy `market_twse_<date>.parquet` 為 normalized | 96-session shadow 已 96/96 accepted；與 index 共 URL 已用 request `type` 做 parameter-aware binding；production cutover 待 owner 批准 |
| `TWSE-PRICE-LATEST` | 上市最新全市場成交 | `GET openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL` | `sources/twse.py` | `pilot-captured-quality-blocked`；legacy 併入 `market_daily` | `0.0000` 可是無一般盤 OHLC sentinel；latest expected date 仍是 caller assumption，需 calendar policy |
| `TPEX-PRICE-HIST` | 上櫃全市場歷史日收盤 | `GET .../stk_wn1430_result.php` | `sources/tpex.py` | `pilot-captured-scope-blocked`；legacy `market_tpex_<date>.parquet` | 保存 raw 與 ROC request；activity scope 不得與 latest OpenAPI 靜默互換 |
| `TPEX-PRICE-LATEST` | 上櫃最新日收盤 | `GET .../openapi/v1/tpex_mainboard_daily_close_quotes` | `sources/tpex.py` | `pilot-captured-scope-blocked`；legacy 併入 `market_daily` | 2026-07-31 與 historical 同 OHLC，但 851／888 rows 的 activity 不同；需分欄／分表與 source lineage |
| `TWSE-INDEX` | TAIEX／大盤統計 | `GET .../afterTrading/MI_INDEX` | `sources/market_indices.py` | normalized `market_indices_<date>.parquet` | 與個股 MI_INDEX 可共用 endpoint/blob，但 `type` 參數及 parser run 必須分離；目前 pilot registry 不可直接升 production |
| `TPEX-INDEX` | TPEx 指數 | `GET .../openapi/v1/tpex_index` | `sources/market_indices.py` | normalized `market_indices_<date>.parquet` | 保存完整 response；明示選取哪一 index_id 作 benchmark |
| `TWSE-REVENUE-LATEST` | 上市月營收 | `GET .../opendata/t187ap05_L` | `sources/mops.py` | normalized Parquet | 保存 latest snapshot 原始 bytes；`first_observed_at` 與官方 period 分離 |
| `TPEX-REVENUE-LATEST` | 上櫃月營收 | `GET .../openapi/v1/mopsfin_t187ap05_O` | `sources/mops.py` | normalized Parquet | 同上；逐端點 live schema 驗證仍 pending |
| `MOPS-REVENUE-HIST` | 歷史月營收 | `GET mopsc.twse.com.tw/nas/t21/{sii|otc}/...html` | `sources/mops_history.py` | normalized `mops_revenue_history_*` | 保存 HTML bytes 與 apparent/declared encoding；保守 available_at 不能冒充精確發布時間 |
| `TWSE-INCOME-LATEST` | 上市季度綜合損益 | `GET .../opendata/t187ap06_L_{category}` | `sources/financials.py` | normalized `quarterly_income_*` | 每個 category 獨立 observation；保存空 category 與 schema 差異 |
| `TPEX-INCOME-LATEST` | 上櫃季度綜合損益 | `GET .../openapi/v1/mopsfin_t187ap06_O_{category}` | `sources/financials.py` | normalized `quarterly_income_*` | 同上；category allowlist 固定版本 |
| `MOPS-INCOME-HIST` | 歷史季度損益 | `POST mopsc.twse.com.tw/mops/web/ajax_t163sb04` | `sources/mops_history.py` | normalized `mops_quarterly_history_*` | 保存 POST form、HTML bytes、拒絕頁與 charset；不得只留 pandas 表格 |
| `MOPS-BALANCE-CASHFLOW` | 公司資產負債／現金流 | `POST .../ajax_t164sb03`、`ajax_t164sb05` | `sources/financials.py` | canonical DB，未見 raw bytes | 保存逐公司逐期 request／HTML；PIT 發布與首次觀測時間分離 |
| `TWSE-ACTIONS-CURRENT` | 上市除權息預告 | `GET .../exchangeReport/TWT48U_ALL` | `corporate_actions.py` | normalized Parquet | 保存完整 payload；不要只留算出的 adjustment factor |
| `TWSE-ACTIONS-HIST` | 上市除權息歷史 | `GET .../rwd/zh/exRight/TWT49U` | `corporate_actions.py` | normalized `twse_twt49u_history_*` | 保存 range request、官方 status 與原始欄位 |
| `TPEX-ACTIONS` | 上櫃除權息預告／結果 | `GET .../tpex_exright_prepost`、`tpex_exright_daily` | `corporate_actions.py` | normalized Parquet | 兩個端點分開 observation，合併只發生在 parser/canonical 層 |
| `TWSE-TRADING-STATUS` | 暫停／恢復、變更交易、注意／處置 | `TWTAWU`、`TWT85U`、`announcement/punish`、`announcement/notice` | 尚無完整 PIT adapter | 無完整 raw v2 | 用於把 no-trade row 分成 official suspension／其他狀態；未接入前不可從 OHLC 缺值推定停牌 |
| `TPEX-TRADING-STATUS` | 暫停／恢復、變更交易、注意／處置 | `tpex_spendi_today`、`tpex_spendi_history`、`tpex_cmode`、warning／disposal endpoints | 尚無完整 PIT adapter | 2026 live audit only，未進 durable raw v2 | 2026 sample 對上 15 個 zero-activity missing-OHLC rows；需歷史 coverage、available_at 與 parser lineage |
| `MOPS-TPEX-ACTIONS-HIST` | 上櫃歷史公司行動 | `POST mopsov.twse.com.tw/mops/web/...` | `sources/mops_tpex_actions.py` | normalized `mops_tpex_exright_history_*` | 保存 endpoint、form、HTML bytes、symbol-year coverage 與拒絕頁 |
| `TWSE-DELISTING` | 上市終止上市 | `GET .../company/suspendListingCsvAndHtml` | `corporate_actions.py` | 未見專屬 raw bytes | 建立 listing-status evidence；名稱易誤解，parser 必須驗證實際欄位 |
| `TPEX-LISTING-STATUS` | 上櫃開始／下櫃狀態 family | listing-start yearly MS950 CSV；delisted company page | `sources/listing_status.py` | 2020–2026 listing CSV 與 580-row delisting page 已有 raw-v2／parser／quality | 舊 `blocked-source-gap` 已解除；正式 IDs 為 `TPEX-LISTING-START-HIST`、`TPEX-DELISTING-HIST`，M3 仍須遵守各端點實際歷史範圍 |

## 4. P1／P2 與隔離來源

| Source ID | 等級 | 現況 | 規則 |
|---|---:|---|---|
| `MOPS-ANNOUNCEMENTS` | P1 | Browser 進入 MOPS realtime/history API，現有 normalized news Parquet | 保存 API response、入口頁、參數、published_at、detail 及 attachment reference；規則式 catalyst 分數不是官方事實 |
| `TWSE-MIS-PROTOTYPE` | P2 | candidate-only 低頻盤中 snapshot | M0 為收盤後系統；正式 intraday 前需授權與市場資料權利審查 |
| `LICENSED-INTRADAY` | P2 | CSV／REST adapter interface | 另立 vendor contract；不得標成官方 TWSE/TPEx raw |
| `TEJ-IMPORT` | X | 商業匯入、已有 normalized Parquet | 保留授權與 provider lineage；不屬官方 raw M2 exit gate |
| `YAHOO-CONSENSUS-PROTOTYPE` | X | research-only normalized snapshot | 永遠不能靜默補官方資料；不得進 formal score |
| 手工 `news_events.csv` | X | 可追溯研究輸入 | 保留 URL、時間、標題、摘要、歸因；v1 research dataset 不含新聞 |

## 5. 現有保存能力判定

### 可保留

- HTTP retry session、timeout 與 `raise_for_status` 基礎。
- Daily pipeline 的日期一致性、完整市場 coverage 與 fail-closed。
- `atomic_output_path`：可確保讀者不會看到半寫入檔案。
- `available_at` 最早觀測日保留邏輯。
- 正規化 Parquet、DuckDB 及既有 parser tests，作為 migration 回歸 oracle。

### 必須改良

- `write_raw_snapshot` 目前接收 DataFrame，而不是 response bytes。
- 檔名只含 source 與日期／期間；相同路徑會由 `os.replace` 完整覆寫。
- 沒有 raw manifest、HTTP metadata、payload hash、snapshot ID、parser ID 或 dependency fingerprint。
- stock master、calendar 與部分公司狀態沒有 raw snapshot。
- parser error 往往只進 run log，原始 error payload 未必保存。
- 4,988 個 legacy raw-tree 檔案全部是 normalized Parquet，不能回溯升格成 raw v2。

## 6. Source owner 與 review cadence

| 責任 | Owner | Review |
|---|---|---|
| endpoint、使用條款、live schema | Data Owner | 每季、官方變更或連續失敗時 |
| raw contract、hash、retention | Data Owner + Infrastructure Owner | 每次 major schema 變更 |
| parser 與 quality rule | Data Owner | 每次 parser release |
| PIT 可得時間 | Validation Owner | M3 前逐資料族批准 |
| research/formal evidence lane | Validation Owner | 每次資料集發布 |
| 來源授權與個資 | Compliance／Project Owner | 新來源導入前 |

## 7. 進入 M2 後的固定順序

1. `TWSE-CALENDAR`、兩市場 master 與四個日行情端點。
2. 兩市場 index、月營收與最新季度財報。
3. 歷史 MOPS、資產負債／現金流及公司行動。
4. listing-status 缺口、完整 backfill 與重解析演練。
5. P1 公告；P2／X 不得搶先影響 M2 exit gate。

任何來源在 raw v2 未通過前，可繼續維持 legacy pipeline 運作，但新舊 evidence 必須明示，不能把 legacy normalized file 命名或呈現為已符合不可變 raw 契約。

## 8. 2026-08-03 endpoint-level 實作結果

本節是目前機器 registry 的權威粒度；若與第 3 節較早的 family-level 名稱衝突，以本節為準。

| 資料族 | Endpoint-level Source IDs | Parser 數 | Live 結果 |
|---|---|---:|---|
| 日曆、master、日行情 | `TWSE-CALENDAR`、`TWSE-MASTER`、`TPEX-MASTER`、`TWSE-PRICE-HIST`、`TWSE-PRICE-LATEST`、`TPEX-PRICE-HIST`、`TPEX-PRICE-LATEST` | 7 | 7/7 captured、parsed、accepted；另完成 96-session TWSE 缺口 shadow |
| 指數、latest 月營收／損益 | `TWSE-INDEX`、`TPEX-INDEX`、`TWSE-REVENUE-LATEST`、`TPEX-REVENUE-LATEST`、`TWSE-INCOME-LATEST`、`TPEX-INCOME-LATEST` | 6 | 12 類損益 observation 中，10 個官方 placeholder 記為 `official_no_data`；其餘正常接受 |
| 歷史 MOPS 文件 | `MOPS-REVENUE-HIST`、`MOPS-INCOME-HIST`、`MOPS-BALANCE-HIST`、`MOPS-CASHFLOW-HIST`、`MOPS-TPEX-ACTIONS-LIST`、`MOPS-TPEX-ACTIONS-DETAIL` | 6 | UTF-8／CP950、security rejection、表格跨列與 input accounting 均有測試；live 全接受 |
| Listing／delisting | `TWSE-LISTING-START-HIST`、`TWSE-DELISTING`、`TPEX-LISTING-START-HIST`、`TPEX-DELISTING-HIST` | 4 | TPEx source gap 已解決；2020–2026 listing CSV 與完整 delisting page 已擷取。TWSE 790 列中 377 列官方缺日期，保留 null + `missing-at-source`，不補值 |
| 交易狀態 | `TWSE-TRADING-SUSPENSION`、`TWSE-TRADING-ALTERED-TRADING`、`TWSE-TRADING-NOTICE`、`TWSE-TRADING-PUNISH`、`TPEX-TRADING-SUSPENSION-TODAY`、`TPEX-TRADING-SUSPENSION-HISTORY`、`TPEX-TRADING-ALTERED-TRADING`、`TPEX-TRADING-WARNING`、`TPEX-TRADING-DISPOSAL` | 9 | 9/9 live capture／parse／quality 接受；current feed 不冒充完整歷史 coverage |
| 公司行動 | `TWSE-ACTIONS-CURRENT`、`TWSE-ACTIONS-HIST`、`TPEX-ACTIONS-PREPOST`、`TPEX-ACTIONS-DAILY` | 4 | current／TPEx 初始接受；`TWSE-ACTIONS-HIST` 初始 quarantined，之後由 `M2-OWNER-APPROVAL-20260803-01` 與唯一 release event `3cf98161…6866a` 解除，原決定不改寫 |

合計 36 個 source definitions、36 個 parser definitions，一對一 endpoint binding。2026-08-03 第二次乾淨演練保存 56 個 hash-verified observations，56/56 parsed；初始決定 55 accepted、1 quarantined，後者已有 1 個有效 release，0 unresolved。沒有 missing source、orphan blob、missing parse、missing quality 或半成品；主封存、備份及 restore drill 均通過 archive audit。

## 9. M3 繼承的邊界

1. `TWSE-ACTIONS-HIST`：Compliance／Project Owner 已批准專案內部保存及 M3 研究／驗證範圍；外部 TWSE 條款仍然有效，不推論可公開再散布或轉售。
2. durable raw-v2 archive：主封存為 `C:\project\tw-sepa-screener\data\raw_v2\m2_2026-08-03`，分離備份為 `E:\tw-sepa-screener-backup\raw_v2\m2_2026-08-03`；無期限保留且自動刪除停用。
3. Validation Owner：已簽核 M2 evidence 與 M3 唯讀／shadow migration 範圍；尚未批准 M3 覆寫正式 DuckDB、legacy raw 或 stock master。
4. 交易狀態歷史：目前清冊精確描述 publisher 可提供的 current／history scope；M3 不得把 current snapshot 回填成過去狀態。

三項 M2 exit gate 均已閉環，因此 M2 milestone 為 `complete`。以上 M3 限制是下一里程碑的資料語意與 cutover 邊界，不是用 caveat 掩蓋 M2 缺口。
