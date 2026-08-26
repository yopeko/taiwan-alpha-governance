# 候選報告契約

| 欄位 | 值 |
|---|---|
| 契約版本 | `candidate-report-v1.1.0`（2026-08-26；§3 判定由拒絕數改為排序一致性，見 [ADR-0002 決策 4 的修訂](../adr/0002-measurement-scale-separate-from-execution-scale.md)。其餘不變）|
| 狀態 | `baseline-approved`，2026-08-25 |
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
| `drawdown_pct` | 最大回撤 |
| `cost_total` | 實扣成本合計 |
| `cost_share_of_capital` | 成本 ÷ 期初資金 |
| `cost_share_of_turnover` | 成本 ÷ 成交額 |
| `completed_trades` | 完成交易數 |

**兩個規模都必須在場。** 只有一列的報告是缺欄位，不是簡化版——ADR 決策 3 要的是兩者的差距，而差距需要兩個數。

### 2.2 拒絕理由全表

| 欄位 | 說明 |
|---|---|
| `refusals` | **每一個**理由碼與次數，不得只列前 N 名 |
| `refusals_total` | 所有拒絕的總數 |
| `ranking_function` | 候選據以排序的分數名稱；沒有排序則為空字串 |
| `rank_consistency_violations` | 成交與排序不一致的場次數；無排序函式時為 −1（不適用）|
| `rank_violation_codes` | 造成違反的理由碼與次數；無排序函式時為空 |
| `selection_logic_measured` | 布林；判定規則見 §3 |

`rank_violation_codes` 是 2026-08-26 補的。只有一個計數說得出規則破了，說不出破在哪，而那些理由碼講的不是同一件事：`position-slots-full` 是稀缺，成本或數量上限則是最高分的那檔塞不進去。兩者要分得開，這個數字才能讀。

### 2.3 譜系

| 欄位 | 說明 |
|---|---|
| `dataset_sha256` | 研究資料集雜湊 |
| `warehouse_dataset_id` | 產生該資料集的倉庫 id |
| `strategy_version` | 策略識別與參數 |
| `rules_version` / `ledger_version` | M4／M5 版本 |
| `broker_terms` | 使用的條款，含 `evidence_state` 與是否含折讓 |
| `built_at` | 產生時間 |

## 3. 選股邏輯判定：看排序一致性，不看拒絕數

**v1.1.0，2026-08-26**（依 [ADR-0002 決策 4 的修訂](../adr/0002-measurement-scale-separate-from-execution-scale.md)）。

`selection_logic_measured` 為真，須同時滿足：

1. `ranking_function` 非空——候選宣告了它據以排序的分數；且
2. `rank_consistency_violations == 0`——同一場次中，沒有任何因**容量**被拒的候選，其分數高於當場開倉的任一部位。

未宣告排序函式者一律為偽，**不論拒絕數多寡**。

### 為什麼不再用拒絕數

v1.0.0 的規則是 `refusals_total > completed_trades × 10`。它換過一次（原本只數 `position-slots-full`），而兩個版本都測錯了東西。

把名額由 2 提到 20 之後 `position-slots-full` 由 277,777 掉到 584，總數卻幾乎不動（277,791 → 279,104）——**稀缺換了形狀**，所以只數一種理由碼會誤報成功。改數總數修好了那一點，但門檻**對廣訊號策略可能永遠無法滿足**：2,000 檔股票池、十萬量級的訊號，對上千量級的容量，即使排序完美也一樣。

那條規則同時混著兩件事：**容量受限**（對任何篩選型策略都成立，不是缺陷）與**選擇無序**（名額滿時先到先得，才是缺陷）。排序一致性只測後者。

### 「容量」拒絕的列舉

以下理由碼視為容量拒絕，納入一致性檢查：

```
entry:position-slots-full
entry:cash-reserve-floor-reached
entry:cash-cannot-cover-position-and-charged-commission
entry:breaches-total-open-risk-cap
entry:no-quantity-satisfies-every-cap
entry:round-trip-cost-exceeds-planned-risk
```

其餘（`not-tradable-restricted`、`no-opening-price`、`opened-below-stop` 等）與帳戶塞不塞得下無關，是該證券自己的狀態，不納入。

最後一項是判斷：成本超過該部位被定量的風險，兼具兩者的性質，歸為容量，因為它隨帳戶規模變動而非隨證券變動。

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
- [候選策略封包契約](strategy-candidate-contract.md)
