from evals.scoring import iou, top3_hit_rate


def test_iou_full_overlap():
    assert iou(0, 100, 0, 100) == 1.0


def test_iou_no_overlap():
    assert iou(0, 100, 200, 300) == 0.0


def test_iou_partial():
    assert abs(iou(0, 100, 50, 150) - (50 / 150)) < 1e-9


def test_top3_all_hit():
    pred = [(0, 100), (200, 300), (400, 500)]
    gt = [(0, 100), (200, 300)]
    assert top3_hit_rate(pred, gt) == 1.0


def test_top3_no_hit():
    assert top3_hit_rate([(0, 100)], [(500, 600)]) == 0.0


def test_top3_only_first_three_count():
    pred = [(900, 1000), (900, 1000), (900, 1000), (0, 100)]
    assert top3_hit_rate(pred, [(0, 100)]) == 0.0


def test_top3_empty_ground_truth():
    assert top3_hit_rate([(0, 100)], []) == 0.0


def test_iou_adjacent_touching_is_zero():
    # intervals that touch at a single point do not overlap
    assert iou(0, 100, 100, 200) == 0.0


def test_top3_partial_hit_rate():
    pred = [(0, 100)]
    gt = [(0, 100), (500, 600), (900, 1000)]
    assert abs(top3_hit_rate(pred, gt) - (1 / 3)) < 1e-9
