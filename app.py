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
# 2. V12 코어 엔진: 도매시장 암호 해독 지능 탑재
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
        
        total_boxes = qty + promo_qty
        base_units = qty * units_per_box         
        total_units = total_boxes * units_per_box 
        
        if total_units == 0: continue
            
        qty_str = f"{int(total_boxes)}개"
        if promo_qty > 0:
            qty_str = f"{int(qty)}+{int(promo_qty)} (총 {int(total_boxes)}개)"
        if units_per_box > 1:
            qty_str += f" / 총 {int(total_units)}알"

        # [단가 계산 로직]
        simple_unit_total = original_price / total_units
        simple_net = simple_unit_total / 1.1 if is_vat_included else simple_unit_total
        simple_vat = simple_unit_total if is_vat_included else simple_unit_total * 1.1
            
        actual_paid_for_item = original_price * payment_ratio
        disc_unit_total = actual_paid_for_item / total_units
        disc_net = disc_unit_total / 1.1 if is_vat_included else disc_unit_total
        disc_vat = disc_unit_total if is_vat_included else disc_unit_total * 1.1

        if promo_qty > 0 and base_units > 0:
            no_bonus_unit_total = actual_paid_for_item / base_units
            no_bonus_vat = no_bonus_unit_total if is_vat_included else no_bonus_unit_total * 1.1
            no_bonus_str = f"{round(no_bonus_vat):,}원"
        else:
            no_bonus_str = "-" 
        
        processed_data.append({
            "상품명": name,
            "수량": qty_str,
            "✨실구매단가(VAT포함)": f"{round(disc_vat):,}원", 
            "🚫보너스제외단가(VAT포함)": no_bonus_str,
            "🅰️정상단가(VAT포함)": f"{round(simple_vat):,}원",
            "🅰️정상단가(VAT제외)": f"{round(simple_net):,}원",
            "🅱️행사단가(VAT제외)": f"{round(disc_net):,}원"
        })
        
    df = pd.DataFrame(processed_data)
    
    # [인간 친화적 UI] 0번 멸종, 1번부터 인덱스 시작
    if not df.empty:
        df.index = range(1, len(df) + 1)
        
    return df

def analyze_receipt(image, model_name):
    model = genai.GenerativeModel(model_name)
    
    # [V12 AI 뇌 개조] 환각 억제 및 한국 도매시장 암호(10.- = 10000) 교육
    prompt = """
    당신은 영수증, B2B 거래명세서, 간이 수기(손글씨) 영수증을 모두 판독하는 최고급 회계 AI입니다. 
    반드시 아래 JSON 객체 형식으로만 응답하세요. 마크다운 제외.
    
    [엄격한 예외 통제 지침 - V12 (한국 도매시장 암호 해독 모드)]
    1. **한국 도매시장 축약어 번역**: 수기 영수증에서 금액에 '10.-', '12,-', '70=' 처럼 숫자 뒤에 점, 쉼표, 대시, 등호 등이 붙어있다면, 이것은 '000(천 단위)'이 생략된 것입니다! 반드시 뒤에 0을 3개 붙여서 정상 금액으로 번역하세요. (예: 10.- -> 10000, 12,- -> 12000, 70= -> 70000)
    2. **환각(소설 쓰기) 절대 금지**: 수량이나 금액을 당신 마음대로 창조해서 계산을 억지로 맞추지 마세요. 사진에 확실하게 보이는 숫자(예: 수량 2, 12, 2)만 정확하게 가져오세요.
    3. **이름은 포기해도 숫자는 포기하지 마라**: 상품명을 도저히 못 읽겠으면 "[수기/판독불가]"로 적으세요. 하지만 눈에 보이는 수량과 금액은 반드시 가져오세요.
    4. **단가 역산 금지**: '원래가격'은 절대 수량으로 나누지 마세요. 무조건 해당 줄에 적힌 '공급가액 총액'을 그대로 적으세요.
    5. **도매/수기 부가세 처리**: B2B 명세서나 간이영수증은 "부가세포함여부"를 false로 하세요.
    
    {
      "summary": {
        "총주문금액": 104000, 
        "총할인금액": 0,
        "최종결제금액": 104000
      },
      "items": [
        {
          "상품명": "[수기/판독불가]",
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
                
                # [UX 핵심 2] 상세 뷰 토글 스위치
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
