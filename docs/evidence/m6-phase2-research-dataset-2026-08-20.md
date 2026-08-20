# M6 Phase 2：凍結研究資料集（2026-08-20）

## 結論

M3 的 as-of 重建逐日輸出為一份可重現的資料集:**382 個交易日 × 1,962 檔證券 = 749,484 列**,63 秒建完,帶內容雜湊與上游 dataset id。

過程中資料集本身揭露了一個既有缺陷,並已修好:**`corporate_actions_pit` 只有 25 列帶官方漲跌停,現在是 1,690 列。**

## 1. 資料集內容

每一列是「某證券在某交易日」,帶三組資訊:

| 組 | 欄位 |
|---|---|
| 官方行情(未還原) | open / high / low / close / volume / turnover / ohlc_state |
| M3.6 判定 | membership / session / market_status / price / corporate_action / **tradability** / reason_codes |
| 漲跌停 | limit_up / limit_down / **limit_basis** / previous_close |

`tradability_state` 分布:

| 狀態 | 列數 | 佔比 |
|---|---:|---:|
| eligible | 701,093 | 93.5% |
| ineligible(未上市／已下市)| 20,771 | 2.8% |
| restricted(處置／注意)| 17,355 | 2.3% |
| blocked(無報價／OHLC 不完整)| 10,265 | 1.4% |

## 2. 資料集揭露的缺陷：官方漲跌停只有 25 筆

第一次建完時 `limit_basis = publisher-exact` 只有 **25** 列。

追下去發現:`corporate_actions_pit` 的 3,861 列中,只有 25 列帶 `limit_up`——那 25 列正是 20 筆減資加 5 筆上市面額變更。**1,665 筆 TWSE 除權息一筆都沒有。**

原因是 M3.4 的 `_action_row()` 用 `first_present(source_row, "limit_up", ...)` 取值,而 TWT49U 的 parser 輸出欄位裡**沒有** `limit_up`。

### 這不只是缺資料，是錯資料

M4.1 已證明:**除權息日的漲跌停不能用前收盤價計算**。而資料集的回退邏輯正是「沒有官方值就用前收盤價算」——等於在 1,665 個 session 上填入**有把握的錯誤值**。

### 修法：原始紀錄本來就保留著

parser 契約規定 `record_preservation: canonical-source-record-json`。檢查後,原始列完整保留:

```
['最近一次申報每股 (單位)淨值', ..., '減除股利參考價', '漲停價格',
 '股票代號', '股票名稱', '詳細資料', '資料日期', '跌停價格',
 '開盤競價基準', '除權息前收盤價', '除權息參考價']
```

**不必改 parser、不必動 source-state 指紋、不必重跑 staging。** 只在建置層從 `source_record_json` 取回三個欄位:

| 欄位 | 用途 |
|---|---|
| `漲停價格` / `跌停價格` | 官方公布值 |
| `減除股利參考價` | **M4.1 的除權息公式必需的第二參考價** |
| `開盤競價基準` | 條文所指的基準,保留備查 |

結果:

| 指標 | 前 | 後 |
|---|---:|---:|
| 帶官方漲跌停 | 25 | **1,690** |
| 帶減除股利參考價 | 0 | **1,665** |
| 其中與除權息參考價不同(含現金增資除權)| — | **77** |

那 77 筆與 M4.1 獨立測得的數字完全一致。

**這是 parser 契約「原始紀錄一律保留」第一次真正付出回報。** 當初沒人想到要把漲跌停打進型別化輸出,而三個月後 M4.1 證明它是必需的——因為原始列還在,代價是改一個建置函式,而不是重跑整條管線。

## 3. 漲跌停的四種來源，各自標明

| `limit_basis` | 列數 | 意義 |
|---|---:|---|
| `computed-from-previous-close` | 723,375 | 一般交易日,由前收盤價 ±10% 並套檔位 |
| `blocked-no-previous-close` | 23,208 | 首日或前一日無報價 |
| `publisher-exact` | 1,629 | 交易所自己公布 |
| `blocked-restatement-without-reference-prices` | 1,272 | **重述價格的 session 但拿不到參考價** |

最後一類幾乎全是**上櫃除權息**——MOPS 公告只給股利金額,不給參考價(見 M3.13)。這些 session 現在是**明確拒絕**,而不是用前收盤價填一個錯值。

「計算出來的漲跌停不是證據」這句話寫進 manifest 的 notes,消費端看得到。

## 4. 一個必須寫進 manifest 的限制

M3 窗有 382 個交易日,但**暖身期會吃掉大半**:

| 指標 | 需要暖身 | 剩餘可用訊號區間 |
|---|---:|---|
| MA200 | 200 日 | 182 日（2025-10-31 起）|
| 52 週高 | 250 日 | **132 日（2026-01-13 起）** |

SEPA 的趨勢樣板同時需要 MA200 與 52 週高,因此**實際可產生訊號的區間只有 6.5 個月**。以其約 7 筆/年的頻率,窗內大約只有 **4 筆交易**。

**4 筆交易在統計上不能證明任何事。** 這句話寫進 manifest 的 notes,免得有人把 382 日誤讀成樣本長度。

## 5. 產出

| 項目 | 值 |
|---|---|
| 腳本 | `scripts/m6/build_research_dataset.py` |
| 輸出 | `C:\tmp\tw-alpha-m6-dataset-02\research_dataset.parquet` |
| 列數 | 749,484 |
| SHA-256 | `aa5ba14bec9bb8aa9db11b15fe7033594ef78bb9f665342ab4a9ed7ab99344cd` |
| 上游 | warehouse dataset `53a2411a0a73cfb0…` |
| 建置時間 | 63 秒 |
| 不變量 | `tests/invariant/test_m6_research_dataset.py`，13 項 |

`corporate_actions_pit` 重建為 `pit-prices-07`,治理倉庫全套 369 通過、1 strict xfail,M3.7 驗證五項全 `passed`。

## 6. 未解決

1. **上櫃除權息無漲跌停**——1,272 個 session 明確拒絕。要補需另尋來源。
2. **暖身期吃掉 65% 的窗**——這是補歷史資料的最強理由,強過任何策略層的改進。
3. **Phase 3(帳本驅動)尚未建**——資料集已含帳本所需的每一個欄位。
