import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import re
from PIL import Image
import io

# ==========================================
# 1. 웹 사이트 기본 설정 및 보안 금고
# ==========================================
st.set_page_config(page_title="지능형 단가 분석 엔진", page_icon="🧾", layout="wide")

try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=API_KEY)
except Exception:
    st.error("❌ 시스템 에러: 서버 금고에 API 키가 없습니다. Settings > Secrets를 확인하세요.")
    st.stop()

def get_best_available_model():
    available_models = []
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            available_models.append(m.name)
    priorities = ['models/gemini-1.5-pro-latest', 'models/gemini-1.5-pro', 'models/gemini-1.5-flash-latest']
    for target in priorities:
        if target in available_models: return target.replace('models/', '')
    return available_models[0].replace('models/', '') if available_models else 'gemini-1.5-flash'

# ==========================================
# 2. V10 코어 엔진: 비즈니스 로직 및 AI 뇌 구조
# ==========================================
def extract_json_from_text(text):
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match: return json.loads(match.group(0))
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match: return json.loads(match.group(0))
    raise ValueError("JSON 형식을 찾을 수 없습니다.")

def calculate_true_unit_price(data):
    summary = data.get("summary", {})
    items = data.get("items", [])
    
    # [수학적 교정] 순수 할인율 도출 로직 (이중 부가세 방지)
    total_original = float(summary.get("총주문금액", 1))
    if total_original == 0: total_original = 1
    total_discount = float(summary.get("총할인금액", 0))
    payment_ratio = (total_original - total_discount) / total_original
    
    processed_data = []
    for item in items:
        name = item.get("상품명", "알수없음")
        original_price = float(item.get("원래가격", 0))
        qty = float(item.get("기본수량", 1))
        promo_qty = float(item.get("증정수량", 0))
        units_per_box = float(item.get("포장당_낱개수량", 1)) 
        is_vat_included = item.get("부가세포함여부", True)
        
        # 전체 수량 계산 (박스 단위 및 낱개 환산)
        total_boxes = qty + promo_qty
        base_units = qty * units_per_box         # 증정품 제외 순수 구매 낱개
        total_units = total_boxes * units_per_box # 증정품 포함 전체 낱개
        
        if total_units == 0: continue
            
        # UI 출력용 텍스트 (보너스 여부 표시)
        qty_str = f"{int(total_boxes)}개"
        if promo_qty > 0:
            qty_str = f"{int(qty)}+{int(promo_qty)} (총 {int(total_boxes)}개)"
        if units_per_box > 1:
            qty_str += f" / 총 {int(total_units)}알"

        # [A안] 정상 단가 (할인 전 1개/알 기준)
        simple_unit_total = original_price / total_units
        simple_net = simple_unit_total / 1.1 if is_vat_included else simple_unit_total
        simple_vat = simple_unit_total if is_vat_included else simple_unit_total * 1.1
            
        # [B안] 최종 실구매 단가 (할인 후 전체 수량 기준)
        actual_paid_for_item = original_price * payment_ratio
        disc_unit_total = actual_paid_for_item / total_units
        disc_net = disc_unit_total / 1.1 if is_vat_included else disc_unit_total
        disc_vat = disc_unit_total if is_vat_included else disc_unit_total * 1.1

        # [C안] 보너스 제외 단가 (마진 방어용 듀얼 계산기)
        if promo_qty > 0 and base_units > 0:
            no_bonus_unit_total = actual_paid_for_item / base_units
            no_bonus_vat = no_bonus_unit_total if is_vat_included else no_bonus_unit_total * 1.1
            no_bonus_str = f"{round(no_bonus_vat):,}원"
        else:
            no_bonus_str = "-" # 보너스가 없는 일반 상품은 빈칸 처리
        
        processed_data.append({
            "상품명": name,
            "수량": qty_str,
            "✨실구매단가(VAT포함)": f"{round(disc_vat):,}원", 
            "🚫보너스제외단가(VAT포함)": no_bonus_str,
            "🅰️정상단가(VAT포함)": f"{round(simple_vat):,}원",
            "🅰️정상단가(VAT제외)": f"{round(simple_net):,}원",
            "🅱️행사단가(VAT제외)": f"{round(disc_net):,}원"
        })
        
    return pd.DataFrame(processed_data)

