# M3.10：減資公告日與停止買賣日（2026-08-19）

## 結論

前一次工作把 20 筆減資併入 `market_status_pit`，但兩個關鍵欄位是空的：

- `capital_reduction_with_announcement: 0`——沒有公告日期，全數 `unknown-blocked`，**資料完整但不可用於 as-of**；
- `effective_from` 全空——恢復買賣表只有 `恢復買賣日期`，沒有 `停止買賣日期`，停牌區間**有終點沒有起點**。

兩者現已全部補齊：**20/20 取得 `publisher-exact` 可用性，20/20 具備完整停牌區間**，並通過一項與停牌資料完全獨立的價格交叉驗證。

## 1. 前一次為何失敗

原設計假設「預告表（TWTAVU）提供公告日期，恢復買賣表（TWTAUU）提供結果，兩者以代號＋恢復日配對」。

實測推翻了這個假設：**預告表不吃日期參數**。20 次月度查詢（2025-01 至 2026-08）全部回傳同一列——1563 巧新，停牌 2026-08-27、恢復 2026-09-07，也就是查詢當下唯一待執行的減資。它是一份「現況清單」，不是歷史表。

歷史公告日期不可能從它取得。配對結果為 0 不是程式錯誤，是來源本身沒有那筆資料。

## 2. 真正的來源：詳細資料端點

兩張表的最後一欄都是 `詳細資料`，內容形如 `2352  ,20250924`。清單頁的內嵌 script 說明了它的用途：

```javascript
t[10]=`<a href="twtavu-detail.html?${t[10].replace(/[^\w,\.\-]/g,"")}">請點選</a>`
```

詳細頁再拆解為兩個參數：

```javascript
$("#form").data("onload-argv",{STK_NO:t[0],FILE_DATE:t[1]})
```

端點為 `https://www.twse.com.tw/rwd/zh/reducation/TWTAVUDetail`。

**路徑一律從頁面原始碼萃取，不用猜的**——這是上一輪 `/reducation/`（官方把 reduction 拼錯）留下的教訓，這次直接沿用。

### 回傳內容

```
fields: 股票代號、股票名稱、停止買賣日期、每壹仟股換發新股票、每股退還股款、
        原股每股配發現金股利、減資並(有償)現金增資、每股認購金額、
        a. 公開承銷、b. 員工認購、c. 原股東認購、按股東持股比例每千股認購
data:   ["2352  ", "佳世達", "114/09/25", "820.00000000 股", "1.800000 元/股", ...]
```

**`停止買賣日期` 只存在於這裡**。恢復買賣表沒有這一欄，預告表雖然有但只涵蓋待執行的那一筆。

## 3. 取得與封存

| 項目 | 值 |
|---|---|
| Source ID | `TWSE-REDUCTION-DETAIL-HIST` |
| Endpoint | `capital-reduction-detail-history` |
| Parser | `twse-capital-reduction-detail/1` |
| 請求數 | 21（20 筆恢復 + 1 筆待執行預告） |
| 結果 | `captured: 21`，無一失敗 |
| Archive | `m3_reduction_detail_2025-2026` |
| Tree SHA-256 | `ed2d404af350c873f415db02c938ac1137bb1d7b9d627c392093d74addd446bb` |
| 驗證 | 21 blobs 逐一比對雜湊，primary 與 E: 備份皆 `archived-and-verified` |

**Key 一律由已擷取的清單推導，不自行列舉。** 任意組合 (代號, 日期) 去請求，只會是兩種結果：捏造出不存在的公告，或漏掉沒人想到要猜的那幾筆。清單本身就寫明了有哪些文件存在。

## 4. 兩項設計決定

### 4.1 以文件鍵配對，不用日期鄰近

恢復買賣列自己就指名了它的公告文件（`詳細資料` 欄）。因此 join 用的是精確鍵 `(代號, FILE_DATE)`，不是「找時間上最接近的那筆公告」。

差別在失效時的行為：日期鄰近法在配對不到時會**接到最近的那筆公告**，安靜地把 A 公司的減資接到 B 公司身上；精確鍵配不到就是配不到，該列維持 `unknown-blocked`。

### 4.2 `effective_to` 是停牌最後一日，不是恢復日

本表 `effective_from`／`effective_to` 一律為**閉區間**。恢復買賣日當天股票已經正常交易，把它放進停牌區間會讓一個交易日落在停牌範圍內。

因此區間結束於恢復日的前一個日曆日，交易所公布的恢復日原值保留於 `measure_text` 的 `resumption_date=`。

這不是推論而是換句話說：交易所寫「X 日停止買賣、Y 日恢復買賣」，停牌區間即 `[X, Y-1]`。§5 的價格驗證亦證實如此。

## 5. 交叉驗證：與停牌資料完全無關的獨立證據

停牌日期來自公告文件；價格來自每日行情表。兩者不共用任何程式路徑。

