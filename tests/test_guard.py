"""Code guard: citations, weak-evidence cap and the numeric check (no LLM)."""

from coverage_detective.agents.guard import Guard, bad_sentences, evidence_numbers, numbers_in

EV = {
    "los_vodafone": {"finding": "Vodafone's nearest approximate site is 3.8 km south-east. Terrain rises 288 m above the "
                                "direct line 2.2 km from here.", "strength": "strong",
                     "value": {"path_length_m": 3838.0, "max_obstruction_m": 288.4}},
    "speed_cell": {"finding": "Mobile download speed averaged 14.4 Mbps in 2026Q3 (4 tests from 4 devices).",
                   "strength": "weak", "value": {"download_mbps": 14.4}, "sample_size": {"tests": 4}},
    "speed_trend": {"finding": "Download speed fell 35% over 4 quarters.", "strength": "weak",
                    "value": {"change_pct": -35.1, "persistence": 0.25}},
}


def guard():
    log = []
    return Guard(EV, log.append), log


def test_numbers_match_within_rounding_and_units():
    allowed = evidence_numbers(list(EV.values()))
    ok = ["The site is 3.8 km away [los_vodafone].", "It is 3.84 km away.", "Terrain rises 288 m.", "About 288.4 m.",
          "A path of 3838 m.", "Speed fell 35%.", "Poor in 25% of quarters.", "14 Mbps from 4 tests in 2026Q3.",
          "All 4 operators."]
    for s in ok:
        assert bad_sentences(s, allowed) == [], s
    assert bad_sentences("Speeds average 22 Mbps here.", allowed) == ["Speeds average 22 Mbps here."]
    assert bad_sentences("The site is 5.1 km away.", allowed)


def test_ids_and_urls_are_not_numbers():
    assert numbers_in("[cand_1] see https://www.ofcom.org.uk/mobile-coverage-checker") == []


def test_unknown_citations_removed_and_recorded():
    g, log = guard()
    assert g.known(["los_vodafone", "made_up_1"], "belief") == ["los_vodafone"]
    assert g.strip_unknown_brackets("Blocked [los_vodafone][made_up_1].", "x") == "Blocked [los_vodafone]."
    assert [i.kind for i in log] == ["unknown_citation", "unknown_citation"]


def test_weak_only_detection():
    g, _ = guard()
    assert g.weak_only(["speed_cell", "speed_trend"]) and not g.weak_only(["speed_cell", "los_vodafone"])


def test_bad_sentence_rewritten_once_then_removed():
    g, log = guard()
    fields = {"explanation": "Hills block the line [los_vodafone]. Speeds average 22 Mbps. The site is 3.8 km away."}
    calls = []

    def rewrite(sentences, cited):
        calls.append(sentences)
        return {"Speeds average 22 Mbps.": "Speeds average 14.4 Mbps [speed_cell]."}

    out = g.check_numbers(fields, {"los_vodafone", "speed_cell"}, "advisor", rewrite)
    assert out["explanation"] == "Hills block the line [los_vodafone]. Speeds average 14.4 Mbps [speed_cell]. The site is 3.8 km away."
    assert len(calls) == 1 and [i.kind for i in log] == ["number_rewritten"]

    g, log = guard()
    out = g.check_numbers(fields, {"los_vodafone"}, "advisor", lambda s, c: {"Speeds average 22 Mbps.": "Still 22 Mbps."})
    assert "22" not in out["explanation"] and [i.kind for i in log] == ["sentence_removed"]
    assert log[0].details["numbers"] == ["22"]
