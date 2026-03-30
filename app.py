import streamlit as st
import google.generativeai as genai
import pandas as pd
import json
import re
from PIL import Image
import io

# ==========================================
# 1. 기본 설정 및 보안 금고
# ==========================================
st.set_page_config(page_title="지능형 단가 분석 엔진", page_icon="🧾", layout="wide")

try:
    API_KEY = st.secrets["GEMINI_API_KEY"]
    genai.configure(api_key=API_KEY)
except Exception:
    st.error("❌ 시스템 에러: 서버 금고에 API 키가 없습니다. Settings > Secrets를 확인하세요.")
    st.stop()

def get_best_available_model():
    # [V13 최적화] 가장 빠르고 가성비 좋은 Flash 모델 우선 할당
    return 'gemini-1.5-flash'

def optimize_image(image, max_size=1600):
    # [V13 속도 방어] OCR 시력을 잃지 않는 선(1600px)에서 이미지 용량 초고속 압축
    image.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)
    return image

# ==========================================
# 2. V13 코어 엔진: AI 통신 및 데이터 처리
# ==========================================
def extract_json_from_text(text):
    match = re.search(r'\{.*\}', text, re.DOTALL)
    if match: return json.loads(match.group(0))
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match: return json.loads(match.group(0))
    raise ValueError("JSON 형식을 찾을 수 없습니다.")

