# M2.3 每日股價隔離 Pilot 與缺口調查證據

## 1. 結論

TWSE／TPEx historical 與 latest 每日股價已接上 capture-first 隔離 pilot，但尚未獲准寫回 production DuckDB 或 legacy Parquet。四個官方回應會先保存 bytes、manifest 與 hash，之後才做日期、key、OHLC 與成交活動檢查；output 僅允許 temporary root。

本輪同時證明兩件事：

1. 「上市少 94 個日期」是舊回補不完整，不是 94 個官方休市日；真正 full-market 修復範圍為 96 日。
2. 缺少 OHLC 大多是來源報告的「無一般盤價格」，不能 forward-fill；另發現 TPEx historical／latest 成交活動口徑不同，現行 last-write-wins 會污染成交量時間序列。

因此每日股價的 raw capture pilot 已建立。後續同日已完成 96-session temporary shadow；canonical production merge 仍需 durable archive／Validation Owner 批准。M2.3 技術工作完成，M2 目前是外部簽核 `blocked`。

## 2. 實作範圍

Taiwan Core `C:\project\tw-sepa-screener` 的本輪檔案：

| 檔案 | SHA-256 | 用途 |
|---|---|---|
| `src/tw_sepa_screener/m2_daily_price_pilot.py` | `a5f92fbb7463fdb0dfce1eedbdee31cfbe4e5a88f21e0b5a4838631ab66ee6fb` | 四來源 temporary-only runner、日期／OHLC／來源差異檢查 |
| `src/tw_sepa_screener/sources/raw_registry.py` | `fdb24effdeac23372abf255a808b285b5cb04e9efe17bf978c05f8f76834fc79` | 登記四個 daily-price pilot source |
| `src/tw_sepa_screener/sources/captured_http.py` | `6fdc0be27db3e8c57b805b18d929659a4e6dc4acb36c7630f043bd6e5cbabb60` | 保存 prepared request，避免 query 重複；period policy 失敗仍留 raw |
| `tests/test_m2_daily_price_pilot.py` | `6c8f13dbb1a019339a5ef5031942a127ff702e3ebc9e0132aaef276b2d45b431` | daily-price capture／日期／缺值／隔離 tests |
| `tests/test_m2_capture_pilot.py` | `ab7cba9229093797a631f4774d705262c33f7c93984852125e9f095e58c5d649` | logical-period failure 與 transport exception tests |

沒有呼叫 `pipeline.run_daily`、`market_backfill`、`write_raw_snapshot`、DuckDB upsert、指標、策略或帳本。

## 3. Capture 與測試結果

| 驗證 | 結果 |
|---|---|
| raw foundation + calendar/master + daily-price targeted tests | `33 passed in 1.18s` |
| 完整專案 pytest | `381 passed in 53.84s` |
| Ruff（本輪檔案） | `All checks passed` |
| mypy（3 個 source files） | 仍有 1 個 `no-any-return`：temporary-root helper 的跨模組回傳被視為 `Any`；runtime tests 不受影響，但 release gate 未宣稱通過 |

測試涵蓋：

- 四來源各自在 adapter `.json()` 前保存 raw；
- prepared URL query 不會與 kwargs 重複，manifest 保持 scalar request date；
- request date 與 logical period 取自實際 prepared request；
- wrong date、stale latest、empty session、invalid JSON 與 mixed activity 均在 raw 保留後 fail closed；
- HTTP 429、transport failure、logical-period policy failure、未知 URL 與 output-root 逃逸；
- 全 OHLC 缺少只分類，不填補；partial OHLC 拒絕；
- actual project root 不能以假的 `project_root` 參數繞過；daily pilot 只允許 temporary base。

## 4. 官方 live capture

### 4.1 同一交易日四來源

隔離 root：`C:\tmp\tw-alpha-m23-price-live-20260803-03`，requested session 為 2026-07-31。

四份 response 均為 HTTP 200、`hash-verified`、request parameters 無重複並已保存；runner 之後因 TWSE latest 的 `1538 正峰` 將 OHLC 回報為四個 `0.0000` 而 fail closed。相同 historical response 對該列回報 `--`，成交活動同為 2 股、19 元、2 筆。這是來源缺價 sentinel 的表示差異，不是可交易的零元價格。

