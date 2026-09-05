# 候選報告契約

| 欄位 | 值 |
|---|---|
| 契約版本 | `candidate-report-v1.5.0`（2026-09-05；§2.4 新增下市處分的三個欄位，見該節。v1.4.0 同日：§2.1 的 `drawdown_pct` 指名為**權益曲線的最大回撤**並新增 `terminal_drawdown_pct`，見 §2.1.2。v1.3.0 見 2026-09-04；§2.1 新增 M0 §9.1 缺的三個比較欄，見 §2.1.1。v1.2.0 見 2026-08-26：§3 判定拆為稀缺與塞不下兩項，只有前者決定判定；v1.1.0 同日把判定由拒絕數改為排序一致性，見 [ADR-0002 決策 4 的修訂](../adr/0002-measurement-scale-separate-from-execution-scale.md)）|
| 狀態 | **`baseline-approved` v1.3.0，2026-09-04**（[D26](../evidence/m3-owner-decision-d26-2026-09-04.md)）。v1.2.0 於 2026-08-25 核准 |
| 用途 | 強制 ADR-0002 決策 3 與 4；作為 M7 巢狀驗證的輸入格式 |
| 核准 | Product Owner（單一簽核人，Owner 決定 2026-08-25）|

## 0. 為什麼需要它

ADR-0002 的決策 3 與 4 目前只是文字：報告要並列兩個規模、名額稀缺要被呈報。沒有產物格式，就沒有東西可以強制，而該 ADR 的六條驗證測試有兩條因此無法實作。

**一條沒有測試盯著的規則，等同於沒有記錄的規則。** 這份契約存在的目的就是讓那兩條可以被寫出來。

## 1. 產物形式

一個 **parquet 加一份 manifest**，與倉庫其餘 lane 相同：

```
<report-root>/
    candidate_report.parquet     逐次執行一列（兩個規模即兩列）
    report_manifest.json         元資料、雜湊、譜系
```

不採 JSON-only。既有的每一個資料產物都是 parquet 加 manifest，而報告要與資料集、倉庫表放在同一組工具下比對。

## 2. 必填欄位

缺任一欄位**整份報告拒絕**，不標記後放行（Owner 決定 2026-08-25）。與 TEJ 匯入器「缺必要欄位整檔拒絕」一致：一份缺欄位的報告若被接受，缺的那一欄就會被當成「沒有問題」。

### 2.1 每個規模一列

| 欄位 | 說明 |
|---|---|
| `scale` | `m0-execution` 或 `reference-measurement` |
| `opening_cash` | 該列的期初資金 |
| `return_pct` | 期末報酬 |
| `drawdown_pct` | **權益曲線的最大回撤**，見 §2.1.2 |
| `terminal_drawdown_pct` | 期末相對高水位的回撤，見 §2.1.2 |
| `cost_total` | 實扣成本合計 |
| `cost_share_of_capital` | 成本 ÷ 期初資金 |
| `cost_share_of_turnover` | 成本 ÷ 成交額 |
| `completed_trades` | 完成交易數 |
| `benchmark_cash_pct` | **M0 §9.1**：現金。名目 0%，見下 |
| `benchmark_equal_weight_universe_gross_pct` | **M0 §9.1**：合資格股票池等權，**毛** |
| `benchmark_index_taiex_price_gross_pct` | **M0 §9.1**：發行量加權股價指數，**毛** |
| `benchmark_index_taiex_total_return_gross_pct` | 同上的報酬指數，**毛** |
| `benchmark_basis` | 恆為 `gross`，見 §2.1.1 |

**兩個規模都必須在場。** 只有一列的報告是缺欄位，不是簡化版——ADR 決策 3 要的是兩者的差距，而差距需要兩個數。

#### 2.1.1 最低比較組（v1.3.0，2026-09-04）

[M0 §9.1](../m0-project-contract.md) 從第一版起就要求每個 challenger 對照「現金、適當市場指數或 ETF benchmark、合資格股票池等權、equal-size same-pool random selection、簡單動能／相對強度、目前 champion 及 challenger」。

**其中三欄從來沒有被任何一份報告帶過，因為沒有東西算得出來。** 隨機選股由對照 001 補上，動能與 challenger 是執行本身，champion 目前不存在（沒有東西是 `validated`）——**缺的是現金、指數、等權池**，而它們現在在這裡。

