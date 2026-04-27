from __future__ import annotations

import re


A0_MODULE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "risk": ("风险", "司法", "裁判文书", "被执行", "限高", "失信", "处罚", "违法"),
    "bidding": ("招投标", "招标", "投标", "中标", "采购", "标讯"),
    "profile": ("基本信息", "工商", "档案", "股东", "投资", "分支", "高管", "联系方式"),
}

DEFERRED_MODULE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "ip": ("专利", "商标", "软著", "版权", "知识产权", "认证", "许可"),
    "operation": ("舆情", "招聘", "新闻", "经营", "海关", "抽查", "商品", "电商"),
    "development": ("融资", "上市", "年报", "财务", "发展", "成长", "破产"),
}

ENTITY_NOISE = (
    "查一下",
    "查下",
    "查询",
    "看下",
    "看一下",
    "分析",
    "最近一年",
    "近一年",
    "最近",
    "竞争格局",
    "招投标",
    "裁判文书",
    "基本信息",
    "风险",
    "工商",
    "专利",
    "商标",
    "软著",
    "版权",
    "知识产权",
    "认证",
    "许可",
    "舆情",
    "招聘",
    "新闻",
    "经营",
    "海关",
    "抽查",
    "商品",
    "电商",
    "融资",
    "上市",
    "年报",
    "财务",
    "发展",
    "成长",
    "破产",
    "查",
)


def route_query(query: str) -> dict[str, object]:
    modules = []
    deferred_modules = []
    for module, keywords in A0_MODULE_KEYWORDS.items():
        if any(keyword in query for keyword in keywords):
            modules.append(module)
    for module, keywords in DEFERRED_MODULE_KEYWORDS.items():
        if any(keyword in query for keyword in keywords):
            deferred_modules.append(module)
    if not modules:
        modules = ["profile"]
    route_warnings = [f"{module}_not_available_in_a0" for module in deferred_modules]
    return {
        "intent": "multi_module_company_query" if len(modules) > 1 else f"company_{modules[0]}",
        "modules": modules,
        "deferred_modules": deferred_modules,
        "route_warnings": route_warnings,
        "need_entity_resolve": True,
        "entity_hint": extract_entity_hint(query),
        "suggested_flow": ["entity_resolve", "snapshot", "summary"],
    }


def extract_entity_hint(query: str) -> str:
    text = query.strip()
    for token in ENTITY_NOISE:
        text = text.replace(token, " ")
    for token in ("的", "和", "以及", "与", "在", "里", "最近三年", "近三年", "最近半年", "近半年"):
        text = text.replace(token, " ")
    parts = [item for item in re.split(r"[ ,，。；;、]+", text) if item]
    if not parts:
        return query.strip()
    candidate = max(parts, key=len)
    candidate = re.sub(r"(一|两|三|四|五|六|七|八|九|十|\d+)(年|个月|月|周|天)$", "", candidate).strip()
    return candidate or query.strip()
