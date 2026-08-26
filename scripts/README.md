# Evidence Scripts

這些腳本產生 `docs/evidence/` 下的證據文件。全部針對 `C:\project\tw-sepa-screener` 執行，路徑寫死在腳本內。

執行方式（需要 Taiwan Core 的虛擬環境）：

```bash
cd /c/project/tw-sepa-screener && ./.venv/Scripts/python.exe <script>
```

## M2

| 腳本 | 用途 | 寫入 |
|---|---|---|
| `final_m2_audit.py` | 對 primary 與 E: backup 執行 release-aware archive audit | 無（唯讀）|
| `m2_release_once.py` | 建立唯一的 `TWSE-ACTIONS-HIST` quarantine release event | M2 primary archive（一次性，已執行）|
| `m3_entry_archive_audit.py` | 依 source 彙整 M2 archive 的欄位與時間範圍 | 無（唯讀）|
| `m3_entry_db_audit.py` | Legacy DuckDB 唯讀盤點 | 無（唯讀）|

## M3

| 腳本 | 用途 | 寫入 |
|---|---|---|
| `m3/m3_gate_check.py` | 比對受保護 stores 與 baseline 指紋、重驗 M2 兩份封存 | 無（唯讀）|
| `m3/source_state.py` | 重算 `src` + `tests` + `pyproject.toml` 的 source-state 指紋 | 無（唯讀）|
| `m3/evidence_inventory.py` | 盤點耐久封存內的 endpoint 與 logical period | 無（唯讀）|
| `m3/archive_96_session.py` | 將 96-session shadow 複製到 primary 與 E: backup | 新目錄（一次性，已執行）|
| `m3/verify_96_archive.py` | 三份副本逐檔比對、96 個 blob 重算雜湊、寫入 archival record | 新封存目錄內的 record 檔 |
| `m3/build_coverage_ledger.py` | 產生 G0-A 固定期間 1,160 列 coverage ledger | 新目錄 `data\raw_v2\m3_coverage_ledger_2026-08-16` |
| `m3/derive_tpex_action_universe.py` | 由該窗口的官方報價推導上櫃公司行動回補的股票池 | 指定的 symbols JSON 與 manifest（封存唯讀）|
| `m3/build_coverage_ledger_v5.py` | 六年窗口（2019-01-01 起）的 coverage ledger，含兩條上櫃公司行動 lane | 新目錄 `data\raw_v2\m3_coverage_ledger_2026-08-24-v5` |
| `m6/rotation_feasibility.py` | 由凍結資料集量排序週轉率與成本閘門效果，**不跑回測** | 無（唯讀，輸出到 stdout）|

`capture_tpex_actions.py` 另有 `--rewrite-manifest`：不送任何請求，只從 append-only ledger 重算 lane manifest。用於 manifest 被一次「什麼都沒做的續跑」覆寫之後的修復（見 [M3.16](../docs/evidence/m3-16-tpex-actions-2019-2023-2026-08-24.md) §4）。

### 為什麼股票池要用腳本推導

上櫃公司行動只能逐 symbol-year 向 MOPS 查詢，因此回補前必須先有清單，而**清單的來源就是這次回補能不能看見已下市證券的全部理由**。沿用 2024–2026 那份 899 檔（推導自 2025–2026 報價）去問 2019 年，等於拿今日名單問六年前：2019–2023 有 55 檔在窗口內交易過但不在該清單中，全部會靜默缺席。改由「交易所當時真的印出報價」推導，取數機制才與它必須捕捉的失敗模式（下市）無關。

## 安全規則

沒有任何腳本可以寫入 `data\tw_sepa.duckdb`、`data\raw`、`data\stock_master.csv` 或 M2 primary／backup 封存的既有檔案。`m3_gate_check.py` 在每輪工作前後執行，用來證明這一點。
