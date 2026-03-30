import streamlit as st
import pandas as pd
import io

# ==========================================
# 1. 웹 사이트 기본 설정 (UI 인테리어)
# ==========================================
st.set_page_config(page_title="지능형 단가 분석 엔진", page_icon="🧾", layout="wide")

st.title("🧾 지능형 단가 분석 엔진 (UI 테스트 중)")
st.markdown("스마트폰이나 PC에서 영수증을 올려 **진짜 1개당 단가**를 확인하세요.")
st.divider()

# ==========================================
# 2. UI/UX 화면 구성 (가짜 데이터로 껍데기만 테스트)
# ==========================================
# [UX 1] 파일 업로드 위젯
uploaded_file = st.file_uploader("영수증 사진을 업로드하세요 (JPG, PNG)", type=['jpg', 'jpeg', 'png'])

if uploaded_file is not None:
    st.info(f"업로드 완료: {uploaded_file.name}")
    
    # [UX 2] 직관적인 실행 버튼
    if st.button("🚀 영수증 분석 시작하기", type="primary"):
        with st.spinner("AI가 데이터를 분석하는 척 하고 있습니다... (UI 테스트 중)"):
            
            # 가짜(Dummy) 데이터 생성 (UI 디자인 확인용)
            dummy_data = [
                {
                    "상품명": "넥스가드 대형견용 (L)",
                    "수량": "15박스 (총 45알)",
                    "✨실구매단가(VAT포함)": "36,185원",
                    "🅰️정상단가(VAT포함)": "47,300원",
                    "🅰️정상단가(VAT제외)": "43,000원",
                    "🅱️행사단가(VAT제외)": "32,895원"
                },
                {
                    "상품명": "넥스가드 소형견용 (S)",
                    "수량": "140박스 (총 420알)",
                    "✨실구매단가(VAT포함)": "24,404원",
                    "🅰️정상단가(VAT포함)": "31,900원",
                    "🅰️정상단가(VAT제외)": "29,000원",
                    "🅱️행사단가(VAT제외)": "22,185원"
                }
            ]
            df = pd.DataFrame(dummy_data)
            
            # ------------------------------------------------
            # [UX 핵심 1] 클린 뷰 (Clean View) - 필수 정보만!
            # ------------------------------------------------
            st.success("✅ 분석 완료! (UI 테스트 화면입니다)")
            st.subheader("📊 핵심 단가 요약")
            
            # 사용자님의 아이디어: 보기 편하게 3개 기둥만 뽑아서 먼저 보여줍니다.
            clean_df = df[["상품명", "수량", "✨실구매단가(VAT포함)"]]
            st.dataframe(clean_df, use_container_width=True)
            
            # ------------------------------------------------
            # [UX 핵심 2] 상세 회계 내역 토글 스위치 (Detail View)
            # ------------------------------------------------
            with st.expander("🔍 상세 회계 내역 및 정상가 비교 보기"):
                st.markdown("회계 장부 기장 및 마진율 계산을 위한 전체 데이터입니다.")
                st.dataframe(df, use_container_width=True)
            
            st.divider()
            
            # ------------------------------------------------
            # [UX 핵심 3] 엑셀 자동 변환 및 다운로드 버튼
            # ------------------------------------------------
            st.markdown("### 💾 결과 저장")
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, index=False, sheet_name='단가분석결과')
            excel_data = output.getvalue()
            
            st.download_button(
                label="📊 전체 데이터 엑셀로 다운로드",
                data=excel_data,
                file_name="단가분석결과_테스트.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
