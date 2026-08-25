# M3.17 六年窗口重建，與它叫醒的三件事（2026-08-25）

## 0. 這一步的產出就是壞掉的東西

M3.16 把五個資料族補到 2019，但 staging 與三組 canonical 表仍是 382 個場次的舊建置。本次以六年窗口重建，並事先聲明預期會壞——跨過制度變更會叫醒只有拉長窗口才會現身的缺陷。

它壞了三次，三次都是真的。

## 1. 結果

| 表 | 列數 | 重點 |
|---|---:|---|
| `trading_calendar_pit` | 5,544 | official-open **3,680**、official-closed 1,864、**unknown 0**，與 coverage ledger v5 逐格相符 |
| `security_intervals` | 2,068 | 117 下市（56 交易所確認、3 由交易所補、**1 截斷**），`missing_at_source` 0 |
| `daily_prices_pit` | **3,316,101** | 1,840 個場次、2,096 檔證券，收斂重複 94,948 列 |
| `corporate_actions_pit` | 12,522 | TPEX 5,485／TWSE 7,037，publisher-exact 7,221 |
| `market_status` / `fundamentals` | 55,030 | 停牌 160、處置 1,880、全額交割 622、減資 319、面額變更 24 |

Staging：`adopted_observations` 18,955、`adopted_rows` 3,528,461、`production_unchanged: true`，dataset_id `ae98a5d4…`。三張表的 `staging_dataset_id` 相同，由測試強制。

價格由 M6 Phase 2 凍結的 749,484 列增至 3,316,101，**4.4 倍**，與場次 382 → 1,840 的比例相符。

`TWSE-PRICE-HIST` 有 932 筆 `parse-rejected`——那是 TWSE 對休市日的回應方式，而 932 恰好等於 v5 ledger 的 `not-session` 1,864 ÷ 2 個市場。是設計行為，不是缺陷。

## 2. 機器睡眠殺掉了第一次嘗試

```
01:12:29  最後一個檔案寫入
01:12:39  id=187  User-mode process attempted to change the system state by calling SetSuspendState
01:12:40  id=42   The system is entering sleep
```

跑了約 6 分鐘、產出 6,025 個 parse manifest 就被殺，stdout／stderr 皆 0 bytes——緩衝區隨行程消失，所以看起來像無聲失敗。

**兩天內第二次**：M3.16 的 TPEx 擷取死在 655/4,310，同一個原因。差別在擷取可續跑，而 `build_staging` 刻意要求空目錄（append-only），被殺就是從頭來。

處置：監督腳本在執行期間持有 `ES_SYSTEM_REQUIRED`。那是**執行緒層級的執行狀態請求，不是設定變更**——行程結束即失效，不觸碰機器的電源組態，螢幕仍可休眠。加上之後 staging 撐完 79.8 分鐘、exit 0。

腳本註記了退路：若仍死於睡眠，代表這台是 modern standby，須由人變更電源設定；腳本不做那件事。

## 3. D14（提案）：交易所擁有下市日，廠商區間跨過它就截斷

### 現象

calendar 階段 6 秒內 fail-closed：

```
the exchange and the vendor disagree on a delisting date, which is a fact
the exchange owns; resolve it rather than choosing:
[{"symbol": "2432", "vendor": "2023-05-31", "official": "2008-09-01"}]
```

### 診斷

TEJ 對 2432 只有一筆紀錄，而它橫跨兩家公司：

```
OTC 1999-05-14 → TSE 2000-09-11 → TIB 2023-05-31    delisting_date: None
```

`board_legs()` 把一腿的結束設為下一腿的開始，然後標為 `delisting_date`——但 TSE → TIB 是**板別轉移不是下市**。交易所說 2432 於 2008-09-01 下市；那是倚天資訊。2023 在創新板掛牌的是倚天酷碁，代號被重新發行。兩個日期都是真的，屬於不同的公司。這就是已記錄例外 #3（TEJ 以 `(market, symbol)` 去重，代號重用被合併）。

