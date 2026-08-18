"""로마자 선박명 -> 한글 후보명 역변환.

국어의 로마자 표기법(RR)을 역으로 뒤집어 빔서치로 후보를 여러 개 뽑는다.
연음규칙 등 문맥 규칙은 무시(단순화) — 표기자가 정확히 RR을 따랐다는
보장도 없어 근사치로 충분하다고 판단.

같은 라틴 철자로 끝나도 분절 지점에 따라 결과가 갈린다(예: HUIMANG ->
'huim'+'ang' 또는 'hui'+'mang'). 종성(받침)을 더 적게 쓰는 분절을
우선한다 — 한국어 표기 관행상 다음 음절이 모음으로 시작 가능하면 앞
음절에 억지로 받침을 붙이지 않는 경향(예: 노트북이지 놑북이 아님)을
근사한 것.

ponytail: 라틴 철자가 여러 한글 자모조합과 겹칠 때 첫 번째 후보만
쓴다(예: ㅐ/ㅔ 등 표기 관행에 따라 달라질 수 있는 모음). 실제 MOF
재질의 결과로 회수율이 낮으면 이 지점부터 확장.
"""

from __future__ import annotations

INITIALS = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
MEDIALS = [
    "a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe",
    "yo", "u", "wo", "we", "wi", "yu", "eu", "ui", "i",
]
FINALS = [
    "", "k", "k", "k", "n", "n", "n", "t", "l", "k", "m", "l", "l", "l",
    "p", "l", "m", "p", "p", "t", "t", "ng", "t", "t", "k", "t", "p", "t",
]

BEAM = 3


# 받침 인덱스(FINALS)는 라틴 철자가 겹치는 경우가 많다(예: "p" = ㄿ/ㅂ/ㅄ/ㅍ).
# 홑받침이 겹받침보다 훨씬 흔하므로, 테이블을 채울 때 홑받침을 먼저 순회해
# 같은 철자 충돌 시 홑받침이 이기게 한다(그냥 index 순으로 돌면 희귀한
# 겹받침 ㄿ이 흔한 ㅂ보다 먼저 채워지는 버그가 있었음).
_SINGLE_FINALS = [0, 1, 2, 4, 7, 8, 16, 17, 19, 20, 21, 22, 23, 24, 25, 26, 27]
_CLUSTER_FINALS = [3, 5, 6, 9, 10, 11, 12, 13, 14, 15, 18]
_FINAL_PRIORITY = _SINGLE_FINALS + _CLUSTER_FINALS


def _build_reverse_table() -> dict:
    table: dict[str, tuple[str, bool]] = {}
    for fi, ini in enumerate(INITIALS):
        for fm, med in enumerate(MEDIALS):
            for ff in _FINAL_PRIORITY:
                fin = FINALS[ff]
                code = 0xAC00 + (fi * 21 + fm) * 28 + ff
                latin = (ini + med + fin).lower()
                if latin and latin not in table:
                    table[latin] = (chr(code), ff != 0)
    return table


REVERSE = _build_reverse_table()
MAX_CHUNK = max(len(k) for k in REVERSE)


def guess_hangul_candidates(word: str, beam: int = BEAM) -> list:
    """받침 개수가 적은 순으로 정렬한 한글 후보 목록. 분절 자체가 불가능하면
    빈 목록."""
    s = word.lower()
    n = len(s)
    # memo[pos] = [(사용한 받침 수, 이어지는 한글), ...] (받침수 오름차순, 상위 beam개)
    memo: dict[int, list] = {n: [(0, "")]}
    for pos in range(n - 1, -1, -1):
        candidates = []
        for length in range(min(MAX_CHUNK, n - pos), 0, -1):
            chunk = s[pos : pos + length]
            hit = REVERSE.get(chunk)
            if not hit:
                continue
            hangul, has_final = hit
            for final_count, suffix in memo.get(pos + length, []):
                candidates.append((final_count + (1 if has_final else 0), hangul + suffix))
        candidates.sort(key=lambda c: c[0])
        memo[pos] = candidates[:beam]

    seen = set()
    out = []
    for _, hangul in memo.get(0, []):
        if hangul not in seen:
            seen.add(hangul)
            out.append(hangul)
    return out


def split_digit_prefix(name: str) -> tuple:
    """'77HUIMANG' -> ('77', 'HUIMANG'). 숫자접두어는 한글 이름에도 그대로
    붙는 경우가 많아 분리해서 후보 앞에 다시 붙인다."""
    i = 0
    while i < len(name) and name[i].isdigit():
        i += 1
    return name[:i], name[i:]


def candidate_names(gfw_name: str, beam: int = BEAM) -> list:
    """GFW 선박명(로마자) -> MOF 질의용 한글 후보명 목록(숫자접두어 복원 포함)."""
    cleaned = gfw_name.replace(" ", "")
    prefix, rest = split_digit_prefix(cleaned)
    return [prefix + h for h in guess_hangul_candidates(rest, beam=beam)]


if __name__ == "__main__":
    samples = [
        "GISUNGHO", "2 DEOKSEUNGHO", "YOU LIM HO", "FISHING MASTER",
        "EUNSEONGHO", "KO SOO", "YUNG IN HO", "77HUIMANG",
    ]
    for name in samples:
        print(f"{name!r:22} -> {candidate_names(name)}")