def analyze_receipt(image, model_name):
    model = genai.GenerativeModel(model_name)
    
    # [V10 AI 뇌 개조] 악필/간이영수증 방어 및 환각 통제 프롬프트
    prompt = """
    당신은 영수증, B2B 거래명세서, 간이 수기(손글씨) 영수증을 모두 판독하는 최고급 회계 AI입니다. 
    반드시 아래 JSON 객체 형식으로만 응답하세요. 마크다운 제외.
    
    [엄격한 예외 통제 지침 - V10]
    1. **손글씨(수기) 판독 방어**: 글씨가 너무 뭉개져서 도저히 읽을 수 없거나 확신이 안 서면 소설을 쓰지 말고 상품명에 "[수기/판독불가]" 라고 적으세요.
    2. **특수기호 무시**: 손글씨 영수증에서 금액이나 수량 뒤에 붙은 펜 자국(`-`, `=`, `ㄴ`, `ㄷ` 등)은 절대 문자로 읽지 말고 순수 아라비아 숫자만 발라내세요. (예: 10,- -> 10000)
    3. **단가 역산 금지**: '원래가격'은 절대 수량으로 나누지 마세요. 무조건 해당 줄에 적힌 '공급가액 총액'을 그대로 적으세요.
    4. **검산 기능**: 당신이 추출한 품목별 금액의 합이 맨 아래에 적힌 '총합계'와 일치하는지 논리적으로 점검한 후 출력하세요.
    5. **도매/수기 부가세 처리**: B2B 명세서나 간이영수증(부가세 별도 표기 등)은 "부가세포함여부"를 false로 하세요.
    
    {
      "summary": {
        "총주문금액": 104000, 
        "총할인금액": 0,
        "최종결제금액": 104000
      },
      "items": [
        {
          "상품명": "상품이름 (모르면 [수기/판독불가])",
          "원래가격": 10000, 
          "기본수량": 2,
          "증정수량": 0,
          "포장당_낱개수량": 1,
          "부가세포함여부": false
        }
      ]
    }
    """
    response = model.generate_content([prompt, image])
    return extract_json_from_text(response.text)

# ==========================================
# 3. UI/UX 화면 구성 (클린 뷰 연동)
# ==========================================
st.title("🧾 지능형 단가 분석 엔진")
st.markdown("스마트폰이나 PC에서 영수증을 올려 **진짜 1개당 실구매가**를 확인하세요.")
st.divider()

uploaded_file = st.file_uploader("영수증 사진을 업로드하세요 (JPG, PNG)", type=['jpg', 'jpeg', 'png'])

if uploaded_file is not None:
    image = Image.open(uploaded_file)
    st.image(image, caption="업로드된 영수증", width=350)
    
    if st.button("🚀 영수증 분석 시작하기", type="primary"):
        with st.spinner("AI가 수기 데이터와 프로모션을 해독 중입니다. 잠시만 기다려주세요..."):
            best_model = get_best_available_model()
            try:
                extracted_data = analyze_receipt(image, best_model)
                result_df = calculate_true_unit_price(extracted_data)
                
                st.success("✅ 분석이 완료되었습니다!")
                
                # [UX 핵심 1] 클린 뷰 (Clean View)
                st.subheader("📊 핵심 단가 요약 (1개/알 기준)")
                clean_df = result_df[["상품명", "수량", "✨실구매단가(VAT포함)"]]
                st.dataframe(clean_df, use_container_width=True)
                
                # [UX 핵심 2] 상세 뷰 토글 스위치 (Detail View - 보너스 단가 포함)
                with st.expander("🔍 상세 회계 내역 및 마진 방어선 보기"):
                    st.markdown("회계 장부 기장 및 행사 종료 후 원가(보너스 제외 단가)를 확인하세요.")
                    st.dataframe(result_df, use_container_width=True)
                
                st.divider()
                
                # [UX 핵심 3] 엑셀 다운로드
                st.markdown("### 💾 결과 저장")
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer:
                    result_df.to_excel(writer, index=False, sheet_name='단가분석결과')
                excel_data = output.getvalue()
                
                st.download_button(
                    label="📊 전체 데이터 엑셀로 다운로드",
                    data=excel_data,
                    file_name=f"단가분석결과_{uploaded_file.name.split('.')[0]}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
                
            except Exception as e:
                st.error(f"❌ 분석 중 오류가 발생했습니다: {e}")
