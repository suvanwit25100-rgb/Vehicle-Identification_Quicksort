from app.vision.stitch import agreement, compatible, group_tracks


def test_agreement_counts_only_characters_both_know():
    assert agreement("DL9CA??014", "DL9C??9014") == (7, 0)
    assert agreement("DL1LAJ2850", "DL1L??2711") == (5, 3)


def test_one_clash_blocks_a_merge_even_with_many_agreeing_characters():
    assert compatible("DL1LAJ2850", "DL1LAJ2850")
    assert not compatible("DL1LAJ2850", "DL1LAJ2851")


def test_too_few_shared_characters_do_not_merge():
    assert not compatible("DL1L??????", "DL1L??2711")
    assert not compatible("??????????", "??????????")


def test_fragments_of_one_plate_merge_and_other_plates_stay_apart():
    groups = group_tracks({1: "UP14CA0914", 2: "UP14CA??14", 3: "??14CA0914", 9: "DL8CAY4767", 5: "??????????"})
    assert [1, 2, 3] in groups
    assert [9] in groups and [5] in groups


def test_a_group_never_contains_two_members_that_clash():
    # A fits B and B fits C, but A and C clash, so all three must not end up together
    groups = group_tracks({1: "DL1LAJ28??", 2: "DL1LAJ????", 3: "DL1LAJ2851"}, min_agree=6)
    for g in groups:
        for a in g:
            for b in g:
                if a != b:
                    pats = {1: "DL1LAJ28??", 2: "DL1LAJ????", 3: "DL1LAJ2851"}
                    assert agreement(pats[a], pats[b])[1] == 0