def analyze_receipt(image, model_name):
    model = genai.GenerativeModel(model_name)
    prompt = """
    당신은 영수증, B2B 거래명세서, 간이 수기(손글씨) 영수증을 모두 판독하는 최고급 회계 AI입니다. 
    반드시 아래 JSON 객체 형식으로만 응답하세요. 마크다운 제외.
    
    [엄격한 예외 통제 지침 - V13 (도매시장 암호 해독 및 본질 집중)]
    1. **한국 도매시장 축약어 번역**: 금액에 '10.-', '12,-', '70=' 처럼 숫자 뒤에 기호가 붙어있으면 '000(천 단위)'이 생략된 것입니다. 반드시 뒤에 0을 3개 붙여 정상 금액으로 번역하세요. (예: 10.- -> 10000)
    2. **환각 절대 금지**: 수량이나 금액을 창조하지 마세요. 사진에 확실하게 보이는 숫자만 가져오세요.
    3. **이름은 포기해도 숫자는 포기 금지**: 상품명을 못 읽겠으면 "[수기/판독불가]"로 적되, 수량과 금액은 반드시 가져오세요.
    4. **단가 역산 금지**: '원래가격'은 절대 수량으로 나누지 마세요. 무조건 해당 줄에 적힌 '공급가액 총액'을 그대로 적으세요.
    5. **도매/수기 부가세 처리**: B2B 명세서나 간이영수증은 "부가세포함여부"를 false로 하세요.
    
    {
      "summary": {
        "총주문금액": 104000, 
        "총할인금액": 0
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

def calculate_true_unit_price(summary_df, items_df):
    # 에디터에서 수정한 총금액/할인금액 가져오기
    try:
        total_original = float(summary_df["금액"].iloc[0])
        total_discount = float(summary_df["금액"].iloc[1])
    except:
        total_original, total_discount = 1, 0
        
    if total_original == 0: total_original = 1
    payment_ratio = (total_original - total_discount) / total_original
    
    processed_data = []
    # 에디터에서 수정한 개별 품목 데이터 순회
    for _, item in items_df.iterrows():
        name = str(item.get("상품명", "알수없음"))
        original_price = float(item.get("원래가격", 0))
        qty = float(item.get("기본수량", 1))
        promo_qty = float(item.get("증정수량", 0))
        units_per_box = float(item.get("포장당_낱개수량", 1)) 
        is_vat_included = bool(item.get("부가세포함여부", True))
        
        total_boxes = qty + promo_qty
        base_units = qty * units_per_box         
        total_units = total_boxes * units_per_box 
        
        if total_units <= 0: continue
            
        qty_str = f"{int(total_boxes)}개"
        if promo_qty > 0:
            qty_str = f"{int(qty)}+{int(promo_qty)} (총 {int(total_boxes)}개)"
        if units_per_box > 1:
            qty_str += f" / 총 {int(total_units)}알"

        # 단가 계산 로직
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
    if not df.empty:
        df.index = range(1, len(df) + 1)
    return df

# ==========================================
# 3. UI/UX 화면 구성 (V13 에디터 탑재)
# ==========================================
st.title("🧾 지능형 단가 분석 엔진")
# [V13 UI 텍스트 업데이트]
st.markdown("영수증을 업로드하여 품목별 실구매 단가를 확인하세요.")
st.divider()

uploaded_file = st.file_uploader("영수증 사진을 업로드하세요 (JPG, PNG)", type=['jpg', 'jpeg', 'png'])

if uploaded_file is not None:
    # 이미지 압축 전처리 (속도 극대화)
    raw_image = Image.open(uploaded_file)
    optimized_image = optimize_image(raw_image)
    
    col1, col2 = st.columns([1, 2])
    with col1:
        st.image(optimized_image, caption="업로드된 영수증", use_container_width=True)
    
    with col2:
        # [세션 관리] 새 파일이 올라오면 이전 AI 추출 기록을 초기화
        if "raw_items" not in st.session_state or st.session_state.get("current_file") != uploaded_file.name:
            if st.button("🚀 영수증 분석 시작하기", type="primary"):
                # [V13 로딩 텍스트 업데이트]
                with st.spinner("영수증을 분석 중입니다. 잠시만 기다려주세요."):
                    best_model = get_best_available_model()
                    try:
                        extracted_data = analyze_receipt(optimized_image, best_model)
                        
                        # AI가 추출한 '원본 데이터'를 세션에 저장 (나중에 직접 편집하기 위함)
                        st.session_state.summary_df = pd.DataFrame([
                            {"항목": "총주문금액", "금액": extracted_data["summary"].get("총주문금액", 0)},
                            {"항목": "총할인금액", "금액": extracted_data["summary"].get("총할인금액", 0)}
                        ])
                        st.session_state.raw_items = pd.DataFrame(extracted_data["items"])
                        st.session_state.current_file = uploaded_file.name
                        
                        # 데이터 저장 후 화면 새로고침
                        st.rerun() 
                    except Exception as e:
                        st.error(f"❌ 분석 중 오류가 발생했습니다: {e}")

        # [V13 핵심] AI 분석이 끝나면 '편집 가능한 표(Data Editor)'를 화면에 띄움
        if "raw_items" in st.session_state and st.session_state.get("current_file") == uploaded_file.name:
            st.success("✅ 1차 분석 완료! (오류나 누락이 있다면 아래 표를 클릭해 직접 수정하세요)")
            
            with st.expander("✏️ 원본 데이터 수정 (AI가 틀렸다면 여기서 고치세요)", expanded=False):
                st.markdown("**1. 결제/할인 요약**")
                edited_summary = st.data_editor(st.session_state.summary_df, num_rows="dynamic", use_container_width=True)
                
                st.markdown("**2. 품목 상세 (마우스로 클릭해서 수정, 행 추가/삭제 가능)**")
                edited_items = st.data_editor(st.session_state.raw_items, num_rows="dynamic", use_container_width=True)

            # [마법의 순간] 사용자가 위에서 표를 수정하면, 단가가 0.1초만에 '자동 재계산'됨
            result_df = calculate_true_unit_price(edited_summary, edited_items)
            
            st.subheader("📊 핵심 단가 요약 (1개/알 기준)")
            clean_df = result_df[["상품명", "수량", "✨실구매단가(VAT포함)"]] if not result_df.empty else result_df
            st.dataframe(clean_df, use_container_width=True)
            
            with st.expander("🔍 상세 회계 내역 및 마진 방어선 보기"):
                st.dataframe(result_df, use_container_width=True)
            
            st.divider()
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
