"""跨 venue 套利净边计算与方向选择。"""
from prediction_markets.models import Quote
from prediction_markets import arb


def _q(venue, cost_yes, cost_no, title="x"):
    return Quote(venue=venue, market_id=f"{venue}-1", title=title,
                 cost_yes=cost_yes, cost_no=cost_no, yes_bid=cost_yes - 0.01,
                 no_bid=cost_no - 0.01)


def test_positive_net_edge_kalshi_poly():
    # 买 YES@kalshi 0.40 + 买 NO@poly 0.55 => gross 0.05；kalshi费=ceil(0.07*.4*.6)=0.02，poly费0
    qk = _q("kalshi", 0.40, 0.62)
    qp = _q("polymarket", 0.45, 0.55)
    e = arb.best_edge(qk, qp, label="t")
    assert e is not None
    assert e.buy_yes_venue == "kalshi" and e.buy_no_venue == "polymarket"
    assert abs(e.gross_edge - 0.05) < 1e-9
    assert abs(e.fee_yes - 0.02) < 1e-9 and e.fee_no == 0.0
    assert abs(e.net_edge - 0.03) < 1e-9
    assert e.capturable is True


def test_direction_selection_picks_better():
    # 反方向更优：买 YES@poly 0.30 + 买 NO@kalshi 0.30 => gross 0.40
    qk = _q("kalshi", 0.80, 0.30)
    qp = _q("polymarket", 0.30, 0.75)
    e = arb.best_edge(qk, qp)
    assert e.buy_yes_venue == "polymarket" and e.buy_no_venue == "kalshi"
    assert e.gross_edge > 0.3


def test_no_edge_when_expensive():
    qk = _q("kalshi", 0.60, 0.60)
    qp = _q("polymarket", 0.60, 0.60)
    e = arb.best_edge(qk, qp)
    # 1-0.6-0.6 = -0.2，扣费更负
    assert e.capturable is False and e.net_edge < 0


def test_reference_price_note_propagates():
    ql = Quote(venue="limitless", market_id="l1", title="x", cost_yes=0.30, cost_no=0.60,
               raw={"price_is_reference": True})
    qp = _q("polymarket", 0.45, 0.55)
    e = arb.best_edge(ql, qp)
    assert "参考价" in e.notes


def test_missing_price_returns_none():
    qk = Quote(venue="kalshi", market_id="k", title="x", cost_yes=None, cost_no=None)
    qp = _q("polymarket", 0.45, 0.55)
    assert arb.best_edge(qk, qp) is None


TESTS = [test_positive_net_edge_kalshi_poly, test_direction_selection_picks_better,
         test_no_edge_when_expensive, test_reference_price_note_propagates,
         test_missing_price_returns_none]
