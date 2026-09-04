# 契約要三個度量，倉庫存了兩個（2026-09-04）

| 欄位 | 值 |
|---|---|
| 日期 | 2026-09-04 |
| 起因 | Owner 要把 FinMind 的 `Trading_turnover` 補進倉庫 |
| 結果 | **不必用 FinMind**——官方擷取一直帶著它，是建置器沒有取 |
| 變更 | `scripts/m3/build_prices_actions.py`，一個欄位 |
| 產物 | `tw-alpha-m3-pit-prices-14`，sha256 `7b31e30b…` |

## 0. 一句話

**[PIT 契約 §6.4](../contracts/pit-warehouse-contract.md) 要求 `daily_prices_pit` 保存「volume／turnover／transactions」，而實作從專案開始就只存了前兩個。**

## 1. 這不是加欄位

契約 §6.4 的原文：

> 保存 raw official price basis、`activity_scope`、`ohlc_state`、**volume／turnover／transactions** 及來源版本。

**解析器從來不是問題。** `transactions` 出現在建置器寫過的**每一份** `source_columns_seen` 裡，兩個市場都有，欄位名相同：

```
TWSE  2019-01-02  {'symbol': '0050', 'close': 74.05, 'volume': 8532073,
                   'turnover': 636107101, 'transactions': 4102}
TPEX  2019-01-02  {'symbol': '1240', 'close': 37.0,  'volume': 27000,
                   'turnover': 998400,   'transactions': 27}
```

是列的組裝按名字挑了 `volume` 與 `turnover`，沒挑第三個。**而沒有任何東西拿建出來的欄位去對那句要求。**

## 2. 它是側面浮出來的，而那個路徑值得記

Owner 問「資料來源可以來自 FinMind 嗎」。[探測](audit-finmind-intraday-probe-2026-09-04.md)發現 FinMind 的 Free 日線回傳 `Trading_turnover`——逐檔成交筆數——而倉庫沒有。

Owner 說「補進倉庫」。

**查下去，答案是「倉庫不是沒有，是丟掉了」。**

再往前兩天，[制度連續性量測](m3-regime-continuity-2026-09-03.md)需要這一欄、發現表裡沒有，**於是改成從原始 blob 抓全市場合計**——逐檔拿不到，問題被縮小到現有資料能回答的形狀。那次量測的結論不受影響（它問的是全市場行為），但它**本來可以逐檔做**。

## 3. 修法

```python
"volume": first_present(source_row, "volume", "trade_volume"),
"turnover": first_present(source_row, "turnover", "trade_value"),
"transactions": first_present(source_row, "transactions"),   # 新增
```

一行。**來自官方解析，不是廠商**——`daily_prices_pit` 的 `evidence_state` 是 `verified-snapshot`，一列裡混進廠商欄位會讓那個標籤說謊。

## 4. 驗證

pit-prices-13 對 pit-prices-14，同一份 staging、同一個 `--window-end`：

| | 值 |
|---|---|
| 列數 | 3,359,704（**相同**）|
| 場次 | 1,862（**相同**）|
| 證券 | 2,098（**相同**）|
| 欄位 | 22 → **23**，新增 `transactions`，未移除任何欄 |
| **既有 22 欄逐列比對** | **全部相同** |

新欄的涵蓋：

| 市場 | 非空 | 比例 |
|---|---:|---:|
| TWSE | 1,854,821 / 1,854,821 | **100.00%** |
| TPEX | 1,504,883 / 1,504,883 | **100.00%** |

值域 0 ~ 1,150,086。

## 5. 守門盯的是契約，不是欄位清單

`tests/unit/test_price_table_fields.py` **去讀契約那句話**，用正則抓出它列的三個度量，再對建置器實際組裝的欄位：

```python
REQUIREMENT = re.compile(r"保存 raw official price basis[^\n]*")
```

**寫死欄位清單的測試擋不住這個缺陷**——若有人擴充契約而沒動建置器，寫死的清單照樣通過，**而那正是這次漏掉的形狀**。

另外三條：

- **防空洞通過**：掃描必須抓到真的列（至少 15 個欄位，含 `market`／`symbol`／`close`）
- **契約仍列三個度量**：若契約改了，上面那條就是在對一句已經不同的話量
- **來源必須是官方解析**：建置器裡不得有廠商 host 或 HTTP client

## 6. 沒有做的

- **沒有傳到研究資料集。** `RESEARCH_DATASET_PRICES` 仍指 pit-prices-13，因為 dataset-10 由它建成，兩者必須成對移動。傳下去要重建 dataset-11、重做封存切分、改一批 invariant 測試——**而目前沒有東西需要在回測器裡用這一欄**。
- **沒有回頭重做任何量測。** 制度連續性那次的結論是關於全市場的，逐檔資料不會改變它；但現在逐檔做得到了。

## 7. 相關文件

- [PIT 契約 §6.4](../contracts/pit-warehouse-contract.md)
- [FinMind 能不能當分鐘資料來源](audit-finmind-intraday-probe-2026-09-04.md)——這個缺陷是從那裡浮出來的
- [制度變更有沒有留下斷點](m3-regime-continuity-2026-09-03.md)——兩天前為缺這一欄而縮小的量測
