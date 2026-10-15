def calculate_average(scores):
    if not scores:
        return 0
    total = 0
    for s in scores:
        total = total + s
    return total / len(scores)


def findStudent(students, id):
    for s in students:
        if s["id"] == id:
            return s
    return None


def process_grades(grades, threshold=60, mode="normal", strict=False, verbose=False, callback=None):
    result = []
    if grades:
        if mode == "normal":
            for g in grades:
                if g >= threshold:
                    if strict:
                        if g > threshold + 10:
                            result.append(g * 1.1)
                        else:
                            result.append(g)
                    else:
                        result.append(g)
                else:
                    if verbose:
                        print("低于阈值:", g)
                    result.append(0)
        elif mode == "curve":
            for g in grades:
                if g >= threshold:
                    result.append(min(100, g + 5))
                else:
                    result.append(g)
    return result


DEFAULT_WEIGHTS = {"math": 0.5, "english": 0.3, "science": 0.2}


def weighted_score(scores, weights=DEFAULT_WEIGHTS):
    score = 0
    for subject, weight in weights.items():
        try:
            score += scores[subject] * weight
        except Exception:
            pass
    return score