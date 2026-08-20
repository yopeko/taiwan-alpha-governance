# M5：現金／股票帳本（2026-08-19）

## 結論

M0 §6 要求的帳本已建立,六項不變量全部以測試強制。**M5 exit gate「帳本恆等式與不可能交易阻擋」通過。**

`test_no_impossible_trade_can_settle` 自 M0 起即為 strict xfail,現已轉為實測通過。治理倉庫僅剩一項 xfail(TEJ 去重鍵),與 M5 無關。

## 1. M5 要解決的問題

M0 §6 開宗明義:「正式驗證不得只計算 `position * return - proportional_cost`」。

理由不是精度。**那個算式無法表達「錢不夠」、無法表達「委託沒成交」、也無法表達「股票還沒交割」**,所以一個在市場上根本不可能執行的策略,在算式裡依然會有漂亮的績效。

M5 的存在就是讓這些失敗變得可表達。

## 2. 核心設計:現金不能被賦值

每一筆 NTD 的移動都是 journal 的一列,`settled_cash` 是「期初餘額 + journal 總和」的**衍生值**。沒有任何路徑可以在不留下一列(且該列必須指名 order 與 fill)的情況下改動餘額。

這讓兩項 M0 不變量從「斷言」變成「結構」:

- **§6.4 每筆費用可回溯至 order 或 fill**——journal 列不帶 id 就無法存在;
- **§6.6 重複執行不得重複成交或重複扣款**——journal 列自帶身分。

## 3. 什麼時候交割

T+2,且以**交易日**計算(沿用 M4 的 `settlement_date`,缺日曆即 fail closed)。成交當日不動 settled cash,而是產生一筆 pending。兩個後果:

- **賣出價款在交割前不是購買力**(§6.5)。`unsettled_proceeds` 特意寫成獨立屬性,讓「不計入」是看得見的排除,而不是算式裡的一個遺漏。
- **當日買進的股票當日不能賣**——那是現股當沖,M0 §8 禁止。但**次一交易日可以賣**:限制到交割才放行等於模擬一條台灣沒有的規則,會讓所有兩日策略無法測試。

## 4. 可交易性由 M3.6 決定,不由帳本決定

`MarketConditions.tradability_state` 由呼叫端從 as-of 重建取得。**`eligible` 以外的每一個值都是拒絕**,理由即該狀態本身。

帳本若自行判斷可交易性,就有權與倉庫不一致,而**不一致會以獲利的形式浮現**。

## 5. 一個被測試抓到的嚴重 bug

第一版寫成 `if request.side is Side.SELL:`。

鏡像設計使得 `Side` **同時存在兩個類別**——Taiwan Core 可匯入時是 `tw_sepa_screener.market_rules.Side`,否則是 `m4.rules.Side`。持有另一個的呼叫端,identity 比對為假,於是**賣單掉進買單分支**。

實測結果:**一筆沒有部位的賣單成交了,憑空建立部位,直接違反 long-only 不變量**——而且只在「兩個模組都可匯入」的機器上發生。

修法不是改成 `==` 比對——那只是把錯誤藏得更好。改為**在邊界正規化**:`_coerce_side()` 把呼叫端傳進來的任何東西轉成本模組的 `Side`,帳本內部因此只有一個 `Side`,任何後續的 identity 比對都不可能出錯。

這個 bug 值得記錄的地方在於:**它是鏡像設計本身引入的風險**,而且是環境相依的——CI 上不會出現,只有本機會。

## 6. 另一項修正:日曆盡頭應是拒絕,不是例外

`settlement_date` 在日曆不足時拋 `RuleError`。第一版讓它直接往上拋,**回測跑到日曆尾端會崩潰**。

改為回傳 `rejected` / `calendar-too-short-to-settle`。fail closed 的正確形式是拒絕並記錄,不是中止整個回測。

## 7. 六項不變量與其測試

