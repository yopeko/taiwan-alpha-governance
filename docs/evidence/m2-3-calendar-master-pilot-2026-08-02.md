# M2.3 Calendar／Master Isolated Adapter Pilot Evidence

## 1. 結論

M2.3 的第一個 adapter pilot 已完成，證據狀態為 `verified-current`。`TWSE-CALENDAR`、`TWSE-MASTER` 與 `TPEX-MASTER` 已透過 requests-compatible capture session，在既有 adapter 取得 `.json()` 前先保存 application-visible response bytes、write-once blob 與 append-only manifest。

這只完成 M2.3 的 calendar／master pilot，不等於全部 P0 adapter migration，也不等於 M2 complete。Production adapter 的預設 session、`data/raw`、stock-master CSV、DuckDB、策略與交易設定均未切換或修改。

## 2. 實作範圍

Taiwan Core `C:\project\tw-sepa-screener` 的 M2.3 變更為：

| 檔案 | SHA-256 | 用途 |
|---|---|---|
| `src/tw_sepa_screener/raw_capture.py` | `db32eeaff07c72775fbc2db3690bc9f9a661ae5696f5f1129f1ffa81599817fe` | 在 M2.2 registry 增加 fail-closed URL／method resolution |
| `src/tw_sepa_screener/sources/raw_registry.py` | `a5b3711745c687513b2faadb7304210f0de10373d79b9df5a273e382a66bf4eb` | 固定三個 pilot source ID、publisher、endpoint、URL 與 method |
| `src/tw_sepa_screener/sources/captured_http.py` | `0d0c0079e6fb740d4f7acc66aa13c3a7187cf4f338c11868ed5ca811285fe049` | 在 response 返回 adapter 前保存 bytes；transport failure 留證後 re-raise |
| `src/tw_sepa_screener/m2_capture_pilot.py` | `615e1f3a03314644b62d001130e1eac6991de7841adc7d1045711574b03a48ec` | 只允許 project 外部 output root 的 calendar／master runner |
| `tests/test_m2_capture_pilot.py` | `4bde264f15b70867cf3ad5b7a2a0782c138cfaea9b5ddd96bf5ee14d70d63ccb` | 6 個 adapter／isolation tests |

既有 `calendar.py` 與 `stock_master.py` 本身沒有修改；它們原本就接受 session 注入。Pilot 只把 `CapturedSession` 注入這兩個 client，production 預設路徑仍使用原本 session。

## 3. 執行與失敗語意

```text
allowlisted URL
    -> delegated HTTP request
    -> response.content
    -> immutable blob + manifest + hash verification
    -> return same response
    -> existing raise_for_status / json / normalize
```

- 未知 URL 或 method 在發出 network call 前拒絕。
- Redirect 後的實際 URL 若不再符合原 source allowlist，raw capture 失敗且 adapter 不得解析。
- HTTP 非 2xx 先保存 response body 為 `http-error-captured + quarantined`，再由既有 `raise_for_status()` 拒絕。
- `requests.RequestException` 保存 `transport-failed + quarantined` manifest，不建立假 blob，之後 re-raise 原 exception。
- Output root 若等於 project、位於 project 內，或是 broad drive root，直接拒絕。
- Raw store 寫入失敗會阻止解析；不會為了繼續 pipeline 而略過 provenance。

## 4. Fake-response 與回歸驗證

| 驗證 | 結果 |
|---|---|
| `test_raw_capture.py` + `test_m2_capture_pilot.py` | `20 passed in 0.85s` |
| 全專案 pytest | `368 passed in 64.87s` |
| Ruff（本輪檔案） | `All checks passed` |
| mypy（4 個 source files） | `Success: no issues found` |

6 個 M2.3 tests 覆蓋：

1. 三個端點各自在自己的 `.json()` 呼叫前已有對應 manifest；
2. 未知 URL 不發出 network request；
3. HTTP 429 先 capture，再由 adapter raise；
4. ConnectTimeout 保存無 blob manifest、不洩漏 exception message，並 re-raise；
5. redirect 到非 allowlisted host 時不 parse、不寫 artifact；
6. project root 與 production `data/raw` 類路徑被拒絕，外部 isolated path 可用。

## 5. 官方 live smoke

執行日為 2026-08-02，output root：

`C:\tmp\tw-alpha-m23-live-20260802-01`

