# M0／M1／M2 證據來源登錄表

核對日期：2026-08-03，時區 `Asia/Taipei`。

| ID | 證據狀態 | 來源 | 支持的決定 | 漂移處理 |
|---|---|---|---|---|
| SRC-TWSE-TRADING | `verified-current` | [TWSE 集中市場交易制度](https://www.twse.com.tw/zh/products/system/trading.html?hl=zh-TW) | 09:00-13:30、1,000 股、一般 10%、tick、零股 1-999、09:10 後每 5 秒、限價 ROD、現股、零股不作普通 OHLC | M4 與每次 live release 重驗 |
| SRC-TWSE-SETTLEMENT | `verified-current` | [TWSE 款券交割作業](https://www.twse.com.tw/zh/clearing/clearing/operations.html) | 投資人與券商 T+2 交割時點 | M4 與 broker integration 重驗 |
| SRC-MOF-TAX | `verified-current` | [證券交易稅條例](https://law-out.mof.gov.tw/LawContent.aspx?id=FL006079&media=print) | 股票賣出 0.3%；合格現股當沖 0.15% 至 2027-12-31 | 每季及法規變更重驗 |
| SRC-TWSE-OPENAPI | `verified-current` | [TWSE OpenAPI](https://openapi.twse.com.tw/) | 2026-08-02 官方 Swagger 仍列出 `STOCK_DAY_ALL`、`MI_INDEX`、交易日曆、公司基本資料、月營收與財報等端點；calendar 與 master 已有 isolated live raw-v2 pilot | 其餘端點仍須逐端點保存 raw bytes、schema 和回應 metadata |
| SRC-TPEX-OPENAPI | `verified-current` | [TPEx OpenAPI](https://www.tpex.org.tw/openapi/)；直接頁面抓取曾遭 403 | 官方 Swagger 與近期索引仍列出 `tpex_mainboard_daily_close_quotes`、指數、公司資料、月營收及財報等端點；保留存取警告 | M2 必須由實際 HTTP client 逐端點核對狀態、schema、使用條款及回應，不得只依 Swagger |
| SRC-MOPS | `verified-current` | [MOPS](https://mops.twse.com.tw/) | 官方財務及重大訊息來源 | M2/M3 逐資料族驗證可得時間 |
| SRC-FEE-ASSUMPTION | `assumption` | [TWSE 零股教育案例](https://www.twse.com.tw/market_insights/zh/detail/ff8080818bf08529018bf6c8a5690016) | 0.1425% 和 NT$20 只作保守研究示例 | M10 前以實際券商契約替換 |
| SRC-ALPHAMASTER | `verified-snapshot` | [AlphaMaster @ 5d145b7](https://github.com/rosemarycox5334-debug/AlphaMaster/tree/5d145b7ba8fec1577a2b48f37ac23cafa8aca0d4) | 研究架構、模組及 AGPL 基準 | 每次 M1 變更或 upstream 更新重驗 |
| SRC-ALPHAMASTER-PR1 | `verified-current` | [PR #1](https://github.com/rosemarycox5334-debug/AlphaMaster/pull/1) | A 股市場抽象只作參考；目前 open、未合併、不可直接合併 | 合併狀態改變時重驗 |
| SRC-ALPHAMASTER-ISSUE2 | `verified-current` | [Issue #2](https://github.com/rosemarycox5334-debug/AlphaMaster/issues/2) | 交易所連接仍是已知缺口 | upstream 實作 connector 時重驗 |
| SRC-TW-SEPA-LOCAL | `verified-current` | `C:\project\tw-sepa-screener` | 官方資料、PIT、storage、simulation、strategy version 能力存在 | M2 entry fingerprint 已建立；每次實作前後重算，且不得稱 clean release |
| SRC-TW-SEPA-M2-BASELINE | `verified-current` | [M2 entry baseline](tw-sepa-baseline-2026-08-02.md) | HEAD、dirty manifests、environment、DB、legacy raw tree 及 40-test baseline | 每次 M2 程式修改前後重算；它是指紋而非備份 |
| SRC-TW-SEPA-M2-2 | `verified-current` | [M2.2 capture foundation evidence](m2-2-capture-foundation-2026-08-02.md) | write-once blob、manifest、allowlist、redaction、failure evidence；14 targeted 與 362 full tests | M2.3 接來源時重驗 URL、schema、live response 與 production isolation |
| SRC-TW-SEPA-M2-3 | `verified-current` | [M2.3 calendar／master pilot evidence](m2-3-calendar-master-pilot-2026-08-02.md) | capture-first session、isolated runner、calendar／TWSE master／TPEx master 三份 live official snapshots；20 targeted 與 368 full tests | Pilot artifacts 位於 `C:\tmp`，不可當 durable production archive；下一批遷移 daily prices |
| SRC-TW-SEPA-M2-3-PRICE | `verified-snapshot` | [M2.3 daily-price／gap evidence](m2-3-daily-price-pilot-and-gap-audit-2026-08-03.md) | 94 個零列日期加 2 個 31 列日期形成 96-session scope；96/96 shadow accepted，OHLC／activity scope 不補值 | M3 cutover 前重驗 frozen target hash 與 current production fingerprint；durable／owner gate 已由 M2 closure 閉環 |
| SRC-TW-SEPA-M2-6 | `verified-snapshot` | [M2.6 exit verification](m2-6-exit-verification-2026-08-03.md) | 批准前 snapshot：36 sources、56 hash-verified／parsed、55 accepted、1 license quarantine、477 tests、idempotent replay 與 production non-mutation | 保留當時 `blocked` 歷史；後續狀態見 M2 closure evidence |
| SRC-TWSE-TWT49U-LICENSE | `owner-approved-released` | [Owner 決定](m2-owner-approval-decision-2026-08-03.md) SHA-256 `7fea2089…eecbf`；[closure evidence](m2-owner-approvals-release-and-durable-audit-2026-08-03.md) | `TWSE-ACTIONS-HIST` 專案內保存與 M3 研究／驗證 gate 由唯一 event `3cf98161…6866a` 解除；原 quarantine 不改寫 | 外部 TWSE 條款仍有效；不得推論可公開再散布或轉售，條款變更時重審 |
| SRC-TW-SEPA-M2-CLOSURE | `verified-snapshot` | [M2 owner approvals、release、durable archive 與 restore closure](m2-owner-approvals-release-and-durable-audit-2026-08-03.md) | 主封存、E: backup、restore、offline replay、483 tests；55 initial accepted + 1 released、0 unresolved | 每季 restore drill；M3 另做 current fingerprint、PIT 與 production cutover evidence |

## 本地台股核心指紋

- HEAD：`fb87f62f8c2c68e2b85982cd102a35fd935bc0a4`
- Commit time：2026-07-17T20:13:49+08:00
- 狀態：tracked modified 加大量 untracked files。
- Git remote：本次檢查未發現已設定 remote。
- LICENSE：本次根目錄檢查未發現 LICENSE 檔。
- 結論：能力盤點有效，但不可將工作樹當作可重現 release 或對外授權基線。
- M2 entry：tracked diff、untracked manifest、DB 與 legacy raw tree 已另行封存指紋；entry 與 M2.6 blocked snapshot 均保留。三項 Owner 決定、release、durable archive、backup／restore 與 final tests 已另立 closure evidence，M2 狀態為 `complete`。

## 證據標籤

- `verified-current`：本次由當前官方或本地狀態核對。
- `verified-snapshot`：可對指定 commit 或不可變資料重現。
- `research-only`：僅供假說與探索。
- `assumption`：尚未有足夠證據。
- `blocked`：缺少必要證據或授權，不能前進至受影響階段。
