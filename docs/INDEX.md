# 文件索引

這個專案的內容在文件裡，不在程式裡。README 是入口，這裡是全部。

**先讀哪一份**：[里程碑登錄表](milestone-register.md) 是唯一的狀態來源；
[M0 專案契約](m0-project-contract.md) 是所有其他文件的前提。

文件命名規則：`m<里程碑>-<序號>-<主題>-<日期>.md` 為證據，
`<主題>-contract.md` 為契約，`NNNN-<主題>.md` 為架構決策紀錄（ADR）。
**契約先於它所規範的執行存在**，日期就是那個順序的證據。

## M0–M1 契約與架構

- [Owner 決定 D25：walk-forward folds 不實作，M0 §9.1 加豁免並預先寫定解除參數](evidence/m3-owner-decision-d25-2026-09-03.md)
- [Owner 決定 D24：三個契約修訂追認、資料集改指 dataset-10、M9 每日軌道登記](evidence/m3-owner-decision-d24-2026-09-03.md)
- [Owner 決定 D23：判斷式研究軌道獲准，M0 §2.1 承認第二個候選來源（m0-v1.7.0）](evidence/m3-owner-decision-d23-2026-09-02.md)
- [Owner 決定 D22：M9 觀察端改為獨立的當日擷取（乙案）](evidence/m3-owner-decision-d22-2026-09-01.md)
- [Owner 決定 D21：名額的第二個耦合寫進 M0 §8（m0-v1.6.0）](evidence/m3-owner-decision-d21-2026-09-01.md)
- [ADR-0001](adr/0001-separate-taiwan-core-and-alphamaster-research.md)
- [ADR-0002](adr/0002-measurement-scale-separate-from-execution-scale.md)
- [M0 專案契約](m0-project-contract.md)
- [M1 架構與重用稽核](m1-architecture-reuse-audit.md)

## M2 官方不可變原始資料

- [M2.2 capture foundation evidence](evidence/m2-2-capture-foundation-2026-08-02.md)
- [M2.3 calendar／master isolated pilot evidence](evidence/m2-3-calendar-master-pilot-2026-08-02.md)
- [M2.3 daily-price pilot and gap audit](evidence/m2-3-daily-price-pilot-and-gap-audit-2026-08-03.md)
- [M2.6 exit verification](evidence/m2-6-exit-verification-2026-08-03.md)
- [M2 三項 Owner 批准決定](evidence/m2-owner-approval-decision-2026-08-03.md)
- [M2 批准、release、durable archive 與 restore closure](evidence/m2-owner-approvals-release-and-durable-audit-2026-08-03.md)
- [M2 不可變官方 Raw Data 實施藍圖](m2-immutable-raw-data-plan.md)
- [M2 操作手冊](m2-operations-runbook.md)
- [M2 官方資料來源清冊](m2-source-inventory.md)

## M3 Point-in-time warehouse

