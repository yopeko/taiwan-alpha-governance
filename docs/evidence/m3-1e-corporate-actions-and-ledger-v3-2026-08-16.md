# M3.1e 完成證據：公司行動抓取與 Coverage Ledger v3（2026-08-16）

## 結論

TWSE 公司行動歷史抓取完成，20/20 區塊成功，取得 **2,388 筆**除權息紀錄。

Coverage ledger v3 首次出現 `supported`：**若 Owner 接受 TEJ 授權廠商證據，TWSE 全部 382 個交易日達到 `supported`**。

但這需要一項 G0 修訂，而 TPEx 仍無法達成。兩者都需要 Owner 決定，本輪不自行認定。

---

## 1. TWSE 公司行動抓取

| 欄位 | 值 |
|---|---|
| Schema ID | `tw-alpha-m3-corporate-action-capture/1.0.0` |
| 來源 | `TWSE-ACTIONS-HIST`（TWT49U）|
| 期間 | 2025-01-01 至 2026-08-03，逐月共 20 區塊 |
| 結果 | **captured 20，失敗 0** |
| 總列數 | **2,388** |
| `production_unchanged` | `true` |

月分布呈現明顯季節性：2025-06 為 245 筆、2025-07 為 428 筆，2026 同期為 272 與 425 筆，其餘月份多在 34 至 104 筆之間。此分布符合台股除權息集中於六至八月的實際情形，是資料合理性的旁證。

**授權範圍**：`TWSE-ACTIONS-HIST` 正是 M2 唯一被初始隔離為 `license-owner-approval-required`、其後由 `M2-OWNER-APPROVAL-20260803-01` 放行的來源。該批准的範圍為「TWT49U 專案內保存／M3 研究驗證」，本次抓取落在此範圍內，未擴張授權。

### 耐久封存

| Copy | 路徑 | Files | Bytes |
|---|---|---:|---:|
| Primary | `data\raw_v2\m3_actions_2025-01-01_2026-08-03` | 42 | — |
| Backup | `E:\tw-sepa-screener-backup\raw_v2\m3_actions_2025-01-01_2026-08-03` | 42 | — |

Tree SHA-256：`4a78f6f9b2ba7017b6fb87c238838a4a9eb102570e3f780b69021225d2d35efe`，三份各自重算 20 個 blob 相符。

---

## 2. TPEx 公司行動：無區間端點

已探測下列 TPEx 路徑，皆回傳同一份 10,892 bytes 的 SPA 外殼頁而非 JSON：

```text
/www/zh-tw/afterTrading/exRight
/www/zh-tw/afterTrading/exRightDividend
/www/zh-tw/afterTrading/exright
/www/zh-tw/afterTrading/exDaily
/www/zh-tw/bulletin/exRight
/www/zh-tw/bulletin/exDividend
/www/zh-tw/bulletin/exRightDividend
```

`openapi/v1/tpex_exright_prepost` 可用但為 current-only（149 筆），即已註冊的 `TPEX-ACTIONS-PREPOST`，**不得**用來填補歷史。

**TPEx 唯一的歷史路徑是 MOPS 逐檔逐年 POST**（`ajax_t108sb19` + `ajax_t108sb22`），既有 client 的介面即為 `fetch_symbol_year(symbol, year)`。以約 890 檔上櫃證券 × 2 年計算，需 **1,780 次以上的 list 請求，外加每筆公告的 detail 請求**，量級遠高於本輪其他抓取。

因此 TPEx 公司行動維持 `unknown`，**未**以 current-only 來源靜默填補。

---

## 3. Coverage Ledger v3

| 欄位 | 值 |
|---|---|
| Certificate ID | `tw-alpha-m3-coverage-ledger-20260816-03` |
| Supersedes | `tw-alpha-m3-coverage-ledger-20260816-02` |
| 列數 | 1,160 |

### 雙軌計分

TEJ 提供的證券生命週期與財報申報日屬 `licensed-vendor-snapshot`，不是官方 raw-v2 證據。**這類證據能否滿足 `supported`，是 G0 未涵蓋的問題，本 build 不自行認定**，因此同時輸出兩種計分：

| State | 嚴格（僅官方證據）| 若接受授權廠商證據 |
|---|---:|---:|
| `supported` | **0** | **382** |
| `partial` | 764 | 382 |
| `not-session` | 396 | 396 |
| `unknown` | 0 | 0 |

發布的 `reconstruction_state` 欄位採**嚴格**計分以維持 fail-closed；寬鬆計分另存於 `reconstruction_state_if_vendor_accepted` 欄位供決策參考。

### 若接受授權廠商證據，逐市場結果

| 市場 | `supported` | `partial` | `not-session` |
|---|---:|---:|---:|
| **TWSE** | **382** | 0 | 198 |
| TPEx | 0 | 382 | 198 |

**TWSE 的每一個交易日都會達到 `supported`。** TPEx 全數卡在公司行動。

### 嚴格計分下的阻擋項

| 阻擋 | 影響 market-date |
|---|---:|
| `security_lifecycle=licensed-vendor` | 764 |
| `fundamental=licensed-vendor` | 764 |
| `corporate_action=unknown`（TPEx）| 382 |

---

## 4. 需要 Owner 決定的兩件事

### 決定一：授權廠商證據可否滿足 `supported`？（G0 修訂）

[G0 決定](m3-g0-owner-decision-2026-08-03.md) §4 定義 `supported` 為「所有必要資料族均通過 gate」，但當時尚無 licensed-vendor lane，因此未規範此情形。

- **若接受**：TWSE 382 個交易日立即達 `supported`。代價是這些日期的證券生命週期與財報可用性依賴單一商業供應商，且 TEJ 為可修訂的現值資料庫。緩解措施是匯入器已強制每列保存 `snapshot_id` 與 `source_file_sha256`，可完整追溯與重現。
- **若不接受**：`supported` 維持 0，直到官方補齊歷史上市日與財報申報日——但官方目前**沒有**提供這兩項的歷史查詢，實務上等同無限期擱置。

這需要新的 G0 版本，不得由執行方自行放寬。

### 決定二：TPEx 公司行動是否投入 MOPS 逐檔抓取？

三個選項：

1. **執行 MOPS 逐檔逐年抓取**——約 1,780 次以上請求，需另設速率與重試政策，工作量約為本輪全部抓取的總和；
2. **查 TEJ 是否有上櫃除權息歷史**——TEJ 的財報大檔已含股利欄位（期末普通股現金股利、股票股利等），可能足以替代，但需確認是否具備除權息基準日；
3. **接受 TPEx 不達 `supported`**——以新的 G0 版本將承諾範圍限縮為 TWSE，TPEx 維持 `partial` 並禁止用於回測。

---

## 5. 本輪未做也未獲授權的事

- 未以 current-only 來源填補 TPEx 公司行動歷史；
- 未自行認定授權廠商證據可滿足 `supported`；
- 未修改 Taiwan Core 的 `raw_registry.py`；
- 未覆寫正式 DuckDB、legacy raw、stock master；
- 未建立 M3.2 append-only staging；
- 未將 M3 標為 `complete`。
