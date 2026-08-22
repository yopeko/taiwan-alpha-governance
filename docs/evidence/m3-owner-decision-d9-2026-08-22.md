# M3 Owner 決定 D9：全額交割的 availability basis（2026-08-22）

## 決定

**採 A：全額交割的 availability basis 為 `approved-conservative-bound`，
`announced_at = effective_from`。**

同時補正 [source-to-table map](../contracts/m3-source-to-table-map.md) §2.2，
availability policy `tw-alpha-m3-availability/1.1.0` → `1.2.0`。

決定人：Owner／Validation Owner。日期：2026-08-22。

---

## 1. 待決事項

全額交割（`event_kind = full-cash-delivery`）已進入 `market_status_pit`，622 筆事件，
影響 **10,004 個場次**——這些場次先前一律標為 `eligible`，等於宣稱它們可以正常交易。

問題不在要不要記錄，而在**何時可以認定市場已經知道**。

契約 §5 的 `availability_basis` 是封閉清單。廠商提供全額交割的**起迄區間，但不提供
公告日**。這使得：

- 記為 `unknown-blocked` → `announced_at` 留空 → `is_knowable("")` 恆為 False
  → **事件進了表但完全不生效**，10,004 個場次回到 `eligible`；
- 記為 `publisher-exact` → 不成立，我們手上沒有公布時間的證據。

剩下的是 `approved-conservative-bound`，而契約 §5 明定該基準需 **Validation Owner
批准**。故不由建置者自行認定。

## 2. 被批准的實作

`announced_at = effective_from`、`availability_basis = approved-conservative-bound`。

理由：**全額交割是持續狀態，不是突發事件。** 區間內的任何一個交易日，該證券就是
以全額交割方式在交易——買方須先繳足價金、賣方須先交付證券，委託才被接受。這在當日
對任何參與者都是可見的。本政策只主張「不早於生效日可知」。

## 3. 呈報的證據

### 3.1 誤差方向對我們有利

交易所的公告必然**早於或等於**生效日。我們主張的可知時點是生效日。

| | 真實 | 我們的主張 |
|---|---|---|
| 可知時點 | 公告日 | 生效日 |
| 關係 | 公告日 ≤ 生效日 | **不早於真實** |

**因此本政策的誤差方向是「比事實晚知道」，不是「比事實早知道」。**
前視偏差是本專案最嚴重的失效模式，而這個 bound 在結構上不可能產生它。

反向的風險——廠商的生效日比實際更早——只會讓證券**提前**被標為 `restricted`，
使回測更保守，同樣不產生前視。

### 3.2 廠商日期落在真實交易日上

窗口內開始的全額交割區間共 **23 段，23/23**（100%）該證券在區間起日當時確實有
官方報價。憑空產生的日期不會全數落在有交易的日子。

### 3.3 區間終點與下市日大量重合

291 段「有結束日且該證券已下市」的區間中，**166 段（57.0%）結束日與下市日完全相同**。
其餘 125 段是解除全額交割後多年才因其他原因下市的公司，屬另一種正常情形。

166 次日期完全吻合不可能是巧合，代表這些區間端點記錄的是實際發生的事。

### 3.4 個案：與我們自己的官方價格資料互相印證

**1589 永冠-KY**（廠商稱全額交割自 2026-02-24 起）：

| 日期 | 收盤 | 我們資料集的判定 |
|---|---:|---|
| 2025-01-02 | 34.95 | `eligible` |
| 2026-02-23 | — | `eligible` |
| **2026-02-24** | **15.25** | **`restricted`（全額交割）** |
| 2026-03-05 | 8.19 | `restricted` + 注意 + 處置 |
| 2026-04-02 | 5.54 | `restricted` |
| 2026-04-07 | 無報價 | `blocked`（推定停牌）|

廠商的全額交割起日落在一段可獨立觀察的惡化過程中間，**其後我們自己的官方狀態來源
才陸續出現注意與處置事件**。日期不是憑空的。

## 4. 呈報的三個選項

| 選項 | 10,004 個場次 | 前視風險 | 代價 |
|---|---|---|---|
| **A. `approved-conservative-bound`＝生效日** | `restricted` | **結構上為零**（誤差方向為偏晚）| 損失「公告日至生效日」之間的反應時間 |
| B. `unknown-blocked` | 回到 `eligible` | 零 | **資料進了表卻不生效；全額交割股被當成正常可交易** |
| C. 擷取交易所變更交易方法公告後再啟用 | 暫時回到 `eligible` | 零 | 需新增一條官方來源與擷取工作；在此之前同 B |

### 我的建議：A

B 的代價不是「保守」，是**錯誤**——把全額交割股標為正常可交易，是對事實的積極錯誤陳述，
比承認「我們只知道它不晚於生效日才可知」更糟。

C 是正確的長期方向，但它與 A 不衝突：取得官方公告日之後，可將這些列升級為
`publisher-exact`，`approved-conservative-bound` 自然退場。**A 是通往 C 的路上該站的位置，
不是 C 的替代品。**

## 5. 批准後的狀態

10,004 個場次自 `eligible` 轉為 `restricted`，每一列帶 `status-full-cash-delivery`。
本基準的適用範圍**僅限** `("full-cash-delivery", "TEJ-COMPANY-MASTER")`，由 §6 第 1 條測試強制。

取得交易所變更交易方法公告（含公告日）後，這些列應升級為 `publisher-exact`，
屆時本基準對本資料族退場。**批准 A 不是放棄 C，是把 C 之前的位置定義清楚。**

## 6. 已鎖住的約束

下列三條不變量測試強制本裁決的邊界：

1. `approved-conservative-bound` **僅限** `("full-cash-delivery", "TEJ-COMPANY-MASTER")`
   使用——避免未來某個來源因為擷取公告日麻煩而伸手拿這個基準；
2. 使用該基準者，`announced_at` **不得早於** `effective_from`；
3. `announced_at` 有值 ⟺ basis 屬於 `{publisher-exact, approved-conservative-bound}`。

## 7. 相關

- 契約 [§6.5.1](../contracts/pit-warehouse-contract.md)
- 稽核與四項修正紀錄 [audit-finmind-crossvalidation-2026-08-21.md](audit-finmind-crossvalidation-2026-08-21.md) §7.8
- 同類先例：[D11 減資 `FILE_DATE`](m3-owner-decision-d11-2026-08-19.md)
