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


class TestAnErrorPageIsNotAnAnswer:
    """實跑八分鐘後才現形的缺陷，而它會讓 lane 留下永久的洞。

    TPEx 偶爾對一個合法請求回 **HTTP 200 加一頁 7,343 位元組的 HTML**——
    六年執行的前 79 個觀測裡出現兩次，而它們的鄰近場次都正常回應。

    那些位元組被忠實保存、雜湊驗證通過。`hash-verified` 講的是位元組與雜湊
    相符，**不是位元組說了什麼**。
    """

    def test_hash_verified_does_not_mean_usable(self, tmp_path):
        """這條測試的存在就是為了把那句話釘住。"""

        import capture_institutional as capture

        root = tmp_path
        blob = "ab" + "0" * 62
        target = root / "raw_blobs" / "sha256" / blob[:2] / blob
        target.mkdir(parents=True)
        (target / "payload.bin").write_bytes(b"<!DOCTYPE html><html>error</html>")
        assert capture.payload_is_json(root, {"blob_id": blob}) is False

    def test_a_json_payload_is_usable(self, tmp_path):
        import capture_institutional as capture

        blob = "cd" + "0" * 62
        target = tmp_path / "raw_blobs" / "sha256" / blob[:2] / blob
        target.mkdir(parents=True)
        (target / "payload.bin").write_bytes(b'{"tables":[]}')
        assert capture.payload_is_json(tmp_path, {"blob_id": blob}) is True

    def test_a_missing_blob_is_not_usable(self, tmp_path):
        import capture_institutional as capture

        assert capture.payload_is_json(tmp_path, {"blob_id": "ef" + "0" * 62}) is False
        assert capture.payload_is_json(tmp_path, {}) is False

    def test_the_resume_would_have_made_the_hole_permanent(self):
        """修正前 `already_held` 只看 `capture_status`。那個 HTML 會被算成
        已持有，續跑永遠跳過那個場次，而下游分不出它與真正的非交易日。"""

        assert "if not payload_is_json(store_root, record):" in CAPTURE
        assert "would make the hole permanent" in CAPTURE

    def test_a_non_json_reply_is_retried_rather_than_accepted(self):
        """重試迴圈原本只處理連線例外。一個 200 帶 HTML 不是發行者說「那天
        沒有交易」，是網站壞了，而鄰近場次正常回應。"""

        assert "if attempt == retry_limit:" in CAPTURE
        assert "Retried, not accepted" in CAPTURE