**為什麼現在才炸**：舊窗口自 2025 起算，這條結束於 2023-05-31 的 TSE 腿根本不重疊；拉到 2019 才進入範圍。

### 決定（提案）

**官方下市名單給出日期時，任何廠商推導的區間不得延伸過該日期，超出部分截斷。** 理由與既有註解一致：「a delisting is the exchange's act」。廠商在該日之後記錄的，屬於這一列不描述的另一段人生；若那段人生為真，它需要自己的區間與自己的證據。

此規則與既有的「區間起始晚於官方下市日則跳過」互補：前者處理**晚於**，本規則處理**跨越**。

**影響範圍：1 檔。** 並已呈報，不靜默套用：

```
delisting_truncated_to_exchange: 1
intervals_starting_after_their_exchange_delisting: 0
```

新增呈報的理由寫在程式註解裡：一個看不見的更正，與「資料本來就不需要更正」無法區分，而這一次它把下市日移動了十五年。

### 尚未處理

2432 的區間帶著「倚天酷碁-創」這個名字——第二段人生的名字掛在第一段的區間上。拆開需要把一筆廠商紀錄分裂成兩段，比截斷更大的變更，本次不做。

## 4. 測試套件給了一次假的綠燈

### 現象

重建完成後全套測試 **422 passed**，與重建前**完全相同的數字**。

### 診斷

五個檔案各自寫死一個上一代的暫存路徑：

```python
PIT = Path(r"C:\tmp\tw-alpha-m3-pit-04")          # 2025–2026 那一代
def rows(name):
    if not path.is_file():
        pytest.skip("not built on this machine")   # 不在就靜默跳過
```

所以 422 passed 驗的是舊表，跟新建的六年表無關。**一個通過的測試比一份過期的文件更有說服力，所以指錯資料的測試比沒有測試更糟。**

第二個問題更安靜：那些是暫存路徑。清掉 `C:\tmp` 會讓整個 M3 不變量套件變成 skip，而在摘要行裡**全部 skip 和全部通過長得一樣**。

這正是 `test_capture_politeness` 已經替自己記下的教訓——「讀取器壞掉時每個案例都會 skip，而全部 skip 看起來和全部通過一樣」——沒有套用到它守護的輸出上。**同一條教訓，第二個地方，第三次。**

### 處置

**單一來源**：[`tests/warehouse.py`](../../tests/warehouse.py) 指名世代、窗口與三個根目錄。移動倉庫只改那幾行。

**不在就 fail 不是 skip**：`_require()` 區分兩種缺席——沒有 Taiwan Core 檢出（CI，合理 skip）與有檢出但倉庫不在（操作者的機器，必須 fail）。`conftest.py` 既有的 `--strict-env` 機制原本就是為此設計，只是這五個檔案沒有用它。

**守衛的守衛**：[`test_warehouse_generation.py`](../../tests/invariant/test_warehouse_generation.py) 五條，含「每個根必須有 manifest」（8/25 那次死於睡眠的目錄有 19,986 個檔案而沒有 manifest——**存在不等於完成**）與「三張表必須來自同一個 staging 層」（否則任何跨表不變量都在比較兩個不同的世界）。

**M6 資料集刻意留在舊世代**並在單一來源裡標明：它與 `pit-prices-09` 是配對的，換成六年表會拿 382 個場次比 1,840 個並把差異當成缺陷。

### 四個凍結在舊窗口的常數

改成關聯檢查，而不是換成新的字面值——換成 1,840 只是把同一個問題推到下一次窗口變更。

| 測試 | 原本 | 現在 |
|---|---|---|
| `test_no_session_outside_the_fixed_window` | `>= "2025-01-01"` | 讀 `warehouse.WINDOW` |
| `test_session_count_matches_the_calendar` | `== 382` | **實際比對日曆表**——它的名字原本就這麼承諾，body 卻是字面值 |
| `test_every_official_event_survives_the_join` | `== 1665` | 每個事件恰好落在一個可用性分類；自然鍵不重複 |
| `test_events_without_a_vendor_row_are_kept_not_dropped` | `== 103` | 該類不為空，且保留官方欄位與 `verified-snapshot` |