- [M3.1 Source-to-Table Map、Availability 與 Conflict Policy](contracts/m3-source-to-table-map.md)
- [M3 Point-in-time warehouse 契約](contracts/pit-warehouse-contract.md)
- [Official Raw Snapshot 契約](contracts/raw-snapshot-contract.md)
- [TEJ PRO 匯入規格](contracts/tej-import-spec.md)
- [M3.1 完成證據：耐久封存與 coverage ledger](evidence/m3-1-coverage-ledger-and-durable-archival-2026-08-16.md)
- [一個寫死的窗口上界，出現在三支建表程式裡——第三支給的是錯答案不是缺資料](evidence/m3-hardcoded-window-end-2026-09-03.md)
- [`tradability_state` 的分佈：unknown 是零，而那不等於資料完整](evidence/m3-tradability-distribution-2026-09-03.md)
- [制度變更有沒有在窗口裡留下斷點：量了，沒有](evidence/m3-regime-continuity-2026-09-03.md)
- [歷史來源回到哪一年：TWSE 2004、TPEx 2007](evidence/m3-history-reach-probe-2026-09-03.md)
- [M3.10 減資公告日與停止買賣日](evidence/m3-10-reduction-announcement-linkage-2026-08-19.md)
- [M3.11 TPEx 公司行動晉升 canonical 表](evidence/m3-11-tpex-actions-promotion-2026-08-19.md)
- [M3.12 變更股票面額取得官方來源](evidence/m3-12-par-value-change-2026-08-19.md)
- [M3.13 上櫃減資與變更股票面額](evidence/m3-13-tpex-reduction-par-value-2026-08-19.md)
- [M3.14 公司行動接入 as-of 重建](evidence/m3-14-actions-in-asof-2026-08-19.md)
- [M3.15 合併兩份 corporate_actions_pit](evidence/m3-15-single-action-table-2026-08-19.md)
- [M3.16 上櫃公司行動 2019–2023 回補](evidence/m3-16-tpex-actions-2019-2023-2026-08-24.md)
- [M3.17 六年窗口重建，與它叫醒的三件事](evidence/m3-17-six-year-rebuild-2026-08-25.md)
- [M3.1b 完成證據：固定期間全量抓取與 ledger v2](evidence/m3-1b-window-capture-2026-08-16.md)
- [M3.1c TEJ licensed-vendor lane 匯入](evidence/m3-1c-tej-import-2026-08-16.md)
- [M3.1e 公司行動抓取與 coverage ledger v3](evidence/m3-1e-corporate-actions-and-ledger-v3-2026-08-16.md)
- [M3.1f TPEx 公司行動與 coverage ledger v4](evidence/m3-1f-tpex-actions-and-ledger-v4-2026-08-16.md)
- [M3.2 Append-only staging](evidence/m3-2-staging-2026-08-16.md)
- [Exit review](evidence/m3-8-exit-review-2026-08-17.md)
- [M3.9 公司行動取得公告日期](evidence/m3-9-action-availability-2026-08-18.md)
- [M3 entry baseline](evidence/m3-entry-baseline-2026-08-03.md)
- [M3 G0 修訂 v2.0.0 與決定 D9–D10](evidence/m3-g0-amendment-d9-d10-2026-08-16.md)
- [M3 G0 Owner 決定](evidence/m3-g0-owner-decision-2026-08-03.md)
- [歷史市場狀態來源調查（2026-08-16）](evidence/m3-market-status-source-discovery-2026-08-16.md)
- [M3 Owner 決定 D11：減資 FILE_DATE 的 availability basis](evidence/m3-owner-decision-d11-2026-08-19.md)
- [D16](evidence/m3-owner-decision-d16-2026-08-25.md)
- [M3 Owner 決定 D17：M10 阻擋事由改寫與優惠到期處置（m0-v1.2.0）](evidence/m3-owner-decision-d17-2026-08-27.md)
- [M3 Owner 決定 D18：M6.1 依 D9 結案、M10 阻擋改為可取得的證據（m0-v1.3.0）](evidence/m3-owner-decision-d18-2026-08-28.md)
- [M3 Owner 決定 D19：優惠證據封存、報告基準改回牌告（m0-v1.4.0）](evidence/m3-owner-decision-d19-2026-08-29.md)
- [M3 Owner 決定 D20：以封存 PDF 為準，M10 第一項阻擋解除（m0-v1.5.0）](evidence/m3-owner-decision-d20-2026-08-29.md)
- [M3 Owner 決定 D9：全額交割的 availability basis](evidence/m3-owner-decision-d9-2026-08-22.md)
- [M3 Owner 決定 D1–D5 與抓取可行性驗證](evidence/m3-owner-decisions-and-capture-feasibility-2026-08-16.md)
- [M3 Owner 決定 D14、D15 與券商條款來源登錄](evidence/m3-owner-decisions-d14-d15-2026-08-25.md)
- [M3 Owner 決定 D6–D8 與市場狀態抓取](evidence/m3-owner-decisions-d6-d8-2026-08-16.md)
- [M3 Point-in-time warehouse 計畫](m3-point-in-time-warehouse-plan.md)

