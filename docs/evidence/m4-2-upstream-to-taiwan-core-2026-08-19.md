# M4.2：上游化至 Taiwan Core 與指紋異動（2026-08-19）

## 結論

M4 契約自訂的最後一項阻擋條件已解除。規則模組的 canonical 位置改為 Taiwan Core 的 `tw_sepa_screener.market_rules`,並依契約要求記錄 source-state 指紋異動。

**M0 對 M4 的退出條件全部滿足。**

## 1. 當初為何延後

契約原文:

> 參考實作放在治理倉庫的 `m4/` 而非 Taiwan Core。理由:M3.1f 的 TPEx 抓取執行中,其 producer evidence 綁定 Taiwan Core 目前的 source-state 指紋 `d4ef6c0f…`;此時修改 `src/` 會使進行中的 M3 證據與指紋不一致。

理由只有指紋一項,而 M3 抓取已於 2026-08-19 全部結束。

## 2. 一個直接搬移會造成的損失

治理 CI 跑在 GitHub Actions,`ci.yml` 自己寫明:

> Archives and the Taiwan Core checkout live only on the operator's machine, so a runner can only prove the static and pure-logic invariants.

M4 的 118 項規則測試**純邏輯、只需要 Python**,是 CI 真正跑得到的少數測試之一。若把模組搬上游並刪除本地副本,這 118 項會從所有自動化執行中消失,只剩操作者本機可驗。

`ci.yml` 用 `-ra` 的理由正是「讓『這裡驗過』與『只在本機驗過』的界線保持可見,而不是悄悄縮小」。直接搬移正好會悄悄縮小它。

## 3. 採用的作法:單一真相 + 強制一致的鏡像

| 位置 | 角色 |
|---|---|
| `tw_sepa_screener.market_rules`（Taiwan Core）| **canonical**。交易系統實際呼叫的地方 |
| `m4/rules.py`（治理倉庫）| **逐位元相同的鏡像**,供 CI 執行測試 |

由 `tests/invariant/test_m4_upstream_parity.py` 以 SHA-256 比對強制一致,並額外確認 canonical 模組在 Taiwan Core 環境下可 import 且行為正確——**逐位元相同不足以保證它在會被使用的地方載得起來**。

改動任一份,parity 測試即失敗。兩者都不是分支。

測試分工:

- 完整邊界套件（118 項）留在治理倉庫,對鏡像執行——而鏡像被證明與 canonical 相同;
- Taiwan Core 另有 6 項 smoke test（`tests/test_market_rules.py`）,驗證模組在該套件內可載入並重現官方數值。這是治理套件無法涵蓋的部分。

## 4. 指紋異動

| 指紋 | 檔數 | 期間 |
|---|---:|---|
| `d4ef6c0f50f4c480…` | 180 | M2 release 至 M3 抓取結束。**2026-08-03 至 08-19 的每一份 archive 記錄此值** |
| `898ef48aa2395e8c…` | 182 | 本次上游化後 |

新增的兩個檔案即 `src/tw_sepa_screener/market_rules.py` 與 `tests/test_market_rules.py`。Taiwan Core 的 HEAD 未變(`fb87f62f…`)。

**既有 archive 記錄的舊值不重寫。** 那些擷取確實發生在該狀態下,是歷史事實。

### 未 commit Taiwan Core

Taiwan Core 的工作樹在本次之前就已是 dirty(數十個與本工作無關的既有修改),這正是 `dirty_fingerprint` 這個欄位存在的原因。在該倉庫執行 commit 會把那些無關修改一併納入,超出本次工作範圍,故**未 commit**。新增的兩個檔案以 untracked 狀態存在,指紋演算法涵蓋 untracked 檔案,因此已計入。

## 5. 順帶消除一個八份複本的漂移風險

該指紋原本**硬編碼在八個腳本裡**:七個擷取腳本的 argparse 預設值,加上 `build_staging` 與 `m3_gate_check` 的 `PRODUCER` dict。

這是本倉庫反覆修過的同一種形狀——必須一起變動的值,存放在會分別變動的地方。今年已出現過:指向過期產物的三個路徑、重複的 §4.2、兩份 `corporate_actions_pit`。

現在集中於 `scripts/m3/source_state.py`,該檔本來就知道如何計算指紋:

