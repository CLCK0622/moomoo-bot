"""事件匹配：token 归一 / Jaccard / 跨 venue 候选建议。"""
from prediction_markets.models import Quote
from prediction_markets import event_matcher as em


def test_normalize_drops_stopwords():
    toks = em.normalize_tokens("Will Bitcoin be up on 2026?")
    assert "bitcoin" in toks
    assert "will" not in toks and "the" not in toks and "2026" not in toks


def test_jaccard_bounds():
    a = em.normalize_tokens("Bitcoin above 70000 friday")
    b = em.normalize_tokens("Bitcoin above 70000 friday")
    assert em.jaccard(a, b) == 1.0
    assert em.jaccard(a, set()) == 0.0


def test_suggest_pairs_cross_venue_only():
    qbv = {
        "kalshi": [Quote(venue="kalshi", market_id="k1",
                         title="Bitcoin above 70000 on friday", expiration_ts=1000)],
        "polymarket": [Quote(venue="polymarket", market_id="p1",
                            title="Bitcoin above 70000 friday close", expiration_ts=1200)],
        "limitless": [Quote(venue="limitless", market_id="l1",
                           title="Ethereum below 3000 friday", expiration_ts=1000)],
    }
    pairs = em.suggest_pairs(qbv, min_jaccard=0.4, max_skew=10_000)
    # 应匹配 k1<->p1（同 bitcoin/70000/friday），不匹配 ETH
    assert any(p["market_a"] == "k1" and p["market_b"] == "p1"
               or p["market_a"] == "p1" and p["market_b"] == "k1" for p in pairs)
    # 不应出现同 venue 配对
    for p in pairs:
        assert p["venue_a"] != p["venue_b"]


def test_suggest_pairs_skew_filter():
    qbv = {
        "kalshi": [Quote(venue="kalshi", market_id="k1",
                         title="Bitcoin above 70000 friday", expiration_ts=1000)],
        "polymarket": [Quote(venue="polymarket", market_id="p1",
                            title="Bitcoin above 70000 friday", expiration_ts=1_000_000)],
    }
    pairs = em.suggest_pairs(qbv, min_jaccard=0.4, max_skew=3600)
    assert pairs == []   # 结算时间错位过大，被过滤


TESTS = [test_normalize_drops_stopwords, test_jaccard_bounds,
         test_suggest_pairs_cross_venue_only, test_suggest_pairs_skew_filter]
