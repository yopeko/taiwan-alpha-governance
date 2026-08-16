# M3 G0 Owner Decision — 2026-08-03

## 1. 決定紀錄

| 欄位 | 值 |
|---|---|
| Decision ID | `tw-alpha-m3-g0/1.0.0` |
| 決定日期 | 2026-08-03 |
| 證據狀態 | `verified-current`；Owner 在本次對話直接批准 |
| 選擇 | `G0-A-fixed-window-certified-dates` |
| 固定開始日 | 2025-01-01 |
| 固定截止日 | 2026-08-03（本次所稱「今天」的絕對日期） |
| 市場 | TWSE、TPEx |
| 商品範圍 | 延續 M0：普通股；ETF 與其他商品不自動納入 |
| Production cutover | 未批准 |

Owner 指示為：`G0-A 2025到今天、承諾明確列入 coverage certificate 的日期`。

## 2. 正式解讀

這項批准同時採用兩層控制：

1. **固定目標期間**：M3 的基準 backfill 與 exit review 固定評估 2025-01-01 至 2026-08-03，首尾皆包含。
2. **逐日明確認證**：系統只承諾 coverage certificate 中明確列出，而且 aggregate `reconstruction_state` 為 `supported` 的 `market + calendar_date`。

「2025 到今天」不是會自行向未來移動的模糊日期。這份決定中的截止日凍結為 2026-08-03。2026-08-04 以後的資料必須透過新的 append-only certificate 版本逐日加入，不能因為曾批准「到今天」就自動視為 supported。

## 3. Coverage certificate 最低粒度

固定期間共有 580 個 calendar dates。TWSE 與 TPEx 必須分開列示，因此一個完整基準 certificate 至少要有 1,160 個 `market + calendar_date` 狀態列；若同一日期需要多個資料族明細，實際列數可以更多。

每個 market-date 至少保存：

- `certificate_id`、`dataset_id`、`market`、`calendar_date`；
- `session_state`：`official-open`、`official-closed`、`special-session` 或 `unknown`；
- `reconstruction_state`：`supported`、`partial`、`blocked`、`not-session` 或 `unknown`；
- calendar、security lifecycle、daily price、market status、corporate action、fundamental 各資料族的 coverage state；
- `known_exceptions`、`reason_codes`、來源與 observation lineage；
- policy／schema version、產生時間與 certificate hash。

## 4. 承諾與 fail-closed 規則

- `supported`：可以依指定 dataset 與 cutoff 重建；所有必要資料族均通過 gate，或有明確且可驗證的 `official-no-data`。
- `not-session`：有足夠官方日曆證據確認該市場當日不是交易日；可以回傳非交易日，但不能產生交易。
- `partial`、`blocked`、`unknown`：不承諾可供回測或決策；查詢必須 fail closed。
- certificate 沒有列出的日期：等同 `unknown`，必須 fail closed。
- 一個市場被認證，不代表另一市場同日也被認證。
- 一個資料族有 coverage，不代表整個 market-date 已 `supported`。

## 5. M3 complete 的 G0-A 門檻

M3 只有在以下條件全部滿足後才可進入 exit review：

1. 2025-01-01 至 2026-08-03 的每個 calendar date，TWSE 與 TPEx 都有明確 certificate 狀態，沒有遺漏日期。
2. 所有官方開市或特殊交易 session 的 aggregate state 都是 `supported`；任何 `partial`、`blocked` 或 `unknown` 都會阻止 M3 complete。
3. 官方休市日必須是有證據的 `not-session`，不可只因沒有價格檔就猜測休市。
4. `supported` 日期的 security lifecycle、價格、狀態、公司行動及當時可得財報均符合 point-in-time、revision 與 lineage 規則。
5. anti-lookahead、deterministic rebuild、protected-store non-mutation、restore 及 Validation Owner signoff 全部通過。

這個定義不允許用「大多數日期都有」或「缺的日期先忽略」把 M3 標成 complete。

## 6. 對後續工作的影響

- M3.1 不再等待 G0；下一步是完成 source-to-table map、availability/cutoff policy 與 conflict policy。
- M3.2 staging 必須以這個固定期間產生逐 market-date coverage ledger。
- 96-session TWSE repair shadow 仍須先耐久封存；它只涵蓋部分日期與單一市場，不能單獨滿足 G0-A。
- 2026-08-04 以後可逐日擴充，但每一日期都要有新 certificate version、完整 evidence gate 與 predecessor／rollback lineage。
- 本決定不改變正式 DuckDB、legacy raw、stock master、策略或交易權限。
