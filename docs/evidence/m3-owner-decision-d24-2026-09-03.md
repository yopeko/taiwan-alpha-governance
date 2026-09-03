# Owner 決定 D24：三個契約修訂追認、資料集改指 dataset-10、M9 每日軌道登記（2026-09-03）

| 欄位 | 值 |
|---|---|
| 日期 | 2026-09-03 |
| 簽核 | Product Owner（單一簽核人）|
| 前次 | [D23](m3-owner-decision-d23-2026-09-02.md)，2026-09-02 |

## 決定一：三個契約修訂全部追認

| # | 契約 | 版本 | 內容 |
|---|---|---|---|
| 甲1 | [判斷式研究](../contracts/discretionary-research-contract.md) | v1.0.0 → **v1.1.0** | `outcome` 階段新增必填的 `controls` 欄位 |
| 甲2 | 同上 | v1.1.0 → **v1.2.0** | 等權池基準由淨額改毛報酬，欄位更名 `equal_weight_universe_gross` |
| 甲3 | [試驗登錄](../contracts/trial-ledger-contract.md) | v1.1.0 → **v1.2.0** | `purpose` 新增 `method-selection` |

三者的理由分別記在各自契約的修訂記錄裡，此處不重複。共同的一點：**三個都是把契約已經說過、但沒有任何東西執行的規則變成機械的**，或把契約說錯的一句改對。沒有一個放寬約束。

**甲2 是其中唯一有時效性的**：它在第一次決策之前定案，否則第一份判定會帶著一個被美化 50 個百分點的基準。

## 決定二：`RESEARCH_DATASET` 改指 `dataset-10`

| | 舊 | 新 |
|---|---|---|
| 研究資料集 | `tw-alpha-m6-dataset-09`，1,840 場次 | **`tw-alpha-m6-dataset-10`，1,862 場次** |
| 對應價格表 | `pit-prices-12` | **`pit-prices-13`** |
| 封存切分 | `tw-alpha-m7-split-01` | **`tw-alpha-m7-split-02`** |
| 開發側 | 1,458 場次 | **1,458 場次（不變）** |
| 封存側 | 382 場次 | **404 場次** |
| **開封次數** | **0** | **0** |

邊界是固定日曆日 `2025-01-01` 而不是百分比，所以延長窗口**不移動邊界**，只讓封存側變長。這是 [`split_sealed_dataset.py`](../../scripts/m7/split_sealed_dataset.py) 當初選日期而不選百分比的設計在付利息。

### 我預測開發側會逐位元不變，而那是錯的

實測：62,613,461 對 **63,061,086** 位元組，雜湊不同。

拆開之後：

- **沒有任何一列消失**
- 多了 **2,916 列 = 2 檔證券 × 1,458 個場次**：`TWSE:2237` 與 `TWSE:7855`

| 證券 | `tradability_state` | `reason_codes` | 有收盤價 |
|---|---|---|---:|
| TWSE:2237 | 1,458 列全 `ineligible` | `not-in-lifecycle-source \| out-of-scope-emerging-board \| suspension-inferred-from-price-absence` | 0 |
| TWSE:7855 | 1,458 列全 `ineligible` | `not-yet-on-any-board \| suspension-inferred-from-price-absence` | 0 |

一檔興櫃（超出 M0 範圍），一檔後來才上市。**資料集自己的註記正好說這件事**：「超出範圍是一個帶理由碼的判定，不是一個缺席。」

### 真正要緊的宣稱，查了而不是假設

**開發側的合格集合逐列相同：**

```
舊 eligible  2,429,932 列
新 eligible  2,429,932 列
鍵只在舊 0    只在新 0    共同鍵中欄位值不同 0
```

價格、漲跌停、基準全部相同。所以**既有的候選結果（對照 001、候選 003–006、診斷 002–004）仍然有效且可比**，它們讀的那些列一個位元都沒動。

不逐位元相同但可交易的部分逐列相同——**這兩件事必須分開說**，因為前者聽起來像後者的否定。

## 決定三：M9 每日軌道登記排程

已註冊 Windows 工作 `tw-alpha-m9-observation`，**每日 18:30**，`StartWhenAvailable`，執行時限 2 小時。

**不是軌道文件原本寫的 18:00。** `tw-alpha-daily-status` 自 2026-08-22 起佔著 18:00，而**兩支都會向交易所擷取**。兩條擷取軌道同時起跑會架空各自的禮貌間隔，而 0.7 秒的間隔曾讓這台機器的位址被 twse.com.tw 拒絕超過一天。狀態快照是 8 個來源、一分鐘內結束；半小時的間隔遠超所需，而間隔是便宜的那一邊。

**計數仍為 0/60。** 本決定讓計數開始有可能前進，不讓它前進——第一個可計數的日子是這條鏈路第一次成功執行的開市日，而那不能回溯補算（[D22](m3-owner-decision-d22-2026-09-01.md)）。

## 決定四、五、六：先不做

| # | 事項 | 決定 |
|---|---|---|
| 四 | 月度上櫃公司行動排程（`monthly_tpex_actions.cmd`）| **先不登記** |
| 五 | [提案 001：脫離風險式定量](m7-proposal-001-sizing-basis-2026-09-02.md) | **先不決定**，維持 `awaiting-owner-decision` |
| 六 | 執行巢狀驗證產物（`run_nested_validation.py`）| **不執行** |

**決定六的理由值得寫下來**：執行它會花掉一次封存區開封，而目前沒有任何候選是 `validated`，所以現在跑等於白花一次不會再生的東西。開封次數維持 **0**。

**決定四的後果要說清楚**：上櫃公司行動目前補到 2026-10-22（預告除權息），所以短期不缺。但那個 lane 不會自己更新，**而缺口不會發出聲音**——它會在 `tradability_state` 裡呈現為 `unknown`，而現在 `unknown` 是零。下次量到非零的 `unknown` 且歸因於 `corporate_action_no_coverage` 時，就是這條決定該被重看的時候。

## 相關文件

- [D22：M9 觀察端改為獨立當日擷取](m3-owner-decision-d22-2026-09-01.md)
- [D23：判斷式研究軌道獲准](m3-owner-decision-d23-2026-09-02.md)
- [判斷式研究契約](../contracts/discretionary-research-contract.md) §3.3、§3.4、§12
- [試驗登錄契約](../contracts/trial-ledger-contract.md) §1
- [`tradability_state` 的分佈](m3-tradability-distribution-2026-09-03.md)
