# 一個寫死的窗口上界，出現在三支建表程式裡

| 欄位 | 值 |
|---|---|
| 日期 | 2026-09-03 |
| 狀態 | 三支皆已修正並重建 |
| 起因 | M9 日常軌道要把資料補到今日，第一支建表程式回報成功但產出 0 列 |
| 相關 | [D22](m3-owner-decision-d22-2026-09-01.md)、[D23](m3-owner-decision-d23-2026-09-02.md) |

## 0. 一句話

**六年重建當天寫下的一個日期常數，被留在三支建表程式裡當成「窗口的上界」，而三支都不會說話。**

## 1. 怎麼被發現的

2026-08-04 至 09-02 的補抓完成，staging 收下 **43,603 列**新的價格觀測。
`build_prices_actions` 跑完，`exit=0`，manifest 顯示：

```
daily_prices_pit.rows  3,316,101      （與補抓前一模一樣）
```

**新增 0 列，而且沒有任何一行輸出提到這件事。** 原因是：

```python
WINDOW = (date(2019, 1, 1), date(2026, 8, 3))
```

每個 `session_date > 2026-08-03` 的觀測都被 `continue` 掉了，沒有計數、沒有警告。

## 2. 修完第一支之後才去看另外兩支

這是本專案第六與第七次同形狀的缺陷（前五次記在 [current_build.py](../../scripts/m3/current_build.py) 的檔頭與 M3.17）。修完 `build_prices_actions` 之後**主動去找同一個常數**，在另外兩支找到了：

| 建表程式 | 常數 | 失效方式 |
|---|---|---|
| `build_prices_actions` | `WINDOW[1]` | 過濾器——丟掉場次 |
| `build_calendar_lifecycle` | `WINDOW_END` | 產生器上界——日曆停在該日，as-of 介面就問不到之後的任何一天 |
| `build_status_fundamentals` | `WINDOW[1]` | **開放區間的結束值——把仍生效的限制提前到期** |

## 3. 第三支不是同一種失效

前兩支停在舊日期，答案是**缺的**，而缺是看得見的：價格表最大場次是 2026-08-03，任何人一眼就知道它沒到今天。

第三支不一樣。`build_full_cash_delivery` 用這個常數當作**尚未解除的全額交割**的 `effective_to`：

```python
"effective_to": end or WINDOW[1].isoformat(),
```

一個 2025 年被打入全額交割、至今未解除的名字，會被寫成「2019-xx-xx 至 **2026-08-03**」。也就是說——**它在 2026-08-04 自動變成正常股票。**

實測，同一份 staging，只差 `--window-end`：

| 2026-09-02 當日仍生效的限制 | pit-status-11（舊）| pit-status-12（新）|
|---|---:|---:|
| 全額交割 | **0** | **31** |
| 處置 | **0** | **24** |
| 減資 | **0** | **1** |

**舊倉庫的答案是「今天沒有任何一檔受限」。那不是缺資料，那是錯答案。** 31 檔不能用普通交割買進的股票，會以「可自由買賣」的身分進入股票池。

而 [判斷式研究契約](../contracts/discretionary-research-contract.md) §3.2 的隨機對照，母體正是 `tradability_state == eligible`。

## 4. 修法

三支都加 `--window-end`，**預設 None，省略時行為完全不變**——常數本身一個字沒動：

```
WINDOW     = (date(2019, 1, 1), date(2026, 8, 3))   # build_prices_actions
WINDOW_END =  date(2026, 8, 3)                      # build_calendar_lifecycle
WINDOW     = (date(2019, 1, 1), date(2026, 8, 3))   # build_status_fundamentals
```

**不改預設是刻意的。** 六年重建的三張表要能被原樣重現，改預設會讓「不帶參數重跑」產出與紀錄不同的表，而那正是本專案一路在防的事。

三支的 manifest 都改成記錄**實際生效的窗口**而不是常數，否則帶參數的一次跑起來與不帶的長得一樣。

`build_prices_actions` 另外加 `sessions_outside_window` 計數：**一個不留下數字的判斷，正是 43,603 列變成 0 列而沒有人知道的原因。**

## 5. 重建結果

staging-14：19,044 個觀測、3,573,272 列，1 小時 45 分，`production_unchanged: true`。

| 表 | 舊 | 新 |
|---|---|---|
| `daily_prices_pit` | 3,316,101 列 / 1,840 場次 / 止於 2026-08-03 | **3,359,704 列 / 1,862 場次 / 止於 2026-09-02** |
| `trading_calendar_pit` | — | 5,604 列（開市 3,724、休市 1,880）|
| `market_status_pit` | 55,030 列 | **56,008 列** |

新增 22 個場次，43,603 列（TWSE 24,070、TPEX 19,533）——與 staging 收下的數字一致。

## 6. 這次留下的守門

`tests/unit/test_daily_observation_lane.py` 對三支各驗四件事：常數本身沒被動、覆寫參數存在且預設為 None、manifest 記錄實際窗口、命令列露出 `--window-end`。

加一個**行為測試**（不需授權資料即可跑）：一段 2026-08-20 開始、尚未結束的上市區間，對常數自身的上界回答「不在窗口內」，對 `2026-09-02` 回答「在」。

**這些守門擋得住回歸，擋不住第四支。** 真正的規則寫在 `current_build.py` 檔頭——**本模組以外不得有任何模組指名倉庫目錄**——而日期常數還沒有等價的規則。下一支新建表程式若再寫一次日期，目前沒有東西會攔它。

## 7. 仍未關閉

- **TPEx 公司行動停在 2026-08-24 前後。** 上櫃的 9 天缺口不會被靜默補上，它會在 `tradability_state` 裡呈現為 `unknown`。補齊要靠 [`monthly_tpex_actions.cmd`](../../scripts/m3/monthly_tpex_actions.cmd)，約 2.5 小時，尚未排程。
- **日期常數沒有集中化。** 見 §6 最後一段。
