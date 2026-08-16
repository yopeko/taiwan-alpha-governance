# M2 Owner 批准、Release、Durable Archive 與 Restore Closure（2026-08-03）

## 結論

M2 exit gate 已全部閉環，milestone 狀態為 `complete`。

- 36/36 endpoint-level P0 sources 有 hash-verified raw、唯一 parser binding、parse 與 quality evidence；
- 56/56 observations parsed；不可變初始 quality 決定保持 55 accepted、1 quarantined；
- 唯一 quarantine 有 1 個合法 append-only `released` event，0 unresolved quarantine；
- 正式封存、E: 分離 volume 備份及 restore copy 的逐檔 SHA-256 相同；
- 正式封存、備份與 restore archive audit 均為 `passed`；
- 從備份還原後的 56-observation offline replay 為 `passed`，55 accepted + 1 released，production fingerprints 前後相同；
- 最終完整專案測試為 `483 passed`，受影響檔案 Ruff 為 `All checks passed!`。

這不授權策略升級、自動下單、真實資金交易或 M3 直接覆寫 production stores。

## 1. 三項人工決定

| 欄位 | 值 |
|---|---|
| Decision ID | `M2-OWNER-APPROVAL-20260803-01` |
| 決定文件 | [m2-owner-approval-decision-2026-08-03.md](m2-owner-approval-decision-2026-08-03.md) |
| 決定文件 SHA-256 | `7fea2089a944b55b544d265a86daa4473bbd1123582d97bcb7b8310db40eecbf` |
| 原始人工證據 | 本 Codex task 使用者訊息：`3項全部批批准` |
| 批准範圍 | TWT49U 專案內保存／M3 研究驗證；durable archive／backup／retention；M2 evidence 與 M3 唯讀／shadow scope |

[M2.6 exit verification](m2-6-exit-verification-2026-08-03.md) 保留批准前 `blocked` 狀態的歷史快照，不回寫；本文件是其後的追加式 closure evidence。

## 2. 唯一 TWT49U Release

Preflight 先驗證正式封存仍是精確的批准前狀態：56 raw、56 parse、56 quality，0 release、1 unresolved quarantine，唯一 blocking issue 是 `quality-quarantined=1`。

| 欄位 | 值 |
|---|---|
| Source | `TWSE-ACTIONS-HIST`／`exright-historical` |
| Logical period | `range:2026-07-31:2026-07-31` |
| Quality run | `6fcb5b423045245c67cde1af46a86dfb31488851df95874e85bd79d80fe65e2b` |
| Initial decision | `quarantined`；`license-owner-approval-required` |
| Quality manifest SHA-256（release 前後） | `4dce384e265a6e8246c75063fcfc17c962833bd774e7df12f43d17589ed47179` |
| Initial event SHA-256（release 前後） | `5e74c62f933995b7c3c912c068fabde2717a6b7f8e26a9bdce3ec7e033b2d008` |
| Release event ID | `3cf981611005079d2557ce974035a5449339ebfdfbb1f2be91eb62e82ec6866a` |
| Release event path | `quality_releases/2026/08/03/3cf981611005079d2557ce974035a5449339ebfdfbb1f2be91eb62e82ec6866a/event.json` |
| Release event SHA-256 | `86b33cf28d510ec0ee972fc76a6b0676ef7644e79cae291a44c4afdb173770ba` |
| Event time | `2026-08-03T10:18:59.986935Z` |
| Evidence refs | decision ID、決定文件路徑與 SHA-256、原始 task user-message ref |

Release 後 audit 結果：

```text
state=passed
raw_observations=56
parse_runs=56
quality_runs=56
quality_decisions={accepted:55, quarantined:1}
quality_release_events=1
released_quality_runs=1
unresolved_quarantined_quality_runs=0
missing_sources=[]
unusable_sources=[]
blocking_issues=[]
```

初始 quarantine 沒有被改成 accepted；有效狀態只能由 release event 鏈推導。

## 3. Durable Archive、Backup 與 Retention

批准前 temporary archive 有 395 files、15,292,559 bytes，tree SHA-256 `0c60a33f964ced3c1e8d5c97ed410524d8b8b13dc21e049437787f55ae9e7cc5`。先逐檔驗證後複製到不存在的新正式路徑，再只在正式封存追加一次 release event。

