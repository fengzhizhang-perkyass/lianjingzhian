import math


def expand_score(risk, neighbor_risk, degree, degree_p99, weights):
    denominator = math.log1p(degree_p99)
    normalized = min(max(math.log1p(degree)/denominator, 0), 1) if denominator > 0 else 0
    penalty = 1-normalized
    return weights["risk"]*risk/100 + weights["neighbor_risk"]*neighbor_risk/100 + weights["degree_penalty"]*penalty


def path_score(expansion_scores, length_decay=0.03):
    if not expansion_scores:
        return 0.0
    return sum(expansion_scores)/len(expansion_scores)*math.exp(-length_decay*(len(expansion_scores)-1))
