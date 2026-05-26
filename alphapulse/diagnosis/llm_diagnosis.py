"""LLM-powered one-line stock diagnosis summary."""
import os


def generate_diagnosis_summary(symbol, name, diagnosis, factor_snapshot=None):
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if api_key:
        try:
            import requests

            prompt = (
                f"你是A股短线诊断专家。一句话诊断（20字以内）：\n"
                f"股票: {name}({symbol})\n评分: {diagnosis['total_score']}/100 评级: {diagnosis['grade']}\n"
                f"技术面: {diagnosis['sub_scores']['technical']}/30 量能: {diagnosis['sub_scores']['volume']}/20 "
                f"形态: {diagnosis['sub_scores']['pattern']}/20 风控: {diagnosis['sub_scores']['risk']}/15 "
                f"板块: {diagnosis['sub_scores']['sector']}/15\n只输出一句话"
            )
            resp = requests.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"model": "deepseek-chat", "messages": [{"role": "user", "content": prompt}], "max_tokens": 60},
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception:
            pass

    grade = diagnosis["grade"]
    top = diagnosis.get("top_dimensions", ["technical"])
    grade_map = {"S": "强势突破", "A": "形态良好", "B": "关注确认", "C": "等待信号", "D": "回避"}
    dim_map = {
        "technical": "技术面优",
        "volume": "量能配合",
        "pattern": "形态到位",
        "risk": "低风险",
        "sector": "板块共振",
    }
    parts = [dim_map.get(d, d) for d in top[:2]]
    return f"{name}: {'+'.join(parts)}，{grade_map.get(grade, grade)}，评级{grade}"
