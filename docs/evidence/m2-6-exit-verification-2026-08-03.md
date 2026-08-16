# M2.6 Exit Verification — 2026-08-03

## 1. 結論

M2 的可自動化技術工作已完成：36 個 P0 官方端點均可 capture-before-parse，56 個 live observations 均通過 raw hash 與離線解析，55 個品質接受，1 個因授權待審而隔離。完整專案測試、重播一致性、防竄改及 production non-mutation 均通過。

Milestone 最終狀態仍為 `blocked`，不是 `complete`。未通過的不是資料解析，而是三個不可自動代簽的 gate：

1. `TWSE-ACTIONS-HIST` 的 Compliance／Project Owner 授權決定；
2. durable raw-v2 位置、備份與 retention 的 Infrastructure Owner 批准；
3. evidence bundle 與 M3 資料範圍的 Validation Owner 簽核。

## 2. 實作範圍

- immutable exact-byte raw blob 與 observation manifest；
- parameter-aware 36-source formal registry；
- 36 個一對一 offline parsers；
- fixed Arrow schema、parser／config／dependency hash；
- rows、reject ledger、diagnostics 與 parse manifest；
- append-only quality decision／release event；
- orphan、missing、tamper、incomplete publication 與 source completeness audit；
- 96-session daily-price shadow；
- 全 P0 capture／replay runner；
- [M2 操作手冊](../m2-operations-runbook.md)。

未實作或未授權：production DB import、legacy raw 覆寫、策略／分數修改、AlphaMaster candidate promotion、券商連線或下單。

## 3. Producer 與隔離路徑

Source repo HEAD：`fb87f62f8c2c68e2b85982cd102a35fd935bc0a4`。

第二次乾淨 capture producer：

- dirty fingerprint：`f6a086c0acea324d9f0fc9ee7612cfa2292e9db7883f386aa9d34ac9f90b39ff`；
- tracked diff SHA-256：`9639ccb42b5227a9b90d4cb1d57283706ef6647660fb9721c5167d43482794dd`；
- untracked manifest SHA-256：`2d8f35b5fc4b18afb024b899857537493d89c8c1e80f727b21f16f15076c3343`。

最終 idempotent replay producer dirty fingerprint：`173cc58d43175c6e51c588f535711cc7f6529871cddc060b2a60b43e5e7c6621`。

隔離根目錄：`C:\tmp\tw-alpha-m2-p0-live-20260803-02`。這是驗證封存，不是 durable production archive。

## 4. 每日股價與 96-session 修復範圍

Frozen targets：`docs/evidence/m2-daily-price-repair-targets.csv`。

- target SHA-256：`5ecf26e039b4d7fb9f6a2ff6bcc6aa2563d0c058f44f88102fce77c83eb7ab10`；
- 94 個 TWSE 零列日期，加 2024-08-02 與 2026-07-02 兩個僅 31 列日期，共 96 sessions；
- first：2020-10-19；last：2026-07-02；
- shadow root：`C:\tmp\tw-alpha-m2-shadow-20260803-02`；
- shadow run ID：`3ca7b2d4d3b7e8a2711466bb584f6fbe54f6ccedfea34c5677015552435e81d7`；
- 96/96 raw hash-verified、96/96 parsed、96/96 quality accepted；
- 96 blobs、archive audit 0 issues；
- 每日 parsed rows 約 955–1090；scope exclusions 保留在 reject ledger，沒有 parser error；
- 不 forward-fill，不把 zero OHLC 自動視為停牌。

Production before／after 完全相同：

| Artifact | Bytes／files | SHA-256／manifest SHA-256 |
|---|---:|---|
| DuckDB | 425,209,856 bytes | `c948a1bd62ff141eabd2216bec358a1b8ea129dd0821bcc785bffe75648bbfba` |
| legacy raw | 4,988 files；188,391,038 bytes | `9b09a95aae389c9502d48201066f9470a86792ec834db1c6a0d32132b9a6993b` |
| stock master | 174,314 bytes | `b13ce5c57ba384e7946adc347de8e9fb538f16bcf753c2fde232dec1e8a0ed7e` |

## 5. 全 P0 live capture

第二次乾淨 capture：

- root：`C:\tmp\tw-alpha-m2-p0-live-20260803-02`；
- capture run ID：`31a0c201d4b6f3af890f303eb6f2f3fac500abb95f2745790e34b43cbd3edb22`；
- reference session：2026-07-31；statement：2026Q1；revenue month：2026-06；
- formal sources：36；observed sources：36；missing sources：0；failed steps：0；
- raw observations：56；hash-verified：56；raw blobs：56。

