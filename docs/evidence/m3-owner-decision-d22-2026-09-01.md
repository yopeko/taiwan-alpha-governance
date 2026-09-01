# Owner 決定 D22：M9 觀察端改為獨立的當日擷取（乙案，2026-09-01）

| 欄位 | 值 |
|---|---|
| 決定 | 採[兩邊同源](m9-both-sides-read-the-same-table-2026-09-01.md) §3 的**乙案** |
| 批准 | Product Owner，2026-09-01 |
| 影響 | 「一次觀察」的定義改變。契約 §1 的主張因此第一次真的被對照 |
| M9 計數 | **仍為 0/60。** 本決定讓計數變得有意義，不讓它前進 |

## 0. 被否決的兩個

**甲（每日全量重建倉庫）**：[M3.17](m3-17-six-year-rebuild-2026-08-25.md) 實測 `build_staging` 六年花 **79.8 分鐘**，且 generation 是累加保留的。每天一次，磁碟無上限。

**丙（承認量不到，暫緩計數）**：誠實，但[契約 §0](../contracts/shadow-observation-contract.md) 存在的全部理由是「把時間變成證據」，而封存區只有 382 個場次且不會再生。停下來就是放棄唯一不需要裁決就會產生的證據來源。

## 1. 乙案是什麼

觀察端不再讀倉庫，改為**當日直接向 TWSE／TPEx 擷取官方收盤表**，再用**同一套建置器**做成同樣的表：

```
capture_window.py        --start D --end D --output-root <當日 raw>
build_staging.py         --archive <當日 raw>        → 小型 staging
build_prices_actions.py                              → 當日 parquet
capture_observation.py   --prices-root <當日 parquet> → 觀察
```

包裝在 `scripts/m9/daily_observation.cmd`。

**兩邊因此成為兩個來源**：觀察來自當天的擷取，重建來自倉庫。差異第一次可能來自「當天實際看到的與倉庫說的不一樣」——而那正是契約 §1 說要量的東西。

## 2. 成本先量再建

| | |
|---|---|
| 全量 staging（六年，1,840 場次）| **79.8 分鐘** |
| 單一封存 staging（15 個觀測、13,525 列）| **9 秒** |
| 該 staging → prices parquet | **1 秒** |
| 觀察寫出 | 即時 |

2026-09-01 以既有封存離線實測，未擷取任何東西。擷取本身受 6 秒禮貌間隔限制，單日兩個市場是分鐘級。

**這使每日鏈路可行，而甲案不可行。**

## 3. 為此做的唯一一處程式變更

`build_staging.py` 的 `ARCHIVES` 原本是寫死的清單，只能全量。新增 `--archive`（可重複，**省略即維持原行為**）。

考慮過但沒有選的替代方案：在觀察端重用解析器註冊表，自己把當日資料整成觀察。**那會是 row shaping 的第二份實作**，而那份邏輯歸 `build_prices_actions` 所有——兩份副本遲早會對同一件事說不同的話，這個專案已經記錄過三次同一形狀。

`assert_publishable` 同時修補一個由此開出的洞：經 `--archive` 傳入的 root 是原始證據，本次執行內一併納入保護，否則覆寫入口會允許把 staging 建在正在讀的封存裡面。

## 4. 這不改變什麼

- **M9 計數維持 0/60。** 本決定讓計數有意義，不讓它前進。第一個可計數的日子是第一次成功執行該鏈路的開市日。
- **不推進 M0 §9 的軌道。** 這是管線 shadow，不是策略 shadow；目前沒有任何候選是 `validated`。
- **不碰封存區。** 開封次數 0。
- **不改變倉庫。** 每日鏈路寫入自己的 root，受保護 store 於建置前後指紋一致（實測 `production_unchanged: true`）。

## 5. 已知代價，寫下來因為它是代價

**多一條每日鏈路要維護。** 擷取失敗的日子不計入 60（契約 §4 已規定），而失敗會寫進 `failures.log` 而不是被吞掉——一條安靜失敗的鏈路會用比它宣稱更少的天數走到 60。

**每日一個 root。** 單日資料小，但仍會累積；清理策略未定，記為待處理。

**擷取端與倉庫可能用到同一份原始回應。** 若某日倉庫日後也從同一次擷取重建，兩邊仍會一致——那不是缺陷，而是 `late-arriving-official-data` 以外的差異本來就該是零。**真正的檢驗在遲到資料出現的那些天。**

## 6. 相關文件

- [M9：兩邊在讀同一份表](m9-both-sides-read-the-same-table-2026-09-01.md)
- [M9：擷取排程之前量到的來源落後](m9-observation-source-staleness-2026-09-01.md)
- [Shadow 觀察契約（M9 前半）](../contracts/shadow-observation-contract.md) §1、§4
- [M3.17 六年窗口重建](m3-17-six-year-rebuild-2026-08-25.md)
