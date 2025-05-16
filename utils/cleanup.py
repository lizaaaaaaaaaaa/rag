def cleanup_answer(text: str, max_lines: int = 20) -> str:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    seen, cleaned = set(), []
    for l in lines:
        norm = l.lstrip("・-• ").strip().lower()
        if norm not in seen:
            seen.add(norm)
            cleaned.append(l.replace("•", "-").replace("・", "-"))
    return "\n".join(cleaned[:max_lines])