**20 檔證券在自己的停牌區間內（共 5–7 個交易日）皆無任何報價，一筆都沒有。**

反向檢查：**20/20 的恢復買賣日當天都有報價**。也就是說若沿用「`effective_to` = 恢復日」的舊寫法，這項驗證會 20 筆全數失敗。這個測試是有鑑別力的，不是恆真。

此驗證已寫成常設 invariant：`test_no_security_trades_during_its_own_halt`。

## 6. `FILE_DATE` 是否為公告日期

判定為 `publisher-exact`。理由與殘餘不確定性一併記錄如下。

| 證據 | 內容 |
|---|---|
| 來源 | 交易所自己用來定址其公告文件的日期參數 |
| 順序 | 20/20 早於停止買賣日 |
| 非機械衍生 | 19/20 落在停牌前一個交易日；**2101 南港例外**，公告 2025-09-02、停牌 2025-09-04，中間 09-03 是交易日。若 `FILE_DATE` 只是由停牌日回推的計算值，不會出現這個例外 |
| 即時案例 | 唯一待執行的 1563，`FILE_DATE` 為 2026-08-18，2026-08-19 已可在預告表看到，發布延遲不超過 1 日 |

**殘餘不確定性**：取得的是日期，不是帶時分的發布紀錄。as-of 判準 `announced_at <= decision_as_of` 為日粒度，因此若真實發布時間晚於 `FILE_DATE`，最大暴露為**一個交易日**（19/20 的公告至停牌僅隔一個交易日）。

**Fail-closed 防護**：三個日期必須滿足 `公告 <= 停牌 < 恢復`，任一不成立該列即退回 `unknown-blocked`，不寫入公告日期。本次 20 筆全數通過。

**Owner 已於 2026-08-19 裁決採 `publisher-exact`**，並要求保留上述 fail-closed 檢查。決定紀錄與被否決的兩個替代方案見 [D11](m3-owner-decision-d11-2026-08-19.md)。

## 7. 結果

| 指標 | 前 | 後 |
|---|---:|---:|
| `capital_reduction_rows` | 20 | 20 |
| `capital_reduction_with_announcement` | **0** | **20** |
| 具備完整停牌區間 | **0** | **20** |
| `availability_basis` | 全為 `unknown-blocked` | 全為 `publisher-exact` |

### As-of 行為（2352 佳世達；公告 09-24、停牌 09-25、恢復 10-07）

| Session | `market_status_state` | `tradability_state` |
|---|---|---|
| 2025-09-24 | `no-event-in-covered-window` | `eligible` |
| 2025-09-25 | `capital-reduction` | `blocked` |
| 2025-09-26 | `capital-reduction` | `blocked` |
| 2025-10-07 | `no-event-in-covered-window` | `eligible` |

**附帶效果**：這 20 段價格空窗先前只能由 D8「價格缺漏推定停牌」解釋，現在有了官方原因。`reason_codes` 同時包含 `status-capital-reduction` 與 `suspension-inferred-from-price-absence`，前者是證據，後者是推論。

## 8. 順帶修正三處指向過期產物的路徑

這三處都不會讓任何測試失敗，只是讓它們驗證的是舊東西：

| 位置 | 原指向 | 實際情況 |
|---|---|---|
| `tests/invariant/test_m3_5_status_fundamentals.py` | `pit-status-01` | 已重建至 `-06`，invariant 從 `-02` 起即在驗證過期產物 |
| `scripts/m3/asof.py` `default_warehouse()` | `pit-status-01` | 同上 |
| `scripts/m3/validate_m3_7.py` `STAGING` | `staging-03` | 早於減資 archive 存在，決定性驗證未涵蓋減資（`status_rows` 15,348 vs 實際 15,368） |

修正後 M3.7 驗證 `verdict: passed`，`status_rows: 15368`，三張表重建逐位元一致。

## 9. 資料狀態

| 表 | 列數 | SHA-256 |
|---|---:|---|
| `market_status_pit` | 15,368 | `7a4499b4f003c74e…` |
| Staging dataset | 6,331 obs／881,280 列 | `0599d78e49fdda00…` |

測試：208 通過、3 strict xfail；`m4/tests` 57 通過。

## 10. 未解決

1. **面額變更／股票分割仍缺來源**——約 10 筆股價驟降至約 1/10 的異常（4763 885→90.5、6919 1215→133.5、8422 250→24.7、2327 546→143）尚未解釋。兩條候選路徑：TWSE `TWTCAU`（頁面標題寫「ETF 分割」，可能不含普通股，需實測）與 MOPS `t05st01`（逐檔逐年，約 2,700 次請求）。
2. **TPEx 減資未涵蓋**——本次只處理上市。櫃買是否有對應端點未查證。
3. ~~`FILE_DATE` 分類待 Owner 確認~~ **已裁決**，見 [D11](m3-owner-decision-d11-2026-08-19.md)。
