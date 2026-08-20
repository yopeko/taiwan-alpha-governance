# M3.15：合併兩份 `corporate_actions_pit`（2026-08-19）

## 結論

同名的兩份表已合併為一份。TEJ 除息公告日期併入 canonical 表，`publisher-exact` 由 2,191 筆增為 **3,753 筆**，無公告日期者由 1,670 筆降為 **108 筆**。

as-of 重建中，除權息日標記為「無法事先得知」的比例由 **19/29 降為 0/29**。

## 1. 問題：兩份表、同一個名字

| 產出者 | 路徑 | 內容 |
|---|---|---|
| `build_prices_actions`（M3.4）| `pit-prices-*/corporate_actions_pit.parquet` | 兩市場、官方為主體、上市無公告日期 |
| `import_dividend_announcements`（M3.9）| `actions-avail/corporate_actions_pit.parquet` | 僅上市、含 TEJ 公告日期 |

**as-of 讀的是前者**，所以 M3.9 補上的公告日期從未進入決策路徑。[M3.14](m3-14-actions-in-asof-2026-08-19.md) 把公司行動接進 as-of 後，這一點才顯現出來：29 檔中 19 檔標為無法事先得知，而那些日期其實早就有了，只是在另一份表裡。

## 2. 順帶修掉一個耐久性缺口

M3.9 的 dataset manifest 記錄其 TEJ 來源為 `C:\tmp\tej-cash-both\a\20260818102515.csv`——**一個 /tmp 路徑**。整份公告日期建立在一個隨時可能消失的檔案上。

因此先把它匯入 licensed-vendor lane：

| 項目 | 值 |
|---|---|
| 新增 module | `dividend-announcement`（`tej_import.py`）|
| 必要欄位 | `證券代碼`、`年月日`（除息交易日）、`除息公告日` |
| 匯入結果 | 5,010 列全數接受，0 拒絕、0 重複鍵 |
| Archive | `m3_tej_dividends_2026-08-19` |
| Tree SHA-256 | `241872492e78cb01f6e6406130a019ab4a15dd66b6cdd8d92dcc8dc6109774ad` |
| 來源 SHA-256 | `fe544b72859f8c9763e4f03affbf34fe8a48a10782b1251a0136aa55b6dc4d79`（與 M3.9 相同檔案）|

## 3. 合併規則與 M3.9 完全相同

`apply_announcements()` 只處理**沒有公告日期且來自 TWT49U** 的列。已帶日期的列不動——那是它自己的發布者給的，供應商不得覆寫發布者。

三種結果各自明示：

| 結果 | 條件 | 筆數 |
|---|---|---:|
| `publisher-exact` | 供應商日期早於除權息日 | **1,562** |
| `unknown-blocked` | 供應商日期不早於除權息日 | 0 |
| `first-observed-only` | 供應商無此事件 | 103 |

**供應商仍然不定義事件集合。** M3.9 已證實 TEJ 缺少交易所確實公告過的事件；反向 join 會無聲刪除它們。

同一除權息日若有多筆供應商公告，取**最早**者——與官方行動的去重方向一致：相同條件公告兩次，第一次起就已可知。

## 4. 一個需要更正的數字

M3.9 的標題數字是「2,388 官方事件中 2,279 筆取得 `publisher-exact`」。canonical 表只有 **1,665** 筆 TWT49U 列，差 723 筆。

逐筆比對後：**723 筆全部在 M0 範圍外**——ETF 645 筆（`00400A`、`006203` 等）、REIT 與特別股 78 筆（`01001T`、`1101B`、`020036` 等）。

**四位數普通股一筆未少（差集為 0）。**

M3.9 的腳本直接讀原始封存、不套用 M0 的 `four-digit-common-stock-v1` scope；canonical 表套用。因此 2,388 是較寬的母體，不是 canonical 表漏了東西。M0 範圍內的正確數字是 **1,665 筆事件、1,562 筆 `publisher-exact`（93.8%）**。

## 5. 表名不再重複

`import_dividend_announcements.py` 改寫 `action_availability_audit.parquet`，並在 docstring 標明其表產出者身分已被取代、保留為推導該 join 的稽核紀錄。`corporate_actions_pit` 現在**只有一個產出者**。

M3.9 的 invariant 一併移到 canonical 表——**守著沒人讀的表等於沒守**。移轉時調整兩處：

- 列數斷言 2,388 → 1,665、`first-observed-only` 109 → 103（§4 的 scope 差異）；
- `lead_days` 不是 canonical 表的欄位，改由 `announced_at` 與 `effective_date` **當場計算**，儲存值不會漂移。

## 6. 一個記錄缺口的測試，因缺口關閉而改寫

`test_twt49u_supplies_no_announcement_date_at_all` 原本斷言 TWT49U 的列一筆都沒有公告日期。合併後不再成立。

但它守的風險並未消失，只是移位了：**供應商的日期若披著官方證據的外衣，讀者會把 TEJ 的話當成交易所的話。** 改寫為：

- TWT49U 列若有公告日期，`announcement_evidence_state` 必為 `licensed-vendor-snapshot`；
- 沒有的則必為 `missing-at-source` 且 `first-observed-only`；
- 另新增一項：`evidence_state` 恆為 `verified-snapshot`——供應商貢獻一個欄位，其餘（事件集合、參考價、漲跌停）都是交易所的，若它跟著跑進供應商 lane，官方紀錄已被悄悄改標。

## 7. 結果

| 指標 | 前 | 後 |
|---|---:|---:|
| `corporate_actions_pit` 份數 | **2** | **1** |
| 列數 | 3,861 | 3,861（未變）|
| `publisher-exact` | 2,191 | **3,753** |
| 無公告日期 | 1,670 | **108** |

### as-of 可見度

| Session | 當日有公司行動 | 標為無法事先得知（前 → 後）|
|---|---:|---|
| 2025-07-15 | 29 | **19 → 0** |
| 2026-07-31 | 8 | **5 → 0** |

剩餘 108 筆無公告日期者：103 筆 TEJ 未涵蓋（維持 `first-observed-only`）、5 筆上市面額變更（維持 `unknown-blocked`，無任何來源提供）。

測試：224 通過、2 strict xfail。M3.7 驗證五項全 `passed`，三張表重建逐位元一致。

## 8. 未解決

1. **103 筆 TEJ 未涵蓋的除權息**仍不可用於 as-of。需要另一個公告來源，或接受這些事件在歷史上不可預期。
2. **5 筆上市面額變更**仍無公告日期（MOPS `ajax_t05st01` 已驗證可行，未建）。
3. TEJ 匯入的 `security-listing` 去重鍵仍為 `(market, symbol)`，代號重用被合併（strict xfail，與本次無關）。