| Source | Logical period | Bytes | Blob SHA-256 | Snapshot ID |
|---|---|---:|---|---|
| `TWSE-PRICE-HIST` | `session:2026-07-31` | 246,216 | `6b8f292e0553d8a53451792091406a831ac17800185ce24ddaa6f0436533d401` | `734b1dcba9a3eed20f90157d57cd280ef62f102294594c7f70a249777473bb15` |
| `TPEX-PRICE-HIST` | `session:2026-07-31` | 145,830 | `daeebd6de7692d5f09c35c2517eee5c4fbc9dcdfa334a779328776f06a15f438` | `134a3f4503df0e6c9f013d3a725a804788bc85a95dec24a74336d34db9508e79` |
| `TWSE-PRICE-LATEST` | `latest-observed` | 317,784 | `a152088518a79d766fd1b9bf3eba14ab8db8314ed9e286aed839db34f28c3bbd` | `4777944168eb6f72add7209b48e217b86271a2ac2b0a7abafc6e4fbff2d23dd5` |
| `TPEX-PRICE-LATEST` | `latest-observed` | 3,978,759 | `4eb180d80addf25b2d040766c659838960c034ff1f91ab2529dd29264d834919` | `6d2a92f860d1fa68f2185682b0731de6a21c7e155dfe00e9e3a318d1b8f441c4` |

同日離線比較：

| 市場 | Common rows | OHLC 不同 | Volume 不同 | Turnover 不同 | Transactions 不同 | Latest 相對 historical totals |
|---|---:|---:|---:|---:|---:|---|
| TWSE | 1,093 | 1（`--` 對 `0.0000` sentinel） | 0 | 0 | 0 | 三項皆 0% |
| TPEx | 888 | 0 | 851 | 851 | 851 | volume +1.5842%；turnover +3.0928%；transactions +48.7582% |

TPEx OHLC 可一致，但成交量／額／筆數不可視為同一口徑。Pilot 只報告差異，不採 last-write-wins。

### 4.2 歷史缺口日抽查

隔離 root：`C:\tmp\tw-alpha-m23-price-gap-sample-20260803-01`，historical request 為 2021-08-23，latest assumption 仍為 2026-07-31。

- `TWSE-PRICE-HIST`：965 個 4 碼商品 rows，全部日期為 2021-08-23；現有 DB 同日 TWSE 為 0。
- `TPEX-PRICE-HIST`：787 rows，全部日期為 2021-08-23。
- 四份 raw 都先保存；runner 最後仍被 latest `0.0000` sentinel gate 阻擋，沒有 canonical write。

歷史 blobs：TWSE `9d4997d77b3d31ce65c8748667a9b9a947cf65f8ad4417cf99e92a985e3eba02`（195,586 bytes）；TPEx `65d2aa5d33880b2898e6eb68ad1b6115ce925e4c0db362c09e435a910f4381a5`（128,648 bytes）。這證明官方 historical endpoint 能回傳該缺口日，不是 endpoint 僅提供最新日。

`latest_expected_date` 是 caller 提供的 completed-session assumption，尚未由 official calendar 與收盤完成時間 policy 自動推導；不能把 date match 宣稱成 calendar verified。

## 5. 「少 94 個日期」根因

DB 中有 94 天 TPEX 有資料、TWSE 為 0：

- 2020-10-19；
- 2020-10-29；
- 2021-08-23 至 2021-12-30，連續 91 個實際交易日；
- 2023-07-13。

真正 full-market repair scope 是 96 天，另含：

- 2024-08-02：DB 只剩 31 筆 TWSE per-symbol rows；
- 2026-07-02：DB 只剩 31 筆 TWSE per-symbol rows。

96 天都有 `market_tpex` normalized file，沒有對應 `market_twse` full-market file。94 個全缺日期的 TPEX files 都寫於 2026-07-13 13:09～13:29，與三次大量回補的 642、619、288 次失敗同時；`market_session_status` 沒有留下這些日期的狀態。舊 raw 只保存 normalized Parquet，所以現在能證明「TWSE 沒產生資料」，不能反推當時是限流、transport、official stat 或 parser error。

舊 `market_backfill` 在單一市場 empty 時不一定標 incomplete，且 combined returned dates 可由 TPEX 掩蓋 TWSE 空白；後續 script 只重抓 2022，recent repair 預設只看 10 天，故舊缺口永久殘留。

證據狀態：日期、檔案與 run log 為 `verified-snapshot`；2026-07-13 當時的精確官方錯誤為 `blocked-unrecoverable-from-legacy-normalized-data`。

## 6. 缺少 OHLC 的實際分類

Legacy DB 原先的 24,254 個 null-OHLC rows 全部是 O/H/L/C 四欄同時缺少，沒有 partial-null：

| 市場 | 活動量／額／筆數皆 0 | 三者皆正值 | Null-OHLC 合計 |
|---|---:|---:|---:|
| TWSE | 1,093 | 1,932 | 3,025 |
| TPEx | 21,184 | 45 | 21,229 |
| 合計 | 22,277 | 1,977 | 24,254 |

另有一筆已入 DB 的 TWSE `1213 大飲`（2026-07-16）OHLC 四欄均為 0、但有 1 股／7 元／1 筆；因此若把 zero sentinel 算成「無一般盤價格」，目前至少有 24,255 筆語意缺價。2026-07-31 live 又見 `1538 正峰` latest 使用相同 zero sentinel，但 historical 使用 null，證明 parser／source contract 必須處理兩種表示。

