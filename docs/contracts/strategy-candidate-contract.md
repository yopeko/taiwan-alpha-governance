# Strategy Candidate Package Contract

## 1. 目的

定義 AlphaMaster 向 Taiwan Core 提交研究候選的不可變封包。封包只是一個可重播的假說，預設狀態永遠是 `research-only`。

## 2. Schema ID

`tw-alpha-candidate/1.0.0`

## 3. 封包內容

| 檔案 | 必要 | 用途 |
|---|---:|---|
| `candidate_manifest.json` | 是 | lineage、版本、hash、狀態 |
| `formula.json` | 是 | token、decoded formula、輸出語義 |
| `research_evaluation.json` | 是 | 研究內指標及限制 |
| checkpoint／history | 否 | 重現訓練，不是批准證據 |

## 4. Manifest 必要欄位

- `schema_id`；
- `candidate_id`；
- `created_at`；
- `producer_repository` 及 AlphaMaster commit SHA；
- `producer_dirty_state`；
- `dataset_id`；
- `research_run_id` 及 random seeds；
- `vocab_version`；
- `feature_allowlist_id`；
- `formula_hash`；
- `training_config_hash`；
- `fold_definition_hash`；
- `files` 與 SHA-256；
- `evidence_state`，固定不得高於 `research-only`；
- `known_limitations`；
- `license_metadata`。

## 5. Formula 必要欄位

- token ID 序列；
- token 名稱序列；
- decoded expression；
- arity／stack validation 結果；
- output type：只允許 `score` 或 `rank_input`；
- lookback；
- required input fields；
- missing-data behavior；
- finite-value／degeneracy 檢查；
- direction selected from training/validation and its provenance。

不得輸出：

- target portfolio percentage；
- LONG／SHORT live command；
- NTD position size；
- broker account 或 credential；
- formal strategy ID；
- 對正式 registry 的 mutation 指令。

## 6. Research evaluation

至少保存：

- training、validation 及任何研究 holdout 的明確日期；
- gap／purge 定義；
- sample、symbol、session 及有效 observation 數；
- IC、rank IC、退化、coverage、相關性及消融結果；
- 研究 proxy 的報酬、成本和限制；
- 搜尋候選總數及剪枝流程；
- multiple-testing 處理或未處理警告；
- 與既有候選的相關性；
- 任何反覆使用驗證資料的紀錄；
- `not_validated_by_taiwan_cash_ledger=true`。

AlphaMaster 的 research evaluation 不得標記為 Taiwan formal OOS。

## 7. Taiwan Core 匯入流程

1. 驗證 schema、hash、vocab、dataset、feature allowlist 及公式結構。
2. 確認來源 dataset 尚可重現。
3. 將候選登錄到 `research-sandbox`，不得直接登錄 challenger 或 formal。
4. 以 Taiwan Core 重新計算特徵或驗證 adapter 一致性。
5. 使用台股 PIT universe、現金帳本、成本、稅、no-fill 及相同 baseline 做 M7 驗證。
6. 由獨立 Validation Owner 產生 evidence report。
7. 通過後建立新的 registry transition；不修改原 candidate package。

## 8. 拒絕條件

- vocab 或 formula hash 不符；
- dataset 不存在或 hash 不符；
- 使用 allowlist 外特徵；
- required field 無 PIT 語義；
- 公式輸出直接代表 short、leverage 或 continuous target position；
- 未說明搜尋候選數或 validation reuse；
- 包含 formal promotion／order side effect；
- 研究 proxy 被冒稱 cash-ledger OOS；
- evidence state 自稱 `validated`、`paper`、`canary` 或 `formal`。

## 9. 不可變與回溯

同一 `candidate_id` 內容不得改變。修正公式、資料、方向、參數或指標即建立新候選，並在 `supersedes` 指向舊 ID。候選被淘汰、退役或證偽時保留原始封包及原因。