Archive byte inventory：

| 區域 | Files | Bytes | Manifest SHA-256 |
|---|---:|---:|---|
| raw blobs | 56 | 12,851,836 | `051f914928dabdad208db4dcdc85e001ba7c5b5095cc8d0be1a23ef5a0e4280a` |
| raw observations | 56 | 94,493 | `078c0aae465d96d4af85695be8d8c849a1bbaf175ffc2cbc9a2c7e7c5910b9a7` |
| parsed observations | 168 | 2,033,051 | `ad5f3c1991bb9ffafdb655b3b001578b59f2e8ade78bb4d1b5ab557ef7132506` |
| quality events | 112 | 218,796 | `5deeba1d15e5063e99e99ef74c2aafe1b458f58cab1a3bbca6998fc2b499fbab` |

## 6. Parser 與品質結果

- formal parser coverage：36 sources／36 definitions，missing 0、unexpected 0、duplicate 0、endpoint mismatch 0；
- observations：56；parsed：56；parse-rejected：0；
- quality accepted：55；quarantined：1；
- official no-data：11 observations，其中 10 個為 latest income category placeholder，1 個為 TWSE notice official zero sentinel；
- TWSE listing-start：790 rows 全部保留；377 筆官方沒有 listing date，記為 `event_date=null`、`event_date_state=missing-at-source`，reject 0；
- 唯一 quarantine：`TWSE-ACTIONS-HIST`，logical period `range:2026-07-31:2026-07-31`，原因 `license-owner-approval-required`。

第一輪 replay 曾有 12 quarantines：10 個 income placeholder 被錯分成普通 scope exclusion、TWSE listing-start 有 377 筆缺日期被拒絕，以及 1 個 license gate。問題未被忽略；parser 修正為官方 no-data 與 missing-at-source 後，在新的乾淨 archive 重跑，降為唯一正當的 license quarantine。

## 7. Idempotent replay

第二次乾淨 replay：

- run ID：`b9412532f19c9e99e7dd9666f89e0cf744b4866c985bf61eb7a64c1a756f4623`；
- 56 parsed；55 accepted；1 quarantined；production unchanged。

再次離線 replay：

- run ID：`4f2f8ab86bb34819ad1cf4e3261796ae5c5a8294cfc4b0ec389e90f59f92940c`；
- parse＋quality tree before：`ddc7d16b60b01fcf6110fa63f7c175f72bb09c0eea929f87375b59e3106c85a1`；
- parse＋quality tree after：`ddc7d16b60b01fcf6110fa63f7c175f72bb09c0eea929f87375b59e3106c85a1`；
- idempotent：true；production unchanged：true；
- audit blocking issue：`quality-quarantined = 1`，即 license gate。

## 8. 測試與防竄改

完整專案：

```text
477 passed in 62.92s
```

M2 與相鄰資料路徑：

```text
154 passed in 6.31s
```

明確 tamper／security／path drill：

```text
7 passed in 0.72s
```

涵蓋：raw 單 byte 竄改、parsed Parquet 竄改、quality event 竄改、manifest 移動、secret redaction、archive tamper、incomplete parse／quality publication。所有情境均 fail closed。

Ruff 對本輪 M2 source／tests：all checks passed。

## 9. Exit gate 判定

| Gate | 結果 | 證據／owner |
|---|---|---|
| 36 P0 endpoint raw capture | passed | 36/36 sources，56/56 hash-verified |
| Offline parser replay | passed | 36 unique bindings，56/56 parsed |
| Reject／missing／no-data preservation | passed | ledger、11 official no-data、377 missing-at-source |
| Quality／quarantine | passed technically | 55 accepted；1 license quarantine 正確阻擋 |
| Idempotency／tamper／security | passed | tree hash 相同；7 focused drills |
| Production non-mutation | passed | DuckDB／legacy raw／master hashes相同 |
| Durable archive／backup／retention | blocked | Infrastructure Owner 未批准 |
| TWT49U license／use scope | blocked | Compliance／Project Owner 未批准 |
| Evidence／M3 scope signoff | blocked | Validation Owner 未簽核 |

結論：自動化與技術驗收已做到可交付程度；依治理契約，M2 維持 `blocked`，不得提早標為 `complete` 或進入 M3 production migration。
