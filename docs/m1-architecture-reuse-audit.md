# M1 架構與重用稽核

## 1. 文件控制

| 欄位 | 值 |
|---|---|
| 稽核版本 | `m1-v1.0.0` |
| 完成日 | 2026-08-02 |
| AlphaMaster 基準 | `rosemarycox5334-debug/AlphaMaster@5d145b7ba8fec1577a2b48f37ac23cafa8aca0d4` |
| AlphaMaster 證據 | `verified-snapshot` |
| 台股核心位置 | `C:\project\tw-sepa-screener` |
| 台股核心 HEAD | `fb87f62f8c2c68e2b85982cd102a35fd935bc0a4` 加未提交工作樹 |
| 台股核心證據 | `verified-current`，但不是可重現 release |
| 稽核目的 | 固定 preserve／adapt／replace／reject 邊界與跨專案介面 |

## 2. 結論

採用「三個責任平面」：

1. **Taiwan Core**：`tw-sepa-screener`，擁有官方資料、Point-in-time、股票池、市場狀態、交易規則、現金帳本、正式策略版本、紙上／未來 canary 和每日營運。
2. **Research Lab**：AlphaMaster，擁有特徵／運算子註冊、公式 VM、候選生成、研究評估、實驗工作及研究 UI。
3. **Governance Repository**：本倉庫，擁有 M0/M1 契約、ADR、跨專案 schema、里程碑及退出門檻。

不把 AlphaMaster fork 全面改寫成台股 SoR，也不把 AlphaMaster 原始碼直接合併到 `tw-sepa-screener`。研究資料單向匯出，候選策略單向匯回；正式批准留在 Taiwan Core／治理平面。

## 3. AlphaMaster 現況證據

### 3.1 已確認能力

- `model_core/registry.py` 提供原子化的 Feature／Operator 註冊及名稱、欄位、arity 驗證。
- `model_core/vocab.py` 由有序 token 產生 deterministic SHA-256 版本，版本不符時拒絕舊 artifact。
- `model_core/vm.py` 提供公式結構及 StackVM 執行邏輯。
- `model_core/features.py`、`ops.py` 提供可重用的因果性技術、波動、成交量、流動性及橫截面機制。
- `model_core/evaluator.py`、`island_engine.py` 可支援退化檢查、相關性剪枝、消融及候選多樣性。
- `web/data_sources/base.py`、背景 training／backtest managers、`training_package.py` 提供資料源抽象、工作管理、checkpoint 與 artifact 封裝。
- tests 目錄提供 unit、property、smoke 類型的測試組織可參考。

### 3.2 已確認不適用假設

- 模型配置仍以 FTMO、forex、H1 與多空／beta 中性為重要背景。
- 訊號及回測使用連續 `tanh` 部位，而不是 NTD 現金與整數股數。
- MT5 fetcher、runner、risk、portfolio 與 margin／lot sizing 不符合台股現貨零股。
- Backtest 主要以報酬及比例成本計算，無法代表最低手續費、賣出稅、T+2、拒單及 partial fill。
- 預設公式搜尋及 walk-forward 配置不是台股驗證契約，需由 M7 重新定義。

### 3.3 上游 PR 與 Issue

