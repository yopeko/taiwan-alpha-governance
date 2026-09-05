"""三大法人買賣超這條 lane，和它靠算術而不是靠記憶釘出來的欄位順序。

TWSE 的欄名唯一，所以按名字讀，三種版面都活得下來。

TPEx 把七組欄位取了**同樣的三個名字**，而 JSON 把說明哪一組是哪一組的表頭
壓平了。欄名完全不帶資訊。

所以順序不是假設來的，是三條算術恆等式定出來的——資料要嘛滿足要嘛不滿足。
測試盯著那三條，因為版面若改了順序，**算術會在訊號被汙染之前先壞掉**。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts" / "m3"))

import build_institutional as lane  # noqa: E402

CAPTURE = (REPO / "scripts" / "m3" / "capture_institutional.py").read_text(
    encoding="utf-8"
)


def tpex_row(symbol: str, groups: list[int], total: int) -> list:
    """一列 TPEx 原始資料：代號、名稱，七組各三欄，最後總計。"""

    row: list = [symbol, "測試"]
    for net in groups:
        row += ["0", "0", f"{net:,}"]
    row.append(f"{total:,}")
    return row


class TestTpexOrderIsDerivedNotAssumed:
    def test_the_three_identities_are_the_ones_documented(self):
        source = (REPO / "scripts" / "m3" / "build_institutional.py").read_text(
            encoding="utf-8"
        )
        assert "g0 + g1 == g2" in source
        assert "g4 + g5 == g6" in source
        assert "g2 + g3 + g6 == T" in source

    def test_a_consistent_session_passes(self):
        # 外資 3 + 外資自營 4 = 7；自營自行 5 + 避險 6 = 11；7 + 投信 2 + 11 = 20
        rows = [tpex_row("1234", [3, 4, 7, 2, 5, 6, 11], 20)]
        checks = lane.verify_tpex_identities(rows, "2022-03-16")
        assert checks == {
            "foreign_subtotal": 0,
            "dealer_subtotal": 0,
            "grand_total": 0,
            "rows": 1,
        }

    @pytest.mark.parametrize(
        "groups, total, broken",
        [
            ([3, 4, 99, 2, 5, 6, 11], 20, "foreign_subtotal"),
            ([3, 4, 7, 2, 5, 6, 99], 20, "dealer_subtotal"),
            ([3, 4, 7, 2, 5, 6, 11], 99, "grand_total"),
        ],
    )
    def test_a_reordered_layout_stops_the_build(self, groups, total, broken):
        """版面若改了順序，按位置讀就會取到別的欄位。**那要在建置時炸掉，
        不是在某個訊號裡靜靜地錯下去。**"""

        with pytest.raises(SystemExit) as caught:
            lane.verify_tpex_identities([tpex_row("1234", groups, total)], "2022-03-16")
        assert broken in str(caught.value)
        assert "Re-derive" in str(caught.value)

    def test_the_investment_trust_column_is_where_the_arithmetic_put_it(self):
        assert lane.TPEX_POSITIONS["investment_trust_net"] == 13

    def test_a_row_with_unparseable_numbers_is_skipped_not_counted_as_broken(self):
        """看不懂的列不是版面壞了的證據，把它算成違反會讓守門失去意義。"""

        row = tpex_row("1234", [3, 4, 7, 2, 5, 6, 11], 20)
        row[4] = "－"
        checks = lane.verify_tpex_identities([row], "2022-03-16")
        assert checks["rows"] == 0 and checks["grand_total"] == 0


class TestTwseIsReadByNameAcrossThreeLayouts:
    def test_the_foreign_column_has_both_layouts_names(self):
        """2012 年版叫「外資買賣超股數」，2018 年版叫「外陸資買賣超股數
        (不含外資自營商)」。按位置讀會在版面交界處靜靜取錯欄。"""

        assert lane.TWSE_FIELDS["foreign_net"] == (
            "外陸資買賣超股數(不含外資自營商)",
            "外資買賣超股數",
        )

    def test_a_measure_with_no_matching_name_is_null(self):
        document = {
            "fields": ["證券代號", "證券名稱", "投信買賣超股數"],
            "data": [["2330", "台積電", "1,000"]],
        }
        rows = lane.twse_rows(document, "2022-03-16", {"snapshot_id": "s"})
        assert rows[0]["investment_trust_net"] == 1000
        assert rows[0]["foreign_net"] is None
        assert rows[0]["dealer_net"] is None

    def test_the_identity_is_scoped_to_ordinary_shares(self):
        """權證的外資自營與自營欄重疊——發行券商是外資自營商，同一筆進兩欄
        而公布的總計只算一次。實測 733/40,175 全部是 0 開頭。

        **在那些列上斷言等式會讓正確的資料建置失敗**，而一個常常誤報的守門
        會被關掉。"""

        warrant = {
            "market": "TWSE", "session_date": "d", "symbol": "03084P",
            "security_name": "權證", "foreign_net": 0, "foreign_dealer_net": -336000,
            "investment_trust_net": 0, "dealer_own_net": 0,
            "dealer_hedge_net": -336000, "dealer_net": -336000,
            "total_net": -336000,
        }
        # 四欄相加是 -672,000，公布總計是 -336,000——不在範圍內，不該擋。
        assert lane.verify_twse_identities([warrant], "d")["ordinary_rows"] == 0

    def test_an_ordinary_share_that_breaks_the_identity_stops_the_build(self):
        share = {
            "market": "TWSE", "session_date": "d", "symbol": "2330",
            "security_name": "台積電", "foreign_net": 1, "foreign_dealer_net": 1,
            "investment_trust_net": 1, "dealer_own_net": 0,
            "dealer_hedge_net": 1, "dealer_net": 1, "total_net": 99,
        }
        with pytest.raises(SystemExit) as caught:
            lane.verify_twse_identities([share], "d")
        assert "grand_total" in str(caught.value)

    def test_the_dealer_subtotal_is_checked_on_every_row(self):
        """自營自行 + 避險 == 自營合計 在權證上也成立，所以那一條不設範圍。"""

        broken = {
            "market": "TWSE", "session_date": "d", "symbol": "03084P",
            "security_name": "權證", "foreign_net": 0, "foreign_dealer_net": 0,
            "investment_trust_net": 0, "dealer_own_net": 1,
            "dealer_hedge_net": 1, "dealer_net": 99, "total_net": 0,
        }
        with pytest.raises(SystemExit) as caught:
            lane.verify_twse_identities([broken], "d")
        assert "dealer_subtotal" in str(caught.value)


class TestTheCaptureKeepsTheLanesManners:
    def test_the_interval_floor_is_the_one_every_lane_uses(self):
        assert "INTERVAL_FLOOR = 6.0" in CAPTURE
        assert "refused by twse.com.tw" in CAPTURE

    def test_output_may_not_land_in_the_repository(self):
        assert "root = args.output_root.resolve()" in CAPTURE
        assert "is inside the repository" in CAPTURE

    def test_it_resumes_on_hash_verified_sessions(self):
        """六小時比這台機器可靠清醒的時間長。一次被砍掉的擷取要能接續，
        否則 lane 永遠補不完。"""

        assert 'record.get("capture_status") != "hash-verified"' in CAPTURE

    def test_the_bytes_are_kept_whatever_they_say(self):
        """交易所的非交易日回應是證據不是錯誤，而錯誤頁也是證據——只是
        不是答案。兩者都被保存，差別在**要不要重試、算不算已持有**。"""

        assert "preserved as evidence either way" in CAPTURE
        assert "not-json" in CAPTURE

    def test_it_refuses_if_a_protected_store_changed(self):
        assert "protected_unchanged" in CAPTURE


class TestTheTwoMarketsAreNotForcedIntoOneShape:
    def test_each_row_carries_which_scope_it_was_drawn_on(self):
        assert lane.TPEX_SCOPE == "tpex-includes-block-odd-lot-omnibus"
        assert lane.TWSE_SCOPE == "twse-t86-as-published"

    def test_twse_has_no_foreign_subtotal_and_that_is_null_not_zero(self):
        """TWSE 的 19 欄版沒有「外資合計」這一欄。**零是一個數字，缺席不是。**"""

        assert "foreign_total_net" not in lane.TWSE_FIELDS
        assert "foreign_total_net" in lane.TPEX_POSITIONS

    def test_the_point_in_time_rule_is_written_down(self):
        """買賣超收盤後才公布。T 日用 T 日的排名進場是前視。"""

        source = (REPO / "scripts" / "m3" / "build_institutional.py").read_text(
            encoding="utf-8"
        )
        # 字串在原始碼裡跨行，所以比對不跨行的片段。
        assert "only point-in-time if the rank is taken after " in source
        assert "acted on the next session" in source


class TestAWellFormedNothingIsNotAnAnswerEither:
    """同一個缺陷有兩個變種，而第一版守門只擋得住其中一個。

    TPEx 偶爾對一個合法請求回 **HTTP 200 加一頁 7,343 位元組的 HTML**——
    六年執行的前 79 個觀測裡出現兩次，鄰近場次都正常。那個變種擋住了，因為
    它的第一個位元組不是 `{`。

    **第二個變種穿過去了，而且撐完了整個六年執行。**

        {"stat":"ok","date":"114/04/09","tables":[{...,"data":[]}]}

    641 位元組、合法 JSON、日期正確、表是空的。那天 TPEx 有 846 檔有量成交，
    重問交易所回 887 列。它以 `hash-verified` / `official-captured` 入庫，
    守門放行，續跑算它已持有，倉庫裡多了一個下游分不出是不是假日的洞。

    它不是被任何守門抓到的，是被算術抓到的：2,002 個平日減 1,862 個場次是
    140 個非交易日，乘二是 280，而建置報了 281 個空的。**差額只有一個，那
    一個就是它。**

    `hash-verified` 講的是位元組與雜湊相符，不是位元組說了什麼。這個 class
    存在是為了把那句話釘死在兩個變種上。
    """

    def _blob(self, root, prefix: str, payload: bytes) -> str:
        blob = prefix + "0" * (64 - len(prefix))
        target = root / "raw_blobs" / "sha256" / blob[:2] / blob
        target.mkdir(parents=True)
        (target / "payload.bin").write_bytes(payload)
        return blob

    def test_an_html_error_page_is_not_an_answer(self, tmp_path):
        import capture_institutional as capture

        blob = self._blob(tmp_path, "ab", b"<!DOCTYPE html><html>error</html>")
        assert capture.payload_has_rows(tmp_path, {"blob_id": blob}) is False

    def test_valid_json_with_an_empty_table_is_not_an_answer(self, tmp_path):
        """**這是撐完六年執行的那一個。**"""

        import capture_institutional as capture

        blob = self._blob(
            tmp_path,
            "cd",
            '{"stat":"ok","date":"114/04/09","tables":[{"data":[]}]}'.encode(),
        )
        assert capture.payload_has_rows(tmp_path, {"blob_id": blob}) is False

    def test_a_table_with_rows_is_an_answer(self, tmp_path):
        import capture_institutional as capture

        blob = self._blob(
            tmp_path, "de", b'{"tables":[{"data":[["1234","TEST"]]}]}'
        )
        assert capture.payload_has_rows(tmp_path, {"blob_id": blob}) is True

    def test_a_missing_blob_is_not_an_answer(self, tmp_path):
        import capture_institutional as capture

        assert capture.payload_has_rows(tmp_path, {"blob_id": "ef" + "0" * 62}) is False
        assert capture.payload_has_rows(tmp_path, {}) is False

    def test_the_resume_would_have_made_the_hole_permanent(self):
        """`already_held` 若只看 `capture_status`，那兩種回應都會被算成已持有，
        續跑永遠跳過那個場次，而下游分不出它與真正的非交易日。"""

        assert "if not payload_has_rows(store_root, record):" in CAPTURE
        assert "would make the hole permanent" in CAPTURE

    def test_the_cost_of_the_stricter_guard_is_written_down(self):
        """代價是真正的非交易日每次續跑都會被重問一次。那是六秒，而且**要
        寫下來**——一個沒有標價的守門，下次有人嫌慢時會被拆掉。"""

        assert "re-asked on" in CAPTURE and "costs six seconds" in CAPTURE

    def test_a_non_json_reply_is_retried_rather_than_accepted(self):
        """重試迴圈原本只處理連線例外。一個 200 帶 HTML 不是發行者說「那天
        沒有交易」，是網站壞了，而鄰近場次正常回應。"""

        assert "if attempt == retry_limit:" in CAPTURE
        assert "Retried, not accepted" in CAPTURE


class TestTheBuildAsksTheWarehouseWhichDaysTraded:
    """擷取端的守門只知道自己拿到什麼，不知道那天該不該有東西。

    只有倉庫知道哪幾天有交易，所以「這個市場那天成交了嗎、我們拿到報表了
    嗎」這個問題只有建置器問得出來。它在每次建置跑，因為那個空表不是被守門
    抓到的——是被事後手算抓到的，而手算不會每次都做。
    """

    def test_a_traded_market_session_with_no_rows_stops_the_build(self, tmp_path):
        import pyarrow as pa
        import pyarrow.parquet as pq

        prices = tmp_path / "p"
        prices.mkdir()
        pq.write_table(
            pa.table(
                {
                    "market": ["TWSE", "TPEX"],
                    "session_date": ["2025-04-09", "2025-04-09"],
                    "volume": [1000, 1000],
                }
            ),
            prices / "daily_prices_pit.parquet",
        )
        with pytest.raises(SystemExit) as caught:
            lane.verify_against_prices({("TWSE", "2025-04-09")}, prices)
        assert "traded and have no institutional rows" in str(caught.value)
        assert "('TPEX', '2025-04-09')" in str(caught.value)

    def test_a_day_with_no_traded_volume_needs_no_rows(self, tmp_path):
        """真正的非交易日仍然合法：那天沒有成交的市場場次可以比對。"""

        import pyarrow as pa
        import pyarrow.parquet as pq

        prices = tmp_path / "p"
        prices.mkdir()
        pq.write_table(
            pa.table(
                {
                    "market": ["TWSE", "TWSE"],
                    "session_date": ["2025-04-09", "2025-04-10"],
                    "volume": [1000, 0],
                }
            ),
            prices / "daily_prices_pit.parquet",
        )
        coverage = lane.verify_against_prices({("TWSE", "2025-04-09")}, prices)
        assert coverage["traded_market_sessions"] == 1
        assert coverage["covered_without_trading"] == 0

    def test_an_attempt_is_not_an_answer(self):
        """一次六年執行留下三種觀測，只有一種是報表。讀到錯誤頁那一份，會把
        一頁 HTML 建成一個訊號。"""

        source = (REPO / "scripts" / "m3" / "build_institutional.py").read_text(
            encoding="utf-8"
        )
        assert 'record.get("capture_status") != "hash-verified"' in source
        assert "An attempt is not an answer" in source


class TestAbsenceMeansZeroNotMissing:
    """這條 lane 最容易被誤用的地方，而誤用不會報錯。

    兩個交易所都會發布 `total_net = 0` 的列（2–8%），所以報表不是「只列有動
    的」。可是有量普通股只被涵蓋 0.83（TPEx）到 0.97（TWSE）。缺席的那些，
    成交量中位數比在席的低一個數量級——2019-01-22 TPEx 是 20,000 對 224,000，
    2019-11-01 TWSE 是 29,000 對 504,994，而 TWSE 缺席者裡量最大的幾檔收在
    0.73、1.80、2.51 元。

    **所以沒有列的意思是那天沒有法人單，不是資料缺。**

    而缺席率隨年份收斂：TPEx 36.6%（2019）→ 9.2%（2026），TWSE 10.6% → 1.0%。
    用 inner join 接這張表，會丟掉一批**隨年份變化、且與規模相關**的股票，
    早年丟得多、小型股丟得多。那個偏誤朝著美化的方向，而且不會有任何錯誤訊息。
    """

    def test_the_join_rule_is_written_down_next_to_the_data(self):
        source = (REPO / "scripts" / "m3" / "build_institutional.py").read_text(
            encoding="utf-8"
        )
        assert "absence of a row means no institutional order flow" in source
        assert "left join" in source

    def test_the_measured_dropout_is_recorded_not_rounded_away(self):
        evidence = (
            REPO / "docs" / "evidence" / "m3-institutional-lane-2026-09-05.md"
        ).read_text(encoding="utf-8")
        assert "36.6%" in evidence and "9.2%" in evidence