禁止把這些列一律稱為停牌：

- `reported_activity_without_regular_ohlc`：有成交活動，但無一般盤 OHLC；可能包含零股或盤後活動，均價不得冒充 close。
- `source_reported_no_trade_unclassified`：活動皆 0；需交易狀態來源才能再分。
- `official_suspension`：只在官方 status evidence 對上時成立。
- `corporate_action_no_trade`：需官方公司行動或 note evidence。
- `partial_ohlc_invalid`：只缺 1～3 欄或 mixed activity，直接 quarantine。

TPEx 2026 status history 已能確認 15 個 zero-activity rows 為正式暫停，但這只是 2026 coverage 下限。22,277 個 zero-activity rows 中 19,625 個連續 1～5 sessions，2,652 個連續至少 6 sessions；不能僅靠長度自動判停牌。

以 4 碼純數字過濾不等於 ordinary common stock；現有 rows 會包含 ETF，且 1,094 個缺價 market-symbol 不在 current master。Raw 必須保存，M3 再用 PIT security type、上市／下市／改名 evidence 分流，不能直接刪除。

## 7. TPEx 來源口徑污染

Legacy DB 以 `(symbol, market, date)` last-write-wins 且沒有 source scope。2026-07-09、07-14～17、07-20、07-31 已混入 latest OpenAPI 口徑，其餘歷史日主要來自 historical endpoint。

2026-07-09 audit 顯示 889 個共同 rows 的 OHLC 相同，但 volume／turnover／transactions 各 874 個不同；latest totals 分別高 1.7087%、3.2876%、62.4491%。這會改變流動性門檻、20 日平均量、相對量、成交量突破及新舊策略公平比較。

在 source contract 完成前：

- historical regular／board-lot-like activity 與 latest exact-share/all-reported activity 分欄或分表；
- 保存 `source_id`、scope、snapshot ID、parser ID；
- 同日多來源只做 comparison，不互相覆寫；
- 不使用 TPEx `Average` 填 close。

## 8. Production non-mutation

Pilot 後 Taiwan Core 與治理 workspace 的 data 指紋均與 entry baseline 相同：

| Artifact | Files／bytes | SHA-256 |
|---|---:|---|
| Taiwan Core legacy raw | 4,988／188,391,038 | `9b09a95aae389c9502d48201066f9470a86792ec834db1c6a0d32132b9a6993b` |
| Governance copy legacy raw | 4,988／188,391,038 | `9b09a95aae389c9502d48201066f9470a86792ec834db1c6a0d32132b9a6993b` |
| Taiwan Core DuckDB | 425,209,856 bytes | `c948a1bd62ff141eabd2216bec358a1b8ea129dd0821bcc785bffe75648bbfba` |
| Governance copy DuckDB | 425,209,856 bytes | `c948a1bd62ff141eabd2216bec358a1b8ea129dd0821bcc785bffe75648bbfba` |
| 兩份 `stock_master.csv` | 174,314 bytes | `b13ce5c57ba384e7946adc347de8e9fb538f16bcf753c2fde232dec1e8a0ed7e` |

Taiwan Core post-state仍是同一 HEAD `fb87f62f…`、29 tracked modified；git-visible untracked 為 124 files、954,391 bytes，manifest SHA-256 `456f58ff6d73243fb7883ef8b75352a187fde3cf274b979d02c81f8adfe4a878`。未 stage、commit、reset、刪除或整理使用者工作樹。

## 9. 後續完成結果

原列技術 gates 已在 M2.4–M2.6 完成：

1. price rows 明示 `ohlc_state` 與 `activity_scope`，null／dash／zero sentinel 不補價；
2. TPEx historical／latest 來源分開保存，不再 last-write-wins；
3. 接入 9 個交易狀態 endpoints 與 4 個公司行動 endpoints；
4. frozen target SHA-256 `5ecf26e039b4d7fb9f6a2ff6bcc6aa2563d0c058f44f88102fce77c83eb7ab10` 的 96 sessions 全部完成 temporary raw／parse／quality；
5. 96/96 accepted，shadow run ID `3ca7b2d4d3b7e8a2711466bb584f6fbe54f6ccedfea34c5677015552435e81d7`；
6. `MI_INDEX` 已依 `type=ALLBUT0999` 與 `type=IND` 做 parameter-aware source binding；
7. production DuckDB、legacy raw 與 stock master 前後 fingerprint 完全相同。

每日股價 remaining gate 不再是資料或 parser 問題，而是 production cutover 授權：durable archive／backup／retention 與 Validation Owner 簽核。詳見 [M2 exit verification](m2-6-exit-verification-2026-08-03.md)。

回滾：production data 沒有變更；temporary artifacts 不屬 production，未經使用者明確要求不刪除。