**三欄皆為毛報酬，而候選的 `return_pct` 是淨額。**

指數是公布的不是交易的；等權池是約兩千檔，在 M0 規模下每檔的部位小到買不到一股。**對一個沒有人能執行的組合套用為真實部位設計的成本模型，量到的是手續費表不是市場**——[2026-09-03 實測那樣做值 50 個百分點，而且是朝美化選股的方向](../evidence/m7-benchmarks-and-cost-stress-2026-09-03.md)。

所以 `benchmark_basis` 恆為 `gross` 且必填：**一份把淨額與毛額並排而不說的報告，是在讓讀者自己去假設。**

**指數表缺席時，該欄為 null 且 manifest 記錄原因，而不是把欄位拿掉。** M0 要求這一欄，而一個靜默消失的基準正是本節存在的理由。

#### 2.1.2 回撤是哪一個回撤（v1.4.0，2026-09-05）

本契約自 v1.0.0 起要求 `drawdown_pct` 並稱它「最大回撤」，**而沒有說是相對
哪個基準、在哪個時點量的**。2026-09-05 發現那不是一個措辭問題：

| 出處 | 算什麼 | 當時的欄名 |
|---|---|---|
| `run_ledger_backtest.py` | `(高水位 − 最後一個場次) / 高水位` | `drawdown_pct` |
| `compare_candidates.py` | 權益曲線的最大值 | `drawdown_pct_in_window` |
| `measure_halt_events.py` | 權益曲線的最大值 | `max_drawdown_pct` |

**同一個名字有兩個定義，而拿到哪一個取決於是哪支工具印的。** 而
`measure_halt_events.py` 把回測報告那個欄位命名為 `final_drawdown_pct_from_run`
——**有人早就知道它是期末值**，在那裡命名正確，而候選報告仍然叫它最大回撤。

兩者只有在執行結束於最低點時相等。實測 102 份既有產物：**33 份低估超過 5 個
百分點，最大低估 59.27pp**（動能在參考規模報 0.00%，權益曲線是 59.27%）。

**M0 §8.1 的 8% 硬停止是一個回撤門檻**，所以這一欄用哪個定義，決定的是一個
候選有沒有通過。

##### 定義

| 欄位 | 定義 |
|---|---|
| `drawdown_pct` | 在整段窗口的每日 NAV 序列上，`max((執行中最高 NAV − 當日 NAV) / 執行中最高 NAV)`，以百分比表示 |
| `terminal_drawdown_pct` | `(整段窗口的最高 NAV − 最後一個場次的 NAV) / 最高 NAV`，以百分比表示 |

**兩欄皆必填。** 期末回撤不是錯的數字——它是「現在離高點多遠」，是一個關於
真實帳戶的真實問題——它只是不叫最大回撤。把它拿掉會讓一個既有欄位無聲消失，
而讓兩個名字並存正是本節存在的理由。

##### 既有產物不需要重跑

每一份報告都帶完整的每日 NAV 序列（`equity`），所以任何一份既有產物的
`drawdown_pct` **由它自己的檔案就重算得出來**（`scripts/m6/correct_drawdown.py`）。
本次修訂因此不觸發重跑，與[停損成交價修正](../evidence/m6-gapped-stop-fill-2026-09-04.md)
那一類必須重跑的修訂不同。

**修正不改寫既有產物。** 一份存下的報告就是那次執行產出的東西；就地改寫會讓
「修正過的檔案」與「本來就對的檔案」再也分不出來。

### 2.2 拒絕理由全表

| 欄位 | 說明 |
|---|---|
| `refusals` | **每一個**理由碼與次數，不得只列前 N 名 |
| `refusals_total` | 所有拒絕的總數 |
| `ranking_function` | 候選據以排序的分數名稱；沒有排序則為空字串 |
| `rank_violations_scarcity` | 因**沒有空位**而擋下高分、卻收下低分的場次數；無排序函式時為 −1（不適用）|
| `rank_violations_sizing` | 最高分那檔**塞不進去**的場次數；無排序函式時為 −1（不適用）|
| `rank_violation_codes` | 造成違反的理由碼與次數；無排序函式時為空 |
| `selection_logic_measured` | 布林；判定規則見 §3 |