| 匯出 | 用途 |
|---|---|
| `SOURCE_STATE_FINGERPRINT` | 唯一寫下的值 |
| `SOURCE_STATE_HISTORY` | 每個曾被 archive 記錄過的值及其期間 |
| `producer(commit=None, fingerprint=None)` | producer metadata;兩部分皆可覆寫,讓重現舊執行的人能標記它實際跑的狀態 |
| `current_fingerprint()` | 由本機 checkout 重新計算 |

保留歷史的理由:**一個 stamp 若無法回溯到某個狀態就無法閱讀**。archive 裡的 `d4ef6c0f…` 必須永遠查得到它代表什麼。

`scripts/final_m2_audit.py` 刻意保留舊值——它稽核的是 M2 release,必須引用 M2 當時的狀態。

### 新增 5 項守護測試

`tests/invariant/test_source_state_fingerprint.py`:

| 測試 | 防的是 |
|---|---|
| 指紋只寫在一處 | 有人再度把它複製進腳本 |
| 記錄值與實際 checkout 相符 | **Taiwan Core 被改動而常數未更新,使此後每一次擷取都標記一個不存在的狀態** |
| 歷史涵蓋每個 archive 可能記錄過的值 | 舊 stamp 變得無法解讀 |
| 現行值是歷史的最後一項 | 兩者各自更新而不一致 |
| `producer()` 使用記錄值且可覆寫 | 預設值悄悄偏離 |

第二項是其中最重要的:它把「指紋失真」從一個沒人會發現的錯誤,變成一個測試失敗。

## 6. 驗證

| 項目 | 結果 |
|---|---|
| Taiwan Core smoke tests | 6 通過 |
| 治理倉庫 | **233 通過**、2 strict xfail |
| `m4/tests` | 118 通過 |
| 鏡像雜湊 | `7e24c123cfa06df3…` 兩邊相同 |
| M3.7 驗證 | 五項全 `passed` |
| 建置與擷取腳本 | 集中化後仍可執行,`--dirty-fingerprint` 預設值為新指紋 |

## 7. 對既有產物的影響

`build_staging` 的 `PRODUCER` 現在標記新指紋,因此**往後重建 staging 會得到與 staging-10 不同的 `dataset_id`**。

這是內容定址正常運作,不是缺陷。M3.2 證據早已寫明:「改程式即產生新 dataset,不會偽裝成同一份」。既有產物記錄它們建置當時的狀態,並未失效。

## 8. M4 退出條件

| M0 要求 | 狀態 |
|---|---|
| 交易單位、零股 | ✅ |
| 檔位 | ✅ 406,445 筆實測推導 |
| 漲跌停（一般日／除權息日／減資恢復日）| ✅ 皆以官方公布值驗證 |
| 停牌 | ✅ 由 M3 提供 |
| 交割 T+2 | ✅ |
| 費用、稅、滑價 | ✅ 結構完成且可設定 |
| 官方範例測試 | ✅ |
| 券商條款可設定 | ✅ `BrokerTerms`,`evidence_state="assumption"` |
| **參考實作上游化** | ✅ **本次** |

券商實際費率仍未定,依 M0 該項阻擋的是 M10 canary,不阻擋 M4。

## 9. 未解決

1. ~~**Taiwan Core 未 commit**——其工作樹的既有 dirty 狀態早於本次工作,是否整理屬 Owner 決定。~~

   **2026-08-27 解決，且它不是整潔問題。** 未 commit 的正是 `market_rules.py` 與 `ledger.py` 本身——兩個檔案從上游化那天起就是 untracked，不是被 ignore，只是從未 `git add`。

   本文件與里程碑登錄都寫著它們是 canonical、治理倉庫這邊是雜湊強制一致的鏡像。實際的權威方向是反的：**有 git 歷史的只有鏡像**。一個沒有 commit 的檔案無法 diff、blame、revert 或復原。

   parity 測試組從頭到尾全綠。它比對兩份檔案位元相同、檢查兩者可 import，沒有一條問過被稱為 canonical 的那一份有沒有歷史。

   Owner 於 2026-08-27 裁示在 Taiwan Core 提交（`afce687`，1,402 行）。`test_the_canonical_copy_is_under_version_control` 從此盯著它，任一份再度脫離版控即轉紅。
2. **M5 現金／股票帳本尚未開始**——`test_no_impossible_trade_can_settle` 仍為 strict xfail。
