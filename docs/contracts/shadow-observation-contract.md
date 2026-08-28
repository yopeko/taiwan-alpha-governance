# Shadow 觀察契約（M9 前半）

| 欄位 | 值 |
|---|---|
| 契約版本 | `shadow-observation-v1.0.0`（2026-08-28）|
| 狀態 | `baseline-approved`，2026-08-28 |
| 用途 | 定義管線 shadow 觀察的內容、差異的定義，以及 60 個交易日怎麼數 |
| 核准 | Product Owner（單一簽核人）|

## 0. 為什麼是現在，以及為什麼不是策略 shadow

### 觸發它的是一個會用完的東西

[巢狀驗證契約 §6](nested-validation-contract.md) 記了一件事：**封存區只有 382 個場次，每開封一次就消耗一點，而它不會再生。**

補充證據的來源只有一個——**時間往前走**。2026-08-03 之後的每一個交易日都是這個窗口裡不存在的新資料，而且它不需要任何人裁決就會產生。

**這份契約的用途，是把時間變成證據。** 不做它，專案就只能反覆消耗一塊固定的資料。

### 但這不是策略 shadow，策略 shadow 走不了

M0 §9 的升級軌道是 `idea → research → validated → shadow → paper → canary → formal`，且明寫「不得跳過任何狀態」。§9.2 要求 `validated → shadow` 前策略 artifact 必須先凍結。

**目前沒有任何候選是 `validated`。** [比較 001](../evidence/m7-comparison-001-result-2026-08-28.md) 的登錄結果是兩個候選誰都沒有勝出，封存區未開封。

所以本契約定義的是**管線 shadow**：觀察資料本身，不觀察任何策略的損益。它不推進 §9 的軌道，也不主張推進。

### 為什麼管線 shadow 仍然有意義

M0 §9.2 對 `shadow → paper` 的條件寫的是「**資料到達、訊號時間與 no-trade 原因穩定後**才可進入」。

那三件事全部是管線的性質。策略 shadow 需要它們先成立，而它們現在就可以開始被觀察。**先做的那一半不會白做。**

## 1. 觀察什麼：as-of 保真度

整個倉庫的核心主張只有一句：**「這是在日期 D 當時可以知道的東西。」**

那句話目前由建構方式保證——lane 帶 `announced_at`、as-of 介面 fail-closed、測試盯著。**但它從來沒有被對照過當天實際看得到什麼。**

管線 shadow 就是那個對照：

| | 何時取得 | 內容 |
|---|---|---|
| **當日觀察** | 交易日 D 收盤後 | 當天實際擷取到的市場狀態 |
| **as-of 重建** | 任何日後時點 | 倉庫回答「D 當天可知」的重建結果 |

兩者的差異就是 as-of 保真度。**零差異是這個倉庫最強的一次驗證；非零差異是它最有價值的一次發現。**

## 2. 差異的定義

比較 `ReconstructionResult` 的四個面向。每一項獨立記錄，不合併成一個分數——**合併會讓一項的惡化被另一項的改善蓋掉**，這與候選報告契約拆開稀缺與塞不下是同一個理由。

| 差異項 | 定義 |
|---|---|
| `session_state_divergence` | 當日觀察到的開市狀態與重建結果不同的市場數 |
| `universe_divergence` | 兩邊證券集合的對稱差集大小 |
| `tradability_divergence` | 兩邊都有、但 `tradability_state` 不同的證券數 |
| `price_divergence` | 兩邊都有、但 OHLC 任一值不同的證券數 |

**`universe_divergence` 是最重要的一項。** 它直接量測倖存者偏誤：若日後重建的股票池與當天實際存在的不同，那個差就是回測看得到而當時看不到的東西。

## 3. 差異不等於缺陷，但一定要有解釋

一筆非零差異必須落入下列其一，且理由碼要記錄：

