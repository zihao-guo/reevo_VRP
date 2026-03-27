import re
from typing import Optional


CPP_BLOCK_PATTERN = re.compile(
    r"```(?:cpp|c\+\+|cc|cxx)\s*(.*?)```",
    re.IGNORECASE | re.DOTALL,
)


def extract_cpp_code(content: str) -> Optional[str]:
    # //modify Extracts a complete C++ source file from an LLM response.
    matches = CPP_BLOCK_PATTERN.findall(content)
    if matches:
        code = matches[-1].strip()
        return code if _looks_like_cpp_source(code) else None

    raw = content.strip()
    return raw if _looks_like_cpp_source(raw) else None


def _looks_like_cpp_source(content: str) -> bool:
    return (
        '#include "selective_route_exchange.h"' in content
        and "selectiveRouteExchange" in content
        and "ProblemData const &data" in content
    )
