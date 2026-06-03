def iou(a_start: int, a_end: int, b_start: int, b_end: int) -> float:
    inter = max(0, min(a_end, b_end) - max(a_start, b_start))
    union = max(a_end, b_end) - min(a_start, b_start)
    return inter / union if union > 0 else 0.0


def top3_hit_rate(predicted, ground_truth, iou_threshold: float = 0.5) -> float:
    """Recall-style: fraction of ground_truth windows hit (IoU>=threshold) by any of the
    first 3 predicted windows. `predicted`/`ground_truth` are lists of (start_ms, end_ms);
    the caller is responsible for ordering `predicted` by score desc. Empty GT -> 0.0."""
    if not ground_truth:
        return 0.0
    top = predicted[:3]
    hits = 0
    for g in ground_truth:
        if any(iou(p[0], p[1], g[0], g[1]) >= iou_threshold for p in top):
            hits += 1
    return hits / len(ground_truth)
