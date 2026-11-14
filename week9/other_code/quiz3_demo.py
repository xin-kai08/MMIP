"""Deterministic UI demonstration ONLY; not VLM inference or accuracy evidence."""
import copy
import json
import re


class DemoEngine:
    mode = "simulation_rules_not_vlm"

    def classify(self, text, has_image, facts):
        if any(word in text for word in ("忽略規則", "忽略所有", "系統提示", "退款完成", "忽略原本")):
            kind = "blocked"
        elif any(word in text for word in ("人工", "真人")):
            kind = "human"
        elif any(word in text for word in ("寫詩", "一首詩", "作業", "天氣")):
            kind = "off_topic"
        else:
            kind = "case"
        return kind, {"source": "demo_keyword_rules", "not_model_prediction": True}

    def extract(self, messages, facts, session_dir):
        text = next(msg["text"] for msg in reversed(messages) if msg["role"] == "user")
        result = copy.deepcopy(facts)
        for product in ("耳機", "鍵盤", "滑鼠", "手機", "USB裝置"):
            if product in text:
                result["product"] = product
                break
        match = re.search(r"(?:訂單編號|訂單號碼|訂單)(?:是|為|[:：]|\s)*([A-Za-z0-9_-]+)", text)
        if match:
            result["order_id"] = match.group(1)
        if "破損" in text or "碎" in text:
            result["problem"] = "使用者回報外觀破損" + ("、零件露出" if "零件" in text else "")
            result["department"] = "returns"
        elif "連不上" in text or "無法連線" in text:
            result["problem"] = "使用者回報裝置無法連線"
            result["department"] = "technical_support"
        elif "配送" in text or "沒收到" in text:
            result["problem"] = "使用者查詢未收到商品的配送狀況"
            result["department"] = "order_logistics"
            result["requested_action"] = "查詢配送狀況"
        if "退貨" in text:
            result["requested_action"] = "退貨"
        elif "換貨" in text:
            result["requested_action"] = "換貨"
        elif "補寄" in text:
            result["requested_action"] = "補寄"
        elif "排查" in text or "排除" in text:
            result["requested_action"] = "協助排查"
        result["needs_clarification"] = result["problem"] is None
        result["clarification_question"] = "請問是按鍵、連線、外觀或其他問題？" if result["needs_clarification"] else None
        return json.dumps(result, ensure_ascii=False), {
            "decoding": "simulation", "limit_reached": False,
            "note": "規則產生的示意資料；未讀取或辨識圖片。",
        }