| Source | HTTP／狀態 | Payload | Blob SHA-256 | Snapshot ID |
|---|---|---:|---|---|
| `TWSE-CALENDAR` | `200 / hash-verified / official-captured` | 3,774 bytes；27 rows；解析出 24 個 closure dates | `7644c1a8af784c09f54670fd7413f536b13eb76c54d658058e8873d1aee32117` | `8c99694a0f6d1a122010f193df5e4836a7b6bed8c261d529e22e85aa44e794ec` |
| `TWSE-MASTER` | `200 / hash-verified / official-captured` | 1,324,867 bytes；1,093 payload rows；1,087 個 4 碼普通股 rows | `6f042fc0b6e4f5c2192c6ec4e01e5ac9e2d6ec75813d6ca90aab3f747fb6a092` | `f5a4ee92670d87943f74e949cb821dc17f361806684bf0c687b6602290e0d058` |
| `TPEX-MASTER` | `200 / hash-verified / official-captured` | 1,070,613 bytes；890 payload rows；890 個 4 碼普通股 rows | `67f67cba249023dc5bfb209471a7a464a70f27e00815f67d6c381befce81586f` | `cad818c9f4cbdb18b7a4fb62797523baba435da9ddba79fbc1f47096a33633cc` |

共 3 manifests、3 blobs。Runner 在回傳 summary 前再次呼叫 store verifier；三份 manifest 的 `parse_status` 仍是 `not-attempted`，pilot 的 in-memory normalize 不冒充 M2.4 parse-run lineage。

第一次 sandbox 內嘗試因 WinError 10013 禁止 network，且 sandbox 不允許建立指定 `C:\tmp` 子目錄而 fail closed；沒有落下 partial manifest。經明確批准以相同 command 在 sandbox 外重跑後成功。這是 execution-environment 限制，不是把 transport failure 誤判成官方 no-data。

## 6. Production non-mutation evidence

M2 entry、M2.2 後及 M2.3 pilot 後完全相同：

| Artifact | M2.3 後 |
|---|---|
| legacy raw tree | 4,988 files；188,391,038 bytes |
| legacy raw content manifest SHA-256 | `9b09a95aae389c9502d48201066f9470a86792ec834db1c6a0d32132b9a6993b` |
| DuckDB | 425,209,856 bytes |
| DuckDB SHA-256 | `c948a1bd62ff141eabd2216bec358a1b8ea129dd0821bcc785bffe75648bbfba` |

## 7. Taiwan Core post-state

| 項目 | M2.2 後 | M2.3 pilot 後 |
|---|---:|---:|
| HEAD | `fb87f62f8c2c68e2b85982cd102a35fd935bc0a4` | 相同 |
| tracked modified | 29 | 29 |
| git-visible untracked | 118 | 122 |
| untracked bytes | 894,193 | 913,145 |
| untracked manifest SHA-256 | `c75cb74475219d9769a389a59e2580c05bcc58e7431d2654444370b722a17b32` | `188f821c0bdeee2552e6619cc8743f4eedfb5d2436f8d3a4bf99b57ee9ebc38c` |

差異是 4 個新增檔案及既有 untracked `raw_capture.py` 的 registry extension。工作樹仍不是 clean commit 或可重現 release，未 stage、commit、reset、刪除或整理任何既有變更。

## 8. 剩餘限制與下一 gate

- `C:\tmp` artifacts 是受控 smoke evidence，不是 durable production archive；未建立 retention、backup 或 operator schedule。
- Production calendar／master 預設流程尚未切換到 raw-v2，故 source inventory 狀態是 `pilot-verified`，不是 `migrated-complete`。
- `logical_period` 暫為 `latest-observed`；每日 production capture 前要建立 endpoint-specific period policy。
- Requests adapter 內部 retry 次數目前無法由 wrapper 精確觀測；manifest 保存 client ID 與 timeout，但 source-specific retry evidence 尚須補強。
- 仍沒有 parser registry、parse-run manifest、reject ledger、schema drift／empty payload quality gate 或 replay。
- Current master 不能重建歷史上市／下市／轉板狀態；`TPEX-LISTING-STATUS` 仍是 blocked source gap。
- Live row counts 是 2026-08-02 observation，不是穩定常數，不得寫成 production threshold。

M2.3 下一批是 TWSE／TPEx historical 與 latest daily prices，繼續沿用同一 capture-first、external-root、failure fixture、live smoke 與 production non-mutation gate。M2 整體維持 `in_progress`。

## 9. Rollback

M2.3 的技術回滾目標是移除 4 個新增檔案，並撤回 `raw_capture.py` 的 `RawSourceRegistry.resolve()` extension。Live smoke artifacts 位於 `C:\tmp`，不是 production data；未經使用者明確要求不執行刪除。Production DB 與 legacy raw 不需復原。