改完之後對六年表：`test_m3_3` golden dates **全數通過**。

## 5. D15（待裁決）：公告日 lane 沒有跟著回補

### 現象

無法定位公告日的公司行動比例，由舊窗口的 6.2% 升到 77.2%（6,854 筆中 5,292 筆為 `first-observed-only`）。

### 診斷

逐年拆開，是一道斷崖不是漸變：

| 年 | publisher-exact | first-observed-only | 不可用 |
|---|---:|---:|---:|
| 2019 | 637 | 801 | 55.7% |
| 2020 | 642 | 799 | 55.4% |
| 2021 | 684 | 867 | 55.9% |
| 2022 | 729 | 898 | 55.2% |
| 2023 | 731 | 907 | 55.4% |
| 2024 | 781 | 917 | 54.0% |
| **2025** | 1,677 | 65 | **3.7%** |
| 2026 | 1,340 | 38 | 2.8% |

斷崖位置正好是舊窗口的起點。查 lane 本身：`m3_tej_dividends_2026-08-19` 有 **5,010 列，`ex_date` 2025-01-02 .. 2026-08-18**。

**這不是 TEJ 沒有資料，是五個資料族回補到 2019、第六個沒有跟上。** 而沒有任何東西注意到，因為 coverage ledger 的 `corporate_action` 檢查的是行動有沒有被**擷取**，不是行動可不可**知**。v5 因此報出 3,680 個 supported，而其中六年的行動有一半以上永遠無法在當時生效。

### 後果

那些行動被正確地 fail-closed——決策當下看不到它們。代價是價格序列上留下無法解釋的跳空，而 M6 回測會踩在上面。

### 選項

| | 作法 | 代價 |
|---|---|---|
| A | 重新匯出 TEJ 股利公告 2019–2024 | 需要人工的 TEJ PRO 匯出；資料存在，只是沒被取回 |
| B | 接受現況，回測限縮在 2025 之後 | 等於放棄這次回補的六分之四 |
| C | 接受並明示標記受影響場次不可用於回測 | 保留窗口長度，但可用場次要重新計算 |

**A 是唯一不損失已完成工作的選項**，且成本是一次匯出。但它需要 Owner 執行——匯出是人工的廠商下載，不是我能觸發的動作。

### 已就位的守衛

[`test_vendor_lane_window_parity.py`](../../tests/invariant/test_vendor_lane_window_parity.py)：lane 的起始日必須不晚於價格窗口的起始日。目前記為 **strict xfail**，附完整理由。匯出一到位它會變成 XPASS 而**失敗**，強迫有人回來移除標記——一個缺口若只寫在文件裡，就是一個會被忘記的缺口。

## 6. 本次不代表

- **`validate_m3_7.py` 尚未執行。** 它自行重建 staging 兩次做決定性驗證，以現在的規模是 160 分鐘起跳，須單獨排程。在它通過之前，本次重建**未經決定性與 restore 驗證**。
- M6 資料集與帳本回測尚未以六年窗口重跑。
- D14 與 D15 皆為**提案**，未經 Owner 裁決。
- 廠商依賴未解除：股票池、板別區間與全額交割仍由 TEJ 定義。

## 7. 重跑方式

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File C:\tmp\m3-rebuild-supervisor.ps1
```

四階段循序，第一個失敗即停（把壞掉的 staging 餵進三個表建置，產出的是沒人能信的表，而且會蓋掉「哪一階段出錯」這個資訊）。執行期間持有 keep-awake。各階段 log 在 `C:\tmp\m3-rebuild-*.log`，總表在 `C:\tmp\m3-rebuild.log`。
