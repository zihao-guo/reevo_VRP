import difflib
import re


COMMENT_PATTERN = re.compile(
    r"//.*?$|/\*.*?\*/",
    re.MULTILINE | re.DOTALL,
)
WHITESPACE_PATTERN = re.compile(r"\s+")


def similarity_ratio(candidate: str, reference: str) -> float:
    # //modify Normalises C++ code before similarity comparison.
    candidate_norm = _normalise(candidate)
    reference_norm = _normalise(reference)
    return difflib.SequenceMatcher(
        a=reference_norm,
        b=candidate_norm,
        autojunk=False,
    ).ratio()


def assert_below_threshold(
    candidate: str,
    reference: str,
    threshold: float,
) -> float:
    ratio = similarity_ratio(candidate, reference)
    if ratio >= threshold:
        raise ValueError(
            f"Candidate rejected by anti-plagiarism check: similarity={ratio:.6f} >= threshold={threshold:.6f}."
        )
    return ratio


def _normalise(content: str) -> str:
    without_comments = COMMENT_PATTERN.sub("", content)
    return WHITESPACE_PATTERN.sub("", without_comments)
