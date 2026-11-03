from funders.match import Matcher, Seed, norm_name


def seeds():
    return [Seed("cn", "Charity Navigator", "2", [norm_name("Charity Navigator")], {"134148824"}, "NJ"),
            Seed("aspen", "Aspen Institute", "2", [norm_name("Aspen Institute")], purpose_words=["990", "OPEN DATA"]),
            Seed("ff", "Fast Forward", "3", [norm_name("Fast Forward")], {"464626500"}, "CA")]


def test_norm_name():
    assert norm_name("The Charity Navigator, Inc.") == "CHARITY NAVIGATOR"
    assert norm_name("Smith & Sons Co") == "SMITH AND SONS"


def test_tax_id_always_matches():
    m = Matcher(seeds()).match("CN", "13-4148824")
    assert m.status == "matched" and m.reason == "tax ID"


def test_exact_name_matches():
    assert Matcher(seeds()).match("Charity Navigator Inc", "", "NJ").status == "matched"


def test_same_name_other_state_goes_to_review():
    m = Matcher(seeds()).match("FAST FORWARD", "", "OH")
    assert m.status == "review" and "OH" in m.reason


def test_same_name_other_tax_id_goes_to_review():
    assert Matcher(seeds()).match("FAST FORWARD", "99-9999999", "CA").status == "review"


def test_purpose_words_required_for_big_organizations():
    mt = Matcher(seeds())
    assert mt.match("ASPEN INSTITUTE", purpose="OPEN 990 DATA PROJECT").status == "matched"
    assert mt.match("ASPEN INSTITUTE", purpose="IDEAS FESTIVAL").status == "review"


def test_partial_name_goes_to_review_and_unrelated_is_ignored():
    mt = Matcher(seeds())
    assert mt.match("FRIENDS OF CHARITY NAVIGATOR FUND").status == "review"
    assert mt.match("LOCAL FOOD PANTRY") is None


def test_quick_byte_check():
    mt = Matcher(seeds())
    assert mt.might_match(b"...CHARITY NAVIGATOR INC...") and not mt.might_match(b"LOCAL PANTRY")


def test_rules_from_the_first_full_scan(tmp_path):
    from pathlib import Path
    from funders.match import load_seeds
    mt = Matcher(load_seeds(Path(__file__).resolve().parents[1] / "config" / "seeds.toml"))
    # unique names count wherever the address is
    assert mt.match("CHARITY NAVIGATOR", "", "IA").status == "matched"
    assert mt.match("CANDID", "", "OH").status == "matched"
    # pass-through products and look-alikes don't count
    assert mt.match("CHARITY NAVIGATOR GIVING BASKET", "", "NJ") is None
    assert mt.match("SIERRA HEALTH FOUNDATION CENTER FOR HEALTH PROGRAM", "45-5282243", "CA") is None
    assert mt.match("GIVEWELL COMMUNITY FOUNDATION INC", "", "FL") is None
    # longer names that are clearly the organization
    assert mt.match("PROPUBLICA ILLINOIS", "", "NY").status == "matched"
    assert mt.match("THE CLEAR FUND DBA GIVEWELL", "", "CA").status == "matched"
    assert mt.match("CANDID (FORMERLY FOUNDATION CENTER)", "", "NY").status == "matched"
    # Aspen only for nonprofit-data work, by tax ID or name
    assert mt.match("ASPEN INSTITUTE", "84-0399006", "DC", "GENERAL SUPPORT") is None
    assert mt.match("ASPEN INSTITUTE", "84-0399006", "DC", "OPEN 990 DATA").status == "matched"
    # a same-name charity in another state still goes to a person
    assert mt.match("FAST FORWARD", "", "SC").status == "review"