## M4 台股規則與成本

- [M4 台股規則與成本契約](contracts/m4-market-rules-contract.md)
- [M4.1 除權息日漲跌停由官方法規解決](evidence/m4-1-ex-rights-limits-2026-08-19.md)
- [M4.2 上游化至 Taiwan Core 與指紋異動](evidence/m4-2-upstream-to-taiwan-core-2026-08-19.md)

## M5 現金／股票帳本

- [M5 現金／股票帳本](evidence/m5-cash-share-ledger-2026-08-19.md)
- [M5 手續費折讓變更說明](m5-fee-rebate-change-spec.md)

## M6 帳本驅動回測

- [M6.1 六年窗口重跑：兩個規模，零個策略結論](evidence/m6-1-six-year-rerun-2026-08-25.md)
- [M6.2 換股可行性：一個在建之前就成立的否定結果](evidence/m6-2-rotation-feasibility-2026-08-26.md)
- [M6.3 第一個被排序的候選：12-1 動能，否決](evidence/m6-3-first-ranked-candidate-2026-08-26.md)
- [M6 Phase 0：既有 SEPA 回測的誠實成本重算](evidence/m6-phase0-cost-recompute-2026-08-20.md)
- [M6 Phase 2：凍結研究資料集](evidence/m6-phase2-research-dataset-2026-08-20.md)
- [M6 Phase 3：帳本驅動的回測](evidence/m6-phase3-ledger-backtest-2026-08-20.md)

## M7 巢狀驗證、候選與比較