v1.1.0 的 `rank_consistency_violations` 由上面兩欄取代（v1.2.0，2026-08-26）。它把兩件講不同話的事加在一起，而加總之後大的那一項會把判定整個帶走：12-1 動能候選的 53／123 次違反，稀缺佔 0、塞不下佔全部。

### 2.3 譜系

| 欄位 | 說明 |
|---|---|
| `dataset_sha256` | 研究資料集雜湊 |
| `warehouse_dataset_id` | 產生該資料集的倉庫 id |
| `strategy_version` | 策略識別與參數 |
| `rules_version` / `ledger_version` | M4／M5 版本 |
| `broker_terms` | 使用的條款，含 `evidence_state` 與是否含折讓 |
| `built_at` | 產生時間 |

### 2.4 下市處分：一筆沒有發生過的成交（v1.5.0，2026-09-05）

[D27](../evidence/m3-owner-decision-d27-2026-09-05.md) 決定：一檔持股的
`membership_state` 變成 `delisted` 之後，以該部位持有期間市場真的印過的
最後一個收盤價認列一次處分。

**那筆成交沒有發生過。** 證券沒有在交易，`MarketConditions` 會拒絕它，而
呼叫端編造了四個欄位讓它過（逐條列在 D27 §2 與驅動器的註解裡）。

一份把編造的成交與真的成交混在一起呈報的報告，就是讓讀者把模型當成市場證據。
所以：

| 欄位 | 說明 |
|---|---|
| `trades[].fill_basis` | 真實成交為 null；編造的處分為 `fabricated-delisting-disposal` |
| `delisted_disposals` | 該次執行的處分筆數 |
| `nav_in_delisted_disposals` | 處分成交額合計，以期初資金的百分比表示 |

**三欄皆必填**，`delisted_disposals` 為 0 時後者為 0.0——**不是省略**。
一份沒有這些欄位的報告與一份處分筆數為零的報告，讀起來必須不一樣。

#### 2.4.1 為什麼欄位而不是註腳

**一筆處分就能讓結果移動 8 個百分點**（D27 §4，診斷 004 最佳格
−25.53% → −33.92%），因為釋放一個名額會改變後面每一次進場。

而處分同時消掉了一個訊號：`inverse-volatility-60` 系統性挑到會停止交易的
股票這件事，原本是靠帳戶明顯凍住才被看見的（完成交易 103 對 306）。
處分之後帳戶看起來正常，而問題還在。**這三欄是那個現象在報告裡唯一的入口。**

## 3. 選股邏輯判定：看排序一致性，不看拒絕數

**v1.2.0，2026-08-26**（依 [ADR-0002 決策 4 的修訂](../adr/0002-measurement-scale-separate-from-execution-scale.md)）。

`selection_logic_measured` 為真，須同時滿足：

1. `ranking_function` 非空——候選宣告了它據以排序的分數；且
2. `rank_violations_scarcity == 0`——同一場次中，沒有任何因**沒有空位**被拒的候選，其分數高於當場開倉的任一部位。

未宣告排序函式者一律為偽，**不論拒絕數多寡**。

`rank_violations_sizing` **不參與判定**，但仍為必填。它講的是帳戶塞不下最高分的那一檔，那是規模的性質，不是選股邏輯的缺陷。

### 這條判定實際上在保證什麼

要說清楚，免得被讀得比它實際上更強。

訊號依分數由高到低走訪，而 `positions` 在進場迴圈中只增不減（出場在更早一步就跑完了）。所以名額一旦滿了就不會再放開，之後不會再有任何一筆成交——**因此稀缺型拒絕在結構上不可能後面跟著一筆開倉**。

也就是說，排序正確時 `rank_violations_scarcity` 必然為 0。它是**排序有沒有真的被套用**的守門員，不是「策略在稀缺下表現良好」的證據。它會變成非零的情況只有一種：排序壞了，或根本沒有排序而改用到達順序。

那正是這個欄位該保證的事，也正是 `selection_logic_measured` 這個名字說的事——這次跑的是一條選股規則，不是先到先得。它沒有說那條規則好。

