import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import re
from PIL import Image
import io

# ==========================================
# 1. 웹 사이트 기본 설정 및 보안 금고 연동
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
# 2. V8 코어 비즈니스 로직 (수학적 오류 완벽 교정)
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
    
    # [교정 1] 사과와 배를 섞지 않는 순수 할인율 도출 로직
    total_original = float(summary.get("총주문금액", 1))
    if total_original == 0: total_original = 1
    total_discount = float(summary.get("총할인금액", 0))
    
    # 예: (5,725,000 - 1,345,375) / 5,725,000 = 0.765 (순수 76.5%에 구매함)
    payment_ratio = (total_original - total_discount) / total_original
    
    processed_data = []
    for item in items:
        name = item.get("상품명", "알수없음")
        original_price = float(item.get("원래가격", 0))
        qty = float(item.get("기본수량", 1))
        promo_qty = float(item.get("증정수량", 0))
        units_per_box = float(item.get("포장당_낱개수량", 1)) # [교정 2] 낱개 환산 지능 탑재
        is_vat_included = item.get("부가세포함여부", True)
        
        total_boxes = qty + promo_qty
        total_units = total_boxes * units_per_box # 최종 낱개 수량
        
        if total_units == 0: continue
            
        # UI 출력용 수량 텍스트 포맷팅
        if units_per_box > 1:
            qty_str = f"{int(total_boxes)}박스 (총 {int(total_units)}개)"
        else:
            qty_str = f"{int(total_boxes)}개"

        # ------------------------------------------------
        # [A안] 정상 단가 (1알/개 기준)
        # ------------------------------------------------
        simple_unit_total = original_price / total_units
        if is_vat_included:
            simple_net = simple_unit_total / 1.1
            simple_vat = simple_unit_total
        else:
            simple_net = simple_unit_total
            simple_vat = simple_unit_total * 1.1
            
        # ------------------------------------------------
        # [B안] 행사가 단가 (1알/개 기준, 순수 할인율 적용)
        # ------------------------------------------------
        disc_unit_total = (original_price * payment_ratio) / total_units
        if is_vat_included:
            disc_net = disc_unit_total / 1.1
            disc_vat = disc_unit_total
        else:
            disc_net = disc_unit_total
            disc_vat = disc_unit_total * 1.1
        
        processed_data.append({
            "상품명": name,
            "수량": qty_str,
            "✨실구매단가(VAT포함)": f"{round(disc_vat):,}원", # 클린 뷰용 핵심 데이터
            "🅰️정상단가(VAT포함)": f"{round(simple_vat):,}원",
            "🅰️정상단가(VAT제외)": f"{round(simple_net):,}원",
            "🅱️행사단가(VAT제외)": f"{round(disc_net):,}원"
        })
        
    return pd.DataFrame(processed_data)

def analyze_receipt(image, model_name):
    model = genai.GenerativeModel(model_name)
    prompt = """
    당신은 영수증 및 B2B 거래명세서 전문 회계 AI입니다. 첨부된 이미지를 분석하여 
    반드시 아래 JSON 객체 형식으로만 응답하세요. 마크다운 제외.
    
    [엄격한 주의사항]
    1. '원래가격'은 절대 1개 단가로 나누어 계산하지 마세요. 해당 줄의 '공급가액 총액'을 그대로 적으세요.
    2. 도매 명세서(B2B)의 경우 품목별 금액이 '공급가액' 기준이면 "부가세포함여부"를 false로 하세요.
    3. 명세서에 포장당 낱개 수량(예: 1박스에 30정, 1통에 60알)이 적혀있다면 "포장당_낱개수량"에 적고, 안 적혀있으면 1로 적으세요.
    4. "총할인금액"은 명세서 하단에 적힌 모든 할인의 총합을 적으세요. 없으면 0.
    
    {
      "summary": {
        "총주문금액": 5725000, 
        "총할인금액": 1345375,
        "최종결제금액": 4817588
      },
      "items": [
        {
          "상품명": "상품이름",
          "원래가격": 645000, 
          "기본수량": 15,
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
# 3. UI/UX 화면 구성 (클린 뷰 연동 완료)
# ==========================================
st.title("🧾 지능형 단가 분석 엔진")
st.markdown("스마트폰이나 PC에서 영수증을 올려 **진짜 1개당 실구매가**를 확인하세요.")
st.divider()

uploaded_file = st.file_uploader("영수증 사진을 업로드하세요 (JPG, PNG)", type=['jpg', 'jpeg', 'png'])

if uploaded_file is not None:
    image = Image.open(uploaded_file)
    st.image(image, caption="업로드된 영수증", width=350)
    
    if st.button("🚀 영수증 분석 시작하기", type="primary"):
        with st.spinner("AI가 프로모션과 부가세를 역산하고 있습니다. 잠시만 기다려주세요..."):
            best_model = get_best_available_model()
            try:
                # 데이터 추출 및 계산 (코어 엔진 가동)
                extracted_data = analyze_receipt(image, best_model)
                result_df = calculate_true_unit_price(extracted_data)
                
                # [UX 핵심 1] 클린 뷰 (Clean View)
                st.success("✅ 분석이 완료되었습니다!")
                st.subheader("📊 핵심 단가 요약 (1개/알 기준)")
                clean_df = result_df[["상품명", "수량", "✨실구매단가(VAT포함)"]]
                st.dataframe(clean_df, use_container_width=True)
                
                # [UX 핵심 2] 상세 뷰 토글 스위치 (Detail View)
                with st.expander("🔍 상세 회계 내역 및 정상가 비교 보기"):
                    st.markdown("회계 장부 기장 및 마진율 계산을 위한 전체 데이터입니다.")
                    st.dataframe(result_df, use_container_width=True)
                
                st.divider()
                
                # [UX 핵심 3] 엑셀 다운로드 (전체 데이터 보존)
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