- [判斷式研究契約](contracts/discretionary-research-contract.md)
- [提案 002：判斷式研究軌道——賺錢也要分得出是運氣還是能力（待 Owner 裁決）](evidence/m7-proposal-002-discretionary-track-2026-09-02.md)
- [提案 001：脫離風險式定量——完整規劃（待 Owner 裁決）](evidence/m7-proposal-001-sizing-basis-2026-09-02.md)
- [診斷 004 結果：不可達，但網格找到一個兩軸都更好的地方](evidence/m7-diagnostic-004-reachability-result-2026-09-02.md)
- [診斷計畫 004：現有的兩個槓桿夠不夠把 33.56% 推到 8%](evidence/m7-diagnostic-plan-004-reachability-2026-09-02.md)
- [候選 006 結果：兩個預期都被否證，方向相反](evidence/m7-candidate-006-result-2026-09-02.md)
- [候選計畫 006：把停損的參考點改成峰值，並把名額收到讓算術成立](evidence/m7-candidate-plan-006-trailing-stop-2026-09-02.md)
- [診斷 003 結果：7.50% 的間隙是用停損價算的，而成交不在停損價](evidence/m7-diagnostic-003-stop-fill-quality-result-2026-09-01.md)
- [診斷計畫 003：停損實際成交在哪裡，與設計差多少](evidence/m7-diagnostic-plan-003-stop-fill-quality-2026-09-01.md)
- [診斷 002 結果：預期成立但理由是錯的，而正確的理由指向政策不指向策略](evidence/m7-diagnostic-002-halt-rules-result-2026-09-01.md)
- [診斷計畫 002：把 M0 §8.1 的停止規則套上去量一次](evidence/m7-diagnostic-plan-002-halt-rules-2026-09-01.md)
- [對照 001 結果：動能勝過 20 個隨機種子的全部，而我的預期因此被否證](evidence/m7-control-001-result-2026-09-01.md)
- [對照計畫 001：隨機選股，M0 §9.1 從未被滿足的那一欄](evidence/m7-control-plan-001-random-selection-2026-09-01.md)
- [候選報告契約](contracts/candidate-report-contract.md)
- [對照比較契約](contracts/control-comparison-contract.md)
- [巢狀驗證契約（M7）](contracts/nested-validation-contract.md)
- [試驗登錄契約](contracts/trial-ledger-contract.md)
- [D9 條件 4：可分離重跑，量出廠商依賴值多少](evidence/d9-condition-4-separable-rerun-2026-08-29.md)
- [LTR 論文可學項目：可學什麼、怎麼落地](evidence/ltr-paper-learnings-2026-08-28.md)
- [候選 003 結果：第一次有東西通過門檻，而我的預期被否證了](evidence/m7-candidate-003-result-2026-08-28.md)
- [候選 004b 結果：誰都沒有通過，而計畫要求的那一欄把比較本身推翻了](evidence/m7-candidate-004b-result-2026-08-28.md)
- [候選 005 結果：預期對了，理由錯了，而正確的理由前一天就量出來了](evidence/m7-candidate-005-result-2026-08-29.md)
- [候選計畫 003：拿掉突破，讓排序第一次獨立被量](evidence/m7-candidate-plan-003-2026-08-28.md)
- [候選計畫 004：把停損從常數改成波動的函數](evidence/m7-candidate-plan-004-2026-08-28.md)
- [候選計畫 004b：拿掉我自己加的兩個夾子](evidence/m7-candidate-plan-004b-2026-08-28.md)
- [候選計畫 005：把唯一有排序能力的東西裝上唯一有效的進場規則](evidence/m7-candidate-plan-005-2026-08-28.md)
- [比較 001 結果：兩個候選誰都沒有勝出](evidence/m7-comparison-001-result-2026-08-28.md)
- [比較計畫 001：12-1 動能 對 60 日低波動](evidence/m7-comparison-plan-001-2026-08-28.md)
- [排名品質量測 001：動能的排序能力與零無法區分](evidence/rank-quality-001-2026-08-28.md)
- [M0 §9.1 缺了三欄，而指數那一欄改變了控制 001 的結論](evidence/m7-benchmarks-and-cost-stress-2026-09-03.md)
- [第 0 步：分鐘資料能改變多少？用日線夾出來，不必先買](evidence/m7-stop-fill-bound-2026-09-04.md)
- [停損不可能成交在當天沒有成交過的價格：修正後差 14.23 個百分點](evidence/m6-gapped-stop-fill-2026-09-04.md)
- [回測器的日線層：記憶體 7.56 → 1.35 GB，耗時 422 → 165 秒](evidence/m6-dataset-column-projection-2026-09-04.md)
- [FinMind 能不能當分鐘資料來源：問了端點，不是問文件](evidence/audit-finmind-intraday-probe-2026-09-04.md)
- [契約要三個度量，倉庫存了兩個](evidence/m3-transactions-restored-2026-09-04.md)

## M9 Shadow 觀察

- [M9：管線 shadow 的兩邊在讀同一份表，而每日重建不是解法](evidence/m9-both-sides-read-the-same-table-2026-09-01.md)
- [M9：擷取排程之前量到的來源落後，與由此加上的拒絕](evidence/m9-observation-source-staleness-2026-09-01.md)
- [Shadow 觀察契約（M9 前半）](contracts/shadow-observation-contract.md)

## 券商條款與成本證據

- [券商條款確認清單](evidence/broker-terms-enquiry-2026-08-27.md)
- [券商條款出處與扣住了什麼](evidence/broker-terms-provenance-2026-08-29.md)

## 研究資料集與候選封包契約

- [研究資料集契約](contracts/research-dataset-contract.md)
- [候選策略封包契約](contracts/strategy-candidate-contract.md)

## 稽核與來源登錄

- [稽核：FinMind 免費層日線交叉驗證](evidence/audit-finmind-crossvalidation-2026-08-21.md)
- [證據來源登錄表](evidence/source-register.md)
- [M2 entry baseline](evidence/tw-sepa-baseline-2026-08-02.md)
