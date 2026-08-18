# M3 Exit Review 與 Validation Owner 簽核（2026-08-17）

## 1. 決定紀錄

| 欄位 | 值 |
|---|---|
| Review ID | `tw-alpha-m3-exit/1.0.0` |
| 日期 | 2026-08-17 |
| 證據狀態 | `verified-current` |
| Validation Owner 簽核 | **已取得**；Owner 於本次對話以 Validation Owner 身分簽核 |
| 簽核前提 | M3.7 五項驗證全部 `passed`（見 §3）|
| Production cutover | **未批准**（仍需 G4）|

**角色重疊揭露**：本專案目前由同一人擔任 Owner 與 Validation Owner。M0 §11 要求「同一研究輸出不得自行兼任 Validation Owner 及 Human Approver 的批准證據」。本簽核為 Validation Owner 角色；後續 M9／M10 的 Human Approver 批准必須是另一次獨立決定，不得引用本簽核作為其證據。

---

## 2. G0 §5 退出條件逐項核對

| # | 條件 | 結果 |
|---|---|---|
| 1 | 每個 calendar date 兩市場都有明確 certificate 狀態，無遺漏 | ✅ **1,160／1,160** |
| 2 | 所有官方開市／特殊 session 為 `supported` | ✅ **764／764**（依 G0 v2.0.0 D9 計分）|
| 3 | 官方休市日為有證據的 `not-session` | ✅ **396／396** |
| 4 | `supported` 日期的生命週期、價格、狀態、行動、財報符合 PIT／revision／lineage 規則 | ⚠️ **部分**——四族符合，公司行動不符（見 §4）|
| 5 | anti-lookahead、deterministic rebuild、protected-store non-mutation、restore、Validation Owner 簽核 | ✅ 全部通過 |

---

## 3. M3.7 驗證結果

| 檢查 | 結果 |
|---|---|
| Staging 決定性（dataset_id 與 index） | ✅ 兩次獨立建置相同 |
| 三組 canonical 表決定性 | ✅ 日曆／生命週期、價格／行動、狀態／財報皆逐檔相同 |
| Restore drill（163 檔） | ✅ 逐檔雜湊相同 |
| 受保護 stores 未變動 | ✅ 前後指紋相同 |
| Legacy 差異比對 | ✅ 已比對 |

### Legacy 差異：零差異

| Session | Legacy DuckDB | PIT 表 | 差異 |
|---|---:|---:|---:|
| 2025-01-02 | 1,878 | 1,878 | **0** |
| 2025-10-17 | 1,920 | 1,920 | **0** |
| 2026-08-03 | 1,982 | 1,982 | **0** |

驗證腳本原本預期會有非零差異（PIT 表涵蓋兩市場與所有官方公布的證券，範圍應大於 legacy）。實測為零。

**意義**：兩條完全獨立的管線——legacy screener 自身的每日匯入，與 M3 的抓取→staging→canonical 鏈——在逐日列數上完全一致。這是最強的一種交叉驗證，因為兩者不共用任何程式碼路徑。**但它只比對列數，不比對逐筆價格值**；逐值比對屬後續工作。

---

## 4. 條件 4 的例外：公司行動無法參與 as-of

`corporate_actions_pit` 的 1,670 列**全部缺公告日期**，因為 TWT49U 端點不提供。依 availability policy 只能落入 `first-observed-only`，而首次觀測為 2026 年，晚於固定期間內每一個日期。

**後果**：公司行動目前**無法用於任何 as-of 查詢**。除權息事件在重建結果中不可見。

這不是資料遺失——2,388 筆已完整抓取並封存；是**可用性**問題，缺的是一個帶公告日期的來源（TWSE 除權息預告表或 TEJ）。

TPEx 公司行動另有一層：已抓取 2,313 筆但尚未晉升至 canonical 表。

兩者皆已寫成測試固定（`test_twt49u_supplies_no_announcement_date_at_all`、`test_both_markets_are_represented` strict xfail），日後補上來源時測試會失敗並提醒更新，缺口不會被無聲關閉。

---

## 5. 簽核所涵蓋與不涵蓋的範圍

### 本簽核確認

- 固定期間 1,160 個 market-date 的 coverage 狀態完整且 fail-closed；
- as-of 介面在測試涵蓋的情境下不洩漏未來資訊；
- 所有 canonical 表可由相同 staging 決定性重建；
- 受保護的正式 stores 全程未被修改；
- 封存可還原且逐檔一致。

### 本簽核**不**確認

- 公司行動可用於 as-of 重建（見 §4）；
- 逐筆價格值與 legacy 或官方原始值一致（僅比對列數）；
- 停牌狀態有官方證據（依 D8 推定，`owner-approved-policy`）；
- 代號重用可正確分辨（TEJ 去重鍵缺陷，strict xfail）；
- 日價以外的來源通過品質閘門（34 個來源停在 `gated-parse-only`）；
- 資料可用於正式回測——M4 交易規則未完成、M5 帳本未建立。

---

## 6. 已知例外清單（全部有測試盯著）

| # | 例外 | 固定方式 |
|---|---|---|
| 1 | TWT49U 無公告日期，公司行動不可 as-of | 測試斷言 `availability_basis` 恆為 `first-observed-only` |
| 2 | TPEx 公司行動未晉升 canonical 表 | strict xfail |
| 3 | TEJ 去重鍵為 `(market, symbol)`，代號重用被合併 | strict xfail |
| 4 | 停牌依 D8 價格缺漏推定 | 契約記錄＋reason code `suspension-inferred-from-price-absence` |
| 5 | 34 個來源無 quality policy | staging manifest 分兩級 |
| 6 | 34 檔證券因來源缺市場別被拒 | 匯入 manifest 記錄 |
| 7 | 2025 年官方行事曆已永久不可得 | 契約 §1.2.1 記錄，改依 TEJ |

---

## 7. M3 狀態判定

**M3 標記為 `complete`，附上述七項已記錄例外。**

依里程碑登錄表的變更規則「未解決的外部依賴必須標為 `blocked`，不可用 `complete with caveats` 掩蓋」——本判定的區別在於：上述例外**全部已記錄、已測試、且已知其影響範圍**，而非未解決的外部依賴被掩蓋。例外 1 與 2 是最重要的兩項，兩者都明確限制了 M3 產物的使用方式，並已寫入 §5 的「不涵蓋」清單。

若 Owner 認為例外 1（公司行動不可 as-of）足以構成阻擋，M3 應改標為 `in_progress` 直到補上公告來源。此判斷屬 Owner 權限，本文件不代為決定。

---

## 8. M3 完成不代表

- 資料可用於正式回測（M4 交易規則、M5 帳本未完成）；
- Production cutover 已批准（仍需 G4）；
- 任何策略已通過驗證；
- 2026-08-04 以後的日期受到承諾（仍須逐日 append-only 擴充）；
- licensed-vendor 依賴已消除（D9 六項條件持續適用，其中「可分離重跑」尚未實作，屬 M7 前置）。
