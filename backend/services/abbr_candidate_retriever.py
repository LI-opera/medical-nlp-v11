from data.abbr_candidates import ABBR_CANDIDATES, reload_abbr_candidates_if_changed

class ABBRCandidateRetriever:
    #医学缩写候选召回器
    #作用:输入一个医学缩写，返回它可能对应的多个完整医学术语
    def retrieve(self, abbreviation: str):
        reload_abbr_candidates_if_changed()
        abbr = abbreviation.upper().strip()
        candidates = ABBR_CANDIDATES.get(abbr, [])
        return [
            {"abbreviation": abbr, "expansion": c["expansion"], "domain": c.get("domain")}
            for c in candidates
        ]
    """
    这种写法等价于
    results = []
    for expansion in candidates:
        results.append({
            "abbreviation":abbr,
            "expansion":expansion
        })
    return results    
       """