| M0 §6 不變量 | 如何強制 | 測試類別 |
|---|---|---|
| 1. 現金＋待交割＋市值 = NAV | `nav()` 由四個成分相加,並經買進、交割、賣出、再交割全程比對 | `TestInvariantOneNavIdentity` |
| 2. 只做多、股數為整數 | 無部位賣出、超額賣出、混合股數皆拒絕 | `TestInvariantTwoLongOnlyIntegerShares` |
| 3. 非交易日／停牌／不合資格不得成交 | 五種 as-of 狀態、休市、漲跌停外、無流動性皆拒絕;**拒絕不動任何現金** | `TestInvariantThreeImpossibleTradesCannotFill` |
| 4. 每筆費用可回溯 | journal 每列皆帶 order 與 fill id;手續費與稅為分開的列 | `TestInvariantFourEveryFeeTracesToAFill` |
| 5. 未交割款不得作為購買力 | 賣出後立即買進被拒;交割後同一筆買進成交 | `TestInvariantFiveUnsettledProceedsAreNotBuyingPower` |
| 6. 重複執行不得重複計算 | 相同 `fill_id` 第二次被拒;交割不可倒退;重複交割不重複入帳 | `TestInvariantSixReplayCannotDoubleCount` |

另有:T+2 以交易日計算並跳過週末、滑價恆為不利方向、NAV 序列與高水位／回撤、部位規模。

**共 51 項測試。**

## 8. 一個示範:天真回測會算出零

同一價格買進再賣出 100 股 @ 50:

| 項目 | 金額 |
|---|---:|
| 買進滑價（+0.20%）| 10 |
| 賣出滑價（−0.20%）| 10 |
| 兩次最低手續費 | 40 |
| 證交稅 0.3% | 14 |
| **合計** | **74** |

`position * return` 會報告 **0**。帳本報告 **−74**,而 NT$10,000 的政策資金下這是 **0.74%**。

## 9. 部位規模:M0 §8 的「不可向上取整後突破上限」

`plan_position()` 依序套用:單筆計畫風險 0.75%、單檔 NAV 上限 45%、最低現金保留 10%、單筆硬上限 1.00%、總開放風險 2.00%,以及**往返成本不得吞掉計畫風險**。

任一項不滿足即回傳 `quantity=0` 與理由,**絕不向上取整**。M0 明文把「向上取整讓部位成立」列為要避免的失效,因此每一道上限都是拒絕而非調整。

最後一項在 NT$10,000 政策下特別會咬人:最低手續費 NT$20 × 2 相對於小額部位的計畫風險往往過大,此時正確答案是 `no_trade`。

## 10. 位置與指紋

沿用 [M4.2](m4-2-upstream-to-taiwan-core-2026-08-19.md) 的作法:

| 位置 | 角色 |
|---|---|
| `tw_sepa_screener.ledger` | **canonical** |
| `m5/ledger.py` | 逐位元相同的鏡像,供治理 CI 執行 51 項測試 |

parity 測試已由單一模組推廣為 `(mirror, canonical)` 清單,同時涵蓋 M4 與 M5,並新增一項檢查:**鏡像的 fallback import 所需的每個符號都存在於 `m4.rules`**。該分支在同時擁有兩個模組的機器上永不執行,否則 CI 會是第一個發現它壞掉的地方。

指紋異動:

| 指紋 | 檔數 | 期間 |
|---|---:|---|
| `d4ef6c0f…` | 180 | M2 release 至 M3 抓取結束 |
| `898ef48a…` | 182 | M4 上游化 |
| `9820fd43…` | 184 | **M5 上游化（本次）** |

Taiwan Core 仍未 commit,理由同 M4.2。

## 11. 驗證

| 項目 | 結果 |
|---|---|
| `m5/tests` | **51 通過** |
| 治理倉庫全套 | **355 通過**、1 strict xfail |
| Taiwan Core smoke | 10 通過（M4 6 + M5 4）|
| M3.7 驗證 | 五項全 `passed` |

`test_no_impossible_trade_can_settle` 已由 strict xfail 轉為實測。**剩餘唯一 xfail 為 TEJ 去重鍵**(代號重用被合併),與 M5 無關。

## 12. 未解決

1. **未與 M3.6 端到端串接**——帳本接受 `tradability_state` 字串,但尚未有把 as-of 重建逐日餵進帳本的驅動程式。那屬 M6 adapter。
2. **零股撮合機率**——M0 規定不得假設必然成交,目前以 `available_quantity` 由呼叫端表達,尚無成交機率模型。
3. **全額交割股預收款券**——未實作;M3 的 `market_status` 已具備辨識所需資料。
4. **券商實際費率**——`assumption`,阻擋 M10。
