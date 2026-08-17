# M3.1f 完成證據：TPEx 公司行動抓取與 Coverage Ledger v4（2026-08-16）

## 結論

依 Owner 決定 D10 完成 TPEx 公司行動 MOPS 逐檔抓取。**固定期間內全部 764 個交易日達到 `supported`，396 個休市日為 `not-session`，`partial` 與 `unknown` 皆為 0。**

G0-A 的 **coverage 條件已滿足**。但 M3 **仍不可標為 complete**——G0 §5 另外要求 anti-lookahead、deterministic rebuild、restore 與 Validation Owner 簽核，這些屬 M3.2–M3.8，尚未開始。

---

## 1. 抓取執行

| 欄位 | 值 |
|---|---|
| Schema ID | `tw-alpha-m3-tpex-action-capture/1.0.0` |
| 證券 universe | 899 檔（固定期間內實際有交易者）|
| 民國年 | 113、114、115 |
| symbol-year 請求 | 2,697 |
| 耗時 | 48 分鐘 |
| `production_unchanged` | `true` |

| Outcome | 數量 |
|---|---:|
| `captured` | 1,901 |
| `official-no-announcements` | 789 |
| `detail-partial` | **7** |
| 公告總數 | **2,313** |
| 儲存觀測 | 5,019 |

## 2. 發現並修補的重試缺口

7 個 symbol-year 出現 `detail-partial`，全部是 MOPS 回 **502 Bad Gateway**。

根因是實作缺陷：`capture_symbol_year` 對 listing 請求有重試，**對逐筆明細請求沒有**。而續跑判斷以 listing observation 為鍵，因此直接重跑整批會把這 7 個 symbol-year 完全跳過，缺漏會靜默留下。

補救方式是另寫 [`retry_tpex_details.py`](../../scripts/m3/retry_tpex_details.py)，直接鎖定這些 symbol-year，並**從已擷取的 listing blob 重新導出公告參數**而非重新請求 listing——確保補抓的公告集合與當初觀測到的完全相同，不會因為來源在期間內變動而抓到不同內容。

結果：7 筆全部 `captured`，`retry-failed` 為 0。

## 3. 耐久封存

| Copy | 路徑 | Files | Bytes |
|---|---|---:|---:|
| Primary | `data\raw_v2\m3_tpex_actions_2024-2026` | 9,606 | 46,656,855 |
| Backup | `E:\tw-sepa-screener-backup\raw_v2\m3_tpex_actions_2024-2026` | 9,606 | 46,656,855 |

Tree SHA-256（三份相同）：`4ceb67e0634af98c0f1d50bf54eafe3aa6464b96dc117f70633485ea8fee3804`

驗證結果：**blobs_verified 5,010、hash_mismatches 0、missing_blobs 0**，另有 **16 筆 observations_without_payload**。

### 封存驗證器的修正

首次驗證把那 16 筆報成 `missing_blobs`，導致 `failed-verification`。追查後確認並非資料損壞：這些是 `capture_status=transport-failed` 的觀測，即框架**正確記錄下來的失敗嘗試**，本來就沒有 payload。例如 `company:TPEX:2641:year:114` 有一筆 transport-failed 觀測，但同一 symbol-year 在 ledger 中是 `captured`——重試成功了，失敗那次被保留為證據。

已修正 `archive_capture.py`：只對 `hash-verified` 觀測要求 payload，其餘計入 `observations_without_payload` 另行報告。這個區分很重要——把「已記錄的失敗嘗試」誤判為「資料遺失」會讓真正的遺失被雜訊淹沒。

---

## 4. Coverage Ledger v4

| 欄位 | 值 |
|---|---|
| Certificate ID | `tw-alpha-m3-coverage-ledger-20260816-04` |
| Supersedes | `tw-alpha-m3-coverage-ledger-20260816-03` |
| 列數 | 1,160 |

### 雙軌計分結果

| State | 嚴格（僅官方）| 依 D9（含授權廠商證據）|
|---|---:|---:|
| `supported` | 0 | **764** |
| `partial` | 764 | **0** |
| `not-session` | 396 | 396 |
| `unknown` | 0 | 0 |

### 逐市場（依 D9）

| 市場 | `supported` | `partial` | `unknown` | `not-session` |
|---|---:|---:|---:|---:|
| TWSE | **382** | 0 | 0 | 198 |
| TPEx | **382** | 0 | 0 | 198 |

嚴格計分下僅剩兩項阻擋，皆為 D9 已批准的授權廠商依賴：

| 阻擋 | market-date |
|---|---:|
| `security_lifecycle=licensed-vendor` | 764 |
| `fundamental=licensed-vendor` | 764 |

`corporate_action` 阻擋已完全消除。

### 全期間演進

| Ledger | `supported` | `partial` | `unknown` | `not-session` |
|---|---:|---:|---:|---:|
| v1（抓取前）| 0 | 3 | 1,140 | 17 |
| v2（日價後）| 0 | 764 | 0 | 396 |
| v3（狀態＋TWSE 行動後）| 382* | 382 | 0 | 396 |
| **v4（TPEx 行動後）** | **764*** | **0** | **0** | **396** |

\* 依 D9 計分。

---

## 5. G0-A 退出條件逐項檢查

| G0 §5 條件 | 狀態 |
|---|---|
| 1. 每個 calendar date 兩市場都有明確 certificate 狀態，無遺漏 | ✅ 1,160／1,160 |
| 2. 所有官方開市／特殊 session 為 `supported` | ✅ 764／764（依 D9）|
| 3. 官方休市日為有證據的 `not-session` | ✅ 396／396 |
| 4. `supported` 日期的生命週期、價格、狀態、行動、財報符合 PIT／revision／lineage 規則 | ❌ **未驗證**——屬 M3.3–M3.5 |
| 5. anti-lookahead、deterministic rebuild、protected-store non-mutation、restore、Validation Owner 簽核 | ❌ **未執行**——屬 M3.6–M3.8 |

**條件 1–3（coverage）已滿足；條件 4–5 尚未開始。**

因此 M3 的正確狀態是「coverage 完成，warehouse 未建」。抓到全部原始資料**不等於**能在指定 cutoff 正確重建當時狀態——後者需要 M3.2 的 append-only staging、M3.6 的 as-of 查詢介面，以及 M3.7 的重建與差異驗證。

---

## 6. 下一步

1. **M3.2 append-only staging**——現在才真正具備足夠輸入；
2. **M3.3–M3.5** 建立 PIT 表並驗證時間語意；
3. **M3.6 as-of 重建介面**與 anti-lookahead 測試；
4. **M3.7** deterministic rebuild、legacy 差異、restore drill；
5. **M3.8** Validation Owner 簽核。

另有兩項待處理：

- D9 條件 4 要求的「可分離重跑」能力尚未實作，屬 M7 前置；
- M4 參考實作待 M3 抓取全部結束後上游化至 Taiwan Core（抓取已結束，可安排）。

---

## 7. 本輪未做也未獲授權的事

- 未建立 M3.2 staging；
- 未覆寫正式 DuckDB、legacy raw、stock master；
- 未修改 Taiwan Core 的 `src/`；
- 未將 M3 或 M4 標為 `complete`。