- [A 股 PR #1](https://github.com/rosemarycox5334-debug/AlphaMaster/pull/1) 仍為 open、未合併、mergeable false。可借用 `market_rules`、UI 參數傳遞、資料切分預覽及規則測試思路；不可整體合併。
- PR 的 Eastmoney／pytdx 資料、A 股 T+1 與連續部位限制不符合台股官方來源、T+2、零股和現金帳本需求。
- [Issue #2](https://github.com/rosemarycox5334-debug/AlphaMaster/issues/2) 仍指出交易所連接缺口，證明 AlphaMaster 目前不能被視為完整交易執行層。
- [Issue #4](https://github.com/rosemarycox5334-debug/AlphaMaster/issues/4) 反映訓練吞吐問題；它屬研究效能議題，不應優先於資料和驗證完整性。

### 3.4 授權

AlphaMaster snapshot 使用 GNU AGPL-3.0。內部評估可以繼續，但修改、散布或提供網路互動服務前必須完成授權義務評估，尤其是遠端使用者取得對應原始碼的義務。此文件不是法律意見。

## 4. AlphaMaster 重用矩陣

| 類別 | 元件 | M1 決定 | 邊界 |
|---|---|---|---|
| Preserve | Registry、FeatureSpec、OperatorSpec | 保留機制 | 台股特徵仍須有 PIT 與 allowlist |
| Preserve | Vocab hash／artifact compatibility | 保留 | 納入候選封包 lineage |
| Preserve | StackVM／公式結構檢查 | 保留 | 只產生研究 score／rank |
| Preserve | Causal ops 與適用的技術特徵 | 保留後逐項審核 | 不因名稱是 causal 就免除 leakage 測試 |
| Preserve | AlphaGPT／formula sampler | 研究使用 | 無正式批准權 |
| Preserve | Evaluator／correlation pruning／ablation | 研究使用 | 不等於 M7 OOS gate |
| Preserve | Island search | 後期候選多樣性 | 多島一致不是正式證據 |
| Preserve | Training／backtest job managers | 保留工作管理模式 | 不沿用 MT5 命令或正式回測語義 |
| Preserve | Training package／checkpoint | 保留封裝模式 | schema 必須加 dataset、rule、cost、evidence hashes |
| Preserve | Charts／reports | 保留視覺框架 | 改讀 NTD NAV 及 order/fill ledger |
| Adapt | DataSource／Parquet manager | 接研究資料集契約 | 禁止直接把網路 API 當可重現訓練輸入 |
| Adapt | Data manager | 改為 PIT universe 與明示 missing state | 禁止 union + forward-fill 製造可交易資料 |
| Adapt | Features | 建立台股正式 allowlist | 基本面、事件必須以 available_at 截止 |
| Adapt | Engine／walk-forward | 只保留搜尋機制 | folds、gap、holdout、baselines 由 M7 契約控制 |
| Adapt | Backtest reward | 只作研究 proxy | 正式比較必須在 Taiwan cash ledger 重播 |
| Adapt | Web UI | 增加 evidence、lane、dataset、approval、rollback | AI 分析與 formal 控制隔離 |
| Replace | MT5 fetcher | 台股 research dataset adapter | 官方資料由 Taiwan Core 擁有 |
| Replace | MT5 runner／position sync | 未來 broker adapter | M12 前不做無人自動化 |
| Replace | MT5 risk／lot sizing／margin | NTD cash-share risk | 遵守 M0 NT$10,000 政策 |
| Replace | `tanh` continuous long-short position | rank／candidate score | 正式股數由 Taiwan allocator 決定 |
| Replace | proportional-only cost／cumsum PnL | order-fill-cash ledger | 最低費用、稅、T+2、no-fill 必須可表示 |
| Reject | 直接執行 `live_trade.py` 於台股 | 拒絕 | 市場、風控及 broker 不相容 |
| Reject | 整體合併 A 股 PR #1 | 拒絕 | 只參考抽象與測試模式 |
| Reject | 研究腳本自動更新 formal strategy | 拒絕 | 必須經 registry 與人工 transition |
| Reject | 近期 Sharpe 自動加碼 | 拒絕 | 只允許自動降風險 |

## 5. `tw-sepa-screener` 現況稽核

### 5.1 可作 Taiwan Core 的能力

目前工作樹已看到下列可重用能力：

- TWSE、TPEx、MOPS、交易日曆、公司行動與市場指數來源模組；
- DuckDB 與 raw Parquet snapshot；
- 每日官方市場 pipeline、完整性檢查、重試及 fail-closed；
- stock master、上市櫃與公司行動處理；
- monthly revenue、quarterly financials 及 `available_at` 類 PIT 控制；
- 原始官方價與可重建調整價分離；
- 可追溯新聞 CSV 與明示 source／URL／published_at；
- backtest、paper orders、executions、NAV、daily audit；
- effective-dated strategy manifest、fingerprint 及禁止 retroactive rewrite；
- 研究-only 路由、factor research、chart patterns 與 formal 邊界測試；
- Streamlit、CLI、Windows scheduler 及嚴格 boundary tests。

### 5.2 必須先封存才能成為 M2 基線

`tw-sepa-screener` 目前 HEAD 是 `fb87f62…`，但有大量已修改及未追蹤檔案；僅追蹤差異就超過 5,800 行新增。M1 只確認「能力存在」，不把當前工作樹宣稱為可重現 release。

M2 開始前應產生獨立且不破壞使用者變更的 baseline fingerprint：

- HEAD SHA；
- tracked diff hash；
- untracked file manifest 及內容 hash；
- Python／DuckDB／Parquet schema 版本；
- 測試及 coverage 結果；
- 資料庫與 raw snapshot schema 版本。

M1 不要求提交或整理該髒工作樹，也不授權刪除、reset 或搬移使用者變更。

### 5.3 Taiwan Core 重用矩陣

| 類別 | 能力 | 決定 |
|---|---|---|
| Preserve | 官方來源 adapters、HTTP 重試、日曆 | 成為 M2 ingestion 基礎 |
| Preserve | raw Parquet、DuckDB、source metadata | 擴充成不可變 provenance contract |
| Preserve | PIT fundamentals、first available semantics | M3 正式化及補覆蓋稽核 |
| Preserve | corporate actions 與原始／調整價分離 | M3 正式化 |
| Preserve | strategy manifests、fingerprints、daily audit | 成為策略 registry 基礎 |
| Preserve | paper orders、executions、NAV | 成為 M5 帳本基礎 |
| Preserve | fail-closed、strict boundary tests | 擴充 M2-M5 gate |
| Adapt | stock master | 建立完整歷史 listing／delisting PIT table；目前舊日期仍有 current metadata proxy 限制 |
| Adapt | simulation／backtest | 固定 M0 NT$10,000、零股、T+2、最低費用、partial/no-fill invariant |
| Adapt | candidate pipeline | 新增 AlphaMaster candidate importer；維持 research-only 預設 |
| Adapt | reports／dashboard | 顯示 dataset ID、evidence、lane、approval、rollback |
| Adapt | intraday prototype | 僅 paper；正式使用需 licensed／broker feed |
| Quarantine | yfinance 或非官方 fallback | 只能 research-only 並明示，不能靜默取代官方資料 |
| Quarantine | 保守推定的 MOPS 歷史日期 | 不得作高精度事件時點證據 |
| Quarantine | v8 router、chart patterns、新 factor variants | 維持 research-only，按 M7 相同 OOS 協定逐項審核 |
| Reject | 以當前髒工作樹作可重現 release | 必須先產生 fingerprint 或正式 snapshot |

## 6. 權威責任邊界

| 責任 | Governance Repo | Taiwan Core | AlphaMaster |
|---|---:|---:|---:|
| M0/M1 契約與 ADR | owner | consume | consume |
| 官方 raw provenance | define gate | owner | read only |
| PIT security master／universe | define gate | owner | consume snapshot |
| Corporate actions／market status | define gate | owner | consume snapshot |
| Feature registry／formula vocab | record contract | approve Taiwan allowlist | owner of research mechanism |
| Candidate generation | audit | provide dataset | owner |
| Candidate OOS cash-ledger validation | define protocol | owner | no authority |
| Orders／fills／cash／NAV | define invariant | owner | none |
| Strategy state／approval／rollback | define transition | owner of registry | submit research only |
| Broker integration | define gate | future owner | none |
| AI analysis | define restriction | commentary only | commentary only |

若兩邊對同一欄位意義不同，以跨專案 schema 和 Taiwan Core 的市場語義為準；不得讓 AlphaMaster 的既有欄位名稱默默改變台股含義。

## 7. 跨專案資料流

### 7.1 Taiwan Core 到 AlphaMaster

輸出不可變 [研究資料集封包](contracts/research-dataset-contract.md)：

```text
dataset_manifest.json
bars.parquet
universe.parquet
market_status.parquet
corporate_actions.parquet
fundamentals_pit.parquet       optional by approved feature set
```

AlphaMaster 對此封包只有讀取權。研究開始後不得就地更新資料；更新資料必須產生新 `dataset_id`。

### 7.2 AlphaMaster 到 Taiwan Core

輸出 [候選策略封包](contracts/strategy-candidate-contract.md)：

```text
candidate_manifest.json
formula.json
research_evaluation.json
checkpoint or training history optional
```

每個封包預設狀態固定為 `research-only`。不能包含正式股數、券商帳號、委託憑證或直接變更正式策略的命令。

### 7.3 候選進入驗證

1. 驗證 schema、hash、dataset、vocab 和 feature allowlist。
2. 以 Taiwan Core 的 PIT universe、台股規則、成本及現金帳本重新計算。
3. 使用 M7 固定 walk-forward 與公平 baseline。
4. 產生獨立 evidence report。
5. 僅 Validation Owner 可將候選登錄為 `validated`。
6. 後續 shadow、paper、canary、formal 仍各需獨立 transition。

## 8. 介面版本政策

- 所有 schema 使用 semantic version，例如 `tw-alpha-dataset/1.0.0`。
- 增加 optional 欄位可提升 minor；改變欄位語義、刪除欄位或改變 PIT 規則必須提升 major。
- 封包保存 SHA-256；任何內容變更都產生新 artifact ID。
- Reader 必須拒絕未知 major version、hash mismatch、缺必要欄位或未批准 evidence state。
- 不允許 reader 以猜測欄名、自動 forward-fill 或默認值把無效封包變成可用。

## 9. 主要風險與處置

| 風險 | M1 處置 |
|---|---|
| AlphaMaster AGPL 網路服務義務 | 保持邊界並在散布／部署前做授權審查 |
| AlphaMaster 驗證與台股 formal 定義不一致 | 所有候選在 Taiwan Core 重播 |
| 台股核心工作樹未封存 | M2 前產生 fingerprint；不改動使用者變更 |
| 零股日線無精確 fill | no-fill／partial-fill 保守模型；M10 前需 broker 證據 |
| 非官方 fallback 污染 formal | schema 必須標 source/evidence；formal reader fail closed |
| 候選搜尋造成多重比較偏誤 | M7 sealed OOS、multiple-testing 及相同 baselines |
| 研究直接覆寫正式策略 | 物理及權限上採單向候選封包；正式 registry 另行批准 |

## 10. M1 退出驗收

- [x] AlphaMaster snapshot、PR、Issue 及授權已重新核對。
- [x] AlphaMaster preserve／adapt／replace／reject 已逐類定義。
- [x] `tw-sepa-screener` 現有能力與髒工作樹限制已明示。
- [x] Taiwan Core、Research Lab、Governance Repo 權責已無重疊歧義。
- [x] 研究資料集與候選策略兩個單向介面已定義。
- [x] AlphaMaster 無正式策略、帳本及下單權。
- [x] M2 前置風險、授權及 baseline fingerprint 要求已記錄。

M1 狀態：`complete`。

