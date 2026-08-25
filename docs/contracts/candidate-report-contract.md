# 候選報告契約

| 欄位 | 值 |
|---|---|
| 契約版本 | `candidate-report-v1.0.0` |
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
| `selection_logic_measured` | 布林；判定規則見 §3 |

### 2.3 譜系

| 欄位 | 說明 |
|---|---|
| `dataset_sha256` | 研究資料集雜湊 |
| `warehouse_dataset_id` | 產生該資料集的倉庫 id |
| `strategy_version` | 策略識別與參數 |
| `rules_version` / `ledger_version` | M4／M5 版本 |
| `broker_terms` | 使用的條款，含 `evidence_state` 與是否含折讓 |
| `built_at` | 產生時間 |

## 3. 名額稀缺判定：數總數，不數單一理由碼

`selection_logic_measured` 為偽，當

```
refusals_total > completed_trades × 10
```

**是總數，不是 `entry:position-slots-full` 一種**（Owner 決定 2026-08-25）。

理由是量到的：2026-08-25 的名額掃描顯示，把名額由 2 提高到 20 之後 `position-slots-full` 由 277,777 掉到 584，看起來問題解決了——而**拒絕總數幾乎不變**（277,791 → 279,104）。同一批訊號改由成本上限、現金上限與最低股數擋下。

**稀缺會換形狀。** 只數一種理由碼的規則，會在放寬那一道閘門時報告成功，而實際上什麼都沒改變。

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
