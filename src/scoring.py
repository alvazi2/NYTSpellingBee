"""NYT Spelling Bee scoring rules — single source of truth for merge.py and generate.py."""


def score_word(word: str, pangrams: set[str]) -> int:
    """NYT scoring: 4 letters = 1 pt, 5+ letters = 1 pt/letter, pangram = +7."""
    n = len(word)
    return (1 if n == 4 else n) + (7 if word.lower() in pangrams else 0)