### 為什麼不再用拒絕數

v1.0.0 的規則是 `refusals_total > completed_trades × 10`。它換過一次（原本只數 `position-slots-full`），而兩個版本都測錯了東西。

把名額由 2 提到 20 之後 `position-slots-full` 由 277,777 掉到 584，總數卻幾乎不動（277,791 → 279,104）——**稀缺換了形狀**，所以只數一種理由碼會誤報成功。改數總數修好了那一點，但門檻**對廣訊號策略可能永遠無法滿足**：2,000 檔股票池、十萬量級的訊號，對上千量級的容量，即使排序完美也一樣。

那條規則同時混著兩件事：**容量受限**（對任何篩選型策略都成立，不是缺陷）與**選擇無序**（名額滿時先到先得，才是缺陷）。排序一致性只測後者。

### 兩類「容量」拒絕的列舉

分界不是取捨，是可查的：`plan_position` 讀不讀候選自己的價格。

**稀缺**——在讀到價格之前就返回，對每一檔證券一視同仁。計入判定：

```
entry:position-slots-full
entry:max-positions-reached
entry:cash-reserve-floor-reached
```

**塞不下**——每一條都讀了該檔的價格或停損，所以停損寬的、價格貴的會失敗，便宜的通過。呈報，不計入判定：

```
entry:cash-cannot-cover-position-and-charged-commission
entry:breaches-hard-risk-cap
entry:breaches-total-open-risk-cap
entry:no-quantity-satisfies-every-cap
entry:round-trip-cost-exceeds-planned-risk
```

`round-trip-cost-exceeds-planned-risk` 在 2026-08-25 被歸為容量，理由是「它隨帳戶規模變動」。那句沒錯，但它同時也隨證券變動，而後者決定它落在「塞不下」這一邊。

其餘（`not-tradable-restricted`、`no-opening-price`、`opened-below-stop` 等）與帳戶塞不塞得下無關，是該證券自己的狀態，兩類都不納入。

`entry:already-held` **不是容量拒絕**。已經持有那檔，代表排序被遵守了而不是被推翻。它在 2026-08-26 之前被併進 `position-slots-full`，而那個併法會拿帳戶自己最好的部位去製造違反：同一檔再次發出訊號、分數很高、因已持有被拒，於是看起來像是高分被擋、低分成交。改碼後 12-1 動能的違反數由 70／375 降到 53／123。

### 拒絕數仍為必填

`refusals`（全表）與 `refusals_total` 仍是必填欄位——**它們只是不再決定判定**。一份看不到拒絕分布的報告，讀者無法判斷帳戶被什麼擋住。

`selection_logic_measured` 為偽時，該報告**不得用於候選之間的排序比較**。它仍可作為基礎建設驗證。

## 4. 不可變性

報告**可以改寫**（Owner 決定 2026-08-25）。

記錄一項後果：倉庫其餘每一條 lane 都是 append-only，理由是「覆寫等於抹掉這支腳本存在的理由」。報告可改寫代表一份較早的主張可以消失而不留痕跡。若日後要追溯「當時報告說了什麼」，需要另行保存。

## 5. 核准

`research → validated` 的升級由 **Product Owner 單一簽核**（Owner 決定 2026-08-25）。

ADR-0002 決策 1 仍然拘束：M0 規模下產生的報酬數字不得作為策略優劣證據，也不得單獨支撐該升級。

## 6. 本契約不涵蓋

- 策略本身的格式（見 [候選策略封包契約](strategy-candidate-contract.md)）。
- M7 巢狀驗證的方法。本契約只定義它的輸入。
- 哪一個候選是好的。報告是輸入，不是判決。

## 7. 相關文件

- [ADR-0002：衡量規模與執行規模分離](../adr/0002-measurement-scale-separate-from-execution-scale.md)
- [M6.1 六年窗口重跑](../evidence/m6-1-six-year-rerun-2026-08-25.md)
- [M6.3 第一個被排序的候選](../evidence/m6-3-first-ranked-candidate-2026-08-26.md)——第一份依本契約產出的報告，也是 v1.1.0 到 v1.2.0 那兩處修訂的來源
- [候選策略封包契約](strategy-candidate-contract.md)
