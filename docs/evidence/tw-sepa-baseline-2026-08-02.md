# tw-sepa-screener M2 Entry Baseline

## 1. 證據範圍

| 欄位 | 值 |
|---|---|
| 擷取時間 | 2026-08-02T22:15:53.2782907+08:00 |
| 路徑 | `C:\project\tw-sepa-screener` |
| 模式 | read-only audit；未 reset、刪除、搬移、stage 或修改 |
| 證據狀態 | `verified-current` dirty worktree snapshot |
| 用途 | M2 回歸與漂移檢查，不是備份或 release |

## 2. Git 與工作樹指紋

| 項目 | 值 |
|---|---|
| branch | `master` |
| HEAD | `fb87f62f8c2c68e2b85982cd102a35fd935bc0a4` |
| HEAD tree | `ec70ebff62996c28ee1649dab262aa85b43abbe4` |
| HEAD commit time | 2026-07-17T20:13:49+08:00 |
| HEAD subject | `feat: compare SEPA signal profiles` |
| tracked modified | 29 files |
| tracked diff stat | 5,812 insertions、362 deletions |
| modified-file content manifest SHA-256 | `a17ee5a65bcb2d8dbcdfbed69ae91b3749f431baff9bd2678c15603a8b8edcec` |
| tracked diff canonical SHA-256 | `15c87e093d6320bb4de9b9492d24447c9db5feedce5cf19a070d47f43f298481` |
| git-visible untracked | 116 files、855,844 bytes |
| untracked content manifest SHA-256 | `dc19e51d676728608378d60ebc9ce2548ed741d608c0986da6b3352804a34fe4` |

完整逐檔 SHA-256 見 [worktree manifest](tw-sepa-worktree-manifest-2026-08-02.txt)。Manifest 規則為 path 依 ordinal 排序，每行 `sha256␠␠path`，各區塊以 LF 連接且末尾無 LF 後計算 aggregate hash。

Untracked 分布：

| 根目錄 | 檔案數 |
|---|---:|
| `.codex_tmp` | 51 |
| `docs` | 5 |
| `examples` | 2 |
| `reports` | 12 |
| `scripts` | 4 |
| `src` | 20 |
| `tests` | 22 |

此指紋只證明當時內容，不能取代可恢復備份。任何 M2 實作前都應重算並比較；不同時先判斷是使用者新變更或預期 M2 變更，不可自動覆蓋。

## 3. 執行環境

| 元件 | 版本 |
|---|---|
| Python | 3.12.13 |
| DuckDB | 1.5.5 |
| pandas | 3.0.5 |
| pyarrow | 24.0.0 |
| pytest | 9.1.1 |

依賴版本來自 `C:\project\tw-sepa-screener\.venv` 的實際 import，不等同 lockfile。M2 parse manifest 仍須加入 lockfile／dependency fingerprint。

## 4. DuckDB 基線

| 項目 | 值 |
|---|---|
| 檔案 | `data/tw_sepa.duckdb` |
| bytes | 425,209,856 |
| last write | 2026-08-01T06:37:37.0268331+08:00 |
| file SHA-256 | `c948a1bd62ff141eabd2216bec358a1b8ea129dd0821bcc785bffe75648bbfba` |
| main tables | 45 |
| columns | 910 |
| canonical schema SHA-256 | `6df85f04461ebdd58c98b0bd9a9303b0307907a69889b82db528d09628e28d39` |

`schema_migrations` 有三筆：

1. `20260718_01_strategy_version_governance`
2. `20260718_02_historical_intraday_bars`
3. `20260718_03_future_strategy_supersession`

目前沒有專門的 raw snapshot schema migration 或 raw manifest table；這是 M2 待實作範圍。

## 5. Legacy raw tree 基線

| 項目 | 值 |
|---|---|
| recursive files | 4,988 |
| bytes | 188,391,038 |
| top-level Parquet | 4,896 |
| `mops_history_news` Parquet | 92 |
| recursive content manifest SHA-256 | `9b09a95aae389c9502d48201066f9470a86792ec834db1c6a0d32132b9a6993b` |
| top-level readable Parquet | 4,896／4,896 |
| distinct Arrow schemas | 17 |
| top-level schema manifest SHA-256 | `eeb5b2ebf7e95799d31112ac7f7158ae91e791445055cafc641d56b7a97ff99c` |

Recursive content manifest 規則為：遞迴檔案依 full path ordinal 排序，relative path 正規化成 `/`，每行 `sha256|bytes|relative_path`，以 UTF-8 LF 連接且末尾無 LF。

最大宗 schema 有 4,666 檔，涵蓋 normalized 日線；其餘包含月營收、季度財報、公司行動、指數、MOPS 公告、TEJ 與 Yahoo prototype。所有檔案依 [raw snapshot contract](../contracts/raw-snapshot-contract.md) 分類為 `legacy-normalized-snapshot`，不是原始 HTTP payload。

## 6. 目前 raw helper 行為

- `storage.write_raw_snapshot` 把 DataFrame 寫成 `{source}_{trade_date}.parquet`。
- `atomic_write_parquet` 先寫 sibling temporary file，再以 `os.replace` 發布。
- 優點：失敗時不暴露半檔，舊完整檔仍可保留。
- 限制：同名路徑成功重跑會完整替換舊檔；無 payload bytes、HTTP manifest、hash ID、parser version 或 parse-run lineage。
- pipeline 是先將 API payload parse 成 canonical rows，再呼叫 raw helper；因此不能由現有檔案重跑不同 parser。

## 7. 測試基線

2026-08-02 以 project venv、`-p no:cacheprovider` 與獨立 `C:\tmp` basetemp 執行下列資料相關測試：

- atomic IO；
- TWSE／TPEx parser 與 sources；
- daily market pipeline；
- market backfill 與 fundamentals；
- data quality、stock master 與 PIT storage；
- MOPS history、announcements、TPEx actions；
- corporate actions／adjustments。

結果：`40 passed in 4.91s`。

這是 legacy 行為回歸基準，不代表 raw v2 驗收已通過。特別是既有測試明確要求第二次 atomic write 取代第一個完整 artifact；M2 必須新增不同的 immutable observation 行為，不能破壞通用 atomic publication helper。

## 8. Baseline 使用規則

- 不以此文件授權修改或整理 dirty worktree。
- 不以 aggregate hash 推定個別檔案誰擁有或是否可刪除。
- M2 實作應在變更前後重算工作樹，並將預期變更與使用者平行變更分列。
- DB 與 legacy raw 指紋只供驗證；不得覆寫、compact、migrate 或回填，除非另有明確實作批准與可恢復備份。