| 理由碼 | 意義 |
|---|---|
| `late-arriving-official-data` | 官方資料在 D 之後才發布，重建因此更完整。**這是預期行為**，as-of 介面用 `announced_at` 隔離它 |
| `revision-of-published-value` | 官方修訂了已發布值。倉庫保留兩者，重建取當時可見的那一個 |
| `capture-failure-on-the-day` | 當日擷取失敗，觀察方缺資料而非重建方多資料 |
| `unexplained` | **以上皆非。這是缺陷，必須開單。** |

**`unexplained` 是這整份契約在找的東西。** 其餘三類已經有機制處理；只有第四類代表 as-of 的主張在某處不成立。

## 4. 60 個交易日怎麼數

M0 §9.2 的門檻是 60 個交易日。本契約對「管線 shadow 的 60 天」定義如下：

1. **只有官方開市日計數。** 休市日沒有可觀察的東西。
2. **當日擷取失敗的日子不計數**，且記為 `capture-failure-on-the-day`。一個沒有觀察到的日子不能算作觀察過。
3. **計數不可回溯補算。** 用歷史資料「補觀察」在定義上是不可能的——當日觀察必須在當日取得，否則它就是重建而不是觀察。
4. **有 `unexplained` 差異的日子照常計數**，但該差異必須在門檻達成前結案。數天數與修缺陷是兩件事。

**天數只能由時間累積，不能由任何方式加速。** 這是本契約唯一不可協商的性質，也是它存在的理由。

## 5. 產物

append-only，每個觀察日一列：

```
<shadow-root>/
    shadow_observations.jsonl     每個交易日一列，只增不改
    shadow_manifest.json          計數、窗口、契約版本
```

### 5.1 每列必填

| 欄位 | 說明 |
|---|---|
| `session_date` | 被觀察的交易日 |
| `observed_at` | 當日觀察的實際取得時間 |
| `observation_source` | 當日擷取的產物位置與雜湊 |
| `reconstruction_dataset_id` | 用來比對的倉庫 dataset id |
| `session_state_divergence` / `universe_divergence` / `tradability_divergence` / `price_divergence` | §2 四項 |
| `divergence_reason_codes` | §3 的理由碼；零差異時為空 |
| `counts_towards_threshold` | 布林，依 §4 |

### 5.2 manifest 必填

| 欄位 | 說明 |
|---|---|
| `trading_days_observed` | 目前計入門檻的天數 |
| `threshold` | 60 |
| `first_observation` / `latest_observation` | 窗口兩端 |
| `unexplained_open` | 尚未結案的 `unexplained` 差異數 |

## 6. 本契約不涵蓋

- **策略 shadow。** 需要一個 `validated` 候選，目前沒有。本契約不推進 M0 §9 的軌道。
- **紙上下單。** 那是 paper，M9 的後半。
- **真實委託。** M0 §10 禁止，M12 未授權。
- **自動排程。** 每日觀察怎麼被觸發屬營運，不屬契約。

## 7. 這份契約承認的限制

**它只能往前累積。** 寫下它的當天，計數是 0，而且沒有任何辦法讓它不是 0。

**當日觀察的品質受限於擷取當時的可得性。** 若某個官方端點在 D 當天故障，那天就是 `capture-failure-on-the-day`，不計數——這會讓門檻變慢，而那是正確的：一個沒被觀察到的日子不該算數。

**零差異不證明 as-of 是對的**，只證明它在被觀察的那些日子上沒有錯。60 天是 M0 訂的門檻，不是一個統計上的充分量。

## 8. 相關文件

- [M0 專案契約](../m0-project-contract.md) §9.2 時間觀察門檻、§10 明確禁止事項
- [巢狀驗證契約](nested-validation-contract.md) §6：封存區會用完
- [M3 Point-in-time warehouse 契約](pit-warehouse-contract.md)
- [比較 001 結果](../evidence/m7-comparison-001-result-2026-08-28.md)