| Copy | 路徑 | Files | Bytes | Tree SHA-256 | Audit |
|---|---|---:|---:|---|---|
| Primary | `C:\project\tw-sepa-screener\data\raw_v2\m2_2026-08-03` | 396 | 15,293,847 | `31f31094f772c3c9a4f78e6234497a74fdf40e28560e6f88dd9415d43e1934a0` | `passed` |
| Backup | `E:\tw-sepa-screener-backup\raw_v2\m2_2026-08-03` | 396 | 15,293,847 | `31f31094f772c3c9a4f78e6234497a74fdf40e28560e6f88dd9415d43e1934a0` | `passed` |
| Restore audit copy | `量化交易測試\.codex_tmp\m2-restore-drill-20260803-01` | 396 | 15,293,847 | `31f31094f772c3c9a4f78e6234497a74fdf40e28560e6f88dd9415d43e1934a0` | `passed` |

系統能確認 `C:` 與 `E:` 是不同 volume／drive letter，但受 OS 權限限制，未取得它們是否位於不同實體裝置的證據。因此本文件不把 E: copy 宣稱為 off-device 或異地備份；每季仍應做 restore drill，並建議另建一份離線或異地副本。

Retention 已批准為無期限保留，`automatic_deletion=disabled`。任何刪除或縮短 retention 必須取得 Data Owner、Infrastructure Owner 與 Compliance 的新人工批准。

## 4. Restore 與 Offline Replay

從 E: 備份另還原到新的 Windows temp root，使用 release-aware replay 重播全部 56 observations：

| 欄位 | 值 |
|---|---|
| Replay run ID | `cc2543a5bae746371972a9a8363316287d60432cfe7447b6391100cf8b3bd516` |
| Run manifest SHA-256 | `200459cce81457d3c34da52ef6e4f9bb8ae295098dbd01bf6985951a6d332ae4` |
| Result | `passed` |
| Observation count | 56 |
| Effective states | `accepted=55`、`released=1` |
| Archive audit | `passed`；1 release、1 released、0 unresolved、0 blocking issues |
| Production unchanged | `true` |

本輪 closure 執行前，既有排程資料已在 15:40–16:03 更新正式 stores，因此其 current fingerprint 與較早的 M2.6 snapshot 不同；修改時間早於本輪 18:18 release。Restore replay 保存的當下 before／after 精確相同：

- DuckDB：426,258,432 bytes；SHA-256 `b35ee8e6e76e6e6e12a14a241d03dcf8d8252a4d9756c56972ef28d05fcd26f1`；
- legacy raw：4,991 files、188,514,234 bytes；manifest SHA-256 `6c69763e244bf4bf6b096ccd052ebafc4b05dfccc23441dc1999506f6a7d2e03`；
- stock master：174,314 bytes；SHA-256 `f179c40e945bfc1e80a2f46922f26605d92b68043ca07841aed89ac7fa8e166c`。

沒有回復、刪除或覆寫這些並行更新。

## 5. Release-aware Audit／Replay 與測試

Archive audit 只接受唯一且完整的 release：事件 hash、固定欄位、路徑日期、target quality run、quarantine predecessor、parse／snapshot／source lineage、actor、reason、evidence refs 與 producer 均須有效。竄改、錯誤血緣、不完整或重複 release 都 fail closed。

Replay 保留 `quality_decision=quarantined`，但只有 audit 驗證的 quality run 才能得到 `effective_quality_state=released`。沒有 release 時 replay 仍失敗；55 accepted + 1 released 且 audit passed 時才可通過。

| 驗證 | 結果 |
|---|---|
| 完整專案 | `483 passed in 92.03s` |
| Release-aware targeted／相鄰測試 | `44 passed` |
| Archive audit 單獨重驗 | `9 passed` |
| Ruff：4 個受影響實作／測試檔 | `All checks passed!` |
| Final source-state fingerprint | `d4ef6c0f50f4c480d39c9f1e7baa3fc10eac8b0fe27b584e1c35c7c80e3b5ee9` |

Final source fingerprint 算法：`src/tw_sepa_screener`、`tests`、`pyproject.toml` 的 tracked + untracked files，共 180 files；每列為排序後 `relative_path|file_sha256` 加 LF，再做 SHA-256。HEAD 保持 `fb87f62f8c2c68e2b85982cd102a35fd935bc0a4`，dirty worktree 未整理、未 stage、未 commit、未 reset。

Release event 的 producer fingerprint 是事件建立當下的 `20e6e5b1cd57c17d82651d4bf985e3d82365a55a1b86850a2f8ec01e85f34f8e`；其後只新增 release-aware replay 與測試，因此 final fingerprint 另行記錄，沒有回寫 immutable event。

## 6. M3 Handoff

已批准的下一步只有：唯讀使用 36-source durable archive 與 96-session daily-price shadow，建立 point-in-time／normalized shadow warehouse，並產生新舊對照、回復與 owner evidence。

尚未批准：覆寫正式 DuckDB、legacy raw、stock master，變更策略分數或 promotion lane，連接券商、自動下單或使用 NT$10,000 真實交易。
