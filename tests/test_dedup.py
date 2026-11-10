import numpy as np

from llm_etl.dedup import embed, find_duplicates

BASE = ("Senior Data Engineer\nAcme | Austin, TX\n\nRequirements:\n- Strong Python skills\n"
        "- Experience with Snowflake\n\nHybrid: 2 days a week in our Austin, TX office.")


def test_embedding_is_deterministic_and_unit_norm():
    a, b = embed(BASE), embed(BASE)
    assert np.array_equal(a, b)
    assert abs(np.linalg.norm(a) - 1) < 1e-5


def test_repost_is_more_similar_than_a_different_posting():
    repost = "[Reposted]\n" + BASE.upper() + "\nApply by 3 July."
    other = BASE.replace("Senior Data Engineer", "Junior BI Developer").replace("Snowflake", "Power BI") \
                .replace("Austin, TX", "London, UK").replace("Hybrid: 2 days a week in our", "On-site in our")
    v = embed(BASE)
    assert v @ embed(repost) > 0.9 > v @ embed(other)


def test_chained_duplicates_point_at_the_original():
    v = embed(BASE)
    vectors = np.stack([v, v, v, embed("something entirely different about cooking pasta")])
    found = find_duplicates(["a", "b", "c", "d"], vectors, 0.9)
    assert [(dup, orig) for dup, orig, _ in found] == [("b", "a"), ("c", "a")]
