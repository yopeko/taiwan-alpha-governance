# M3.14：公司行動接入 as-of 重建（2026-08-19）

## 結論

M3.6 的 as-of 介面原本只讀交易日曆、股價與市場狀態，**完全不讀公司行動**。3,861 筆已建好的公司行動對查詢者不存在。

現已接入。`SecurityState` 新增 `corporate_action_state`，並帶三個 reason code。

## 1. 這是一個安靜的缺陷

先前每一個除權息日在 as-of 重建中都看起來像普通交易日。以該日前後收盤價相減的策略，會把配息**當成虧損**計入。

這比抓不到資料更危險：資料明明已經建好，查詢介面卻不讀，兩邊各自看起來都正常。M3.9 花力氣補上的 2,279 筆公告日期、M3.11 的 2,149 筆上櫃行動、今日 M3.13 的 22 筆上櫃停牌——全部止步於表，沒有一筆進入決策路徑。

## 2. 關鍵設計判斷：公司行動**不**依公告日期過濾

市場狀態與股價依 `is_knowable(announced_at, decision_as_of)` 過濾。公司行動**刻意不這麼做**。

理由：**除權息是當日事實，不是未來資訊。**

交易所在該日重述了價格，不論它有沒有事先告知。站在那一天的人會直接觀察到價格基準改變。把它藏起來不會防止前視偏差——它的效果與該 session 同時發生，不在未來——只會隱藏一個**真實發生過的價格斷點**，讓回測算出一筆虛構的虧損。

前視偏差的真正防線是另一條：**只呈現 `effective_date` 等於該 session 的行動**。呈現未來的除息日才是洩漏，這由 `test_no_action_dated_after_the_session_ever_appears` 盯著。

「能不能事先預期」是另一個問題，另外回答：

| Reason code | 意義 |
|---|---|
| `action-{類型}` | 該 session 有此類公司行動 |
| `price-not-comparable-to-previous-close` | 收盤價與前一日基準不同，直接相減即錯 |
| `action-not-announced-in-advance` | 公告日期不存在，或不早於生效日——無人能事先布局 |

## 3. 兩市場的差異首次在查詢層顯現

今日三項工作的結果，現在看得見：

| Session | 證券 | `corporate_action_state` | `action-not-announced-in-advance` |
|---|---|---|---|
| 2025-06-30 | 4763（上市面額變更）| `par_value_change` | **有**——TWSE 不提供公告日期 |
| 2026-03-09 | 8932（上櫃面額變更）| `par_value_change` | **無**——櫃買公告檔案帶發文日期 |

同一種事件、兩個市場、兩種證據等級，在同一個查詢介面上一眼可辨。這正是 [M3.13](m3-13-tpex-reduction-par-value-2026-08-19.md) §3 所述的互補關係。

## 4. 生效日不影響可交易性

除權息日股票照常交易，改變的是價格基準而非交易能力。若在此把 `tradability_state` 降級，等於在每一檔配息股的除息日把它踢出可選池。

`test_an_action_does_not_make_a_tradable_security_untradable` 明確固定這一點。

唯一會降級的情況是 **coverage 缺失**：查詢日期落在建置窗之外時 `tradability` 為 `unknown`，因為「當日無公司行動」與「該日期從未建置」不是同一件事。窗的起訖直接讀自 `corporate_actions_pit` 的 `dataset_manifest.json`，不另行假設。

## 5. 新增 8 項 invariant

寫在 M3.6 anti-lookahead 模組，其中三項是刻意的反向防護：

| 測試 | 防的是 |
|---|---|
| `test_an_ordinary_session_reports_no_action` | 旗標若永遠為真就沒有意義 |
| `test_an_action_does_not_make_a_tradable_security_untradable` | 過度保守把配息股踢出池 |
| `test_no_action_dated_after_the_session_ever_appears` | 呈現未來除息日 |
| `test_a_later_cutoff_does_not_change_what_happened_that_day` | 有人日後把行動「修正」成依 cutoff 過濾，重新製造虛構虧損 |
| `test_an_announced_action_is_not_labelled_as_unannounced` | 公告日期停止流入表而無人察覺 |
| `test_a_date_outside_the_built_window_is_unknown_not_empty` | 窗外被讀成「查無事件」 |

`output_hash` 的輸入亦加入 `corporate_action_state`，否則兩次重建的差異不會反映在雜湊上。

## 6. 實測

以 2025-07-15 為例：**29 檔當日有公司行動**（現金股利 27、股利含配股 2），其中 19 檔標記為無法事先得知——與 TWT49U 不提供公告日期、而 TEJ 補充僅涵蓋部分事件的已知狀態一致。

測試：220 通過、2 strict xfail。M3.7 驗證五項全 `passed`。

## 7. 未解決

1. **`corporate_actions_pit` 仍有兩份**——M3.4 產出官方版（as-of 讀的是這份），M3.9 產出 TEJ 補公告日版（僅上市）。因此上市除權息的 2,279 筆公告日期**尚未進入 as-of**，故 §6 中 19/29 標為無法事先得知。合併是下一項工作。
2. 上市面額變更仍無公告日期，維持 `action-not-announced-in-advance`。
